import hashlib
import json
import os
import secrets
import shutil
import stat
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from .db import Database, dumps


WORKSPACES = {"hotel-mock-20261109": "full-demo-original", "cxo-hotel-20261109": "full-demo-cxo"}
TABLES = {"workspaces", "stores", "records", "chunks", "events", "record_assets", "experience_actions", "reports"}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_demo(descriptor, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "voc-hotel-full-demo-v1.zip"
    if target.exists():
        if sha256(target) != descriptor["sha256"]:
            raise ValueError("已缓存的演示包校验失败，请手动移走后重试")
        return target
    if not descriptor["url"].startswith("https://github.com/zbpan/voc/releases/download/"):
        raise ValueError("演示下载地址不是本项目的HTTPS Release地址")
    expected_bytes = int(descriptor["bytes"])
    if not 0 < expected_bytes <= 128 * 1024 * 1024:
        raise ValueError("演示包声明大小超出限制")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix="voc-demo-", suffix=".part", dir=directory, delete=False) as output:
            temporary = Path(output.name)
            size, reported, started = 0, 0, time.monotonic()
            with urllib.request.urlopen(descriptor["url"], timeout=60) as response:
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > expected_bytes:
                        raise ValueError("下载内容超过发布声明的大小")
                    output.write(chunk)
                    if size - reported >= 4 * 1024 * 1024:
                        print(f"Downloading {size / 1024 / 1024:.1f}/{expected_bytes / 1024 / 1024:.1f} MiB ({time.monotonic()-started:.0f}s)", flush=True)
                        reported = size
            if size != expected_bytes:
                raise ValueError("下载不完整，请重试")
        if sha256(temporary) != descriptor["sha256"]:
            raise ValueError("下载SHA-256校验失败，未导入任何内容")
        os.replace(temporary, target)
        return target
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def validate_archive(archive, expected_sha256):
    if sha256(archive) != expected_sha256:
        raise ValueError("演示包SHA-256与发布信息不符")
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        if len(entries) > 1000 or len({item.filename for item in entries}) != len(entries):
            raise ValueError("演示包条目过多或有重复路径")
        if sum(item.file_size for item in entries) > 512 * 1024 * 1024:
            raise ValueError("演示包解压大小超出限制")
        for item in entries:
            path = PurePosixPath(item.filename)
            if not path.parts or path.as_posix() != item.filename or path.is_absolute() or ".." in path.parts or "\\" in item.filename or ":" in item.filename or stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError("演示包包含不安全路径或符号链接")
        manifest = json.loads(bundle.read("manifest.json"))
        if manifest.get("schema_version") != 1 or manifest.get("synthetic") is not True:
            raise ValueError("不支持的演示格式或缺少虚构数据声明")
        if {item["workspace_id"] for item in manifest["datasets"]} != set(WORKSPACES):
            raise ValueError("演示空间清单不符")
        if len(manifest["datasets"]) != len(WORKSPACES):
            raise ValueError("演示空间清单有重复")
        if any("\\" in name or PurePosixPath(name).as_posix() != name for name in manifest["files"]):
            raise ValueError("文件清单包含不安全路径")
        if {item.filename for item in entries} != set(manifest["files"]) | {"manifest.json"}:
            raise ValueError("文件清单与压缩包不一致")
        for name, info in manifest["files"].items():
            content = bundle.read(name)
            if len(content) != info["bytes"] or hashlib.sha256(content).hexdigest() != info["sha256"]:
                raise ValueError("包内文件校验失败：" + name)
        payloads = []
        media = {name for name in manifest["files"] if name.startswith("media/")}
        all_ids = set(WORKSPACES)
        for description in manifest["datasets"]:
            payload = json.loads(bundle.read(description["file"]))
            source = description["workspace_id"]
            if payload["workspace"]["id"] != source or len(payload["records"]) != description["records"] or len(payload["stores"]) != description["stores"]:
                raise ValueError("空间记录数量不符")
            event_count = sum(len(row["events"]) for row in payload["records"])
            if event_count != description["events"]:
                raise ValueError("事件数量不符")
            ids = [row["id"] for row in payload["stores"] + payload["actions"] + payload["reports"]]
            if any(row["workspace_id"] != source for row in payload["stores"] + payload["actions"] + payload["reports"]):
                raise ValueError("门店、行动或报告的空间关联错误")
            if any(row["status"] != "completed" for row in payload["reports"]):
                raise ValueError("演示报告必须已完成，不允许导入待执行任务")
            store_ids = {row["id"] for row in payload["stores"]}
            for row in payload["records"]:
                if row["workspace_id"] != source or row["status"] != "completed" or row["metadata_json"].get("synthetic") is not True or row["store_id"] not in store_ids:
                    raise ValueError("反馈不是完整的虚构样例或门店关联无效")
                ids.append(row["id"])
                chunks = {chunk["id"] for chunk in row["chunks"]}
                for group in ("chunks", "events", "assets"):
                    for child in row[group]:
                        if child["record_id"] != row["id"] or ("workspace_id" in child and child["workspace_id"] != source):
                            raise ValueError("子记录关联错误")
                        ids.append(child["id"])
                for event in row["events"]:
                    if any(proof["chunk_id"] not in chunks for proof in event["evidence_json"]):
                        raise ValueError("事件的片段引用无效")
                references = [row.get("original_path"), row.get("audio_path"), *[asset["file_path"] for asset in row["assets"]]]
                if any(name not in media for name in references if name):
                    raise ValueError("反馈媒体引用不存在")
            if len(ids) != len(set(ids)) or all_ids.intersection(ids):
                raise ValueError("演示包含重复ID")
            all_ids.update(ids)
            payloads.append(payload)
        return manifest, payloads, all_ids


