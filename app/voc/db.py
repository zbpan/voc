import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def uid():
    return uuid.uuid4().hex


def dumps(value):
    return json.dumps(value, ensure_ascii=False)


class Database:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=15000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def execute(self, sql, args=()):
        with self.connect() as con:
            result = con.execute(sql, args)
            return result.rowcount

    def all(self, sql, args=()):
        with self.connect() as con:
            return [dict(row) for row in con.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        rows = self.all(sql, args)
        return rows[0] if rows else None

    def initialize(self):
        with self.connect() as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript("""
            CREATE TABLE IF NOT EXISTS workspaces (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS stores (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                name TEXT NOT NULL, region TEXT NOT NULL DEFAULT '', collection_token TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL, UNIQUE(workspace_id,name)
            );
            CREATE TABLE IF NOT EXISTS records (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                store_id TEXT REFERENCES stores(id), title TEXT NOT NULL, source_type TEXT NOT NULL,
                language_hint TEXT NOT NULL DEFAULT 'auto', channel TEXT NOT NULL DEFAULT 'mixed',
                original_path TEXT, audio_path TEXT, text_input TEXT, media_type TEXT NOT NULL,
                duration REAL NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'queued',
                stage TEXT NOT NULL DEFAULT '等待处理', progress INTEGER NOT NULL DEFAULT 0,
                error TEXT, created_at TEXT NOT NULL, completed_at TEXT, language TEXT,
                summary TEXT NOT NULL DEFAULT '', transcript TEXT NOT NULL DEFAULT '',
                sentiment TEXT NOT NULL DEFAULT 'neutral', is_feedback INTEGER NOT NULL DEFAULT 0,
                usage_json TEXT NOT NULL DEFAULT '{}', waveform_json TEXT NOT NULL DEFAULT '[]',
                model TEXT NOT NULL, prompt_version TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY, record_id TEXT NOT NULL REFERENCES records(id) ON DELETE CASCADE,
                position INTEGER NOT NULL, start REAL NOT NULL, end REAL NOT NULL,
                transcript TEXT NOT NULL, analysis_json TEXT NOT NULL, usage_json TEXT NOT NULL,
                UNIQUE(record_id,position)
            );
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                record_id TEXT NOT NULL REFERENCES records(id) ON DELETE CASCADE,
                title TEXT NOT NULL, theme TEXT NOT NULL, summary TEXT NOT NULL, quote TEXT NOT NULL,
                recommendation TEXT NOT NULL, severity TEXT NOT NULL, sentiment TEXT NOT NULL,
                role TEXT NOT NULL, evidence_json TEXT NOT NULL, review_status TEXT NOT NULL DEFAULT 'pending',
                workflow_status TEXT NOT NULL DEFAULT 'new', owner TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS event_audit (
                id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL, changes_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reports (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                title TEXT NOT NULL, created_at TEXT NOT NULL, completed_at TEXT,
                status TEXT NOT NULL DEFAULT 'queued', error TEXT, scope_json TEXT NOT NULL,
                snapshot_json TEXT NOT NULL, content_json TEXT NOT NULL DEFAULT '{}',
                usage_json TEXT NOT NULL DEFAULT '{}', model TEXT NOT NULL, session_id TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS record_assets (
                id TEXT PRIMARY KEY, record_id TEXT NOT NULL REFERENCES records(id) ON DELETE CASCADE,
                kind TEXT NOT NULL, file_path TEXT NOT NULL, mime_type TEXT NOT NULL,
                filename TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS assets_record ON record_assets(record_id);
            CREATE TABLE IF NOT EXISTS experience_actions (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                store_id TEXT REFERENCES stores(id), topic TEXT NOT NULL, title TEXT NOT NULL,
                owner TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT, due_at TEXT NOT NULL,
                decision TEXT NOT NULL, success_criterion TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS records_scope ON records(workspace_id,created_at);
            CREATE INDEX IF NOT EXISTS events_scope ON events(workspace_id,record_id);
            CREATE INDEX IF NOT EXISTS records_queue ON records(status,created_at);
            """)
            columns = {row["name"] for row in con.execute("PRAGMA table_info(records)")}
            if "metadata_json" not in columns:
                con.execute("ALTER TABLE records ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'")
            con.execute("INSERT OR IGNORE INTO workspaces VALUES (?,?,?)", ("default", "我的工作空间", now()))
            con.execute("UPDATE records SET status='queued',stage='恢复未完成任务',progress=0 WHERE status='processing'")
            con.execute("UPDATE reports SET status='queued' WHERE status='processing'")
