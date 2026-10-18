"""API key lifecycle tests: issuance, authentication, redaction, revocation."""

import hashlib
from uuid import uuid4

from agenttrust_api import models


def _issue(client, admin_headers, project_id, name="ci-key"):
    return client.post(
        "/api/v1/keys",
        json={"project_id": str(project_id), "name": name},
        headers=admin_headers,
    )


def test_issue_key_returns_secret_once(client, admin_headers, project_id, db_session):
    session, _project = db_session
    resp = _issue(client, admin_headers, project_id)
    assert resp.status_code == 201
    body = resp.json()
    raw = body["api_key"]
    assert raw.startswith("at_")
    assert body["key_prefix"] == raw[:15]

    stored = session.query(models.ApiKey).filter_by(id=body["id"]).one()
    assert stored.key_hash != raw  # the secret is never persisted in plaintext
    assert stored.key_hash == hashlib.sha256(raw.encode()).hexdigest()
    assert raw not in stored.key_prefix


def test_issue_key_requires_admin_token(client, project_id):
    resp = client.post(
        "/api/v1/keys",
        json={"project_id": str(project_id)},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "admin_forbidden"


def test_issue_key_unknown_project_returns_404(client, admin_headers):
    resp = client.post(
        "/api/v1/keys", json={"project_id": str(uuid4())}, headers=admin_headers
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "project_not_found"


def test_list_keys_redacts_secrets(client, admin_headers, project_id):
    _issue(client, admin_headers, project_id)
    resp = client.get("/api/v1/keys", headers=admin_headers)
    assert resp.status_code == 200
    items = resp.json()["keys"]
    assert len(items) >= 1
    for item in items:
        assert "api_key" not in item
        assert "key_hash" not in item
        assert item["key_prefix"]


def test_key_authenticates_whoami(client, admin_headers, project_id):
    raw = _issue(client, admin_headers, project_id).json()["api_key"]
    resp = client.get("/api/v1/me", headers={"Authorization": f"Bearer {raw}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["project_id"] == str(project_id)
    assert body["project_name"] == "demo"


def test_invalid_key_rejected(client):
    resp = client.get("/api/v1/me", headers={"Authorization": "Bearer at_nonexistent-key"})
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "invalid_api_key"


def test_revoke_key_disables_it(client, admin_headers, project_id):
    body = _issue(client, admin_headers, project_id).json()
    key_id, raw = body["id"], body["api_key"]

    resp = client.post(f"/api/v1/keys/{key_id}/revoke", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["revoked_at"]

    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {raw}"})
    assert me.status_code == 403
    assert me.json()["error_code"] == "key_revoked"

    again = client.post(f"/api/v1/keys/{key_id}/revoke", headers=admin_headers)
    assert again.status_code == 409
    assert again.json()["error_code"] == "key_already_revoked"


def test_revoke_unknown_key_returns_404(client, admin_headers):
    resp = client.post(f"/api/v1/keys/{uuid4()}/revoke", headers=admin_headers)
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "key_not_found"