def import_archive(archive, root, expected_sha256):
    root = Path(root).resolve()
    if (root / "server.pid").exists():
        raise ValueError("请先停止VOC服务再导入；若是残留PID文件，请核实进程已退出后处理")
    manifest, payloads, identifiers = validate_archive(archive, expected_sha256)
    database = Database(root / "voc.sqlite3")
    database.initialize()
    existing = [database.one("SELECT id FROM workspaces WHERE id=?", (target,)) for target in WORKSPACES.values()]
    if all(existing):
        counts = {target: database.one("SELECT COUNT(*) AS n FROM records WHERE workspace_id=?", (target,))["n"] for target in WORKSPACES.values()}
        expected = {WORKSPACES[item["workspace_id"]]: item["records"] for item in manifest["datasets"]}
        if counts != expected:
            raise ValueError("已有演示空间数量与清单不同；不会覆盖，请使用新的VOC_DATA_DIR")
        return {"status": "already-present", "records": counts}
    if any(existing):
        raise ValueError("已有部分完整演示空间；不会覆盖，请使用新的VOC_DATA_DIR")
    mapping = {identifier: "full-demo-" + identifier for identifier in identifiers}
    mapping.update(WORKSPACES)

    def remap(value):
        if isinstance(value, str):
            return mapping.get(value, value)
        if isinstance(value, list):
            return [remap(item) for item in value]
        if isinstance(value, dict):
            return {key: remap(item) for key, item in value.items()}
        return value

    bundles = root / "demo-bundles"
    bundles.mkdir(exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix="full-demo-v1-", dir=bundles))
    committed = False
    try:
        with zipfile.ZipFile(archive) as bundle:
            for name in ["manifest.json", *manifest["files"]]:
                target = destination.joinpath(*PurePosixPath(name).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(name) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
        with database.connect() as connection:
            columns = {table: {row["name"] for row in connection.execute("PRAGMA table_info(" + table + ")")} for table in TABLES}

            def insert(table, value):
                if table not in TABLES or set(value) - columns[table]:
                    raise ValueError("数据字段与当前应用结构不一致：" + table)
                value = {key: dumps(item) if key.endswith("_json") else item for key, item in value.items()}
                fields = list(value)
                connection.execute("INSERT INTO " + table + "(" + ",".join(fields) + ") VALUES (" + ",".join("?" for _ in fields) + ")", [value[key] for key in fields])

            for source_payload in payloads:
                payload = remap(source_payload)
                insert("workspaces", payload["workspace"])
                for store in payload["stores"]:
                    store["collection_token"] = secrets.token_urlsafe(24)
                    insert("stores", store)
                for row in payload["records"]:
                    chunks, events, assets = row.pop("chunks"), row.pop("events"), row.pop("assets")
                    for field in ("original_path", "audio_path"):
                        if row[field]:
                            row[field] = str(destination / row[field])
                    insert("records", row)
                    for chunk in chunks:
                        insert("chunks", chunk)
                    for event in events:
                        insert("events", event)
                    for asset in assets:
                        asset["file_path"] = str(destination / asset["file_path"])
                        insert("record_assets", asset)
                for action in payload["actions"]:
                    insert("experience_actions", action)
                for report in payload["reports"]:
                    insert("reports", report)
            for description in manifest["datasets"]:
                target = WORKSPACES[description["workspace_id"]]
                counts = [connection.execute("SELECT COUNT(*) FROM " + table + " WHERE workspace_id=?", (target,)).fetchone()[0] for table in ("records", "events", "stores")]
                if counts != [description["records"], description["events"], description["stores"]]:
                    raise ValueError("导入后数量核对失败，事务已撤销")
        committed = True
        return {"status": "imported", "workspaces": list(WORKSPACES.values()), "package_id": manifest["package_id"], "media_directory": str(destination)}
    finally:
        if not committed:
            shutil.rmtree(destination)
