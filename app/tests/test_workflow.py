import json
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from voc.audio import AudioError, prepare, segments
from voc.config import Settings
from voc.main import create_app
from voc.provider import ProviderError, clean_analysis


TEXT = "等了四十分钟才入住，前台一直没有解释。"


def analysis(text=TEXT):
    return {"language": "zh", "transcript": text, "summary": "客户反馈入住等待过长。", "sentiment": "negative", "is_customer_feedback": True, "issues": [{"title": "入住等候过长", "theme": "等待效率", "summary": "等候四十分钟且未获解释", "customer_quote": text, "recommendation": "核查办理流程并提供等候说明", "severity": "medium", "sentiment": "negative", "role": "customer"}]}


class Provider:
    calls = 0

    def analyze(self, source_type, language_hint, audio=None, text=None):
        self.calls += 1
        return analysis(text or TEXT), {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}

    def complete(self, prompt, **kwargs):
        snapshot = json.loads(prompt.split("\n数据快照：")[1])
        event_id = snapshot["events"][0]["id"]
        return json.dumps({"summary": "入住等待问题需要核查。", "priorities": [{"title": "改善入住", "detail": "核查等候情况", "event_ids": [event_id]}], "strengths": [], "actions": []}), {"total_tokens": 200}


@pytest.fixture
def setup(tmp_path):
    provider = Provider()
    app = create_app(Settings(tmp_path, "test-key", "http://unused", "test"), provider=provider, run_worker=False)
    with TestClient(app) as client:
        yield client, app.state.db, app.state.worker, provider


def completed(setup):
    client, db, worker, provider = setup
    identifier = client.post("/api/records/text", json={"text": TEXT}).json()["id"]
    row = worker.claim("records")
    worker.perform("records", row, worker.process_record)
    detail = client.get(f"/api/records/{identifier}").json()
    assert detail["status"] == "completed", detail
    return detail


def test_scope_isolation_and_public_collection_binding(setup):
    client, db, worker, provider = setup
    other = client.post("/api/workspaces", json={"name": "其他空间"}).json()["id"]
    store = client.post("/api/stores", json={"workspace_id": other, "name": "门店"}).json()
    assert client.post("/api/records/text", json={"text": TEXT, "store_id": store["id"]}).status_code == 404
    result = client.post(f"/api/collect/{store['collection_token']}/text", json={"workspace_id": "default", "text": TEXT})
    assert result.status_code == 202
    identifier = result.json()["id"]
    assert client.get(f"/api/records/{identifier}").status_code == 404
    assert client.get(f"/api/records/{identifier}/audio").status_code == 404
    assert client.post(f"/api/records/{identifier}/retry").status_code == 404
    assert client.delete(f"/api/records/{identifier}").status_code == 404
    assert client.get(f"/api/records/{identifier}?workspace_id={other}").json()["store_id"] == store["id"]
    assert client.get("/api/records").json()["total"] == 0


def test_review_audit_counts_and_conflict(setup):
    client, db, worker, provider = setup
    detail = completed(setup)
    event = detail["events"][0]
    assert detail["transcript"] == TEXT
    assert detail["usage"]["total_tokens"] == 150
    assert event["quote"] == TEXT and event["evidence"][0]["precision"] == "text"
    stats = client.get("/api/dashboard").json()
    assert (stats["records"], stats["events"], stats["negative_percent"]) == (1, 1, 100)
    patch = {"version": 1, "review_status": "confirmed", "workflow_status": "resolved", "owner": "运营"}
    assert client.patch(f"/api/events/{event['id']}", json=patch).status_code == 200
    assert client.patch(f"/api/events/{event['id']}", json=patch).status_code == 409
    assert client.patch(f"/api/events/{event['id']}?workspace_id=unknown", json=patch).status_code == 404
    audit = client.get(f"/api/events/{event['id']}/audit").json()
    assert len(audit) == 1 and audit[0]["changes"]["owner"]["before"] == ""
    assert client.get("/api/dashboard").json()["resolved"] == 1
    assert client.patch(f"/api/events/{event['id']}", json={"version": 2, "review_status": "dismissed"}).status_code == 200
    assert client.get("/api/events").json()["total"] == 0
    assert client.get("/api/events?review_status=dismissed").json()["total"] == 1
    assert client.get("/api/dashboard").json()["events"] == 0


