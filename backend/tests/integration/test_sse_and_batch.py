import json

from app.agent.models import DemoHeuristicModel
from tests.conftest import (
    OPERATOR,
    SUPERVISOR,
    count,
    drain,
    investigation_script,
    refund,
    use_model,
    use_script,
)
from tests.integration.test_workflow import approvals_for, decide, run_detail, start


def parse_sse(body: str) -> list[dict]:
    events = []
    for block in body.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line and not line.startswith(":"))
        if "event" in fields:
            events.append({"id": fields.get("id"), "event": fields["event"], "data": json.loads(fields["data"])})
    return events


def stream(client, run_id: str, last_event_id: str | None = None) -> list[dict]:
    headers = OPERATOR()
    if last_event_id:
        headers["Last-Event-ID"] = last_event_id
    with client.stream("GET", f"/api/v1/runs/{run_id}/events", headers=headers) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        return parse_sse(r.read().decode())


def finished_run(client, graph) -> str:
    use_script(investigation_script("T-101", "O-101", [refund("O-101", 120000)]))
    run_id = start(client, "T-101")
    drain(graph)
    decide(client, approvals_for(client, run_id)["refund"]["approval_id"], "approve")
    drain(graph)
    assert run_detail(client, run_id)["status"] == "completed"
    return run_id


def test_sse_replays_the_full_timeline(client, graph):
    run_id = finished_run(client, graph)
    events = stream(client, run_id)
    kinds = [e["event"] for e in events]
    for expected in ("run_created", "tool_started", "tool_completed", "investigation_completed",
                     "approval_requested", "approval_approved", "action_executed", "run_completed"):
        assert expected in kinds, expected
    assert kinds[-1] == "stream_end"
    ids = [int(e["id"]) for e in events if e["id"]]
    assert ids == sorted(ids) and len(ids) == len(set(ids))
    statuses = [e["data"]["status"] for e in events if e["event"] == "status_changed"]
    assert statuses[:3] == ["running", "investigating", "validating"]
    assert statuses[-1] == "completed"


def test_t25_reconnect_with_last_event_id_has_no_gaps_or_repeats(client, graph):
    run_id = finished_run(client, graph)
    full = [e for e in stream(client, run_id) if e["id"]]
    cut = len(full) // 2
    resumed = [e for e in stream(client, run_id, last_event_id=full[cut - 1]["id"]) if e["id"]]
    assert [e["id"] for e in full[:cut]] + [e["id"] for e in resumed] == [e["id"] for e in full]


def test_t29_batch_creates_child_runs_and_isolates_failures(client, graph):
    class FlakyDemo(DemoHeuristicModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            if "T-102" in str(messages[1].content if len(messages) > 1 else messages[0].content):
                raise RuntimeError("provider exploded for this ticket")
            return super()._generate(messages, stop, run_manager, **kwargs)

    use_model(lambda _: FlakyDemo())
    r = client.post("/api/v1/runs", json={"mode": "batch", "instruction": "Review delayed tickets",
                                          "filters": {"priority": "high", "status": "open"}, "limit": 10},
                    headers=OPERATOR())
    assert r.status_code == 202
    parent_id = r.json()["run_id"]
    drain(graph)

    parent = run_detail(client, parent_id)
    children = {c["ticket_number"]: c for c in parent["children"]}
    assert set(children) == {"T-101", "T-102", "T-105", "T-107", "T-108"}
    assert children["T-102"]["status"] == "failed"
    assert children["T-105"]["status"] == "completed_no_action"  # payment failed
    for t in ("T-101", "T-107", "T-108"):
        assert children[t]["status"] == "awaiting_approval", t
    assert parent["status"] == "awaiting_approval"

    pending = client.get("/api/v1/approvals", params={"status": "pending"}, headers=SUPERVISOR()).json()
    assert {a["ticket_number"] for a in pending if a["action_type"] == "refund"} == {"T-101", "T-107", "T-108"}
    for a in pending:
        decide(client, a["approval_id"], "approve" if a["ticket_number"] != "T-108" else "reject")
    drain(graph)
    assert count("SELECT count(*) FROM refunds WHERE action_id IS NOT NULL") == 2
    parent = run_detail(client, parent_id)
    assert parent["status"] == "completed"

    # batch stream includes child events
    kinds = {e["event"] for e in stream(client, parent_id)}
    assert {"batch_fanned_out", "approval_requested", "run_completed"} <= kinds


def test_batch_concurrency_setting_is_capped():
    from app.core.config import get_settings

    assert get_settings().max_concurrent_ticket_runs == 2
    assert get_settings().max_batch_tickets == 10
