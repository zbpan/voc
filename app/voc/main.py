import io
import json
import secrets
import shutil
import sqlite3
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated, Literal

import qrcode
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError, field_validator

from .config import APP_ROOT, PROMPT_VERSION, SESSION_ID, THEMES, load_settings
from .db import Database, dumps, now, uid
from .queries import Scope, dashboard, decode, event_rows, record_public, record_where
from .service import REPORT_LABELS, Worker
from .executive import executive_dashboard, executive_markdown
from .model_settings import model_router


Source = Literal["voice_message", "call", "interview", "text"]
Channel = Literal["mixed", "left", "right"]


class NameInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def meaningful(cls, value):
        if not value.strip():
            raise ValueError("名称不能为空")
        return value.strip()


class StoreInput(NameInput):
    workspace_id: str = "default"
    region: str = Field(default="", max_length=80)


class TextInput(BaseModel):
    workspace_id: str = "default"
    store_id: str | None = None
    title: str = Field(default="文字反馈", min_length=1, max_length=200)
    text: str = Field(min_length=2, max_length=20000)
    source_type: Source = "text"
    language_hint: str = Field(default="auto", max_length=40)

    @field_validator("text")
    @classmethod
    def meaningful(cls, value):
        if len(value.strip()) < 2:
            raise ValueError("请填写反馈内容")
        return value.strip()


class EventUpdate(BaseModel):
    version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    theme: str | None = None
    severity: Literal["low", "medium", "high", "critical"] | None = None
    sentiment: Literal["positive", "neutral", "negative", "mixed"] | None = None
    review_status: Literal["pending", "confirmed", "dismissed"] | None = None
    workflow_status: Literal["new", "in_progress", "resolved"] | None = None
    owner: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=4000)


class ReportInput(BaseModel):
    title: str = Field(default="客户原声洞察报告", min_length=1, max_length=160)
    scope: Scope = Field(default_factory=Scope)


def scope_query(workspace_id: str = "default", store_id: str = "", start: date | None = None, end: date | None = None, search: str = "", language: str = "", theme: str = "", severity: str = "", review_status: str = "", workflow_status: str = "", sentiment: str = ""):
    try:
        return Scope(**locals())
    except ValidationError as exc:
        raise HTTPException(422, "筛选条件不合法，请检查日期和文本长度") from exc


def report_markdown(report):
    snap, content = report["snapshot"], report["content"]
    m = snap["metrics"]
    scope = report["scope"]
    store = next((e["store_name"] for e in snap["events"] if e["store_name"]), "指定门店") if scope.get("store_id") else "全部门店"
    filters = [f"门店：{store}", f"日期：{scope.get('start') or '不限开始日期'} 至 {scope.get('end') or '生成时'}（UTC）"]
    for key, name in (("search", "原文搜索"), ("theme", "主题"), ("severity", "严重度"), ("review_status", "复核结果"), ("workflow_status", "跟进状态"), ("sentiment", "情绪"), ("language", "语言")):
        if scope.get(key):
            filters.append(f"{name}：{REPORT_LABELS.get(scope[key], scope[key])}")
    cited = {identifier for section in ("priorities", "strengths", "actions") for item in content[section] for identifier in item["event_ids"]}
    lines = [f"# {report['title']}", f"Session ID：`{report['session_id']}`", f"生成时间：{report['completed_at']}；模型：{report['model']}", "## 范围与口径", "；".join(filters), f"原始反馈 {m['records']} 条；分析完成 {m['completed']} 条；有效体验反馈 {m['feedback_records']} 条；有效事件 {m['events']} 条；待复核 {m['pending_review']} 条；高严重度未解决 {m['high_open']} 条。", f"模型读取 {len(snap['events'])} 条候选事件，正文引用 {len(cited)} 条不同事件。统计为生成时快照，默认排除已排除事件。音频定位为实际处理片段范围，不是字级时间戳。", "## 摘要", content["summary"]]
    for key, title in (("priorities", "优先关注"), ("strengths", "正向体验"), ("actions", "行动建议")):
        lines += ["", f"## {title}"]
        for item in content[key]:
            lines += [f"### {item['title']}", item["detail"], "证据：" + "、".join(f"`{i}`" for i in item["event_ids"])]
        if not content[key]:
            lines += ["本次样本暂无充分证据。"]
    if snap.get("executive"):
        executive = snap["executive"]
        p, m = executive["period"], executive["metrics"]
        lines += ["", "## 全量经营对照", f"本期{p['start']}至{p['end']}；前期{p['previous_start']}至{p['previous_end']}。下列指标来自全量聚合，不受前200条事件引用上限影响。", executive["headline"], executive["summary"], f"本期负向反馈{m['negative']}/{m['feedback']}；前期{m['previous']['negative']}/{m['previous']['feedback']}。"]
        for s in executive["stores"]:
            lines.append(f"- {s['name']}：本期{s['negative']}/{s['feedback']}；前期{s['previous']['negative']}/{s['previous']['feedback']}。")
    lines += ["", "## 证据索引"]
    for event in snap["events"]:
        date_note = f"；反馈日期：{event['record_created_at'][:10]}" if event.get("record_created_at") else ""
        lines += [f"### {event['title']}", f"事件ID：`{event['id']}`；反馈ID：`{event['record_id']}`；门店：{event['store_name'] or '未分配'}{date_note}；复核状态：{REPORT_LABELS.get(event['review_status'], event['review_status'])}", "> " + event["quote"].replace("\n", "\n> ")]
    return "\n\n".join(line for line in lines if line)


