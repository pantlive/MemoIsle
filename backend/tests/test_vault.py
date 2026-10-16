"""密码库接口测试：服务器只存密文，按账号隔离。"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import replace
from uuid import uuid4

from app.auth_service import create_dev_session
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from fastapi.testclient import TestClient

ITERATIONS = 600_000
# 与浏览器端 vault.ts 保持一致。
KEY_WRAP_AAD = b"memoisle-vault-key:v1"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def make_vault(password: str) -> tuple[dict[str, object], bytes]:
    """按浏览器端同样的方式生成包裹参数，返回请求体和明文库密钥。"""

    salt = os.urandom(16)
    kek = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=ITERATIONS,
    ).derive(password.encode())
    vault_key = AESGCM.generate_key(bit_length=256)
    wrap_iv = os.urandom(12)
    wrapped = AESGCM(kek).encrypt(wrap_iv, vault_key, KEY_WRAP_AAD)
    payload = {
        "kdf": "pbkdf2-sha256",
        "kdf_iterations": ITERATIONS,
        "kdf_salt": b64(salt),
        "wrapped_key": b64(wrapped),
        "wrap_iv": b64(wrap_iv),
    }
    return payload, vault_key


def encrypt_item(
    vault_key: bytes, item_id: str, data: dict[str, object]
) -> dict[str, str]:
    iv = os.urandom(12)
    aad = f"memoisle-vault-item:v1:{item_id}".encode()
    ciphertext = AESGCM(vault_key).encrypt(iv, json.dumps(data).encode(), aad)
    return {"ciphertext": b64(ciphertext), "iv": b64(iv)}


def test_vault_setup_unlock_material_and_item_crud(client: TestClient) -> None:
    """设置后可取回包裹参数解锁，条目增改删都按版本号，服务器看不到明文。"""

    assert client.get("/api/v1/vault").json() == {
        "configured": False,
        "kdf": None,
        "kdf_iterations": None,
        "kdf_salt": None,
        "wrapped_key": None,
        "wrap_iv": None,
        "version": None,
        "item_count": 0,
    }
    assert client.get("/api/v1/vault/items").status_code == 404

    payload, vault_key = make_vault("correct horse battery")
    created = client.post("/api/v1/vault", json=payload)
    assert created.status_code == 201
    assert client.post("/api/v1/vault", json=payload).status_code == 409

    status = client.get("/api/v1/vault").json()
    assert status["configured"] is True
    # 用主密码重新派生即可解开库密钥。
    kek = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=base64.b64decode(status["kdf_salt"]),
        iterations=status["kdf_iterations"],
    ).derive(b"correct horse battery")
    unwrapped = AESGCM(kek).decrypt(
        base64.b64decode(status["wrap_iv"]),
        base64.b64decode(status["wrapped_key"]),
        KEY_WRAP_AAD,
    )
    assert unwrapped == vault_key

    item_id = str(uuid4())
    secret = {"kind": "login", "title": "GitHub", "password": "hunter2-very-secret"}
    response = client.post(
        "/api/v1/vault/items",
        json={"id": item_id, **encrypt_item(vault_key, item_id, secret)},
    )
    assert response.status_code == 201
    item = response.json()
    assert item["version"] == 1
    assert "hunter2" not in response.text and "GitHub" not in response.text
    assert client.get("/api/v1/vault").json()["item_count"] == 1

    updated = client.put(
        f"/api/v1/vault/items/{item_id}",
        json={
            "expected_version": 1,
            **encrypt_item(vault_key, item_id, {**secret, "title": "GitHub 2"}),
        },
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    stale = client.put(
        f"/api/v1/vault/items/{item_id}",
        json={"expected_version": 1, **encrypt_item(vault_key, item_id, secret)},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["current"]["version"] == 2

    listed = client.get("/api/v1/vault/items").json()
    assert [entry["id"] for entry in listed] == [item_id]
    aad = f"memoisle-vault-item:v1:{item_id}".encode()
    plain = AESGCM(vault_key).decrypt(
        base64.b64decode(listed[0]["iv"]),
        base64.b64decode(listed[0]["ciphertext"]),
        aad,
    )
    assert json.loads(plain)["title"] == "GitHub 2"

    assert (
        client.delete(
            f"/api/v1/vault/items/{item_id}",
            params={"expected_version": 1},
        ).status_code
        == 409
    )
    assert (
        client.delete(
            f"/api/v1/vault/items/{item_id}",
            params={"expected_version": 2},
        ).status_code
        == 204
    )
    assert client.get("/api/v1/vault/items").json() == []


def test_vault_rejects_malformed_material(client: TestClient) -> None:
    """拒绝过少迭代、错误长度和非 Base64 的数据。"""

    payload, vault_key = make_vault("another long password")
    weak = {**payload, "kdf_iterations": 100_000}
    assert client.post("/api/v1/vault", json=weak).status_code == 422
    assert (
        client.post(
            "/api/v1/vault", json={**payload, "wrap_iv": b64(os.urandom(16))}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/vault", json={**payload, "wrapped_key": "not base64!"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/vault", json={**payload, "kdf_salt": b64(os.urandom(8))}
        ).status_code
        == 422
    )
    assert client.post("/api/v1/vault", json=payload).status_code == 201

    item_id = str(uuid4())
    encrypted = encrypt_item(vault_key, item_id, {"title": "x"})
    assert (
        client.post(
            "/api/v1/vault/items",
            json={"id": item_id, **encrypted, "iv": b64(os.urandom(8))},
        ).status_code
        == 422
    )
    too_big = b64(os.urandom(64 * 1024 + 1))
    assert (
        client.post(
            "/api/v1/vault/items",
            json={"id": item_id, "ciphertext": too_big, "iv": encrypted["iv"]},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/vault/items", json={"id": item_id, **encrypted}
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/v1/vault/items", json={"id": item_id, **encrypted}
        ).status_code
        == 409
    )


def test_change_master_password_and_reset(client: TestClient) -> None:
    """更改主密码只替换包裹参数；清空需要固定确认参数。"""

    payload, vault_key = make_vault("first master password")
    client.post("/api/v1/vault", json=payload)
    item_id = str(uuid4())
    client.post(
        "/api/v1/vault/items",
        json={"id": item_id, **encrypt_item(vault_key, item_id, {"t": 1})},
    )

    new_payload, _ = make_vault("second master password")
    assert (
        client.put(
            "/api/v1/vault/key", json={**new_payload, "expected_version": 2}
        ).status_code
        == 409
    )
    changed = client.put(
        "/api/v1/vault/key", json={**new_payload, "expected_version": 1}
    )
    assert changed.status_code == 200
    assert changed.json()["version"] == 2
    assert changed.json()["kdf_salt"] == new_payload["kdf_salt"]
    assert changed.json()["item_count"] == 1

    assert client.delete("/api/v1/vault", params={"confirm": "yes"}).status_code == 400
    assert client.get("/api/v1/vault").json()["configured"] is True
    assert (
        client.delete(
            "/api/v1/vault",
            params={"confirm": "delete-all-vault-items"},
        ).status_code
        == 204
    )
    assert client.get("/api/v1/vault").json()["configured"] is False
    # 清空后可以重新设置。
    assert client.post("/api/v1/vault", json=payload).status_code == 201
    assert client.get("/api/v1/vault").json()["item_count"] == 0


def test_vault_is_account_scoped_and_kept_out_of_memos(client: TestClient) -> None:
    """其他账号看不到也改不了；密码库不出现在内容列表、搜索和导出里。"""

    assert client.post("/api/v1/auth/dev-login").status_code == 200
    payload, vault_key = make_vault("owner master password")
    client.post("/api/v1/vault", json=payload)
    item_id = str(uuid4())
    client.post(
        "/api/v1/vault/items",
        json={"id": item_id, **encrypt_item(vault_key, item_id, {"t": 1})},
    )

    assert client.get("/api/v1/memos").json()["total_count"] == 0
    exported = client.get("/api/v1/exports/json")
    assert exported.status_code == 200
    assert item_id not in exported.text and payload["wrapped_key"] not in exported.text

    settings = client.app.state.settings
    with client.app.state.database.session_factory() as session:
        token = create_dev_session(
            session, replace(settings, local_user_id=str(uuid4()))
        ).token
    client.app.state.settings = replace(settings, auth_dev_mode=False)
    other = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/vault", headers=other).json()["configured"] is False
    assert client.get("/api/v1/vault/items", headers=other).status_code == 404
    other_payload, other_key = make_vault("intruder master password")
    client.post("/api/v1/vault", json=other_payload, headers=other)
    assert client.get("/api/v1/vault/items", headers=other).json() == []
    assert (
        client.put(
            f"/api/v1/vault/items/{item_id}",
            json={"expected_version": 1, **encrypt_item(other_key, item_id, {"t": 2})},
            headers=other,
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/vault/items/{item_id}",
            params={"expected_version": 1},
            headers=other,
        ).status_code
        == 404
    )
    # 同一 ID 不能被其他账号抢占。
    assert (
        client.post(
            "/api/v1/vault/items",
            json={"id": item_id, **encrypt_item(other_key, item_id, {"t": 3})},
            headers=other,
        ).status_code
        == 409
    )
