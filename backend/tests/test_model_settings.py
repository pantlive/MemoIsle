"""模型设置的凭据保护、账号隔离和即时生效测试。"""

from __future__ import annotations

import json
import json as json_module
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from app.auth_service import create_dev_session
from app.category_generation_service import generate_category_suggestions
from app.config import Settings
from app.model_settings_service import (
    ModelSettingError,
    credential_cipher,
    credential_key_file,
    resolve_model_settings,
    verify_model_connection,
)
from app.models import ModelProviderSetting
from app.resource_processing import ResourceMetadata
from app.resource_service import enrich_resource
from app.schemas import (
    ModelConnectionResult,
    ModelProvider,
    ModelSettingUpdate,
    ResourceCategoryGenerateResponse,
    ResourceCategoryRead,
)
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def test_save_masks_encrypts_and_preserves_key(client: TestClient) -> None:
    """保存只返回掩码，数据库不存明文，空密钥可安全修改模型。"""

    key = "test-deepseek-secret-1234"
    response = client.put(
        "/api/v1/model-settings/deepseek",
        json={
            "model": "deepseek-flash",
            "api_key": key,
        },
    )
    assert response.status_code == 200
    saved = response.json()
    assert saved["has_api_key"] is True
    assert saved["key_hint"] == "••••1234"
    assert saved["credential_source"] == "account"
    assert key not in response.text
    assert key not in client.get("/api/v1/model-settings").text
    settings = client.app.state.settings
    with client.app.state.database.session_factory() as session:
        row = session.get(
            ModelProviderSetting,
            (
                settings.local_user_id,
                "deepseek",
            ),
        )
        assert row is not None
        assert row.credential_cipher is not None
        assert key not in row.credential_cipher
        assert (
            credential_cipher(settings)
            .decrypt(
                row.credential_cipher.encode(),
            )
            .decode()
            == key
        )
    updated = client.put(
        "/api/v1/model-settings/deepseek",
        json={
            "model": "custom-deepseek",
            "api_key": "  ",
        },
    ).json()
    assert updated["has_api_key"] is True
    assert updated["model"] == "custom-deepseek"
    assert updated["key_hint"] == saved["key_hint"]
    key_file = credential_key_file(settings)
    assert key_file.stat().st_mode & 0o777 == 0o600
    assert key not in key_file.read_text()
    exported = client.get("/api/v1/exports/json")
    assert exported.status_code == 200
    assert key not in exported.text
    assert "model_provider_setting" not in exported.text


def test_keys_survive_restart_and_auth_secret_change(
    client: TestClient,
) -> None:
    """重建配置和会话后沿用持久密钥，不依赖随机登录密钥。"""

    key = "test-persistent-key"
    assert (
        client.put(
            "/api/v1/model-settings/jev",
            json={
                "model": "jev-1.13.0",
                "api_key": key,
            },
        ).status_code
        == 200
    )
    restarted = replace(
        client.app.state.settings, auth_token_secret="new-secret"
    )
    with client.app.state.database.session_factory() as session:
        resolved = resolve_model_settings(
            session,
            restarted.local_user_id,
            restarted,
        )
    assert resolved.jev_api_key == key
    assert restarted.jev_api_key is None


def test_settings_require_authentication(client: TestClient) -> None:
    """正常模式下，匿名请求不能读写或测试账号凭据。"""

    client.app.state.settings = replace(
        client.app.state.settings,
        auth_dev_mode=False,
    )
    assert client.get("/api/v1/model-settings").status_code == 401
    assert (
        client.put(
            "/api/v1/model-settings/jev",
            json={
                "model": "jev-1.13.0",
                "api_key": "anonymous-test-key",
            },
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/model-settings/jev/test",
            json={
                "model": "jev-1.13.0",
                "api_key": "anonymous-test-key",
            },
        ).status_code
        == 401
    )
    assert client.delete("/api/v1/model-settings/jev").status_code == 401


