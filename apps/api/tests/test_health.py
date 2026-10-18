"""Health endpoint tests."""


def test_live_returns_ok(client):
    resp = client.get("/health/live")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "agenttrust-api"
    assert body["timestamp"]
    assert resp.headers["x-request-id"]


def test_ready_reports_database_up(client):
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json()["database"] == "up"


def test_unknown_route_returns_structured_error(client):
    resp = client.get("/no-such-route")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error_code"] == "http_404"
    assert body["message"]
    assert body["request_id"]
