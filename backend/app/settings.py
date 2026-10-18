"""Persisted cameras, zones and rules as JSON files shaped like the API bodies.

Every save validates the whole request against the saved configuration before
writing anything, and writes atomically (temp file in the same folder, then
os.replace), so a rejected or interrupted save never leaves a partial file.
"""

import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path

from pydantic import BaseModel, ValidationError

from app.demo import demo_cameras, demo_rules, demo_zones
from app.models import Camera, Rule, Zone
from engine.zones import validate_polygon

MAX_CAMERAS = 3
log = logging.getLogger(__name__)


class SettingsError(ValueError):
    """A configuration change was rejected; the message is safe to show users."""


def _duplicates(ids: list[str]) -> list[str]:
    seen, repeated = set(), []
    for item in ids:
        if item in seen and item not in repeated:
            repeated.append(item)
        seen.add(item)
    return repeated


class Settings:
    FILES = {'cameras': (Camera, 'cameras.json'), 'zones': (Zone, 'zones.json'),
             'rules': (Rule, 'policy.json')}

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def path(self, key: str) -> Path:
        return self.directory / self.FILES[key][1]

    # Reading

    def _read(self, key: str) -> list:
        model, _ = self.FILES[key]
        path = self.path(key)
        with self._lock:
            if not path.exists():
                return []
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                return [model.model_validate(item) for item in data[key]]
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise SettingsError(f'{path.name} is unreadable: {error}') from error

    def cameras(self) -> list[Camera]:
        return self._read('cameras')

    def zones(self) -> list[Zone]:
        return self._read('zones')

    def rules(self) -> list[Rule]:
        return self._read('rules')

    # Writing

    def _coerce(self, key: str, items) -> list:
        model, _ = self.FILES[key]
        try:
            return [model.model_validate(item.model_dump() if isinstance(item, BaseModel) else item)
                    for item in items]
        except (ValidationError, TypeError) as error:
            raise SettingsError(f'Invalid {key}: {error}') from error

    def _write(self, key: str, items: list[BaseModel]) -> None:
        path = self.path(key)
        body = json.dumps({key: [item.model_dump(mode='json') for item in items]}, indent=2)
        handle, temp = tempfile.mkstemp(prefix=f'.{path.stem}.', suffix='.tmp', dir=self.directory)
        try:
            with os.fdopen(handle, 'w', encoding='utf-8') as file:
                file.write(body + '\n')
                file.flush()
                os.fsync(file.fileno())
            for attempt in range(5):
                try:
                    os.replace(temp, path)
                    break
                except PermissionError:
                    # Windows: antivirus or sync clients can hold the target briefly.
                    if attempt == 4:
                        raise
                    time.sleep(0.05)
        except BaseException:
            try:
                os.unlink(temp)
            except OSError:
                pass
            raise

    def _check_unique(self, key: str, items: list) -> None:
        repeated = _duplicates([item.id for item in items])
        if repeated:
            raise SettingsError(f'Duplicate {key[:-1]} id: {", ".join(repeated)}')

    def save_cameras(self, cameras: list[Camera]) -> list[Camera]:
        """Replace the camera list (at most three, unique ids)."""
        cameras = self._coerce('cameras', cameras)
        if len(cameras) > MAX_CAMERAS:
            raise SettingsError(f'At most {MAX_CAMERAS} cameras are supported')
        self._check_unique('cameras', cameras)
        with self._lock:
            ids = {camera.id for camera in cameras}
            orphans = sorted({zone.camera_id for zone in self.zones()} - ids)
            if orphans:
                raise SettingsError(f'Cannot remove camera {", ".join(orphans)}: '
                                    'zones still reference it; delete those zones first')
            self._write('cameras', cameras)
        return [camera.model_copy(deep=True) for camera in cameras]

    def save_zones(self, zones: list[Zone]) -> list[Zone]:
        """Replace the zone list; each zone needs a saved camera and a valid polygon."""
        zones = self._coerce('zones', zones)
        self._check_unique('zones', zones)
        for zone in zones:
            try:
                validate_polygon(zone.polygon)
            except ValueError as error:
                raise SettingsError(f'Zone {zone.id}: {error}') from error
        with self._lock:
            camera_ids = {camera.id for camera in self.cameras()}
            for zone in zones:
                if zone.camera_id not in camera_ids:
                    raise SettingsError(f'Zone {zone.id} references unknown camera {zone.camera_id}')
            ids = {zone.id for zone in zones}
            orphans = sorted({rule.zone for rule in self.rules()} - ids)
            if orphans:
                raise SettingsError(f'Cannot remove zone {", ".join(orphans)}: '
                                    'rules still reference it; update the policy first')
            self._write('zones', zones)
        return [zone.model_copy(deep=True) for zone in zones]

    def save_rules(self, rules: list[Rule]) -> list[Rule]:
        """Replace the active policy; each rule must reference a saved zone."""
        rules = self._coerce('rules', rules)
        self._check_unique('rules', rules)
        with self._lock:
            zone_ids = {zone.id for zone in self.zones()}
            for rule in rules:
                if rule.zone not in zone_ids:
                    raise SettingsError(f'Rule {rule.id} references unknown zone {rule.zone}')
            self._write('rules', rules)
        return [rule.model_copy(deep=True) for rule in rules]

    def seed_demo(self) -> None:
        """Write the demo configuration only for files that do not exist yet."""
        steps = [('cameras', self.save_cameras, demo_cameras),
                 ('zones', self.save_zones, demo_zones),
                 ('rules', self.save_rules, demo_rules)]
        with self._lock:
            for key, save, demo in steps:
                if self.path(key).exists():
                    continue
                try:
                    save(demo())
                except SettingsError as error:
                    log.warning('Not seeding demo %s: %s', key, error)