def test_concurrent_key_creation_is_atomic(
    client: TestClient,
    tmp_path: Path,
) -> None:
    """并发初始化均能解密同一凭据，不产生半写入密钥文件。"""

    settings = replace(
        client.app.state.settings,
        model_credential_key_file=tmp_path / "private" / ".memoisle-model.key",
    )

    def encrypt(_index: int) -> bytes:
        """模拟首次保存同时到达的加密请求。"""

        return credential_cipher(settings).encrypt(b"shared-test-secret")

    with ThreadPoolExecutor(max_workers=8) as pool:
        encrypted = list(pool.map(encrypt, range(24)))
    cipher = credential_cipher(settings)
    assert all(
        cipher.decrypt(value) == b"shared-test-secret" for value in encrypted
    )
    assert not list(credential_key_file(settings).parent.glob("*.tmp"))


def test_configuration_isolated_between_authenticated_users(
    client: TestClient,
) -> None:
    """两个真实登录会话分别读写自身配置，删除不影响另一账号。"""

    settings = client.app.state.settings
    with client.app.state.database.session_factory() as session:
        first = create_dev_session(session, settings).token
        second = create_dev_session(
            session,
            replace(
                settings,
                local_user_id="00000000-0000-0000-0000-000000000002",
            ),
        ).token
    first_headers = {"Authorization": f"Bearer {first}"}
    second_headers = {"Authorization": f"Bearer {second}"}
    response = client.put(
        "/api/v1/model-settings/deepseek",
        json={
            "model": "first-model",
            "api_key": "first-private-key",
        },
        headers=first_headers,
    )
    assert response.status_code == 200
    other = client.get(
        "/api/v1/model-settings", headers=second_headers
    ).json()[0]
    assert other["has_api_key"] is False
    assert other["model"] == "deepseek-flash"
    assert (
        client.put(
            "/api/v1/model-settings/deepseek",
            json={
                "model": "second-model",
                "api_key": "second-private-key",
            },
            headers=second_headers,
        ).status_code
        == 200
    )
    assert (
        client.delete(
            "/api/v1/model-settings/deepseek",
            headers=second_headers,
        ).status_code
        == 200
    )
    own = client.get("/api/v1/model-settings", headers=first_headers).json()[0]
    assert own["model"] == "first-model"
    assert own["has_api_key"] is True
    assert (
        client.get(
            "/api/v1/model-settings",
            headers={"Authorization": "Bearer invalid"},
        ).status_code
        == 401
    )


def test_override_disable_and_reset_environment_defaults(
    client: TestClient,
) -> None:
    """账号配置优先于环境默认值，停用明确阻止使用两种凭据。"""

    settings = replace(
        client.app.state.settings, deepseek_api_key="env-test-key"
    )
    client.app.state.settings = settings
    default = client.get("/api/v1/model-settings").json()[0]
    assert default["credential_source"] == "environment"
    assert default["has_api_key"] is True
    client.put(
        "/api/v1/model-settings/deepseek",
        json={
            "model": "custom-model",
            "api_key": "account-private-key",
        },
    )
    with client.app.state.database.session_factory() as session:
        resolved = resolve_model_settings(
            session, settings.local_user_id, settings
        )
    assert resolved.deepseek_api_key == "account-private-key"
    client.put(
        "/api/v1/model-settings/deepseek",
        json={
            "model": "custom-model",
            "enabled": False,
        },
    )
    with client.app.state.database.session_factory() as session:
        assert (
            resolve_model_settings(
                session,
                settings.local_user_id,
                settings,
            ).deepseek_api_key
            is None
        )
    restored = client.delete("/api/v1/model-settings/deepseek").json()
    assert restored["has_custom_settings"] is False
    assert restored["model"] == "deepseek-flash"
    assert restored["credential_source"] == "environment"


