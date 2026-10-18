"""FastAPI application implementing the approved PolicyLens REST/WS contract."""

import asyncio
from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Literal

import anyio

from fastapi import Body, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import Field

from app.adapters import demo_compile, integrated_compile, validate_compile_result
from app.events import EventHub
from app.models import Camera, Decision, Model, Rule, Zone
from app.pipelines import FakePipeline, VisionAdapter
from app.runtime import Monitor
from engine.evidence import EvidenceWriter
from engine.verification import StubVerifier, VerificationScheduler
from store.config import ConfigurationStore, DuplicateConfiguration
from store.db import AlertStore

log = logging.getLogger('policylens.app')


class CamerasBody(Model):
    cameras: list[Camera]


class ZonesBody(Model):
    zones: list[Zone]


class PolicyBody(Model):
    rules: list[Rule]


class CompileBody(Model):
    prompt: str = Field(min_length=1, max_length=2000)


class DecisionBody(Model):
    decision: Decision


class EmptyBody(Model):
    pass


def create_app(*, data_dir=None, mode=None, pipeline_factory=None, compiler=None,
               verifier=None, realtime=True):
    selected_mode = mode or os.environ.get('POLICYLENS_MODE', 'demo')
    if selected_mode not in ('demo', 'integrated'):
        raise ValueError('POLICYLENS_MODE must be demo or integrated')
    root = Path(data_dir or os.environ.get('POLICYLENS_DATA_DIR') or
                Path(__file__).resolve().parents[1] / 'store' / 'runtime')

    @asynccontextmanager
    async def lifespan(app):
        settings = ConfigurationStore(root / 'config.json')
        store = AlertStore(root / 'alerts.sqlite3')
        hub = EventHub()
        provider = verifier
        if provider is None and selected_mode == 'integrated':
            from verify.verifier import verify_crop
            provider = verify_crop
        if provider is None:
            provider = StubVerifier()
        scheduler = VerificationScheduler(provider)
        writer = EvidenceWriter(root / 'evidence')
        factory = pipeline_factory or (
            (lambda camera: FakePipeline(camera, realtime=realtime)) if selected_mode == 'demo' else
            (lambda camera: VisionAdapter(camera, multi_camera=len(settings.snapshot().cameras) > 1)))
        monitor = Monitor(settings, store, hub, scheduler, writer, factory)
        app.state.services = SimpleNamespace(settings=settings, store=store, hub=hub,
            monitor=monitor, compiler=compiler or (demo_compile if selected_mode == 'demo' else integrated_compile),
            evidence_dir=root / 'evidence', mode=selected_mode)
        log.warning('PolicyLens mode=%s; demo mode uses saved tracks and explicitly unclear stub verdicts', selected_mode)
        try:
            yield
        finally:
            try:
                monitor.stop()
            except RuntimeError:
                log.warning('Camera shutdown still pending')
            scheduler.close(wait=False)
            writer.close()

    app = FastAPI(title='PolicyLens', lifespan=lifespan)

    def services():
        return app.state.services

    def camera(camera_id):
        found = next((item for item in services().settings.snapshot().cameras if item.id == camera_id), None)
        if found is None:
            raise HTTPException(404, 'Camera not found')
        return found

    def change_config(**changes):
        service = services()
        with service.monitor.control_lock:
            if service.monitor.running:
                raise HTTPException(409, 'Stop monitoring before editing configuration')
            try:
                result = service.settings.replace(**changes)
            except DuplicateConfiguration as exc:
                raise HTTPException(409, str(exc)) from None
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            service.monitor.invalidate_preview()
            return result

    @app.get('/api/health')
    def health():
        return {'status': 'ok'}

    @app.get('/api/cameras')
    def cameras():
        return {'cameras': services().settings.snapshot().cameras}

    @app.put('/api/cameras')
    def save_cameras(body: CamerasBody):
        return {'cameras': change_config(cameras=body.cameras).cameras}

    @app.get('/api/zones')
    def zones():
        return {'zones': services().settings.snapshot().zones}

    @app.put('/api/zones')
    def save_zones(body: ZonesBody):
        return {'zones': change_config(zones=body.zones).zones}

    @app.get('/api/policy')
    def policy():
        return {'rules': services().settings.snapshot().rules}

    @app.put('/api/policy')
    def save_policy(body: PolicyBody):
        return {'rules': change_config(rules=body.rules).rules}

    @app.post('/api/policy/compile')
    def compile_policy(body: CompileBody):
        service = services()
        config = service.settings.snapshot()
        try:
            result = service.compiler(body.prompt, config.zones)
            return validate_compile_result(result, config.cameras, config.zones)
        except ValueError:
            raise HTTPException(422, 'Compiler returned invalid or unsupported rules') from None
        except Exception:
            raise HTTPException(503, 'Policy compilation unavailable') from None

    @app.get('/api/monitor')
    def monitor_status():
        state = services().monitor.snapshot()
        return {'running': state['running'], 'cameras': state['cameras']}

    @app.post('/api/monitor/start')
    def start_monitoring(body: EmptyBody | None = Body(default=None)):
        try:
            services().monitor.start()
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from None
        return {'running': True}

    @app.post('/api/monitor/stop')
    def stop_monitoring(body: EmptyBody | None = Body(default=None)):
        try:
            services().monitor.stop()
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from None
        return {'running': False}

    @app.get('/api/snapshot/{camera_id}')
    def snapshot(camera_id: str):
        selected = camera(camera_id)
        try:
            with services().monitor.control_lock:
                jpeg = services().monitor.preview(selected)
        except Exception:
            jpeg = None
        if jpeg is None:
            raise HTTPException(503, 'Camera image unavailable')
        return Response(jpeg, media_type='image/jpeg', headers={'Cache-Control': 'no-store'})

    @app.get('/api/stream/{camera_id}')
    def stream(camera_id: str, request: Request):
        selected = camera(camera_id)
        try:
            with services().monitor.control_lock:
                jpeg = services().monitor.preview(selected)
        except Exception:
            jpeg = None
        if jpeg is None:
            raise HTTPException(503, 'Camera stream unavailable')

        async def chunks():
            last_version = -1
            while not await request.is_disconnected():
                frame, version = services().monitor.latest(camera_id)
                if frame is not None and version != last_version:
                    yield (b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: '
                           + str(len(frame)).encode() + b'\r\n\r\n' + frame + b'\r\n')
                    last_version = version
                await asyncio.sleep(0.05)
        return StreamingResponse(chunks(), media_type='multipart/x-mixed-replace; boundary=frame',
                                 headers={'Cache-Control': 'no-store'})

    @app.get('/api/alerts')
    def alerts(camera_id: str | None = None, status: Literal['open', 'reviewed'] | None = None,
               limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
        rows, total = services().store.list(camera_id=camera_id, status=status, limit=limit, offset=offset)
        return {'alerts': rows, 'total': total}

    @app.get('/api/alerts/{alert_id}')
    def get_alert(alert_id: str):
        try:
            return services().store.get(alert_id)
        except KeyError:
            raise HTTPException(404, 'Alert not found') from None

    @app.post('/api/alerts/{alert_id}/decision')
    def decide(alert_id: str, body: DecisionBody):
        try:
            alert = services().store.decide(alert_id, body.decision)
        except KeyError:
            raise HTTPException(404, 'Alert not found') from None
        services().hub.publish('alert_updated', alert.model_dump(mode='json'))
        return alert

    @app.get('/evidence/{filename}')
    def evidence(filename: str):
        directory = services().evidence_dir.resolve()
        if not re.fullmatch(r'[0-9a-f]{32}\.(jpg|mp4)', filename):
            raise HTTPException(404, 'Evidence not found')
        path = (directory / filename).resolve()
        if path.parent != directory or not path.is_file():
            raise HTTPException(404, 'Evidence not found')
        return FileResponse(path, media_type='video/mp4' if filename.endswith('.mp4') else 'image/jpeg')

    @app.websocket('/ws')
    async def websocket(websocket: WebSocket):
        await websocket.accept()
        service = services()
        client = service.hub.subscribe()
        try:
            await websocket.send_json({'type': 'snapshot', 'data': service.monitor.snapshot()})
            async with anyio.create_task_group() as group:
                async def disconnected():
                    try:
                        while (await websocket.receive())['type'] != 'websocket.disconnect':
                            pass
                    except (WebSocketDisconnect, RuntimeError):
                        pass
                    finally:
                        group.cancel_scope.cancel()

                async def send_events():
                    try:
                        while True:
                            message = await client.queue.get()
                            if message['type'] == '__overflow__':
                                await websocket.close(code=1013, reason='Reload alerts and reconnect')
                                return
                            await websocket.send_json(message)
                    except (WebSocketDisconnect, RuntimeError):
                        pass
                    finally:
                        group.cancel_scope.cancel()

                group.start_soon(disconnected)
                group.start_soon(send_events)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            service.hub.unsubscribe(client)

    return app


app = create_app()
