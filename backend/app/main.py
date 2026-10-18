"""PolicyLens HTTP + WebSocket server (contracts/api.md).

Run from backend/:  uvicorn app.main:app --port 8000

Environment:
- POLICYLENS_DATA_DIR      settings/, alerts.db and evidence/ (default backend/data)
- POLICYLENS_SEED_DEMO=1   write the demo cameras, zones and rules if none are saved
- POLICYLENS_DEMO_SOURCES=synthetic   seed the demo cameras with synthetic scenes (no webcam)
- POLICYLENS_SCENE=<file>  load a demo scene (cameras, zones, rules, cached verdicts) at startup,
                           replacing saved ones
- POLICYLENS_FAKE_LLM=1    offline compiler and verifier (no network)
- POLICYLENS_SOURCE_SPEED  playback speed multiplier for synthetic/replay sources
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse

from app.broadcast import Broadcaster
from app.demo import demo_cameras
from app.evidence import EvidenceWriter
from app.models import Alert, Camera, CompileResult, Decision, Model, Rule, Zone
from app.settings import Settings, SettingsError
from app.sources import snapshot_image
from app.render import encode_jpeg
from app.verdicts import CachedVerdicts
from app.workers import MonitorManager
from engine.alerts import utc_now
from store.db import AlertStore

log = logging.getLogger('policylens.app')

BACKEND_DIR = Path(__file__).resolve().parents[1]
CORS_ORIGINS = ['http://localhost:5173', 'http://127.0.0.1:5173']
STREAM_INTERVAL = 0.1  # ~10 fps MJPEG
BOUNDARY = 'frame'
SYNTHETIC_DEMO_SOURCES = {'cam_entrance': 'synthetic:entrance_bag', 'cam_exit': 'synthetic:exit_bag'}


# Request and response bodies (extra fields are rejected with 422) --------------------

class CamerasBody(Model):
    cameras: list[Camera]


class ZonesBody(Model):
    zones: list[Zone]


class RulesBody(Model):
    rules: list[Rule]


class CompileBody(Model):
    prompt: str


class DecisionBody(Model):
    decision: Decision


class CameraStatus(Model):
    camera_id: str
    status: Literal['online', 'offline', 'connecting']
    fps: float
    last_frame_ts: float | None
    error: str | None


class MonitorStatus(Model):
    running: bool
    cameras: list[CameraStatus]


class RunningBody(Model):
    running: bool


class AlertList(Model):
    alerts: list[Alert]
    total: int


class Health(Model):
    status: Literal['ok']


# Helpers --------------------------------------------------------------------------

def _env_flag(name: str) -> bool:
    return os.getenv(name, '').strip().lower() in ('1', 'true', 'yes')


def settings_status(error: SettingsError) -> int:
    """409 for duplicate ids and reference conflicts, 500 for unreadable files, else 422."""
    message = str(error)
    if (message.startswith('Duplicate') or message.startswith('Cannot remove')
            or 'references unknown' in message):
        return 409
    if 'is unreadable' in message:
        return 500
    return 422


def seed(settings: Settings) -> CachedVerdicts | None:
    """Load the demo scene or seed the demo configuration; returns the scene's cached verdicts."""
    scene = os.getenv('POLICYLENS_SCENE', '').strip()
    if scene:
        from app.scenes import load_scene
        loaded = load_scene(Path(scene), settings)
        log.info('Loaded demo scene %r from %s', loaded.name, scene)
        if loaded.cached_verdicts is None:
            return None
        try:
            return CachedVerdicts.load(Path(loaded.cached_verdicts.file), loaded.cached_verdicts.cameras)
        except (OSError, ValueError) as error:
            log.warning('Cached verdicts unavailable (%s); every check goes to the live verifier', error)
            return None
    if not _env_flag('POLICYLENS_SEED_DEMO'):
        return None
    if (os.getenv('POLICYLENS_DEMO_SOURCES', '').strip().lower() == 'synthetic'
            and not settings.path('cameras').exists()):
        cameras = [camera.model_copy(update={'source': SYNTHETIC_DEMO_SOURCES.get(camera.id, camera.source)})
                   for camera in demo_cameras()]
        settings.save_cameras(cameras)
    settings.seed_demo()
    return None


