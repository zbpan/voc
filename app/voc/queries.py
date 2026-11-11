import json
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from pydantic import BaseModel, Field, model_validator


class Scope(BaseModel):
    workspace_id: str = "default"
    store_id: str = ""
    start: date | None = None
    end: date | None = None
    search: str = Field(default="", max_length=200)
    language: str = Field(default="", max_length=40)
    theme: str = Field(default="", max_length=60)
    severity: str = ""
    review_status: str = ""
    workflow_status: str = ""
    sentiment: str = ""

    @model_validator(mode="after")
    def dates(self):
        if self.start and self.end and self.start > self.end:
            raise ValueError("开始日期不能晚于结束日期")
        return self


def record_where(scope):
    parts, args = ["r.workspace_id=?"], [scope.workspace_id]
    for name in ("store_id", "language"):
        value = getattr(scope, name)
        if value:
            parts.append(f"r.{name}=?")
            args.append(value)
    if scope.start:
        parts.append("r.created_at>=?")
        args.append(scope.start.isoformat())
    if scope.end:
        parts.append("r.created_at<=?")
        args.append(scope.end.isoformat() + "T23:59:59.999999+00:00")
    if scope.search:
        parts.append("(r.title LIKE ? ESCAPE '!' OR r.transcript LIKE ? ESCAPE '!')")
        query = scope.search.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        args.extend([f"%{query}%"] * 2)
    return " AND ".join(parts), args


def event_where(scope):
    where, args = record_where(scope)
    parts = [where, "r.status='completed'"]
    for name in ("theme", "severity", "review_status", "workflow_status", "sentiment"):
        value = getattr(scope, name)
        if value:
            parts.append(f"e.{name}=?")
            args.append(value)
    if not scope.review_status:
        parts.append("e.review_status!='dismissed'")
    return " AND ".join(parts), args


def decode(row, fields):
    if row is None:
        return None
    for field in fields:
        row[field.removesuffix("_json")] = json.loads(row.pop(field))
    return row


def record_public(row):
    if row is None:
        return None
    row = dict(row)
    row["has_audio"] = bool(row.pop("audio_path", None))
    row.pop("original_path", None)
    row["submitted_text"] = row.pop("text_input", None)
    return decode(row, ["usage_json", "waveform_json", "metadata_json"])


def event_rows(db, scope, limit=100, offset=0):
    where, args = event_where(scope)
    join = " FROM events e JOIN records r ON r.id=e.record_id LEFT JOIN stores s ON s.id=r.store_id WHERE "
    count = db.one("SELECT COUNT(*) AS n" + join + where, args)["n"]
    rows = db.all("SELECT e.*,r.title AS record_title,r.created_at AS record_created_at,r.media_type,r.duration,r.language,s.name AS store_name" + join + where + " ORDER BY CASE e.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,e.created_at DESC,e.id LIMIT ? OFFSET ?", [*args, limit, offset])
    return {"total": count, "items": [decode(row, ["evidence_json"]) for row in rows]}


def dashboard(db, scope):
    where, args = record_where(scope)
    records = db.all("SELECT r.id,r.status,r.duration,r.sentiment,r.is_feedback,r.created_at,r.language FROM records r WHERE " + where, args)
    ew, ea = event_where(scope)
    events = db.all("SELECT e.theme,e.severity,e.sentiment,e.review_status,e.workflow_status FROM events e JOIN records r ON r.id=e.record_id WHERE " + ew, ea)
    completed = [r for r in records if r["status"] == "completed"]
    feedback = [r for r in completed if r["is_feedback"]]
    sentiments = Counter(r["sentiment"] for r in feedback)
    high = [e for e in events if e["severity"] in ("high", "critical") and e["workflow_status"] != "resolved"]
    day_counts = Counter(r["created_at"][:10] for r in records)
    negative_days = Counter(r["created_at"][:10] for r in feedback if r["sentiment"] in ("negative", "mixed"))
    end = scope.end or datetime.now(timezone.utc).date()
    start = scope.start or (min(date.fromisoformat(r["created_at"][:10]) for r in records) if records else end - timedelta(days=13))
    start = max(start, end - timedelta(days=89))
    trend = [{"date": (start + timedelta(days=i)).isoformat(), "total": day_counts[(start + timedelta(days=i)).isoformat()], "negative": negative_days[(start + timedelta(days=i)).isoformat()]} for i in range(max(0, (end - start).days + 1))]
    return {
        "records": len(records), "completed": len(completed), "feedback_records": len(feedback),
        "queued": sum(r["status"] in ("queued", "processing") for r in records),
        "failed": sum(r["status"] == "failed" for r in records),
        "audio_seconds": round(sum(r["duration"] for r in completed), 1),
        "events": len(events), "high_open": len(high),
        "pending_review": sum(e["review_status"] == "pending" for e in events),
        "resolved": sum(e["workflow_status"] == "resolved" for e in events),
        "negative_percent": round(100 * (sentiments["negative"] + sentiments["mixed"]) / len(feedback), 1) if feedback else None,
        "sentiments": dict(sentiments), "themes": [{"name": k, "count": v} for k, v in Counter(e["theme"] for e in events).most_common()],
        "languages": dict(Counter(r["language"] for r in completed if r["language"])),
        "trend": trend, "trend_window_days": len(trend), "scope": scope.model_dump(mode="json"),
    }
