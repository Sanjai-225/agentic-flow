"""Authentication and credential management (secrets are write-only, user-scoped)."""

import uuid

from builders import single_node_after_trigger
from conftest import register
from fastapi.testclient import TestClient


def test_register_login_me(app_client: TestClient):
    email = f"Person_{uuid.uuid4().hex[:6]}@Example.com"
    res = app_client.post("/api/auth/register", json={"email": email, "password": "long-enough-pw"})
    assert res.status_code == 201
    assert res.json()["user"]["email"] == email.lower()
    assert app_client.post("/api/auth/register", json={"email": email, "password": "another-pw-1"}).status_code == 409

    login = app_client.post("/api/auth/login", json={"email": email, "password": "long-enough-pw"})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert app_client.get("/api/auth/me", headers=headers).json()["email"] == email.lower()

    assert app_client.post("/api/auth/login", json={"email": email, "password": "wrong-password"}).status_code == 401
    assert app_client.post("/api/auth/register", json={"email": "x@y.com", "password": "short"}).status_code == 422


def test_protected_endpoints_require_valid_token(app_client: TestClient):
    for method, path in [("get", "/api/workflows"), ("post", "/api/workflows/validate"), ("get", "/api/credentials"),
                         ("get", "/api/executions/exe_x"), ("get", "/api/auth/me")]:
        assert getattr(app_client, method)(path).status_code == 401, path
    bad = {"Authorization": "Bearer not-a-jwt"}
    assert app_client.get("/api/workflows", headers=bad).status_code == 401
    # Public endpoints stay public.
    assert app_client.get("/health").status_code == 200
    assert app_client.get("/api/registry/nodes").status_code == 200


def test_credentials_are_write_only_and_user_scoped(app_client: TestClient, auth_headers):
    res = app_client.post("/api/credentials", json={"type": "http_basic", "name": "Basic",
                                                    "data": {"username": "svc", "password": "pa55word!"}},
                          headers=auth_headers)
    assert res.status_code == 201
    cred = res.json()
    assert cred["hints"] == {"username": "svc"} and "pa55word!" not in res.text

    listing = app_client.get("/api/credentials", headers=auth_headers)
    assert cred["id"] in {c["id"] for c in listing.json()} and "pa55word!" not in listing.text

    other = register(app_client)
    assert cred["id"] not in {c["id"] for c in app_client.get("/api/credentials", headers=other).json()}
    assert app_client.delete(f"/api/credentials/{cred['id']}", headers=other).status_code == 404

    # Another user's workflow cannot reference this credential.
    defn = single_node_after_trigger("http.request", {"url": "https://example.com",
                                                      "auth": {"type": "basic", "credential_id": cred["id"]}})
    v = app_client.post("/api/workflows/validate", json={"definition": defn}, headers=other).json()
    assert any(i["category"] == "MISSING_CREDENTIALS" for i in v["issues"])
    mine = app_client.post("/api/workflows/validate", json={"definition": defn}, headers=auth_headers).json()
    assert mine["valid"] is True

    assert app_client.delete(f"/api/credentials/{cred['id']}", headers=auth_headers).status_code == 204


def test_invalid_credential_payloads(app_client: TestClient, auth_headers):
    assert app_client.post("/api/credentials", json={"type": "oauth_magic", "name": "x", "data": {}},
                           headers=auth_headers).status_code == 422
    assert app_client.post("/api/credentials", json={"type": "http_bearer", "name": "x", "data": {}},
                           headers=auth_headers).status_code == 422
    assert app_client.get("/api/credentials/types").json()["http_header"] == ["name", "value"]
