"""自定义请求地址、默认回退与旧配置迁移的回归测试。"""

from __future__ import annotations

from dataclasses import replace

import httpx
import pytest
from app.config import Settings
from app.model_settings_service import (
    resolve_model_settings,
    verify_model_connection,
)
from app.models import ModelProviderSetting
from app.schemas import (
    ModelConnectionResult,
    ModelProvider,
    ModelSettingUpdate,
)
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session


@pytest.mark.parametrize(
    "provider,endpoint",
    [
        (ModelProvider.DEEPSEEK, "/chat/completions"),
        (ModelProvider.JEV, "/systemone"),
    ],
)
def test_custom_url_normalizes_and_survives_model_only_updates(
    client: TestClient,
    provider: ModelProvider,
    endpoint: str,
) -> None:
    """完整接口地址只拼一次端点，旧客户端省略地址时保留配置。"""

    base = "https://relay.example/custom/v1"
    response = client.put(
        f"/api/v1/model-settings/{provider}",
        json={
            "model": "relay-model",
            "base_url": f" {base}{endpoint}/ ",
            "api_key": "relay-private-key",
        },
    )
    assert response.status_code == 200
    assert response.json()["base_url"] == base
    assert response.json()["custom_base_url"] == base
    updated = client.put(
        f"/api/v1/model-settings/{provider}",
        json={
            "model": "updated-relay-model",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["base_url"] == base
    settings = client.app.state.settings
    with client.app.state.database.session_factory() as session:
        resolved = resolve_model_settings(
            session, settings.local_user_id, settings
        )
    assert getattr(resolved, f"{provider}_base_url") == base
    assert getattr(resolved, f"{provider}_model") == "updated-relay-model"
    assert getattr(resolved, f"{provider}_api_key") == "relay-private-key"
    assert getattr(settings, f"{provider}_base_url") != base


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_blank_address_restores_default(
    client: TestClient,
    blank: str | None,
) -> None:
    """主动清空请求地址时恢复默认服务，并使用用户对应的新密钥。"""

    client.put(
        "/api/v1/model-settings/deepseek",
        json={
            "model": "relay-model",
            "base_url": "https://relay.example/v1",
            "api_key": "relay-private-key",
        },
    ).raise_for_status()
    restored = client.put(
        "/api/v1/model-settings/deepseek",
        json={
            "model": "deepseek-flash",
            "base_url": blank,
            "api_key": "official-private-key",
        },
    )
    assert restored.status_code == 200
    assert restored.json()["custom_base_url"] is None
    assert (
        restored.json()["base_url"]
        == client.app.state.settings.deepseek_base_url
    )
    assert restored.json()["key_hint"].endswith("-key")


def test_changing_service_never_reuses_existing_or_environment_key(
    client: TestClient,
) -> None:
    """更换服务不能悄悄带走服务器默认或账号已经保存的密钥。"""

    settings = client.app.state.settings
    # 分别覆盖服务器默认凭据与账号凭据两种来源。
    client.app.state.settings = replace(
        settings, deepseek_api_key="server-key"
    )
    for existing_key in [None, "account-private-key"]:
        if existing_key:
            client.put(
                "/api/v1/model-settings/deepseek",
                json={
                    "model": "deepseek-flash",
                    "api_key": existing_key,
                },
            ).raise_for_status()
        for endpoint in ["/deepseek", "/deepseek/test"]:
            method = (
                client.put if not endpoint.endswith("/test") else client.post
            )
            response = method(
                f"/api/v1/model-settings{endpoint}",
                json={
                    "model": "relay-model",
                    "base_url": "https://other.example/v1",
                },
            )
            assert response.status_code == 400
            assert "对应服务的 API Key" in response.json()["detail"]
            assert "server-key" not in response.text
            assert "account-private-key" not in response.text
        saved = client.get("/api/v1/model-settings").json()[0]
        assert saved["custom_base_url"] is None
        assert saved["model"] == "deepseek-flash"


def test_same_service_path_change_preserves_key(client: TestClient) -> None:
    """同一服务的基础路径调整可以继续使用已经保存的密钥。"""

    client.put(
        "/api/v1/model-settings/deepseek",
        json={
            "model": "relay-model",
            "base_url": "https://relay.example/v1",
            "api_key": "relay-private-key",
        },
    ).raise_for_status()
    response = client.put(
        "/api/v1/model-settings/deepseek",
        json={
            "model": "relay-model",
            "base_url": "https://relay.example:443/v2",
        },
    )
    assert response.status_code == 200
    assert response.json()["has_api_key"] is True
    assert response.json()["base_url"] == "https://relay.example:443/v2"


@pytest.mark.parametrize(
    "address",
    [
        "relay.example/v1",
        "ftp://relay.example/v1",
        "https://user:sensitive-password@relay.example/v1",
        "https://relay.example/v1?api_key=sensitive-password",
        "https://relay.example/v1#fragment",
        "https://relay.example:invalid/v1",
        "https://relay.example:0/v1",
        "https://relay.example/bad path",
    ],
)
def test_invalid_addresses_do_not_echo_secrets(
    client: TestClient,
    address: str,
) -> None:
    """拒绝异常协议、内嵌凭据及查询参数，校验响应不暴露输入。"""

    response = client.put(
        "/api/v1/model-settings/deepseek",
        json={
            "model": "relay-model",
            "base_url": address,
            "api_key": "sensitive-request-key",
        },
    )
    assert response.status_code == 422
    assert "sensitive-password" not in response.text
    assert "sensitive-request-key" not in response.text


@pytest.mark.parametrize(
    "provider,endpoint",
    [
        (ModelProvider.DEEPSEEK, "/chat/completions"),
        (ModelProvider.JEV, "/systemone"),
    ],
)
def test_unsaved_address_is_used_for_connection_test(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    provider: ModelProvider,
    endpoint: str,
) -> None:
    """连接测试立即使用未保存地址和模型，但不改变账号设置。"""

    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """模拟兼容中转，记录实际收到的请求。"""

        calls.append(request)
        if provider == ModelProvider.DEEPSEEK:
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "OK"}}],
                },
            )
        return httpx.Response(
            200,
            json={
                "answers": {"test": {"choice": "ok", "confidence": 0.99}},
            },
        )

    def verify(
        session: Session,
        user_id: str,
        settings: Settings,
        selected: ModelProvider,
        payload: ModelSettingUpdate | None,
    ) -> ModelConnectionResult:
        """保留真实配置解析，仅替换外部 HTTP 传输。"""

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
    result = client.post(
        f"/api/v1/model-settings/{provider}/test",
        json={
            "model": "relay-model",
            "base_url": f"https://relay.example/v1{endpoint}",
            "api_key": "relay-private-key",
        },
    )
    assert result.status_code == 200
    assert str(calls[0].url) == f"https://relay.example/v1{endpoint}"
    assert calls[0].headers["authorization"] == "Bearer relay-private-key"
    default = client.get("/api/v1/model-settings").json()
    assert all(item["custom_base_url"] is None for item in default)