def create_app(data_dir: Path | None = None, *, verifier=None, source_factory=None) -> FastAPI:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    configured_dir = data_dir

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        root = Path(configured_dir or os.getenv('POLICYLENS_DATA_DIR') or BACKEND_DIR / 'data')
        settings = Settings(root / 'settings')
        cached_verdicts = seed(settings)
        store = AlertStore(root / 'alerts.db')
        evidence = EvidenceWriter(root / 'evidence')
        broadcaster = Broadcaster()
        broadcaster.bind(asyncio.get_running_loop())
        manager = MonitorManager(settings, store, evidence, broadcaster.publish,
                                 verifier=verifier, source_factory=source_factory,
                                 cached_verdicts=cached_verdicts)
        app.state.settings, app.state.store, app.state.evidence = settings, store, evidence
        app.state.broadcaster, app.state.manager = broadcaster, manager
        log.info('PolicyLens data directory: %s', root)
        try:
            yield
        finally:
            await asyncio.to_thread(manager.close)
            broadcaster.unbind()
            await asyncio.to_thread(evidence.shutdown, True)
            store.close()

    app = FastAPI(title='PolicyLens', lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=False,
                       allow_methods=['*'], allow_headers=['*'])

    def state(request: Request):
        return request.app.state

    def require_stopped(request: Request) -> None:
        if state(request).manager.running:
            raise HTTPException(409, 'Stop monitoring before changing the configuration')

    def save(request: Request, saver, items):
        # Serialize configuration writes with monitor startup.
        with state(request).manager._lock:
            require_stopped(request)
            try:
                return saver(items)
            except SettingsError as error:
                raise HTTPException(settings_status(error), str(error)) from error

    def read(getter):
        try:
            return getter()
        except SettingsError as error:
            raise HTTPException(500, str(error)) from error

    def camera_or_404(request: Request, camera_id: str) -> Camera:
        for camera in read(state(request).settings.cameras):
            if camera.id == camera_id:
                return camera
        raise HTTPException(404, f'Unknown camera {camera_id}')

    # Health and configuration ----------------------------------------------------------

    @app.get('/api/health', response_model=Health)
    def health():
        return {'status': 'ok'}

    @app.get('/api/cameras', response_model=CamerasBody)
    def get_cameras(request: Request):
        return {'cameras': read(state(request).settings.cameras)}

    @app.put('/api/cameras', response_model=CamerasBody)
    def put_cameras(body: CamerasBody, request: Request):
        return {'cameras': save(request, state(request).settings.save_cameras, body.cameras)}

    @app.get('/api/zones', response_model=ZonesBody)
    def get_zones(request: Request):
        return {'zones': read(state(request).settings.zones)}

    @app.put('/api/zones', response_model=ZonesBody)
    def put_zones(body: ZonesBody, request: Request):
        return {'zones': save(request, state(request).settings.save_zones, body.zones)}

    @app.post('/api/policy/compile', response_model=CompileResult)
    def compile_route(body: CompileBody, request: Request):
        from policy.compiler import compile_policy
        return compile_policy(body.prompt, read(state(request).settings.zones))

    @app.get('/api/policy', response_model=RulesBody)
    def get_policy(request: Request):
        return {'rules': read(state(request).settings.rules)}

    @app.put('/api/policy', response_model=RulesBody)
    def put_policy(body: RulesBody, request: Request):
        # Rules are the one setting that may change while monitoring: running cameras switch
        # to the new rules at once and keep their sources (contracts/api.md).
        manager = state(request).manager
        with manager._lock:
            try:
                rules = state(request).settings.save_rules(body.rules)
            except SettingsError as error:
                raise HTTPException(settings_status(error), str(error)) from error
            manager.apply_rules(rules)
        return {'rules': rules}

    # Monitoring ----------------------------------------------------------------------

    @app.post('/api/monitor/start', response_model=RunningBody)
    def monitor_start(request: Request):
        try:
            state(request).manager.start()
        except SettingsError as error:
            raise HTTPException(500, str(error)) from error
        except ValueError as error:
            raise HTTPException(409, f'Cannot start monitoring: {error}') from error
        return {'running': True}

    @app.post('/api/monitor/stop', response_model=RunningBody)
    def monitor_stop(request: Request):
        state(request).manager.stop()
        return {'running': False}

    @app.get('/api/monitor', response_model=MonitorStatus)
    def monitor(request: Request):
        manager = state(request).manager
        return {'running': manager.running, 'cameras': manager.statuses()}

    # Alerts --------------------------------------------------------------------------

    @app.get('/api/alerts', response_model=AlertList)
    def list_alerts(request: Request, camera_id: str | None = None,
                    status: Literal['open', 'reviewed'] | None = None,
                    limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
        alerts, total = state(request).store.list(camera_id=camera_id, status=status,
                                                  limit=limit, offset=offset)
        return {'alerts': alerts, 'total': total}

    @app.get('/api/alerts/{alert_id}', response_model=Alert)
    def get_alert(alert_id: str, request: Request):
        alert = state(request).store.get(alert_id)
        if alert is None:
            raise HTTPException(404, 'Unknown alert')
        return alert

    @app.post('/api/alerts/{alert_id}/decision', response_model=Alert)
    def decide(alert_id: str, body: DecisionBody, request: Request):
        store = state(request).store
        before = store.get(alert_id)
        if before is None:
            raise HTTPException(404, 'Unknown alert')
        alert = store.decide(alert_id, body.decision, utc_now())
        if alert is None:
            raise HTTPException(404, 'Unknown alert')
        if alert != before:
            state(request).broadcaster.publish('alert_updated', alert)
        return alert

    @app.get('/evidence/{filename}')
    def evidence_file(filename: str, request: Request):
        path = state(request).evidence.resolve(filename)
        if path is None:
            raise HTTPException(404, 'Unknown evidence file')
        media = 'video/mp4' if path.suffix == '.mp4' else 'image/jpeg'
        return FileResponse(path, media_type=media)

    # Frames ---------------------------------------------------------------------------

    @app.get('/api/snapshot/{camera_id}')
    def snapshot(camera_id: str, request: Request):
        camera = camera_or_404(request, camera_id)
        manager = state(request).manager
        data = None
        worker = manager.worker(camera_id) if manager.running else None
        if worker is not None:
            data = worker.raw_jpeg()
        elif not manager.running:
            image = snapshot_image(camera)
            data = encode_jpeg(image) if image is not None else None
        if data is None:
            raise HTTPException(503, 'No frame available for this camera')
        return Response(data, media_type='image/jpeg', headers={'Cache-Control': 'no-store'})

    @app.get('/api/stream/{camera_id}')
    async def stream(camera_id: str, request: Request):
        await asyncio.to_thread(camera_or_404, request, camera_id)
        manager = state(request).manager
        if not manager.running or manager.worker(camera_id) is None:
            raise HTTPException(503, 'Not monitoring; start monitoring to stream')

        async def frames():
            last = None
            while manager.running:
                worker = manager.worker(camera_id)
                if worker is None or await request.is_disconnected():
                    break
                data = await asyncio.to_thread(worker.annotated_jpeg)
                if data is not None and data is not last:
                    last = data
                    yield (f'--{BOUNDARY}\r\nContent-Type: image/jpeg\r\n'
                           f'Content-Length: {len(data)}\r\n\r\n').encode() + data + b'\r\n'
                await asyncio.sleep(STREAM_INTERVAL)

        return StreamingResponse(frames(), media_type=f'multipart/x-mixed-replace; boundary={BOUNDARY}',
                                 headers={'Cache-Control': 'no-store'})

    # WebSocket -------------------------------------------------------------------------

    @app.websocket('/ws')
    async def websocket(ws: WebSocket):
        app_state = ws.app.state
        await app_state.broadcaster.serve(ws, app_state.manager.snapshot)

    return app


logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
app = create_app()
