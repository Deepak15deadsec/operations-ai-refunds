"""Analytics aggregation and eval-report endpoints: data correctness, tenant isolation, auth."""

import json

from app.api import reads
from tests.conftest import (
    ADMIN,
    GLOBEX_SUPERVISOR,
    OPERATOR,
    SUPERVISOR,
    drain,
    investigation_script,
    refund,
    reply,
    use_script,
)


def _start(client, ticket: str) -> str:
    r = client.post("/api/v1/runs", json={"mode": "ticket", "ticket_number": ticket,
                                          "instruction": "Investigate and resolve."}, headers=OPERATOR())
    assert r.status_code == 202, r.text
    return r.json()["run_id"]


def _approve_all(client, run_id: str) -> None:
    for a in client.get("/api/v1/approvals", params={"run_id": run_id}, headers=SUPERVISOR()).json():
        assert client.post(f"/api/v1/approvals/{a['approval_id']}/decision",
                           json={"decision": "approve", "note": "ok"}, headers=SUPERVISOR()).status_code == 200


def _seed_runs(client, graph) -> None:
    # One run that produces an executed refund + reply.
    use_script(investigation_script("T-101", "O-101", [refund("O-101", 120000), reply("T-101")]))
    run_id = _start(client, "T-101")
    drain(graph)
    _approve_all(client, run_id)
    drain(graph)
    # One run that resolves with no action.
    use_script(investigation_script("T-105", None, [{"action_type": "no_action", "ticket_number": "T-105",
                                                     "reason": "Delivered on time; nothing to resolve."}]))
    _start(client, "T-105")
    drain(graph)


def test_analytics_requires_auth(client):
    assert client.get("/api/v1/analytics").status_code == 401


def test_analytics_aggregates_measured_telemetry(client, graph):
    _seed_runs(client, graph)
    data = client.get("/api/v1/analytics", headers=OPERATOR()).json()

    assert data["runs_total"] == 2
    assert data["runs_active"] == 0
    assert data["by_status"]["completed"] == 1
    assert data["outcomes"]["completed"] == 1
    assert data["outcomes"]["no_action"] == 1
    assert data["success_rate"] == 0.5  # 1 completed / 2 finished

    # Latency is measured per run (count tracks runs that recorded a duration).
    assert data["latency"]["count"] == 2
    assert data["latency"]["p95_ms"] >= data["latency"]["p50_ms"] >= 0

    # Simulated effects actually executed.
    assert data["refunds"] == 1
    assert data["refund_total_minor"] == 120000
    assert data["messages"] == 1

    # Read tools were traced with per-tool reliability + latency.
    assert data["tools_total_calls"] >= 4
    assert data["tools_total_errors"] == 0
    tools = {t["tool"]: t for t in data["tools"]}
    assert "get_ticket" in tools and tools["get_ticket"]["calls"] >= 1

    # Model roll-up (offline/scripted model has a known zero price).
    models = {m["model"]: m for m in data["models"]}
    assert "scripted:test" in models
    assert models["scripted:test"]["runs"] == 2
    assert data["cost_complete"] is True

    # 14-day daily series with gaps filled.
    assert len(data["daily"]) == 14
    assert sum(d["runs"] for d in data["daily"]) == 2
    assert sum(d["completed"] for d in data["daily"]) == 1


def test_analytics_is_tenant_scoped(client, graph):
    _seed_runs(client, graph)  # all in the Acme tenant
    other = client.get("/api/v1/analytics", headers=GLOBEX_SUPERVISOR()).json()
    assert other["runs_total"] == 0
    assert other["refunds"] == 0
    assert other["tools_total_calls"] == 0
    assert other["models"] == []


def test_analytics_window_filter(client, graph):
    _seed_runs(client, graph)
    windowed = client.get("/api/v1/analytics", params={"window_hours": 48}, headers=OPERATOR()).json()
    assert windowed["window_hours"] == 48
    assert windowed["runs_total"] == 2  # seeded "now" under the fixed clock
    assert len(windowed["daily"]) == 2  # 48h -> 2 day buckets


def test_eval_report_available(client, tmp_path, monkeypatch):
    payload = {"scenarios_total": 37, "scenarios_passed": 37, "metrics": {"policy_violations": 0}}
    report = tmp_path / "evaluation-report.json"
    report.write_text(json.dumps(payload))
    monkeypatch.setattr(reads, "_eval_report_path", lambda: report)
    body = client.get("/api/v1/eval-report", headers=OPERATOR()).json()
    assert body["available"] is True
    assert body["data"]["scenarios_passed"] == 37


def test_eval_report_missing_is_graceful(client, tmp_path, monkeypatch):
    monkeypatch.setattr(reads, "_eval_report_path", lambda: tmp_path / "nope.json")
    body = client.get("/api/v1/eval-report", headers=ADMIN()).json()
    assert body["available"] is False
    assert body["data"] is None
