"""Alerts and decision audit rows in SQLite.

`alerts.data` holds the full Alert JSON and is the source of truth; the other
columns mirror it for filtering and ordering. One connection is shared by all
threads behind a lock, which is plenty for a few alerts per minute.
"""

from __future__ import annotations  # AlertStore.list shadows the builtin in annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from app.models import Alert

DECISIONS = ('confirmed', 'dismissed', 'unclear')
STATUSES = ('open', 'reviewed')
MAX_LIMIT = 500

SCHEMA = '''
CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY,
    camera_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL,
    decision TEXT,
    created_at TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS alerts_created ON alerts (created_at DESC, id);
CREATE INDEX IF NOT EXISTS alerts_camera ON alerts (camera_id, created_at DESC);
CREATE INDEX IF NOT EXISTS alerts_status ON alerts (status, created_at DESC);
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    decided_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS decisions_alert ON decisions (alert_id, id);
'''


def sort_key(created_at: str) -> str:
    """Fixed-width UTC text so string order is time order ('...00Z' vs '...00.5Z')."""
    try:
        moment = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
    except ValueError:
        return created_at
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def _columns(alert: Alert) -> tuple:
    return (alert.camera_id, alert.rule_id, alert.severity, alert.status, alert.decision,
            sort_key(alert.created_at), alert.model_dump_json())


class AlertStore:
    def __init__(self, path: Path | str):
        path = str(path)
        if path != ':memory:':
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        with self._lock:
            if path != ':memory:':
                self._conn.execute('PRAGMA journal_mode=WAL')
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def add(self, alert: Alert) -> bool:
        """Insert a new alert; False (no change) if the id already exists."""
        with self._lock, self._conn:
            cursor = self._conn.execute(
                'INSERT OR IGNORE INTO alerts (id, camera_id, rule_id, severity, status, decision, '
                'created_at, data) VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (alert.id, *_columns(alert)))
            return cursor.rowcount == 1

    def update(self, alert: Alert) -> Alert | None:
        """Replace a stored alert (evidence completion); returns the stored result.

        Review fields (status, decision, decided_at) belong to `decide`, so a late
        evidence update never undoes an operator decision. None if the id is unknown.
        """
        with self._lock, self._conn:
            stored = self._get(alert.id)
            if stored is None:
                return None
            merged = stored.model_copy(update={
                'evidence_status': alert.evidence_status,
                'evidence_image_url': alert.evidence_image_url,
                'evidence_clip_url': alert.evidence_clip_url})
            self._save(merged)
            return merged

    def get(self, alert_id: str) -> Alert | None:
        with self._lock:
            return self._get(alert_id)

    def list(self, camera_id: str | None = None, status: str | None = None,
             limit: int = 50, offset: int = 0) -> tuple[list[Alert], int]:
        """Newest created_at first (then id), plus the total ignoring limit/offset."""
        if status is not None and status not in STATUSES:
            raise ValueError(f'status must be one of {", ".join(STATUSES)}')
        limit = min(MAX_LIMIT, max(1, int(limit)))
        offset = max(0, int(offset))
        where, params = [], []
        if camera_id is not None:
            where.append('camera_id = ?')
            params.append(camera_id)
        if status is not None:
            where.append('status = ?')
            params.append(status)
        clause = f' WHERE {" AND ".join(where)}' if where else ''
        with self._lock:
            total = self._conn.execute(f'SELECT COUNT(*) FROM alerts{clause}', params).fetchone()[0]
            rows = self._conn.execute(
                f'SELECT data FROM alerts{clause} ORDER BY created_at DESC, id LIMIT ? OFFSET ?',
                [*params, limit, offset]).fetchall()
        return [Alert.model_validate_json(row[0]) for row in rows], total

    def decide(self, alert_id: str, decision: str, decided_at: str) -> Alert | None:
        """Record an operator decision; repeating the same decision changes nothing."""
        if decision not in DECISIONS:
            raise ValueError(f'decision must be one of {", ".join(DECISIONS)}')
        with self._lock, self._conn:
            alert = self._get(alert_id)
            if alert is None:
                return None
            if alert.status == 'reviewed' and alert.decision == decision:
                return alert
            alert = alert.model_copy(update={'status': 'reviewed', 'decision': decision,
                                             'decided_at': decided_at})
            self._save(alert)
            self._conn.execute('INSERT INTO decisions (alert_id, decision, decided_at) VALUES (?, ?, ?)',
                               (alert_id, decision, decided_at))
            return alert

    def decisions(self, alert_id: str) -> list[dict]:
        """Audit rows for one alert, oldest first."""
        with self._lock:
            rows = self._conn.execute(
                'SELECT alert_id, decision, decided_at FROM decisions WHERE alert_id = ? ORDER BY id',
                (alert_id,)).fetchall()
        return [{'alert_id': row[0], 'decision': row[1], 'decided_at': row[2]} for row in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # Callers hold the lock.

    def _get(self, alert_id: str) -> Alert | None:
        row = self._conn.execute('SELECT data FROM alerts WHERE id = ?', (alert_id,)).fetchone()
        return Alert.model_validate_json(row[0]) if row else None

    def _save(self, alert: Alert) -> None:
        self._conn.execute(
            'UPDATE alerts SET camera_id = ?, rule_id = ?, severity = ?, status = ?, decision = ?, '
            'created_at = ?, data = ? WHERE id = ?', (*_columns(alert), alert.id))
