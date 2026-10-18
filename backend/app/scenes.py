"""Demo scenes: a JSON file with cameras, zones, rules and the policy sentence that produces them.

    python -m app.scenes ../demo/scenes/lobby.json [--data-dir data]   # then start the server
    POLICYLENS_SCENE=../demo/scenes/lobby.json uvicorn app.main:app     # or load it at startup

Loading replaces the saved cameras, zones and rules. File paths inside `clip:`, `replay:` and `loop:`
sources (both sides of `tracks@video`) are resolved relative to the scene file, so scenes work
from any directory. Scenes are data only; nothing in them is executed.
"""

import argparse
import json
from pathlib import Path

from app.models import Camera, Model, Rule, Zone
from app.settings import Settings

PATH_SOURCES = ('clip', 'replay', 'loop')


class SceneVerdicts(Model):
    """Known verifier answers for the scene's footage (see app/verdicts.py)."""
    file: str                  # relative to the scene file
    cameras: dict[str, str]    # camera id -> clip name used in the file's keys


class Scene(Model):
    name: str
    description: str = ''
    policy: str = ''
    cameras: list[Camera]
    zones: list[Zone]
    rules: list[Rule]
    needs: list[str] = []      # e.g. ["person1-vision", "gemini"]: what the scene needs to be meaningful
    credits: list[str] = []
    cached_verdicts: SceneVerdicts | None = None


def read_scene(path: Path) -> Scene:
    scene = Scene.model_validate_json(path.read_text(encoding='utf-8'))
    base = path.resolve().parent
    cameras = [camera.model_copy(update={'source': _resolve(camera.source, base)}) for camera in scene.cameras]
    update = {'cameras': cameras}
    if scene.cached_verdicts is not None:
        update['cached_verdicts'] = scene.cached_verdicts.model_copy(
            update={'file': str((base / scene.cached_verdicts.file).resolve())})
    return scene.model_copy(update=update)


def _resolve(source: str, base: Path) -> str:
    kind, sep, value = source.partition(':')
    if not sep or kind not in PATH_SOURCES:
        return source
    parts = [str((base / part).resolve()) if part and not Path(part).is_absolute() else part
             for part in value.split('@')]
    return f'{kind}:{"@".join(parts)}'


def load_scene(path: Path, settings: Settings) -> Scene:
    """Replace the saved configuration with the scene's. Validated by Settings like API edits."""
    scene = read_scene(path)
    # Clear in reference order first: rules point at zones, zones point at cameras.
    settings.save_rules([])
    settings.save_zones([])
    settings.save_cameras(scene.cameras)
    settings.save_zones(scene.zones)
    settings.save_rules(scene.rules)
    return scene


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('scene', type=Path)
    parser.add_argument('--data-dir', type=Path, default=Path(__file__).resolve().parents[1] / 'data')
    args = parser.parse_args()
    scene = load_scene(args.scene, Settings(args.data_dir / 'settings'))
    print(f'Loaded scene {scene.name!r}: {len(scene.cameras)} cameras, {len(scene.zones)} zones, '
          f'{len(scene.rules)} rules into {args.data_dir / "settings"}')
    if scene.needs:
        print(f'Needs: {", ".join(scene.needs)}')
    print(f'Policy: {scene.policy}')


if __name__ == '__main__':
    main()
