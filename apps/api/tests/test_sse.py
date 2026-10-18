"""SSE stream tests (M08 realtime): backfill, live delivery, resume,
project isolation, heartbeats, and bounded subscriptions.

The stream generator reads through its own database sessions, so fixtures
here commit a real stack via SessionLocal (like test_sdk.py) instead of the
transactional db_session fixture.
"""

import socket
import threading
import time
import uuid

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from agenttrust_api.config import settings
from agenttrust_api.db import SessionLocal
from agenttrust_api.events import record_event
from agenttrust_api.main import create_app
from agenttrust_api.models import AgentRun, ApiKey, Project, User
from agenttrust_api.security import generate_api_key
from agenttrust_api.util import utcnow


@pytest.fixture()
def stack():
    """Committed (user, project, api key); cleaned up after the test."""
    suffix = uuid.uuid4().hex[:8]
    session = SessionLocal()
    try:
        user = User(username=f"sse-{suffix}")
        session.add(user)
        session.flush()
        project = Project(name=f"sse-{suffix}", owner_id=user.id)
        session.add(project)
        session.flush()
        raw, prefix, digest = generate_api_key()
        session.add(
            ApiKey(
                project_id=project.id,
                name="sse",
                key_prefix=prefix,
                key_hash=digest,
                scopes=["*"],
            )
        )
        session.commit()
        yield {"api_key": raw, "project_id": project.id}
    finally:
        session.query(ApiKey).filter(ApiKey.project_id == project.id).delete()
        session.query(AgentRun).filter(AgentRun.project_id == project.id).delete()
        session.query(Project).filter(Project.id == project.id).delete()
        session.query(User).filter(User.username == f"sse-{suffix}").delete()
        session.commit()
        session.close()


@pytest.fixture()
def sse_client():
    """Plain TestClient (no dependency overrides needed for the stream)."""
    app = create_app()
    with TestClient(app) as client:
        yield client


def _seed_events(project_id, kinds, run_id=None):
    """Commit N events; returns the assigned project_seqs."""
    session = SessionLocal()
    try:
        seqs = []
        for kind in kinds:
            event = record_event(
                session,
                project_id=project_id,
                run_id=run_id,
                kind=kind,
                payload_redacted={"n": kind},
            )
            seqs.append(event.project_seq)
        session.commit()
        return seqs
    finally:
        session.close()


def _stream_url(raw_key, cursor=None):
    url = f"/api/v1/events/stream?api_key={raw_key}"
    if cursor is not None:
        url += f"&cursor={cursor}"
    return url


def _collect_data_lines(response, want, timeout=10.0):
    """Read SSE data lines until `want` data payloads arrive."""
    data_lines = []
    id_lines = []
    deadline = time.time() + timeout
    for line in response.iter_lines():
        if time.time() > deadline:
            break
        if line.startswith("id:"):
            id_lines.append(line)
        elif line.startswith("data:"):
            data_lines.append(line)
            if len(data_lines) >= want:
                break
    return id_lines, data_lines