def create_app(settings=None, provider=None, run_worker=True):
    settings = settings or load_settings()
    db = Database(settings.db_path)
    worker = Worker(db, settings, provider)

    @asynccontextmanager
    async def lifespan(app):
        db.initialize()
        if run_worker:
            worker.start()
        yield
        worker.stop()

    app = FastAPI(title="VOC 客户原声工作台", version="0.1.0", lifespan=lifespan)
    app.state.db, app.state.worker, app.state.settings = db, worker, settings
    app.include_router(model_router(settings, worker))

    @app.exception_handler(RequestValidationError)
    async def safe_validation_error(request, exc):
        return JSONResponse(status_code=422, content={"detail": [{"loc": error["loc"], "msg": error["msg"], "type": error["type"]} for error in exc.errors()]})

    @app.middleware("http")
    async def headers(request: Request, call_next):
        if request.method in ("POST", "PATCH", "DELETE"):
            if request.headers.get("sec-fetch-site") == "cross-site":
                return Response("不接受跨站请求", status_code=403)
            if int(request.headers.get("content-length", "0")) > settings.max_bytes + 1024 * 1024:
                return Response("单次上传不能超过512MB", status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def workspace_exists(workspace_id):
        if not db.one("SELECT id FROM workspaces WHERE id=?", (workspace_id,)):
            raise HTTPException(404, "工作空间不存在")

    def store_valid(workspace_id, store_id):
        workspace_exists(workspace_id)
        if store_id and not db.one("SELECT id FROM stores WHERE id=? AND workspace_id=?", (store_id, workspace_id)):
            raise HTTPException(404, "当前工作空间中没有此门店")

    def find_record(record_id, workspace_id):
        row = db.one("SELECT r.*,s.name AS store_name FROM records r LEFT JOIN stores s ON s.id=r.store_id WHERE r.id=? AND r.workspace_id=?", (record_id, workspace_id))
        if not row:
            raise HTTPException(404, "反馈不存在")
        return row

    def insert_record(workspace_id, store_id, title, source_type, language_hint, channel, media_type, original_path=None, text=None, record_id=None):
        record_id = record_id or uid()
        db.execute("INSERT INTO records(id,workspace_id,store_id,title,source_type,language_hint,channel,original_path,text_input,media_type,created_at,model,prompt_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (record_id, workspace_id, store_id or None, title, source_type, language_hint, channel, original_path, text, media_type, now(), settings.model, PROMPT_VERSION))
        worker.wake.set()
        return {"id": record_id, "status": "queued"}

    async def save_upload(file, workspace_id, store_id, source_type, language_hint, channel, title=None):
        store_valid(workspace_id, store_id)
        if len(language_hint) > 40:
            raise HTTPException(422, "语言提示过长")
        name = (file.filename or "录音.webm").replace("\\", "/").split("/")[-1]
        suffix = Path(name).suffix.lower()
        if suffix not in (".wav", ".mp3", ".m4a", ".mp4", ".flac", ".ogg", ".webm", ".aac", ".opus"):
            await file.close()
            raise HTTPException(415, "请上传WAV、MP3、M4A、MP4、FLAC、OGG、WebM、AAC或Opus音频")
        record_id = uid()
        folder = settings.root / "media" / record_id
        folder.mkdir(parents=True)
        target = folder / ("original" + suffix)
        try:
            size = 0
            with target.open("wb") as output:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > settings.max_bytes:
                        raise HTTPException(413, "单个文件不能超过512MB")
                    output.write(chunk)
            if not size:
                raise HTTPException(422, "不能上传空文件")
            return insert_record(workspace_id, store_id, (title or name)[:200], source_type, language_hint, channel, "audio", original_path=str(target), record_id=record_id)
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        finally:
            await file.close()

    @app.get("/api/health")
    def health():
        return {"status": "ok", "model": settings.model, "region": settings.region, "configured": bool(settings.api_key), "ffmpeg": bool(shutil.which(settings.ffmpeg)), "mode": "local", "session_id": SESSION_ID, "themes": THEMES}

    @app.get("/api/workspaces")
    def workspaces():
        return db.all("SELECT * FROM workspaces ORDER BY created_at,id")

    @app.post("/api/workspaces", status_code=201)
    def add_workspace(body: NameInput):
        identifier = uid()
        db.execute("INSERT INTO workspaces VALUES (?,?,?)", (identifier, body.name, now()))
        return {"id": identifier, "name": body.name}

    @app.get("/api/stores")
    def stores(workspace_id: str = "default"):
        workspace_exists(workspace_id)
        return db.all("SELECT s.*,COUNT(r.id) AS record_count FROM stores s LEFT JOIN records r ON r.store_id=s.id WHERE s.workspace_id=? GROUP BY s.id ORDER BY s.created_at,s.id", (workspace_id,))

    @app.post("/api/stores", status_code=201)
    def add_store(body: StoreInput):
        workspace_exists(body.workspace_id)
        identifier, token = uid(), secrets.token_urlsafe(24)
        try:
            db.execute("INSERT INTO stores VALUES (?,?,?,?,?,?)", (identifier, body.workspace_id, body.name, body.region, token, now()))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "当前工作空间已存在同名门店") from exc
        return {"id": identifier, "name": body.name, "collection_token": token}

    @app.post("/api/records/text", status_code=202)
    def add_text(body: TextInput):
        store_valid(body.workspace_id, body.store_id)
        return insert_record(body.workspace_id, body.store_id, body.title, body.source_type, body.language_hint, "mixed", "text", text=body.text)

    @app.post("/api/records/upload", status_code=202)
    async def upload(file: Annotated[UploadFile, File()], workspace_id: Annotated[str, Form()] = "default", store_id: Annotated[str, Form()] = "", source_type: Annotated[Source, Form()] = "voice_message", language_hint: Annotated[str, Form()] = "auto", channel: Annotated[Channel, Form()] = "mixed", title: Annotated[str, Form()] = ""):
        return await save_upload(file, workspace_id, store_id, source_type, language_hint, channel, title)

    @app.get("/api/records")
    def records(scope: Annotated[Scope, Depends(scope_query)], status: str = "", limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
        workspace_exists(scope.workspace_id)
        where, args = record_where(scope)
        if status:
            where += " AND r.status=?"
            args.append(status)
        total = db.one("SELECT COUNT(*) AS n FROM records r WHERE " + where, args)["n"]
        rows = db.all("SELECT r.*,s.name AS store_name,(SELECT COUNT(*) FROM events e WHERE e.record_id=r.id AND e.review_status!='dismissed') AS event_count FROM records r LEFT JOIN stores s ON s.id=r.store_id WHERE " + where + " ORDER BY r.created_at DESC,r.id LIMIT ? OFFSET ?", [*args, limit, offset])
        items = []
        for row in rows:
            item = record_public(row)
            item.pop("waveform")
            item.pop("transcript")
            items.append(item)
        return {"total": total, "items": items}

    @app.get("/api/records/{record_id}")
    def record_detail(record_id: str, workspace_id: str = "default"):
        row = record_public(find_record(record_id, workspace_id))
        row["chunks"] = db.all("SELECT id,position,start,end,transcript FROM chunks WHERE record_id=? ORDER BY position", (record_id,))
        row["events"] = [decode(e, ["evidence_json"]) for e in db.all("SELECT * FROM events WHERE record_id=? ORDER BY created_at,id", (record_id,))]
        row["assets"] = [decode(e, ["metadata_json"]) for e in db.all("SELECT id,record_id,kind,mime_type,filename,metadata_json FROM record_assets WHERE record_id=? ORDER BY id", (record_id,))]
        return row

    @app.get("/api/records/{record_id}/assets/{asset_id}")
    def record_asset(record_id: str, asset_id: str, workspace_id: str = "default"):
        find_record(record_id, workspace_id)
        asset = db.one("SELECT * FROM record_assets WHERE id=? AND record_id=?", (asset_id, record_id))
        if not asset or not Path(asset["file_path"]).is_file():
            raise HTTPException(404, "附件不存在")
        return FileResponse(asset["file_path"], media_type=asset["mime_type"], content_disposition_type="inline")

    @app.get("/api/records/{record_id}/audio")
    def record_audio(record_id: str, workspace_id: str = "default"):
        row = find_record(record_id, workspace_id)
        if not row["audio_path"] or not Path(row["audio_path"]).is_file():
            raise HTTPException(404, "音频尚未就绪")
        return FileResponse(row["audio_path"], media_type="audio/wav", content_disposition_type="inline")

    @app.post("/api/records/{record_id}/retry", status_code=202)
    def retry(record_id: str, workspace_id: str = "default"):
        find_record(record_id, workspace_id)
        changed = db.execute("UPDATE records SET status='queued',stage='等待重试',error=NULL,progress=0 WHERE id=? AND workspace_id=? AND status='failed'", (record_id, workspace_id))
        if not changed:
            raise HTTPException(409, "仅失败任务可以重试")
        worker.wake.set()
        return {"id": record_id, "status": "queued"}

    @app.delete("/api/records/{record_id}")
    def remove_record(record_id: str, workspace_id: str = "default"):
        find_record(record_id, workspace_id)
        changed = db.execute("DELETE FROM records WHERE id=? AND workspace_id=? AND status IN ('failed','completed')", (record_id, workspace_id))
        if not changed:
            raise HTTPException(409, "请等待处理结束后删除")
        shutil.rmtree(settings.root / "media" / record_id, ignore_errors=True)
        return {"deleted": True}

    @app.get("/api/events")
    def events(scope: Annotated[Scope, Depends(scope_query)], limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
        workspace_exists(scope.workspace_id)
        return event_rows(db, scope, limit, offset)

    @app.patch("/api/events/{event_id}")
    def update_event(event_id: str, body: EventUpdate, workspace_id: str = "default"):
        fields = body.model_dump(exclude_none=True, exclude={"version"})
        if fields.get("theme") and fields["theme"] not in THEMES:
            raise HTTPException(422, "请选择已有主题")
        with db.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            previous = con.execute("SELECT * FROM events WHERE id=? AND workspace_id=?", (event_id, workspace_id)).fetchone()
            if not previous:
                raise HTTPException(404, "事件不存在")
            if previous["version"] != body.version:
                raise HTTPException(409, "此事件已被更新，请刷新后重试")
            if fields:
                con.execute("UPDATE events SET " + ",".join(f"{key}=?" for key in fields) + ",version=version+1 WHERE id=?", [*fields.values(), event_id])
                changes = {key: {"before": previous[key], "after": value} for key, value in fields.items() if previous[key] != value}
                con.execute("INSERT INTO event_audit VALUES (?,?,?,?)", (uid(), event_id, now(), dumps(changes)))
        return decode(db.one("SELECT * FROM events WHERE id=?", (event_id,)), ["evidence_json"])

    @app.get("/api/events/{event_id}/audit")
    def event_audit(event_id: str, workspace_id: str = "default"):
        if not db.one("SELECT id FROM events WHERE id=? AND workspace_id=?", (event_id, workspace_id)):
            raise HTTPException(404, "事件不存在")
        return [decode(row, ["changes_json"]) for row in db.all("SELECT * FROM event_audit WHERE event_id=? ORDER BY created_at,id", (event_id,))]

    @app.get("/api/dashboard")
    def stats(scope: Annotated[Scope, Depends(scope_query)]):
        workspace_exists(scope.workspace_id)
        return dashboard(db, scope)

    @app.get("/api/reports")
    def reports(workspace_id: str = "default"):
        workspace_exists(workspace_id)
        return db.all("SELECT id,title,status,error,created_at,completed_at,model FROM reports WHERE workspace_id=? ORDER BY created_at DESC,id", (workspace_id,))

    @app.get("/api/executive")
    def executive(scope: Annotated[Scope, Depends(scope_query)], window_days: int = Query(20, ge=1, le=90)):
        store_valid(scope.workspace_id, scope.store_id)
        return executive_dashboard(db, scope, window_days)

    @app.get("/api/executive/export")
    def executive_export(scope: Annotated[Scope, Depends(scope_query)], window_days: int = Query(20, ge=1, le=90)):
        store_valid(scope.workspace_id, scope.store_id)
        data = executive_dashboard(db, scope, window_days)
        return Response(executive_markdown(data, SESSION_ID), media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="VOC-executive-brief.md"'})

    @app.post("/api/reports", status_code=202)
    def add_report(body: ReportInput):
        workspace_exists(body.scope.workspace_id)
        entries = event_rows(db, body.scope, 200)
        if not entries["total"]:
            raise HTTPException(422, "当前范围没有有效事件，请先导入并完成分析")
        executive = executive_dashboard(db, body.scope)
        evidence = {r["id"]: r for r in executive.pop("evidence")}
        for event in entries["items"]:
            source = evidence.get(event["record_id"], {})
            event["executive_topics"] = source.get("topics", [])
            event["executive_period"] = source.get("period", "outside")
        snapshot = {"metrics": dashboard(db, body.scope), "events": entries["items"], "total_events": entries["total"], "sampled": entries["total"] > 200, "executive": executive}
        identifier = uid()
        db.execute("INSERT INTO reports(id,workspace_id,title,created_at,scope_json,snapshot_json,model,session_id) VALUES (?,?,?,?,?,?,?,?)", (identifier, body.scope.workspace_id, body.title, now(), dumps(body.scope.model_dump(mode="json")), dumps(snapshot), settings.model, SESSION_ID))
        worker.wake.set()
        return {"id": identifier, "status": "queued"}

    def find_report(report_id, workspace_id):
        report = db.one("SELECT * FROM reports WHERE id=? AND workspace_id=?", (report_id, workspace_id))
        if not report:
            raise HTTPException(404, "报告不存在")
        return decode(report, ["scope_json", "snapshot_json", "content_json", "usage_json"])

    @app.get("/api/reports/{report_id}")
    def report_detail(report_id: str, workspace_id: str = "default"):
        return find_report(report_id, workspace_id)

    @app.post("/api/reports/{report_id}/retry", status_code=202)
    def retry_report(report_id: str, workspace_id: str = "default"):
        find_report(report_id, workspace_id)
        if not db.execute("UPDATE reports SET status='queued',error=NULL WHERE id=? AND workspace_id=? AND status='failed'", (report_id, workspace_id)):
            raise HTTPException(409, "仅失败报告可以重试")
        worker.wake.set()
        return {"id": report_id, "status": "queued"}

    @app.get("/api/reports/{report_id}/export")
    def export_report(report_id: str, workspace_id: str = "default"):
        report = find_report(report_id, workspace_id)
        if report["status"] != "completed":
            raise HTTPException(409, "报告尚未生成完成")
        return Response(report_markdown(report), media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="VOC-report-{report_id[:8]}.md"'})

    def find_collection(token):
        store = db.one("SELECT s.*,w.name AS workspace_name FROM stores s JOIN workspaces w ON w.id=s.workspace_id WHERE s.collection_token=?", (token,))
        if not store:
            raise HTTPException(404, "采集入口不存在")
        return store

    @app.get("/api/collect/{token}")
    def collection(token: str):
        store = find_collection(token)
        return {"name": store["name"], "region": store["region"], "workspace_name": store["workspace_name"]}

    @app.get("/api/collect/{token}/qr")
    def collection_qr(token: str, request: Request):
        find_collection(token)
        image = qrcode.make(str(request.base_url).rstrip("/") + "/collect/" + token)
        output = io.BytesIO()
        image.save(output, format="PNG")
        return Response(output.getvalue(), media_type="image/png")

    @app.post("/api/collect/{token}/text", status_code=202)
    def collection_text(token: str, body: TextInput):
        store = find_collection(token)
        return insert_record(store["workspace_id"], store["id"], "门店文字反馈", "text", body.language_hint, "mixed", "text", text=body.text)

    @app.post("/api/collect/{token}/upload", status_code=202)
    async def collection_upload(token: str, file: Annotated[UploadFile, File()]):
        store = find_collection(token)
        return await save_upload(file, store["workspace_id"], store["id"], "voice_message", "auto", "mixed", "门店语音留言")

    dist = APP_ROOT / "dist"
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "接口不存在")
        if not (dist / "index.html").is_file():
            raise HTTPException(503, "前端尚未构建，请在app目录运行npm run build")
        return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
