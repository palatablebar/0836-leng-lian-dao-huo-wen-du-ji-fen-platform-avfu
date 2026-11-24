import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=8)
        connection.row_factory = sqlite3.Row
        return connection

    def init(self):
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS runs(
              id TEXT PRIMARY KEY,
              request_key TEXT UNIQUE NOT NULL,
              created_at TEXT NOT NULL,
              profile TEXT NOT NULL,
              status TEXT NOT NULL,
              revision INTEGER NOT NULL,
              payload TEXT NOT NULL,
              comment TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS probe_tolerances(
              sensor_id TEXT PRIMARY KEY,
              tolerance TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS calibration_reports(
              run_id TEXT NOT NULL,
              sensor_id TEXT NOT NULL,
              measured_offset TEXT NOT NULL,
              content_digest TEXT NOT NULL,
              created_at TEXT NOT NULL,
              PRIMARY KEY(run_id, sensor_id)
            );
            ''')

    def find_by_request(self, request_key):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE request_key=?", (request_key,)).fetchone()
        return dict(row) if row else None

    def create(self, request_key, profile, payload):
        existing = self.find_by_request(request_key)
        if existing:
            return existing
        run_id = uuid.uuid4().hex[:12]
        with self.connect() as db:
            db.execute("INSERT INTO runs(id,request_key,created_at,profile,status,revision,payload) VALUES(?,?,?,?,?,?,?)",
                       (run_id, request_key, datetime.now(timezone.utc).isoformat(), profile, "DRAFT", 0,
                        json.dumps(payload, ensure_ascii=False)))
        return self.get(run_id)

    def get(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return dict(row) if row else None

    def review(self, run_id, decision, comment, expected_revision):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                return None, "missing"
            if row["revision"] != expected_revision:
                return None, "stale"
            db.execute("UPDATE runs SET status=?, revision=revision+1, comment=? WHERE id=?",
                       (decision, comment, run_id))
        return self.get(run_id), None

    def upsert_tolerance(self, sensor_id, tolerance):
        with self.connect() as db:
            db.execute(
                "INSERT INTO probe_tolerances(sensor_id,tolerance,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(sensor_id) DO UPDATE SET tolerance=excluded.tolerance, updated_at=excluded.updated_at",
                (sensor_id, str(tolerance), datetime.now(timezone.utc).isoformat()))

    def tolerances(self, sensor_ids=None):
        with self.connect() as db:
            if sensor_ids is None:
                rows = db.execute("SELECT sensor_id, tolerance FROM probe_tolerances").fetchall()
            else:
                if not sensor_ids:
                    return {}
                marks = ",".join("?" for _ in sensor_ids)
                rows = db.execute(
                    f"SELECT sensor_id, tolerance FROM probe_tolerances WHERE sensor_id IN ({marks})",
                    tuple(sensor_ids)).fetchall()
        return {row["sensor_id"]: row["tolerance"] for row in rows}

    def reports(self, run_id):
        with self.connect() as db:
            rows = db.execute(
                "SELECT sensor_id, measured_offset, content_digest, created_at "
                "FROM calibration_reports WHERE run_id=? ORDER BY sensor_id", (run_id,)).fetchall()
        return [dict(row) for row in rows]

    def report_digest(self, run_id, sensor_id):
        with self.connect() as db:
            row = db.execute(
                "SELECT content_digest FROM calibration_reports WHERE run_id=? AND sensor_id=?",
                (run_id, sensor_id)).fetchone()
        return row["content_digest"] if row else None

    def upsert_report(self, run_id, sensor_id, measured_offset, content_digest):
        """写入校准报告。返回 True 表示内容发生变化（产生新版本），False 表示同内容重试。"""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT content_digest FROM calibration_reports WHERE run_id=? AND sensor_id=?",
                (run_id, sensor_id)).fetchone()
            if existing is not None and existing["content_digest"] == content_digest:
                return False
            db.execute(
                "INSERT INTO calibration_reports(run_id,sensor_id,measured_offset,content_digest,created_at) "
                "VALUES(?,?,?,?,?) ON CONFLICT(run_id,sensor_id) DO UPDATE SET "
                "measured_offset=excluded.measured_offset, content_digest=excluded.content_digest, "
                "created_at=excluded.created_at",
                (run_id, sensor_id, str(measured_offset), content_digest,
                 datetime.now(timezone.utc).isoformat()))
            db.execute("UPDATE runs SET revision=revision+1 WHERE id=?", (run_id,))
        return True

    def save_payload(self, run_id, payload):
        with self.connect() as db:
            db.execute("UPDATE runs SET payload=? WHERE id=?",
                       (json.dumps(payload, ensure_ascii=False), run_id))

    def supersede(self, run_id):
        """已签发批次在实测重算后超限：停止凭旧结论放行，凭据仍保留可下载。"""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status, revision FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                return None, "missing"
            if row["status"] != "APPROVED":
                return dict(row), "unchanged"
            db.execute("UPDATE runs SET status=?, revision=revision+1 WHERE id=?",
                       ("SUPERSEDED", run_id))
        return self.get(run_id), None
