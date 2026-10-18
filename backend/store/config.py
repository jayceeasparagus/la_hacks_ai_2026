"""Validated configuration persisted as one atomically replaced JSON document."""

import json
import os
from pathlib import Path
import tempfile
import threading

from pydantic import Field

from app.models import Camera, Model, Rule, Zone
from engine.zones import validate_polygon


class DuplicateConfiguration(ValueError):
    pass


class Configuration(Model):
    cameras: list[Camera] = Field(default_factory=list)
    zones: list[Zone] = Field(default_factory=list)
    rules: list[Rule] = Field(default_factory=list)


def validate_configuration(config: Configuration):
    if len(config.cameras) > 3:
        raise ValueError('At most three cameras are supported')
    for name in ('cameras', 'zones', 'rules'):
        ids = [item.id for item in getattr(config, name)]
        if len(set(ids)) != len(ids):
            raise DuplicateConfiguration(f'Duplicate {name} IDs')
    cameras = {camera.id for camera in config.cameras}
    zones = {zone.id for zone in config.zones}
    for zone in config.zones:
        if zone.camera_id not in cameras:
            raise ValueError(f'Zone {zone.id} references an unknown camera')
        validate_polygon(zone.polygon)
    for rule in config.rules:
        if rule.zone not in zones:
            raise ValueError(f'Rule {rule.id} references an unknown zone')


class ConfigurationStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._config = Configuration()
        if self.path.exists():
            self._config = Configuration.model_validate_json(self.path.read_text(encoding='utf-8'))
            validate_configuration(self._config)

    def snapshot(self):
        with self._lock:
            return self._config.model_copy(deep=True)

    def replace(self, **changes):
        with self._lock:
            data = self._config.model_dump()
            data.update(changes)
            proposed = Configuration.model_validate(data)
            validate_configuration(proposed)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(prefix='config-', suffix='.tmp', dir=self.path.parent)
            try:
                with os.fdopen(handle, 'w', encoding='utf-8') as stream:
                    json.dump(proposed.model_dump(mode='json'), stream, indent=2)
                    stream.write('\n')
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                Path(temporary).unlink(missing_ok=True)
            self._config = proposed
            return self.snapshot()
