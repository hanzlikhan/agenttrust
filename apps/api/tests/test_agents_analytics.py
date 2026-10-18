"""Agents directory + analytics read endpoints (M09, Phase 6).

Seeds rows directly in the transactional test session so timestamps are
exact (e.g. a decision 20 days old must fall outside the 14-day window).
All reads go through the same session via the overridden get_db.
"""

import uuid
from datetime import timedelta

from agenttrust_api import models
from agenttrust_api.security import generate_api_key
from agenttrust_api.util import utcnow


def _key_for(session, project_id):
    raw, prefix, digest = generate_api_key()
    session.add(
        models.ApiKey(
            project_id=project_id, name="analytics-test", key_prefix=prefix,
            key_hash=digest, scopes=["*"],
        )
    )
    session.flush()
    return {"Authorization": f"Bearer {raw}"}


def _agent(session, project_id, name, version="1.0.0", environment="local"):
    agent = models.Agent(
        project_id=project_id, name=name, version=version,
        environment=environment, created_at=utcnow(),
    )
    session.add(agent)
    session.flush()
    return agent


def _run(session, project_id, agent_id, started_at, state="COMPLETED", ended_at=None):
    run = models.AgentRun(
        project_id=project_id, agent_id=agent_id, state=state,
        started_at=started_at, ended_at=ended_at or started_at,
    )
    session.add(run)
    session.flush()
    return run


def _tool_def(session, project_id, slug):
    tool = models.ToolDefinition(
        project_id=project_id, slug=slug, version=1,
        schema_json={"type": "object"}, risk_class="high_impact",
        created_at=utcnow(),
    )
    session.add(tool)
    session.flush()
    return tool


_call_seq = 0


def _call_with_decision(
    session, project_id, run_id, tool_id, outcome, decided_at, reason="test_reason",
):
    global _call_seq
    _call_seq += 1
    call = models.ToolCall(
        project_id=project_id, run_id=run_id, tool_id=tool_id,
        args_redacted={}, args_hash=f"hash-{_call_seq}",
        state="DECIDED", idempotency_key=f"idem-{uuid.uuid4().hex}",
        created_at=decided_at,
    )
    session.add(call)
    session.flush()
    session.add(
        models.PolicyDecision(
            tool_call_id=call.id, version_id=None, outcome=outcome,
            reason_code=reason, explanation="seeded for analytics tests",
            decided_at=decided_at,
        )
    )
    session.flush()
    return call


# ---------------------------------------------------------------------------
# Agents list / detail
# ---------------------------------------------------------------------------


