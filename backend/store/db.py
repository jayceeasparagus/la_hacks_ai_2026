"""SQLite transactions shared safely by API threads and camera workers."""

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3

from app.models import Alert, Decision
from engine.alerts import utc_now


class AlertStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS alerts (
                    id TEXT PRIMARY KEY, camera_id TEXT NOT NULL,
                    severity TEXT NOT NULL, status TEXT NOT NULL,
                    created_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id TEXT NOT NULL REFERENCES alerts(id),
                    decision TEXT NOT NULL, decided_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS alerts_camera ON alerts(camera_id);
                CREATE INDEX IF NOT EXISTS decisions_alert ON decisions(alert_id);
            ''')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def save(self, alert: Alert) -> bool:
        with self.connection() as db:
            cursor = db.execute('INSERT OR IGNORE INTO alerts VALUES (?,?,?,?,?,?)', (
                alert.id, alert.camera_id, alert.severity, alert.status,
                alert.created_at, alert.model_dump_json()))
            return cursor.rowcount == 1

    def get(self, alert_id: str) -> Alert:
        with self.connection() as db:
            return self._get(db, alert_id)

    @staticmethod
    def _get(db, alert_id):
        row = db.execute('SELECT payload FROM alerts WHERE id=?', (alert_id,)).fetchone()
        if row is None:
            raise KeyError(alert_id)
        return Alert.model_validate_json(row['payload'])

    @staticmethod
    def _update(db, alert):
        db.execute('UPDATE alerts SET status=?, payload=? WHERE id=?',
                   (alert.status, alert.model_dump_json(), alert.id))

    def list(self, *, camera_id=None, status=None, limit=50, offset=0):
        if not 1 <= limit <= 500 or offset < 0:
            raise ValueError('Invalid pagination')
        if status not in (None, 'open', 'reviewed'):
            raise ValueError('Invalid alert status')
        filters, params = [], []
        for name, value in [('camera_id', camera_id), ('status', status)]:
            if value is not None:
                filters.append(f'{name}=?')
                params.append(value)
        where = ' WHERE ' + ' AND '.join(filters) if filters else ''
        with self.connection() as db:
            total = db.execute('SELECT COUNT(*) FROM alerts' + where, params).fetchone()[0]
            rows = db.execute('SELECT payload FROM alerts' + where + '''
                ORDER BY CASE WHEN severity='urgent' AND status='open' THEN 0 ELSE 1 END,
                created_at DESC, id ASC LIMIT ? OFFSET ?''', [*params, limit, offset]).fetchall()
            return [Alert.model_validate_json(row['payload']) for row in rows], total

    def decide(self, alert_id: str, decision: Decision) -> Alert:
        if decision not in ('confirmed', 'dismissed', 'unclear'):
            raise ValueError('Invalid decision')
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            alert = self._get(db, alert_id)
            if alert.decision == decision:
                return alert
            alert.status, alert.decision, alert.decided_at = 'reviewed', decision, utc_now()
            db.execute('INSERT INTO decisions (alert_id,decision,decided_at) VALUES (?,?,?)',
                       (alert.id, decision, alert.decided_at))
            self._update(db, alert)
            return alert

    def apply_evidence(self, patch) -> Alert:
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            alert = patch.apply(self._get(db, patch.alert_id))
            self._update(db, alert)
            return alert

    def decision_history(self, alert_id):
        with self.connection() as db:
            return [dict(row) for row in db.execute(
                'SELECT decision,decided_at FROM decisions WHERE alert_id=? ORDER BY id', (alert_id,))]
