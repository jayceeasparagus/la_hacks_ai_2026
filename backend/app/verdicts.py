"""Known verifier answers for demo footage: deterministic, instant and offline.

`demo/ppe_verdicts.json` holds real Gemini verdicts keyed "<clip>:<track_id>:<check>", made by
`demo/render_ppe_examples.py` with the track ids of the clip's `.tracks.jsonl`. A scene names
the file and which clip each camera plays:

    "cached_verdicts": {"file": "../ppe_verdicts.json",
                        "cameras": {"cam_site": "construction_site", "cam_warehouse": "warehouse"}}

The engine asks the cache first; tracks it doesn't know, or whose entry records an error, go to
the live verifier as usual. A cached "unclear" (answer null) is replayed as is, so the demo stays
deterministic. Answers below the verifier's confidence threshold become unclear.
Make a cache for a new clip with demo/cache_verdicts.py.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable

from app.models import Verdict
from verify.verifier import CONFIDENCE_THRESHOLD

log = logging.getLogger('policylens.verdicts')

Lookup = Callable[[int, str], Verdict | None]


class CachedVerdicts:
    def __init__(self, entries: dict[str, dict], cameras: dict[str, str]):
        self.entries = entries
        self.cameras = dict(cameras)

    @classmethod
    def load(cls, path: Path, cameras: dict[str, str]) -> 'CachedVerdicts':
        """Raises OSError or ValueError for a missing or malformed file."""
        entries = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(entries, dict):
            raise ValueError(f'{path.name} must map "<clip>:<track_id>:<check>" to verdicts')
        log.info('Loaded %d cached verdicts from %s for cameras %s', len(entries), path, ', '.join(cameras))
        return cls(entries, cameras)

    def get(self, camera_id: str, track_id: int, check: str) -> Verdict | None:
        clip = self.cameras.get(camera_id)
        entry = self.entries.get(f'{clip}:{track_id}:{check}') if clip else None
        if not isinstance(entry, dict) or entry.get('error'):
            return None  # unknown, or no real answer was recorded: let the live verifier look
        try:
            verdict = Verdict(answer=entry['answer'], confidence=entry.get('confidence', 0),
                              reason=entry.get('reason') or 'cached verdict')
        except (KeyError, ValueError):
            return None
        if verdict.confidence < CONFIDENCE_THRESHOLD:
            return verdict.model_copy(update={'answer': None})
        return verdict

    def lookup(self, camera_id: str) -> Lookup | None:
        """The engine's `verdict_lookup` for one camera, or None if the camera has no cached clip."""
        if camera_id not in self.cameras:
            return None
        return lambda track_id, check: self.get(camera_id, track_id, check)