def test_agents_list_pagination_and_run_counts(client, db_session, project_id):
    session, _ = db_session
    headers = _key_for(session, project_id)
    now = utcnow()
    agents = [_agent(session, project_id, f"agent-{i}") for i in range(3)]
    # agent-0 gets 2 runs; the rest get none.
    _run(session, project_id, agents[0].id, now - timedelta(hours=2))
    later_run = _run(session, project_id, agents[0].id, now - timedelta(hours=1))

    resp = client.get("/api/v1/agents?limit=2", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 3
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert len(body["agents"]) == 2

    resp = client.get("/api/v1/agents?limit=2&offset=2", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["offset"] == 2
    assert len(body["agents"]) == 1

    # Full list: newest agents first, run counts + last_run_at correct.
    body = client.get("/api/v1/agents?limit=100", headers=headers).json()
    assert body["total"] == 3
    by_name = {a["name"]: a for a in body["agents"]}
    assert by_name["agent-0"]["run_count"] == 2
    assert by_name["agent-0"]["last_run_at"] is not None
    assert by_name["agent-1"]["run_count"] == 0
    assert by_name["agent-1"]["last_run_at"] is None
    # last_run_at is the newest run's start.
    assert by_name["agent-0"]["last_run_at"].startswith(
        later_run.started_at.date().isoformat()
    )


def test_agents_project_isolation(client, db_session, project_id):
    session, project = db_session
    headers = _key_for(session, project_id)
    own = _agent(session, project_id, "own-agent")

    # A second project with its own agent.
    owner = models.User(username=f"other-owner-{uuid.uuid4().hex[:8]}")
    session.add(owner)
    session.flush()
    other_project = models.Project(name="other", owner_id=owner.id)
    session.add(other_project)
    session.flush()
    foreign = _agent(session, other_project.id, "foreign-agent")

    # List shows only our agent.
    body = client.get("/api/v1/agents", headers=headers).json()
    names = [a["name"] for a in body["agents"]]
    assert names == ["own-agent"]
    assert str(foreign.id) not in str(body)

    # Detail of the foreign agent is a clean 404 that leaks nothing.
    resp = client.get(f"/api/v1/agents/{foreign.id}", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "agent_not_found"
    assert str(other_project.id) not in resp.text
    assert str(foreign.id) not in resp.text

    # Our own agent resolves.
    resp = client.get(f"/api/v1/agents/{own.id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "own-agent"


def test_agent_detail_recent_runs(client, db_session, project_id):
    session, _ = db_session
    headers = _key_for(session, project_id)
    agent = _agent(session, project_id, "busy-agent")
    now = utcnow()
    # 21 runs: the endpoint caps recent_runs at 20, total_runs reports 21.
    for i in range(21):
        run = _run(session, project_id, agent.id, now - timedelta(minutes=i))
        if i % 2 == 0:
            call = models.ToolCall(
                project_id=project_id, run_id=run.id, tool_id=None,
                args_redacted={}, args_hash=f"h-{i}", state="DECIDED",
                idempotency_key=f"detail-idem-{uuid.uuid4().hex}",
                created_at=now - timedelta(minutes=i),
            )
            session.add(call)
    session.flush()

    body = client.get(f"/api/v1/agents/{agent.id}", headers=headers).json()
    assert body["name"] == "busy-agent"
    assert body["total_runs"] == 21
    assert len(body["recent_runs"]) == 20
    # Newest first.
    started = [r["started_at"] for r in body["recent_runs"]]
    assert started == sorted(started, reverse=True)
    # Even-indexed (newest, i=0) runs have a tool call; odd ones have none.
    assert body["recent_runs"][0]["tool_call_count"] == 1
    assert body["recent_runs"][1]["tool_call_count"] == 0


def test_agent_detail_unknown_id_404_leaks_nothing(client, db_session, project_id):
    session, _ = db_session
    headers = _key_for(session, project_id)
    resp = client.get(f"/api/v1/agents/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "agent_not_found"
    assert str(project_id) not in resp.text


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


def _seed_analytics(session, project_id):
    """Seed a realistic, fully-in-window dataset plus out-of-window rows."""
    now = utcnow()
    agent = _agent(session, project_id, "analytics-agent")
    run = _run(session, project_id, agent.id, now - timedelta(days=1))
    tool_a = _tool_def(session, project_id, "refund_payment")
    tool_b = _tool_def(session, project_id, "issue_credit")

    def at(**kwargs):
        return now - timedelta(**kwargs)

    # Decisions: today 2 ALLOW / 2 DENY / 1 REVIEW; yesterday 1 ALLOW / 1 DENY.
    _call_with_decision(session, project_id, run.id, tool_a.id, "ALLOW", at(hours=3))
    _call_with_decision(session, project_id, run.id, tool_a.id, "ALLOW", at(hours=2))
    _call_with_decision(session, project_id, run.id, tool_a.id, "DENY", at(hours=1))
    _call_with_decision(session, project_id, run.id, tool_b.id, "DENY", at(minutes=30))
    _call_with_decision(session, project_id, run.id, tool_b.id, "REVIEW", at(minutes=10))
    _call_with_decision(session, project_id, run.id, tool_a.id, "ALLOW", at(days=1, hours=2))
    _call_with_decision(session, project_id, run.id, tool_a.id, "DENY", at(days=1, hours=1))
    # Outside the 14-day window: must not appear.
    _call_with_decision(session, project_id, run.id, tool_a.id, "ALLOW", at(days=20))

    # Executions: 3 finished with 100/200/300 ms latencies + 1 unfinished.
    for ms in (100, 200, 300):
        call = _call_with_decision(
            session, project_id, run.id, tool_a.id, "ALLOW", at(hours=1)
        )
        started = at(hours=1)
        session.add(
            models.ToolExecution(
                call_id=call.id, state="SUCCEEDED",
                result_json_redacted={"ok": True},
                started_at=started,
                finished_at=started + timedelta(milliseconds=ms),
            )
        )
    unfinished_call = _call_with_decision(
        session, project_id, run.id, tool_a.id, "ALLOW", at(hours=1)
    )
    session.add(
        models.ToolExecution(
            call_id=unfinished_call.id, state="RUNNING",
            result_json_redacted={}, started_at=at(hours=1), finished_at=None,
        )
    )
    old_call = _call_with_decision(
        session, project_id, run.id, tool_a.id, "ALLOW", at(days=20)
    )
    session.add(
        models.ToolExecution(
            call_id=old_call.id, state="SUCCEEDED",
            result_json_redacted={}, started_at=at(days=20),
            finished_at=at(days=20) + timedelta(milliseconds=999),
        )
    )

    # Approvals: two decided (60s / 120s turnaround), one pending, one old.
    _, prefix, digest = generate_api_key()
    key_row = models.ApiKey(
        project_id=project_id, name="req-key", key_prefix=prefix,
        key_hash=digest, scopes=["*"],
    )
    session.add(key_row)
    session.flush()
    for turnaround_s in (60, 120):
        call = _call_with_decision(
            session, project_id, run.id, tool_a.id, "REVIEW", at(hours=2)
        )
        created = at(hours=2)
        session.add(
            models.Approval(
                tool_call_id=call.id, requester_key_id=key_row.id,
                state="APPROVED", expires_at=at(hours=1),
                decided_at=created + timedelta(seconds=turnaround_s),
                created_at=created,
            )
        )
    pending_call = _call_with_decision(
        session, project_id, run.id, tool_a.id, "REVIEW", at(minutes=5)
    )
    session.add(
        models.Approval(
            tool_call_id=pending_call.id, requester_key_id=key_row.id,
            state="PENDING", expires_at=now + timedelta(minutes=15),
            decided_at=None, created_at=at(minutes=5),
        )
    )
    old_approval_call = _call_with_decision(
        session, project_id, run.id, tool_a.id, "REVIEW", at(days=20)
    )
    session.add(
        models.Approval(
            tool_call_id=old_approval_call.id, requester_key_id=key_row.id,
            state="REJECTED", expires_at=at(days=20),
            decided_at=at(days=20) + timedelta(seconds=500),
            created_at=at(days=20),
        )
    )
    session.flush()
    return now


def test_analytics_empty_project(client, db_session, project_id):
    session, _ = db_session
    headers = _key_for(session, project_id)
    body = client.get("/api/v1/dashboard/analytics", headers=headers).json()
    assert body["window_days"] == 14
    assert body["decisions_by_day"] == []
    assert body["execution_latency_ms"] == {"p50": None, "p95": None, "count": 0}
    assert body["top_denied_tools"] == []
    assert body["approval_turnaround_s"] == {"p50": None, "p95": None, "count": 0}


def test_analytics_with_seeded_data(client, db_session, project_id):
    session, _ = db_session
    headers = _key_for(session, project_id)
    now = _seed_analytics(session, project_id)

    body = client.get("/api/v1/dashboard/analytics", headers=headers).json()
    today = now.date().isoformat()
    yesterday = (now - timedelta(days=1)).date().isoformat()

    # Decisions grouped by UTC day; zero-fill for absent outcomes; window applied.
    # (today also includes the ALLOW decisions behind the execution seeds and
    # the REVIEW decisions behind the approval seeds.)
    assert body["decisions_by_day"] == [
        {"day": yesterday, "ALLOW": 1, "DENY": 1, "REVIEW": 0},
        {"day": today, "ALLOW": 6, "DENY": 2, "REVIEW": 4},
    ]

    # Nearest-rank percentiles over 100/200/300 ms; unfinished + old excluded.
    latency = body["execution_latency_ms"]
    assert latency["count"] == 3
    assert latency["p50"] == 200.0
    assert latency["p95"] == 300.0

    # Top denied tools: refund_payment x2, issue_credit x1 (REVIEW rows excluded).
    denied = body["top_denied_tools"]
    assert denied == [
        {"tool_name": "refund_payment", "deny_count": 2},
        {"tool_name": "issue_credit", "deny_count": 1},
    ]

    # Approval turnaround: 60s and 120s; pending + old excluded.
    turnaround = body["approval_turnaround_s"]
    assert turnaround["count"] == 2
    assert turnaround["p50"] == 60.0
    assert turnaround["p95"] == 120.0


def test_analytics_window_days_param(client, db_session, project_id):
    session, _ = db_session
    headers = _key_for(session, project_id)
    _seed_analytics(session, project_id)

    body = client.get("/api/v1/dashboard/analytics?window_days=30", headers=headers).json()
    assert body["window_days"] == 30
    # The 20-day-old ALLOW decision now falls inside the window: 3 days present.
    days = [d["day"] for d in body["decisions_by_day"]]
    assert len(days) == 3
    assert days == sorted(days)

    # window_days is clamped to 90.
    resp = client.get("/api/v1/dashboard/analytics?window_days=500", headers=headers)
    assert resp.status_code == 422


def test_analytics_project_isolation(client, db_session, project_id):
    session, _ = db_session
    headers = _key_for(session, project_id)
    _seed_analytics(session, project_id)

    # A second project sees none of the first project's analytics.
    owner = models.User(username=f"iso-owner-{uuid.uuid4().hex[:8]}")
    session.add(owner)
    session.flush()
    other = models.Project(name="iso-other", owner_id=owner.id)
    session.add(other)
    session.flush()
    other_headers = _key_for(session, other.id)

    body = client.get("/api/v1/dashboard/analytics", headers=other_headers).json()
    assert body["decisions_by_day"] == []
    assert body["execution_latency_ms"]["count"] == 0
    assert body["top_denied_tools"] == []
    assert body["approval_turnaround_s"]["count"] == 0

    # And the original project still sees its data with its own key.
    body = client.get("/api/v1/dashboard/analytics", headers=headers).json()
    assert body["execution_latency_ms"]["count"] == 3


def test_analytics_requires_valid_key(client, db_session, project_id):
    session, _ = db_session
    headers = _key_for(session, project_id)
    resp = client.get("/api/v1/dashboard/analytics")
    assert resp.status_code == 401
    resp = client.get("/api/v1/agents")
    assert resp.status_code == 401
    # A key from the test suite's other fixture stack is still valid auth.
    assert client.get("/api/v1/agents", headers=headers).status_code == 200