def test_corrupted_credential_can_be_replaced(client: TestClient) -> None:
    """无法解密时显示重新填写提示，禁止悄悄改用环境凭据。"""

    client.put(
        "/api/v1/model-settings/jev",
        json={
            "model": "jev-1.13.0",
            "api_key": "account-private-key",
        },
    )
    settings = replace(client.app.state.settings, jev_api_key="env-test-key")
    client.app.state.settings = settings
    with client.app.state.database.session_factory() as session:
        saved = session.get(
            ModelProviderSetting, (settings.local_user_id, "jev")
        )
        assert saved is not None
        saved.credential_cipher = "damaged-ciphertext"
        session.commit()
        assert (
            resolve_model_settings(
                session,
                settings.local_user_id,
                settings,
            ).jev_api_key
            is None
        )
    summary = client.get("/api/v1/model-settings").json()[1]
    assert summary["has_api_key"] is False
    assert "重新填写" in summary["error"]
    replaced = client.put(
        "/api/v1/model-settings/jev",
        json={
            "model": "jev-1.13.0",
            "api_key": "new-account-key",
        },
    ).json()
    assert replaced["has_api_key"] is True
    assert replaced["error"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"api_key": "sensitive-input"},
        {"model": "", "api_key": "sensitive-input"},
        {"model": "   ", "api_key": "sensitive-input"},
        {"model": "jev", "api_key": {"key": "sensitive-input"}},
        {"model": "jev", "api_key": "sensitive-input\ninvalid"},
    ],
)
def test_invalid_inputs_never_echo_keys(
    client: TestClient,
    payload: dict[str, Any],
) -> None:
    """请求校验错误不能把完整正文或凭据回显到响应。"""

    for endpoint in [
        "/api/v1/model-settings/jev",
        "/api/v1/model-settings/jev/test",
    ]:
        method = client.put if not endpoint.endswith("/test") else client.post
        response = method(endpoint, json=payload)
        assert response.status_code in {400, 422}
        assert "sensitive-input" not in response.text


@pytest.mark.parametrize(
    "provider", [ModelProvider.DEEPSEEK, ModelProvider.JEV]
)
def test_connection_uses_unsaved_input_without_persisting(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    provider: ModelProvider,
) -> None:
    """测试调用真实接口格式，使用新输入，并保持数据库原配置。"""

    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """模拟两个服务的正式响应结构。"""

        calls.append(request)
        if provider == ModelProvider.DEEPSEEK:
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "OK"}}],
                },
            )
        return httpx.Response(
            200, json={"answers": {"test": {"choice": "ok"}}}
        )

    def verify(
        session: Session,
        user_id: str,
        settings: Settings,
        selected: ModelProvider,
        payload: ModelSettingUpdate | None,
    ) -> ModelConnectionResult:
        """将路由测试请求注入模拟传输。"""

        with httpx.Client(
            transport=httpx.MockTransport(handler)
        ) as model_client:
            return verify_model_connection(
                session,
                user_id,
                settings,
                selected,
                payload,
                model_client,
            )

    monkeypatch.setattr(
        "app.model_settings_api.verify_model_connection", verify
    )
    response = client.post(
        f"/api/v1/model-settings/{provider}/test",
        json={
            "model": "test-model",
            "api_key": "unsaved-test-key",
        },
    )
    assert response.status_code == 200
    assert calls[0].headers["authorization"] == "Bearer unsaved-test-key"
    body = json.loads(calls[0].content)
    assert body["model"] == "test-model"
    assert "categories" not in body
    assert calls[0].url.path.endswith(
        "/chat/completions"
        if provider == ModelProvider.DEEPSEEK
        else "/systemone",
    )
    assert not any(
        item["has_custom_settings"]
        for item in client.get("/api/v1/model-settings").json()
    )


