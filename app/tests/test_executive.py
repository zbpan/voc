import json

import pytest
from fastapi.testclient import TestClient

from voc.config import Settings
from voc.db import dumps, uid
from voc.main import create_app


@pytest.fixture
def cx(tmp_path):
    app = create_app(Settings(tmp_path, "", "http://unused", "test"), run_worker=False)
    with TestClient(app) as client:
        yield client, app.state.db


def add(db, day, sentiment="negative", store=None, topic="设施", copies=1, is_feedback=1, workspace="default", severity="medium"):
    rid = uid()
    text = f"酒店反馈 {rid}"
    db.execute("INSERT INTO records(id,workspace_id,store_id,title,source_type,text_input,media_type,created_at,status,transcript,sentiment,is_feedback,model,prompt_version,metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (rid, workspace, store, text, "text", text, "text", day + "T12:00:00+00:00", "completed", text, sentiment, is_feedback, "test", "test", dumps({"executive": {"topic": topic}, "guest_segment": "家庭"})))
    for _ in range(copies):
        db.execute("INSERT INTO events(id,workspace_id,record_id,title,theme,summary,quote,recommendation,severity,sentiment,role,evidence_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (uid(), workspace, rid, "反馈事件", "设施环境", text, text, "核查", severity, sentiment, "customer", "[]", day))
    return rid


def get(client, extra=""):
    response = client.get("/api/executive?start=2026-10-21&end=2026-11-09" + extra)
    assert response.status_code == 200, response.text
    return response.json()


def test_equal_windows_unique_feedback_and_review_semantics(cx):
    client, db = cx
    prior = add(db, "2026-10-01")
    add(db, "2026-10-20")
    current = add(db, "2026-10-21", copies=3, severity="high")
    add(db, "2026-11-09", sentiment="positive")
    add(db, "2026-09-30")
    add(db, "2026-11-10")
    result = get(client)
    assert result["metrics"]["feedback"] == result["metrics"]["previous"]["feedback"] == 2
    assert result["metrics"]["delta_pp"] == -50
    assert result["topics"][0]["count"] == 1
    assert result["metrics"]["high_open"] == 3
    assert result["metrics"]["high_records"] == 1
    assert len(result["evidence"]) == 4
    assert result["metrics"]["priority_records"] == 1
    assert sum(r["records"] for r in result["trend"]) == 4
    db.execute("UPDATE events SET review_status='dismissed' WHERE record_id=?", (current,))
    result = get(client)
    assert result["topics"] == []
    assert result["metrics"]["high_open"] == 0
    assert result["metrics"]["negative_rate"] == 50


def test_scope_isolation_search_and_empty_rates(cx):
    client, db = cx
    store = client.post("/api/stores", json={"name": "一店"}).json()["id"]
    other = client.post("/api/workspaces", json={"name": "其他"}).json()["id"]
    foreign = client.post("/api/stores", json={"name": "二店", "workspace_id": other}).json()["id"]
    add(db, "2026-11-09", store=store)
    add(db, "2026-11-09", store=foreign, workspace=other)
    assert get(client)["metrics"]["records"] == 1
    assert get(client, "&store_id=" + store)["metrics"]["records"] == 1
    assert client.get("/api/executive?store_id=" + foreign).status_code == 404
    empty = get(client, "&search=%25")
    assert empty["metrics"]["records"] == 0
    assert empty["metrics"]["negative_rate"] is None
    assert empty["metrics"]["priority_coverage"] is None
    assert empty["metrics"]["delta_pp"] is None
    assert empty["evidence"] == []
    assert client.get("/api/executive?window_days=0").status_code == 422
    assert client.get("/api/executive?start=2026-11-10&end=2026-11-01").status_code == 422


def test_all_records_aggregated_beyond_200_and_report_snapshot(cx):
    client, db = cx
    ids = [add(db, "2026-11-09") for _ in range(205)]
    result = get(client)
    assert result["metrics"]["records"] == result["topics"][0]["count"] == 205
    assert set(r["id"] for r in result["evidence"]) == set(ids)
    exported = client.get("/api/executive/export?start=2026-10-21&end=2026-11-09").text
    assert all(rid in exported for rid in ids) and "Session ID" in exported
    report = client.post("/api/reports", json={"scope": {"start": "2026-10-21", "end": "2026-11-09"}}).json()
    snap = client.get("/api/reports/" + report["id"]).json()["snapshot"]
    assert len(snap["events"]) == 200 and snap["total_events"] == 205
    assert snap["executive"]["metrics"]["records"] == 205
    assert all(e["record_created_at"].startswith("2026-11-09") and e["executive_period"] == "current" and e["executive_topics"] == ["设施"] for e in snap["events"])
    db.execute("DELETE FROM records WHERE id=?", (ids[0],))
    assert client.get("/api/reports/" + report["id"]).json()["snapshot"]["executive"]["metrics"]["records"] == 205


def test_action_before_after_uses_store_and_equal_windows(cx):
    client, db = cx
    store = client.post("/api/stores", json={"name": "一店"}).json()["id"]
    add(db, "2026-10-10", store=store)
    add(db, "2026-10-11", store=store)
    add(db, "2026-11-01", store=store)
    add(db, "2026-11-02", store=store, sentiment="positive")
    add(db, "2026-11-02", store=store, sentiment="positive")
    add(db, "2026-11-03", topic="其他", store=store)
    add(db, "2026-11-03")
    db.execute("INSERT INTO experience_actions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", ("action", "default", store, "设施", "试点", "负责人", "观察中", "2026-10-21", "2026-11-12", "核查", "跟踪", "{}"))
    comparison = get(client)["actions"][0]["comparison"]
    assert comparison["days"] == 20
    assert (comparison["before"], comparison["before_base"], comparison["after"], comparison["after_base"]) == (2, 2, 1, 4)
    assert comparison["delta_pp"] == -75
    assert comparison["small_sample"] is True
    assert len(comparison["record_ids"]) == 3


def test_image_only_and_pending_records_not_in_denominator(cx):
    client, db = cx
    add(db, "2026-11-09", is_feedback=0, copies=0, sentiment="neutral")
    rid = add(db, "2026-11-09")
    db.execute("UPDATE records SET status='queued' WHERE id=?", (rid,))
    result = get(client)
    assert result["metrics"]["feedback"] == 0
    assert result["metrics"]["negative_rate"] is None
    assert result["metrics"]["pending_records"] == 1
    assert result["topics"] == []
