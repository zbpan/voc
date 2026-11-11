import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from voc.db import Database
from voc.demo_import import WORKSPACES, import_archive


def make_archive(tmp_path, mutation=None, extra=None):
    payloads = []
    media_path = "media/" + "a" * 64 + ".wav"
    for source in WORKSPACES:
        record_id, chunk_id, event_id = source + "-record", source + "-chunk", source + "-event"
        store_id = source + "-store"
        payloads.append({"workspace": {"id": source, "name": "虚构完整演示", "created_at": "2026-11-09"},
            "stores": [{"id": store_id, "workspace_id": source, "name": "虚构酒店", "region": "测试", "created_at": "2026-11-09"}],
            "records": [{"id": record_id, "workspace_id": source, "store_id": store_id, "title": "虚构测试", "source_type": "text", "media_type": "text", "text_input": "虚构体验反馈", "status": "completed", "created_at": "2026-11-09", "model": "precomputed-test", "prompt_version": "test", "metadata_json": {"synthetic": True}, "original_path": media_path, "audio_path": media_path,
                "chunks": [{"id": chunk_id, "record_id": record_id, "position": 0, "start": 0, "end": 1, "transcript": "虚构体验反馈", "analysis_json": {}, "usage_json": {}}],
                "events": [{"id": event_id, "workspace_id": source, "record_id": record_id, "title": "测试事件", "theme": "服务体验", "summary": "虚构", "quote": "虚构体验反馈", "recommendation": "核实", "severity": "low", "sentiment": "neutral", "role": "customer", "evidence_json": [{"chunk_id": chunk_id}], "created_at": "2026-11-09"}], "assets": []}],
            "actions": [], "reports": [{"id": source + "-report", "workspace_id": source, "title": "虚构报告", "created_at": "2026-11-09", "status": "completed", "scope_json": {"workspace_id": source}, "snapshot_json": {"events": [{"id": event_id, "record_id": record_id}]}, "content_json": {"priorities": [{"event_ids": [event_id]}]}, "model": "test", "session_id": "test-session"}]})
    if mutation:
        mutation(payloads)
    contents = {f"datasets/{index}.json": json.dumps(payload, ensure_ascii=False).encode() for index, payload in enumerate(payloads)}
    contents[media_path] = b"test audio fixture"
    if extra:
        contents.update(extra)
    manifest = {"schema_version": 1, "synthetic": True, "package_id": "test-package", "datasets": [{"workspace_id": source, "file": f"datasets/{index}.json", "records": 1, "events": 1, "stores": 1} for index, source in enumerate(WORKSPACES)], "files": {name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)} for name, data in contents.items()}}
    path = tmp_path / "demo.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for name, data in contents.items():
            archive.writestr(name, data)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_import_remaps_ids_preserves_existing_data_and_is_idempotent(tmp_path):
    archive, digest = make_archive(tmp_path)
    runtime = tmp_path / "runtime"
    db = Database(runtime / "voc.sqlite3")
    db.initialize()
    db.execute("INSERT INTO workspaces VALUES ('existing','Keep this space','2026-11-01')")
    result = import_archive(archive, runtime, digest)
    assert result["status"] == "imported"
    assert db.one("SELECT name FROM workspaces WHERE id='existing'")["name"] == "Keep this space"
    stores = db.all("SELECT collection_token FROM stores")
    assert len(stores) == 2 and len({row["collection_token"] for row in stores}) == 2
    original_token = stores[0]["collection_token"]
    event = db.one("SELECT * FROM events WHERE workspace_id='full-demo-cxo'")
    proof = json.loads(event["evidence_json"])[0]
    assert db.one("SELECT record_id FROM chunks WHERE id=?", (proof["chunk_id"],))["record_id"] == event["record_id"]
    record = db.one("SELECT audio_path FROM records WHERE id=?", (event["record_id"],))
    assert Path(record["audio_path"]).read_bytes() == b"test audio fixture"
    report = db.one("SELECT * FROM reports WHERE workspace_id='full-demo-cxo'")
    assert json.loads(report["content_json"])["priorities"][0]["event_ids"] == [event["id"]]
    assert json.loads(report["scope_json"])["workspace_id"] == "full-demo-cxo"
    repeated = import_archive(archive, runtime, digest)
    assert repeated["status"] == "already-present"
    assert db.all("SELECT collection_token FROM stores")[0]["collection_token"] == original_token
    assert len(list((runtime / "demo-bundles").iterdir())) == 1


def test_hash_mismatch_does_not_create_database(tmp_path):
    archive, _ = make_archive(tmp_path)
    with pytest.raises(ValueError, match="SHA-256"):
        import_archive(archive, tmp_path / "runtime", "0" * 64)
    assert not (tmp_path / "runtime/voc.sqlite3").exists()


@pytest.mark.parametrize("path", ["../outside.txt", "/absolute.txt", "C:/outside.txt", "media\\outside.txt", "media//normalized.txt"])
def test_archive_paths_rejected(tmp_path, path):
    archive, digest = make_archive(tmp_path, extra={path: b"unsafe"})
    with pytest.raises(ValueError, match="不安全"):
        import_archive(archive, tmp_path / "runtime", digest)
    assert not (tmp_path / "runtime/voc.sqlite3").exists()


def test_running_server_blocks_import(tmp_path):
    archive, digest = make_archive(tmp_path)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "server.pid").write_text("123")
    with pytest.raises(ValueError, match="停止"):
        import_archive(archive, runtime, digest)


def test_database_failure_rolls_back_and_cleans_only_new_bundle(tmp_path):
    def mutation(payloads):
        payloads[1]["records"][0]["unexpected_column"] = "reject"
    archive, digest = make_archive(tmp_path, mutation=mutation)
    runtime = tmp_path / "runtime"
    with pytest.raises(ValueError, match="字段"):
        import_archive(archive, runtime, digest)
    db = Database(runtime / "voc.sqlite3")
    assert db.one("SELECT COUNT(*) AS n FROM workspaces")["n"] == 1
    assert db.one("SELECT COUNT(*) AS n FROM records")["n"] == 0
    assert not list((runtime / "demo-bundles").iterdir())


def test_partial_existing_space_never_overwritten(tmp_path):
    archive, digest = make_archive(tmp_path)
    runtime = tmp_path / "runtime"
    db = Database(runtime / "voc.sqlite3")
    db.initialize()
    db.execute("INSERT INTO workspaces VALUES ('full-demo-cxo','User changed name','2026-11-09')")
    with pytest.raises(ValueError, match="部分"):
        import_archive(archive, runtime, digest)
    assert db.one("SELECT name FROM workspaces WHERE id='full-demo-cxo'")["name"] == "User changed name"


def test_queued_reports_cannot_trigger_model_requests(tmp_path):
    def mutation(payloads):
        payloads[0]["reports"][0]["status"] = "queued"
    archive, digest = make_archive(tmp_path, mutation=mutation)
    with pytest.raises(ValueError, match="必须已完成"):
        import_archive(archive, tmp_path / "runtime", digest)