def test_connection_allows_reasoning_before_final_answer(
    client: TestClient,
) -> None:
    """推理占用输出预算时，连接测试仍能得到最终答复。"""

    def handler(request: httpx.Request) -> httpx.Response:
        """复现中转模型先推理、超过旧版 16 token 后才作答的行为。"""

        body = json.loads(request.content)
        truncated = body["max_tokens"] < 22
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "length" if truncated else "stop",
                        "message": {
                            "content": "" if truncated else "OK",
                            "reasoning_content": "先确认用户需要简短的连接测试答复。",
                        },
                    }
                ],
            },
        )

    with client.app.state.database.session_factory() as session:
        with httpx.Client(
            transport=httpx.MockTransport(handler),
        ) as model_client:
            result = verify_model_connection(
                session,
                client.app.state.settings.local_user_id,
                client.app.state.settings,
                ModelProvider.DEEPSEEK,
                ModelSettingUpdate(
                    model="deepseek/deepseek-v4.1-flash",
                    base_url="https://api.commandcode.ai/provider/v1",
                    api_key="test-commandcode-key",
                ),
                model_client,
            )
    assert result.message == "连接成功，模型接口可用"


@pytest.mark.parametrize(
    ("finish_reason", "expected_message"),
    [
        ("length", "模型已响应，但输出达到长度上限，未返回最终答复"),
        ("stop", "连接失败或响应无效，请检查模型名称和服务状态"),
    ],
)
def test_connection_distinguishes_truncated_and_empty_response(
    client: TestClient,
    finish_reason: str,
    expected_message: str,
) -> None:
    """达到长度上限应提示截断，空响应不能被误判为接口可用。"""

    def handler(_request: httpx.Request) -> httpx.Response:
        """模拟只含推理且不含最终答复的响应，不回显上游内容。"""

        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": finish_reason,
                        "message": {
                            "content": None,
                            "reasoning_content": "private-upstream-key",
                        },
                    }
                ],
            },
        )

    with client.app.state.database.session_factory() as session:
        with httpx.Client(
            transport=httpx.MockTransport(handler),
        ) as model_client:
            with pytest.raises(ModelSettingError) as error:
                verify_model_connection(
                    session,
                    client.app.state.settings.local_user_id,
                    client.app.state.settings,
                    ModelProvider.DEEPSEEK,
                    ModelSettingUpdate(
                        model="model", api_key="private-upstream-key",
                    ),
                    model_client,
                )
    assert str(error.value) == expected_message
    assert "private-upstream-key" not in str(error.value)


def test_connection_timeout_has_safe_specific_message(
    client: TestClient,
) -> None:
    """超时与无效响应分别提示，异常中的上游密钥不能泄露。"""

    def handler(request: httpx.Request) -> httpx.Response:
        """模拟带有敏感上下文的读取超时。"""

        raise httpx.ReadTimeout("private-upstream-key", request=request)

    with client.app.state.database.session_factory() as session:
        with httpx.Client(
            transport=httpx.MockTransport(handler),
        ) as model_client:
            with pytest.raises(ModelSettingError) as error:
                verify_model_connection(
                    session,
                    client.app.state.settings.local_user_id,
                    client.app.state.settings,
                    ModelProvider.DEEPSEEK,
                    ModelSettingUpdate(
                        model="model", api_key="private-upstream-key",
                    ),
                    model_client,
                )
    assert str(error.value) == "模型响应超时，请稍后重试或检查服务连接"
    assert "private-upstream-key" not in str(error.value)


@pytest.mark.parametrize("status", [401, 403, 402, 429, 500])
def test_connection_errors_hide_upstream_secrets(
    client: TestClient,
    status: int,
) -> None:
    """认证、额度及服务错误只返回安全提示，不携带上游原文。"""

    def handler(_request: httpx.Request) -> httpx.Response:
        """上游故意回显密钥，验证客户端错误仍保持脱敏。"""

        return httpx.Response(status, text="private-upstream-key")

    with client.app.state.database.session_factory() as session:
        with httpx.Client(
            transport=httpx.MockTransport(handler)
        ) as model_client:
            with pytest.raises(ValueError) as error:
                verify_model_connection(
                    session,
                    client.app.state.settings.local_user_id,
                    client.app.state.settings,
                    ModelProvider.DEEPSEEK,
                    ModelSettingUpdate(
                        model="model", api_key="private-upstream-key"
                    ),
                    model_client,
                )
    assert "private-upstream-key" not in str(error.value)


