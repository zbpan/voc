import json

import pytest
from fastapi.testclient import TestClient

from voc.config import Settings
from voc.db import dumps, uid
from voc.main import create_app
from voc.service import report_material


@pytest.fixture
def cx(tmp_path):
    app = create_app(Settings(tmp_path, "", "http://unused", "test"), run_worker=False)
    with TestClient(app) as client:
        yield client, app.state.db


def add(db, day, sentiment="negative", store=None, topic="设施", copies=1, is_feedback=1, workspace="default", severity="medium", segment="家庭"):
    rid = uid()
    text = f"酒店反馈 {rid}"
    db.execute("INSERT INTO records(id,workspace_id,store_id,title,source_type,text_input,media_type,created_at,status,transcript,sentiment,is_feedback,model,prompt_version,metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (rid, workspace, store, text, "text", text, "text", day + "T12:00:00+00:00", "completed", text, sentiment, is_feedback, "test", "test", dumps({"executive": {"topic": topic}, "guest_segment": segment})))
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


def agenda(client, extra=""):
    return {item["kind"]: item for item in get(client, extra)["improvements"]}


def test_recovery_counts_submissions_and_follows_review_and_ownership(cx):
    client, db = cx
    rid = add(db, "2026-11-09", copies=3, severity="high", topic=None)
    events = [e["id"] for e in db.all("SELECT id FROM events WHERE record_id=? ORDER BY id", (rid,))]
    db.execute("UPDATE events SET review_status='confirmed',owner='值班经理' WHERE id=?", (events[0],))
    db.execute("UPDATE events SET theme='卫生安全',severity='low' WHERE id=?", (events[2],))
    unreviewed = add(db, "2026-11-08", severity="critical")
    closed = add(db, "2026-11-08", severity="high")
    db.execute("UPDATE events SET workflow_status='resolved' WHERE record_id=?", (closed,))
    excluded = add(db, "2026-11-08", severity="critical")
    db.execute("UPDATE events SET review_status='dismissed' WHERE record_id=?", (excluded,))
    add(db, "2026-11-08", severity="high", is_feedback=0)
    add(db, "2026-10-20", severity="high")
    item = agenda(client)["recovery"]
    assert "2条反馈" in item["finding"] and "2条至少有一项未填跟进人" in item["finding"]
    assert [(g["label"], [x["record_id"] for x in g["entries"]]) for g in item["groups"]] == [
        ("待核实", [unreviewed]), ("已有确认", [rid])]
    assert item["groups"][1]["entries"][0]["event_id"] == events[0]
    assert next(x for x in get(client)["topics"] if x["name"] == "卫生安全")["high_open"] == 0
    assert "recovery" not in agenda(client, "&severity=low")
    assert not agenda(client, "&search=nonmatching")


def test_recurring_compares_the_same_affected_locations_and_deduplicates(cx):
    client, db = cx
    a, b, c = [client.post("/api/stores", json={"name": n}).json()["id"] for n in "甲乙丙"]
    before = [add(db, "2026-10-20", store=a) for _ in range(2)]
    add(db, "2026-10-20", store=b, sentiment="positive")
    add(db, "2026-10-20", store=c)
    ids = [add(db, "2026-11-08", store=s, copies=2) for s in (a, a, b, b)]
    add(db, "2026-11-08", store=a, sentiment="neutral")
    add(db, "2026-11-09", store=c)
    add(db, "2026-11-09", store=b, copies=0, is_feedback=0)
    item = agenda(client)["recurrence"]
    assert "4/5" in item["finding"] and "2/3" in item["finding"]
    assert [b["count"] for b in item["bases"]] == [5, 3]
    assert all(expected <= set(b["record_ids"]) for expected, b in zip((set(ids), set(before)), item["bases"]))
    assert [{h["record_id"] for h in g["entries"]} for g in item["groups"]] == [set(ids), set(before)]
    assert "连续两期" in agenda(client, "&store_id=" + a)["recurrence"]["title"]
    assert "recurrence" not in agenda(client, "&store_id=" + b)
    db.execute("DELETE FROM records WHERE created_at<'2026-10-21'")
    assert "没有有效反馈" in agenda(client)["recurrence"]["finding"]


def test_segment_gap_compares_other_labeled_feedback_and_respects_minimums(cx):
    client, db = cx
    for segment, n in [("家庭", 3), ("商务", 2), ("", 10)]:
        for i in range(10):
            add(db, "2026-11-09", topic="接待", segment=segment, copies=2, sentiment="negative" if i < n else "neutral")
    add(db, "2026-11-09", topic="接待", segment="家庭", copies=0, is_feedback=0)
    item = agenda(client)["segment"]
    assert "3/10" in item["finding"] and "2/10" in item["finding"] and "10.0个百分点" in item["finding"]
    assert [g["count"] for g in item["groups"]] == [3, 2]
    assert [b["count"] for b in item["bases"]] == [10, 10]
    assert not set(item["bases"][0]["record_ids"]).intersection(item["bases"][1]["record_ids"])
    db.execute("DELETE FROM records WHERE id=(SELECT id FROM records WHERE sentiment='neutral' AND metadata_json LIKE '%商务%' LIMIT 1)")
    assert "segment" not in agenda(client)


def test_transfer_requires_two_locations_matching_topic_and_polarity(cx):
    client, db = cx
    a, b = [client.post("/api/stores", json={"name": n}).json()["id"] for n in "甲乙"]
    praise = [add(db, "2026-11-08", store=a, sentiment="positive", copies=2, topic=None) for _ in range(2)]
    for rid in praise:
        db.execute("UPDATE events SET theme='其他反馈',sentiment='neutral' WHERE id=(SELECT MIN(id) FROM events WHERE record_id=?)", (rid,))
    issues = [add(db, "2026-11-08", store=b, copies=2, topic=None) for _ in range(2)]
    add(db, "2026-11-08", store=b, sentiment="positive", topic="无关主题")
    item = agenda(client)["transfer"]
    assert "设施环境" in item["title"]
    assert [g["count"] for g in item["groups"]] == [2, 2]
    for g, expected in zip(item["groups"], (praise, issues)):
        assert {x["record_id"] for x in g["entries"]} == set(expected)
        for x in g["entries"]:
            assert db.one("SELECT theme FROM events WHERE id=?", (x["event_id"],))["theme"] == "设施环境"
    assert "transfer" not in agenda(client, "&store_id=" + b)
    for store, scenario in ((a, "遮光"), (b, "排水")):
        db.execute("UPDATE records SET metadata_json=? WHERE store_id=?", (dumps({"executive": {"topic": "客房", "scenario": scenario}}), store))
    different = agenda(client)["transfer"]
    assert "表扬样例谈遮光，问题样例谈排水" in different["title"]
    assert "不同环节" in different["manager_step"]
    db.execute("UPDATE records SET sentiment='mixed' WHERE id=?", (praise[0],))
    assert "transfer" not in agenda(client)


def test_improvement_snapshot_keeps_evidence_and_only_sends_supported_short_refs(cx):
    client, db = cx
    rid = add(db, "2026-11-09", severity="high")
    event = db.one("SELECT * FROM events WHERE record_id=?", (rid,))
    report_id = client.post("/api/reports", json={"scope": {"end": "2026-11-09"}}).json()["id"]
    url = "/api/reports/" + report_id
    snap = client.get(url).json()["snapshot"]
    cue = snap["executive"]["improvements"][0]
    assert "entries" not in cue["groups"][0] and cue["groups"][0]["example"]["quote"] == event["quote"]
    materials, refs = report_material(snap)
    assert refs[materials["改善线索"][0]["代表事件"]["待核实"]] == event["id"]
    assert event["id"] not in dumps(materials["改善线索"])
    assert "改善线索" not in report_material({**snap, "events": []})[0]
    db.execute("UPDATE events SET review_status='dismissed' WHERE id=?", (event["id"],))
    assert "recovery" not in agenda(client)
    assert client.get(url).json()["snapshot"]["executive"]["improvements"] == [cue]
    assert event["id"] not in client.get("/api/executive/export").text
    db.execute("UPDATE reports SET status='completed',content_json=? WHERE id=?", (dumps({"summary": "测试报告", "priorities": [], "strengths": [], "actions": []}), report_id))
    assert cue["finding"] in client.get(url + "/export").text


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