def test_backfill_respects_cursor_and_order(sse_client, stack, monkeypatch):
    monkeypatch.setattr(settings, "AGENTTRUST_SSE_MAX_SECONDS", 30.0)
    kinds = [f"test.evt{i}" for i in range(5)]
    seqs = _seed_events(stack["project_id"], kinds)
    assert seqs == [1, 2, 3, 4, 5]

    with sse_client.stream(
        "GET",
        _stream_url(stack["api_key"]),
        headers={"Last-Event-ID": "2"},
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        id_lines, data_lines = _collect_data_lines(resp, 3)

    assert id_lines == ["id: 3", "id: 4", "id: 5"]
    assert len(data_lines) == 3
    for line, kind, seq in zip(data_lines, kinds[2:], [3, 4, 5], strict=True):
        assert f'"kind":"{kind}"' in line
        assert f'"project_seq":{seq}' in line


def test_backfill_repeat_is_byte_identical(sse_client, stack, monkeypatch):
    """Same cursor twice -> identical bytes: clients can dedup safely."""
    monkeypatch.setattr(settings, "AGENTTRUST_SSE_MAX_SECONDS", 30.0)
    _seed_events(stack["project_id"], ["test.a", "test.b"])

    def once():
        with sse_client.stream(
            "GET", _stream_url(stack["api_key"], cursor=0)
        ) as resp:
            ids, data = _collect_data_lines(resp, 2)
            return ids, data

    assert once() == once()


def test_live_event_arrives_within_deadline(live_server):
    """An event committed mid-connection is delivered to the open stream.

    Uses a real uvicorn server: TestClient's in-process portal cannot serve
    an infinite SSE stream from a spawned thread (harness limitation —
    verified with a minimal repro), while the production topology is a real
    HTTP server anyway.
    """
    suffix = uuid.uuid4().hex[:8]
    session = SessionLocal()
    try:
        user = User(username=f"sse-live-{suffix}")
        session.add(user)
        session.flush()
        project = Project(name=f"sse-live-{suffix}", owner_id=user.id)
        session.add(project)
        session.flush()
        raw, prefix, digest = generate_api_key()
        session.add(
            ApiKey(project_id=project.id, name="live", key_prefix=prefix,
                   key_hash=digest, scopes=["*"])
        )
        session.commit()
        project_id = project.id
    finally:
        session.close()

    received: list[str] = []

    def reader():
        with httpx.stream(
            "GET",
            f"{live_server}/api/v1/events/stream",
            params={"api_key": raw},
            timeout=15.0,
            trust_env=False,
        ) as resp:
            assert resp.status_code == 200
            for line in resp.iter_lines():
                if line.startswith("data:") and '"kind":"live.ping"' in line:
                    received.append(line)
                    break

    try:
        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        time.sleep(1.0)  # let the stream connect and finish backfill
        _seed_events(project_id, ["live.ping"])
        thread.join(timeout=10.0)
        assert len(received) == 1, "live event was not delivered to the open stream"
    finally:
        cleanup = SessionLocal()
        try:
            cleanup.query(ApiKey).filter(ApiKey.project_id == project_id).delete()
            cleanup.query(Project).filter(Project.id == project_id).delete()
            cleanup.query(User).filter(User.username == f"sse-live-{suffix}").delete()
            cleanup.commit()
        finally:
            cleanup.close()


def test_project_isolation(sse_client, stack, monkeypatch):
    """Project B's key receives none of project A's events."""
    monkeypatch.setattr(settings, "AGENTTRUST_SSE_MAX_SECONDS", 3.0)
    monkeypatch.setattr(settings, "AGENTTRUST_SSE_HEARTBEAT_SECONDS", 60.0)
    _seed_events(stack["project_id"], ["secret.a", "secret.b", "secret.c"])

    other = SessionLocal()
    try:
        user = User(username=f"sse-other-{uuid.uuid4().hex[:8]}")
        other.add(user)
        other.flush()
        project = Project(name=f"sse-other-{user.username}", owner_id=user.id)
        other.add(project)
        other.flush()
        raw, prefix, digest = generate_api_key()
        other.add(
            ApiKey(
                project_id=project.id,
                name="other",
                key_prefix=prefix,
                key_hash=digest,
                scopes=["*"],
            )
        )
        other.commit()
        other_project_id, other_key = project.id, raw
    finally:
        other.close()

    try:
        with sse_client.stream("GET", _stream_url(other_key)) as resp:
            assert resp.status_code == 200
            _ids, data = _collect_data_lines(resp, 1, timeout=4.0)
        assert data == [], "project B received project A's events"
    finally:
        cleanup = SessionLocal()
        try:
            cleanup.query(ApiKey).filter(ApiKey.project_id == other_project_id).delete()
            cleanup.query(Project).filter(Project.id == other_project_id).delete()
            cleanup.query(User).filter(User.username == user.username).delete()
            cleanup.commit()
        finally:
            cleanup.close()


def test_forged_cursor_yields_nothing(sse_client, stack, monkeypatch):
    monkeypatch.setattr(settings, "AGENTTRUST_SSE_MAX_SECONDS", 3.0)
    monkeypatch.setattr(settings, "AGENTTRUST_SSE_HEARTBEAT_SECONDS", 60.0)
    _seed_events(stack["project_id"], ["test.a"])
    with sse_client.stream(
        "GET",
        _stream_url(stack["api_key"]),
        headers={"Last-Event-ID": "999999"},
    ) as resp:
        assert resp.status_code == 200
        _ids, data = _collect_data_lines(resp, 1, timeout=4.0)
    assert data == []


def test_invalid_cursor_rejected(sse_client, stack):
    resp = sse_client.get(
        _stream_url(stack["api_key"]),
        headers={"Last-Event-ID": "not-a-number"},
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "invalid_cursor"


def test_heartbeat_received(sse_client, stack, monkeypatch):
    monkeypatch.setattr(settings, "AGENTTRUST_SSE_HEARTBEAT_SECONDS", 1.0)
    monkeypatch.setattr(settings, "AGENTTRUST_SSE_MAX_SECONDS", 30.0)
    with sse_client.stream("GET", _stream_url(stack["api_key"])) as resp:
        assert resp.status_code == 200
        deadline = time.time() + 8.0
        saw_ping = False
        for line in resp.iter_lines():
            if time.time() > deadline:
                break
            if line == ": ping":
                saw_ping = True
                break
    assert saw_ping, "no SSE heartbeat comment received"


def test_stream_is_bounded(sse_client, stack, monkeypatch):
    """A subscription ends after AGENTTRUST_SSE_MAX_SECONDS (client reconnects)."""
    monkeypatch.setattr(settings, "AGENTTRUST_SSE_MAX_SECONDS", 2.0)
    monkeypatch.setattr(settings, "AGENTTRUST_SSE_HEARTBEAT_SECONDS", 60.0)
    start = time.time()
    with sse_client.stream("GET", _stream_url(stack["api_key"])) as resp:
        assert resp.status_code == 200
        list(resp.iter_lines())  # consume until the server closes
    assert time.time() - start < 10.0


def test_stream_requires_valid_key(sse_client, stack):
    resp = sse_client.get("/api/v1/events/stream?api_key=at_bogus")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# SDK event ingestion + run lifecycle telemetry, over real HTTP.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live_server():
    app = create_app()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 15
    while True:
        try:
            httpx.get(f"{base}/health/live", timeout=1.0, trust_env=False)
            break
        except Exception:
            if time.time() > deadline:
                raise TimeoutError("test server did not start") from None
            time.sleep(0.1)
    yield base
    server.should_exit = True
    thread.join(timeout=10)


def test_sdk_report_event_persists_and_streams(live_server):
    """report_event -> 201 -> visible in a later SSE backfill."""
    from agenttrust import AgentTrust

    suffix = uuid.uuid4().hex[:8]
    session = SessionLocal()
    try:
        user = User(username=f"sse-sdk-{suffix}")
        session.add(user)
        session.flush()
        project = Project(name=f"sse-sdk-{suffix}", owner_id=user.id)
        session.add(project)
        session.flush()
        raw, prefix, digest = generate_api_key()
        session.add(
            ApiKey(project_id=project.id, name="sdk", key_prefix=prefix,
                   key_hash=digest, scopes=["*"])
        )
        session.flush()
        run = AgentRun(project_id=project.id, state="RUNNING", started_at=utcnow())
        session.add(run)
        session.commit()
        run_id, project_id = run.id, project.id
    finally:
        session.close()

    try:
        trust = AgentTrust(api_key=raw, base_url=live_server)
        body = trust.report_event(str(run_id), "agent.thinking", {"step": 1})
        assert body["accepted"] == 1
        assert body["first_seq"] == body["last_seq"] == 1

        # The ingested event shows up in the SSE backfill.
        # trust_env=False: this host's proxy env vars crash httpx's proxy
        # handling (same root cause as ADR-026); the stream must not be
        # routed through the egress proxy anyway.
        stream = httpx.stream(
            "GET",
            f"{live_server}/api/v1/events/stream",
            params={"api_key": raw},
            timeout=10.0,
            trust_env=False,
        )
        with stream as resp:
            assert resp.status_code == 200
            for line in resp.iter_lines():
                if line.startswith("data:") and '"kind":"agent.thinking"' in line:
                    assert '"project_seq":1' in line
                    break
            else:
                raise AssertionError("ingested event missing from SSE backfill")
    finally:
        cleanup = SessionLocal()
        try:
            cleanup.query(AgentRun).filter(AgentRun.id == run_id).delete()
            cleanup.query(ApiKey).filter(ApiKey.project_id == project_id).delete()
            cleanup.query(Project).filter(Project.id == project_id).delete()
            cleanup.query(User).filter(User.username == f"sse-sdk-{suffix}").delete()
            cleanup.commit()
        finally:
            cleanup.close()


def test_sdk_run_context_emits_lifecycle_events(live_server):
    """trust.run() emits run.started / run.completed around the block."""
    from agenttrust import AgentTrust

    suffix = uuid.uuid4().hex[:8]
    session = SessionLocal()
    try:
        user = User(username=f"sse-run-{suffix}")
        session.add(user)
        session.flush()
        project = Project(name=f"sse-run-{suffix}", owner_id=user.id)
        session.add(project)
        session.flush()
        raw, prefix, digest = generate_api_key()
        session.add(
            ApiKey(project_id=project.id, name="sdk", key_prefix=prefix,
                   key_hash=digest, scopes=["*"])
        )
        session.commit()
        project_id = project.id
    finally:
        session.close()

    try:
        trust = AgentTrust(api_key=raw, base_url=live_server)
        with trust.run(agent="sse-agent", version="9.9.9") as run_id:
            assert run_id
        # And the failure path.
        try:
            with trust.run(agent="sse-agent", version="9.9.9"):
                raise RuntimeError("boom")
        except RuntimeError:
            pass

        check = SessionLocal()
        try:
            from agenttrust_api.models import Event

            kinds = [
                e.kind
                for e in check.query(Event)
                .filter(Event.project_id == project_id)
                .order_by(Event.project_seq)
                .all()
            ]
        finally:
            check.close()
        assert "run.started" in kinds
        assert "run.completed" in kinds
        assert "run.failed" in kinds
    finally:
        cleanup = SessionLocal()
        try:
            cleanup.query(AgentRun).filter(AgentRun.project_id == project_id).delete()
            cleanup.query(ApiKey).filter(ApiKey.project_id == project_id).delete()
            cleanup.query(Project).filter(Project.id == project_id).delete()
            cleanup.query(User).filter(User.username == f"sse-run-{suffix}").delete()
            cleanup.commit()
        finally:
            cleanup.close()