@pytest.mark.parametrize(
    ("status", "payload", "expected"),
    [
        (
            403,
            {"error": {"message": "upgrade", "type": "permission_error", "code": "upgrade_required"}},
            "当前套餐不能调用该模型接口，请升级服务商套餐后再试",
        ),
        (
            400,
            {"error": {"message": "missing from catalog", "type": "invalid_request_error", "code": "unsupported_model"}},
            "模型名称不受该服务支持，请对照服务商的模型列表修改",
        ),
        (
            400,
            {"error": {"message": "private-upstream-key", "type": "invalid_request_error"}},
            "模型服务拒绝请求，请检查模型名称、请求地址和接口格式",
        ),
    ],
)
def test_connection_maps_provider_error_codes(
    client: TestClient,
    status: int,
    payload: dict[str, object],
    expected: str,
) -> None:
    """把服务商错误码转成可操作提示，不回显上游正文。"""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    with client.app.state.database.session_factory() as session:
        with httpx.Client(
            transport=httpx.MockTransport(handler),
        ) as model_client:
            with pytest.raises(ModelSettingError) as error:
                verify_model_connection(
                    session,
                    client.app.state.settings.local_user_id,
                    client.app.state.settings,
                    ModelProvider.DEEPSEEK,
                    ModelSettingUpdate(
                        model="deepseek/deepseek-v4.1-flash",
                        api_key="private-upstream-key",
                    ),
                    model_client,
                )
    assert str(error.value) == expected
    assert "private-upstream-key" not in str(error.value)