def test_recovery_reuses_saved_chunks(setup):
    client, db, worker, provider = setup
    identifier = client.post("/api/records/text", json={"text": TEXT}).json()["id"]
    row = worker.claim("records")
    worker.save_chunk(row, 0, 0, 0, text=TEXT)
    db.initialize()
    assert db.one("SELECT status FROM records WHERE id=?", (identifier,))["status"] == "queued"
    worker.perform("records", worker.claim("records"), worker.process_record)
    assert provider.calls == 1
    assert client.get(f"/api/records/{identifier}").json()["status"] == "completed"
    assert client.post(f"/api/records/{identifier}/retry").status_code == 409


def test_failed_task_retry_and_bad_upload(setup):
    client, db, worker, provider = setup
    assert client.post("/api/records/upload", files={"file": ("file.exe", b"bad")}).status_code == 415
    assert client.post("/api/records/upload", files={"file": ("file.wav", b"")}).status_code == 422
    identifier = client.post("/api/records/upload", files={"file": ("file.wav", b"not audio")}).json()["id"]
    row = worker.claim("records")
    worker.perform("records", row, worker.process_record)
    detail = client.get(f"/api/records/{identifier}").json()
    assert detail["status"] == "failed" and detail["error"]
    assert client.post(f"/api/records/{identifier}/retry").status_code == 202
    assert client.delete(f"/api/records/{identifier}").status_code == 409


def test_report_snapshot_export_and_reference_validation(setup):
    client, db, worker, provider = setup
    detail = completed(setup)
    report = client.post("/api/reports", json={"title": "测试报告"}).json()
    worker.perform("reports", worker.claim("reports"), worker.process_report)
    result = client.get(f"/api/reports/{report['id']}").json()
    assert result["status"] == "completed"
    export = client.get(f"/api/reports/{report['id']}/export")
    assert "Session ID" in export.text and TEXT in export.text
    assert client.get(f"/api/reports/{report['id']}?workspace_id=unknown").status_code == 404
    assert client.delete(f"/api/records/{detail['id']}").status_code == 200
    assert client.get("/api/events").json()["total"] == 0
    assert TEXT in client.get(f"/api/reports/{report['id']}/export").text
    report2 = {**db.one("SELECT * FROM reports WHERE id=?", (report["id"],)), "id": report["id"]}
    provider.complete = lambda *a, **kw: (json.dumps({"summary": "bad", "priorities": [{"title": "bad", "detail": "bad", "event_ids": ["unknown"]}], "strengths": [], "actions": []}), {})
    with pytest.raises(ProviderError, match="不存在"):
        worker.process_report(report2)


def test_evidence_guard_and_non_customer_filter():
    value = analysis()
    value["issues"][0]["customer_quote"] = "不存在的引文"
    with pytest.raises(ProviderError, match="引用"):
        clean_analysis(value)
    value["is_customer_feedback"] = False
    assert clean_analysis(value)["issues"] == []
    value = analysis()
    value["issues"][0]["role"] = "agent"
    assert clean_analysis(value)["issues"] == []