def test_old_configuration_table_migrates_without_losing_credentials(
    client: TestClient,
) -> None:
    """升级旧表只增加地址列，保留账号、模型和加密凭据。"""

    client.put(
        "/api/v1/model-settings/deepseek",
        json={
            "model": "old-model",
            "api_key": "old-private-key",
        },
    ).raise_for_status()
    database = client.app.state.database
    user_id = client.app.state.settings.local_user_id
    with database.session_factory() as session:
        saved = session.get(ModelProviderSetting, (user_id, "deepseek"))
        assert saved is not None
        old_cipher = saved.credential_cipher
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE model_provider_setting DROP COLUMN base_url",
            )
        )
    database.create_schema()
    database.create_schema()
    summary = client.get("/api/v1/model-settings").json()[0]
    assert summary["custom_base_url"] is None
    assert summary["model"] == "old-model"
    assert summary["has_api_key"] is True
    with database.session_factory() as session:
        saved = session.get(ModelProviderSetting, (user_id, "deepseek"))
        assert saved is not None
        assert saved.credential_cipher == old_cipher


def test_model_provider_setting_migrates_min_confidence(
    client: TestClient,
) -> None:
    """旧库缺少分类阈值列时，升级只补字段、不丢凭据。"""

    database = client.app.state.database
    user_id = client.app.state.settings.local_user_id
    client.put(
        "/api/v1/model-settings/deepseek",
        json={"model": "old-model", "api_key": "old-private-key"},
    ).raise_for_status()
    with database.session_factory() as session:
        saved = session.get(ModelProviderSetting, (user_id, "deepseek"))
        assert saved is not None
        old_cipher = saved.credential_cipher
    with database.engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE model_provider_setting DROP COLUMN min_confidence"),
        )
    database.create_schema()
    columns = {
        column["name"]
        for column in inspect(database.engine).get_columns("model_provider_setting")
    }
    assert "min_confidence" in columns
    with database.session_factory() as session:
        saved = session.get(ModelProviderSetting, (user_id, "deepseek"))
        assert saved is not None
        assert saved.credential_cipher == old_cipher
        assert saved.min_confidence is None