def test_saved_settings_reach_generation_and_web_classification(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同一后端无需重启，后续模板生成及网页处理采用账号密钥。"""

    for provider in ModelProvider:
        assert (
            client.put(
                f"/api/v1/model-settings/{provider}",
                json={
                    "model": f"custom-{provider}",
                    "api_key": f"private-{provider}-key",
                    "base_url": f"https://{provider}.relay.example/v1",
                },
            ).status_code
            == 200
        )

    def generation_handler(request: httpx.Request) -> httpx.Response:
        """断言生成请求实际使用设置页保存的凭据和模型。"""

        assert (
            request.headers["authorization"] == "Bearer private-deepseek-key"
        )
        assert str(request.url) == (
            "https://deepseek.relay.example/v1/chat/completions"
        )
        assert json.loads(request.content)["model"] == "custom-deepseek"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json_module.dumps(
                                {
                                    "categories": [
                                        {
                                            "name": "代理工具",
                                            "parent_code": "tool",
                                        }
                                    ],
                                }
                            ),
                        }
                    }
                ]
            },
        )

    def generate(
        instructions: str,
        existing: Sequence[ResourceCategoryRead],
        settings: Settings,
        max_categories: int,
        **_kwargs: object,
    ) -> ResourceCategoryGenerateResponse:
        """仅替换 HTTP 传输，保留生成逻辑及设置读取。"""

        with httpx.Client(
            transport=httpx.MockTransport(generation_handler),
        ) as model_client:
            return generate_category_suggestions(
                instructions,
                existing,
                settings,
                max_categories,
                model_client,
            )

    monkeypatch.setattr("app.api.generate_category_suggestions", generate)
    generated = client.post(
        "/api/v1/resource-categories/generate",
        json={
            "instructions": "细化开发工具分类",
        },
    )
    assert generated.status_code == 200
    custom = client.post(
        "/api/v1/resource-categories",
        json=generated.json()["categories"][0],
    ).json()["code"]
    memo_response = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "resource",
            "title": "Paseo",
            "body": "https://github.com/getpaseo/paseo",
            "source_url": "https://github.com/getpaseo/paseo",
        },
    )
    assert memo_response.status_code == 201
    memo = memo_response.json()

    def model_request(
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
        timeout: float,
    ) -> httpx.Response:
        """断言网页处理使用账号里保存的 DeepSeek 和 Jev 配置。"""

        if url.endswith("/chat/completions"):
            assert headers["Authorization"] == "Bearer private-deepseek-key"
            assert url == "https://deepseek.relay.example/v1/chat/completions"
            assert json["model"] == "custom-deepseek"
            content = json_module.loads(json["messages"][1]["content"])
            codes = [item["code"] for item in content["categories"]]
            assert custom in codes
            assert codes[0] == custom
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json_module.dumps(
                                    {
                                        "category": custom,
                                        "confidence": 0.98,
                                        "reason": "命中小类口径",
                                    }
                                )
                            }
                        }
                    ]
                },
            )
        assert headers["Authorization"] == "Bearer private-jev-key"
        assert url == "https://jev.relay.example/v1/systemone"
        assert json["model"] == "custom-jev"
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"answers": {"category": {"choice": custom, "confidence": 0.9}}},
        )

    def metadata_fetcher(url: str) -> ResourceMetadata:
        """提供固定网页内容，避免测试访问外部网站。"""

        return ResourceMetadata(
            final_url=url,
            page_title="Paseo",
            description="AI coding agent tool",
            site_name="GitHub",
            favicon_url=None,
            http_status=200,
        )

    monkeypatch.setattr("app.resource_processing.httpx.post", model_request)
    monkeypatch.setattr("app.resource_classification_judge.httpx.post", model_request)
    settings = client.app.state.settings
    with client.app.state.database.session_factory() as session:
        result = enrich_resource(
            session,
            settings.local_user_id,
            memo["id"],
            settings,
            metadata_fetcher=metadata_fetcher,
        )
        assert result.resource_category_source in {"llm", "jev"}
        assert result.resource_category == custom
    assert settings.deepseek_api_key is None
    assert settings.jev_api_key is None


def test_saved_confidence_threshold_reaches_classification(
    client: TestClient,
) -> None:
    """设置页保存的置信度阈值会用于该账号的分类判定。"""

    assert (
        client.put(
            "/api/v1/model-settings/deepseek",
            json={
                "model": "custom-deepseek",
                "api_key": "private-deepseek-key",
                "base_url": "https://deepseek.relay.example/v1",
                "min_confidence": 0.55,
            },
        ).status_code
        == 200
    )
    read = next(
        item
        for item in client.get("/api/v1/model-settings").json()
        if item["provider"] == "deepseek"
    )
    assert read["min_confidence"] == 0.55
    assert read["default_min_confidence"] == 0.7

    settings = client.app.state.settings
    with client.app.state.database.session_factory() as session:
        resolved = resolve_model_settings(
            session,
            settings.local_user_id,
            settings,
        )
    assert resolved.classification_min_confidence == 0.55
    # 未配置阈值的通道继续使用服务器默认值。
    assert resolved.jev_min_confidence == settings.jev_min_confidence


def test_confidence_threshold_is_validated_and_resettable(
    client: TestClient,
) -> None:
    """阈值必须在 0 到 1 之间，重置配置后回到默认值。"""

    assert (
        client.put(
            "/api/v1/model-settings/jev",
            json={
                "model": "typesafe/jev",
                "api_key": "private-jev-key",
                "min_confidence": 1.5,
            },
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/api/v1/model-settings/jev",
            json={
                "model": "typesafe/jev",
                "api_key": "private-jev-key",
                "min_confidence": 0.4,
            },
        ).status_code
        == 200
    )
    settings = client.app.state.settings
    with client.app.state.database.session_factory() as session:
        resolved = resolve_model_settings(
            session,
            settings.local_user_id,
            settings,
        )
    assert resolved.jev_min_confidence == 0.4
    assert client.delete("/api/v1/model-settings/jev").status_code == 200
    reset = next(
        item
        for item in client.get("/api/v1/model-settings").json()
        if item["provider"] == "jev"
    )
    assert reset["min_confidence"] == settings.jev_min_confidence