def test_audio_conversion_channel_and_exact_boundaries(tmp_path):
    source = tmp_path / "source.wav"
    with wave.open(str(source), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\x01\x00" * 40000)
    settings = Settings(tmp_path, "", "", "test")
    with pytest.raises(AudioError, match="右声道"):
        prepare(source, tmp_path / "right.wav", "right", settings)
    duration, waveform = prepare(source, tmp_path / "output.wav", "mixed", settings)
    chunks = list(segments(tmp_path / "output.wav", 1))
    assert duration == 2.5
    assert [(c[1], c[2]) for c in chunks] == [(0, 1), (1, 2), (2, 2.5)]
    assert all(0 <= v <= 1 for v in waveform)


def test_dates_literal_search_and_empty_report(setup):
    client, db, worker, provider = setup
    completed(setup)
    assert client.get("/api/records?search=%25").json()["total"] == 0
    assert client.get("/api/records?start=2026-11-09&end=2026-11-01").status_code == 422
    assert client.get("/api/records?limit=10000").status_code == 422
    assert client.post("/api/reports", json={"scope": {"search": "不存在的记录"}}).status_code == 422


def test_image_assets_scoped_and_deleted_with_record(setup, tmp_path):
    client, db, worker, provider = setup
    identifier = client.post("/api/records/text", json={"text": TEXT}).json()["id"]
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"image bytes")
    db.execute("INSERT INTO record_assets VALUES (?,?,?,?,?,?,?,?)", ("asset1", identifier, "image", str(photo), "image/jpeg", "photo.jpg", '{"license":"CC0"}', "2026-11-09"))
    detail = client.get(f"/api/records/{identifier}").json()
    assert detail["assets"][0]["metadata"]["license"] == "CC0"
    assert "file_path" not in detail["assets"][0]
    assert detail["submitted_text"] == TEXT
    assert client.get(f"/api/records/{identifier}/assets/asset1").content == b"image bytes"
    assert client.get(f"/api/records/{identifier}/assets/asset1?workspace_id=another").status_code == 404
    assert client.get(f"/api/records/{identifier}/assets/missing").status_code == 404
    db.execute("UPDATE records SET status='failed' WHERE id=?", (identifier,))
    assert client.delete(f"/api/records/{identifier}").status_code == 200
    assert not db.all("SELECT * FROM record_assets WHERE record_id=?", (identifier,))


def test_multimodal_worker_keeps_one_record_and_all_inputs(setup, tmp_path):
    client, db, worker, provider = setup
    identifier = client.post("/api/records/text", json={"text": "请听语音说明。"}).json()["id"]
    folder = worker.settings.root / "media" / identifier
    folder.mkdir(parents=True)
    audio_path = folder / "original.wav"
    with wave.open(str(audio_path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\x01\x00" * 32000)
    photo = folder / "photo.jpg"
    photo.write_bytes(b"fake image for mocked provider")
    db.execute("UPDATE records SET original_path=?,media_type='multimodal',metadata_json=? WHERE id=?", (str(audio_path), '{"synthetic":true,"modalities":["text","audio","image"]}', identifier))
    db.execute("INSERT INTO record_assets VALUES (?,?,?,?,?,?,?,?)", ("photo", identifier, "image", str(photo), "image/jpeg", "photo.jpg", "{}", "2026-11-09"))
    calls = []

    def analyze(source_type, language_hint, **kwargs):
        calls.append(kwargs)
        return analysis("请听语音说明。\n" + TEXT), {"total_tokens": 120}

    provider.analyze = analyze
    worker.perform("records", worker.claim("records"), worker.process_record)
    detail = client.get(f"/api/records/{identifier}").json()
    assert detail["status"] == "completed", detail
    assert len(calls) == 1 and calls[0]["audio"][:4] == b"RIFF"
    assert calls[0]["text"] == "请听语音说明。"
    assert calls[0]["images"][0]["data"] == photo.read_bytes()
    assert detail["metadata"]["modalities"] == ["text", "audio", "image"]
    assert detail["events"][0]["evidence"][0]["precision"] == "chunk"
    assert client.get("/api/dashboard").json()["records"] == 1


def test_workspace_specific_claim_does_not_take_other_jobs(setup):
    client, db, worker, provider = setup
    client.post("/api/records/text", json={"text": TEXT})
    other = client.post("/api/workspaces", json={"name": "模拟数据空间"}).json()["id"]
    identifier = client.post("/api/records/text", json={"text": TEXT, "workspace_id": other}).json()["id"]
    assert worker.claim("records", other)["id"] == identifier
    assert worker.claim("records", other) is None
    assert worker.claim("records")["workspace_id"] == "default"
