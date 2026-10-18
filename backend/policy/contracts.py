"""Shared contracts, imported from backend/app/models.py (Person 4).

Until app/models.py exists, this falls back to a TEMPORARY copy of the models from the
Person 2 briefing. Every policy/ and verify/ module imports contracts from here, so once
Person 4 lands app/models.py the real models are used with no other change.
Delete the fallback copy below once app/models.py is on main.
"""

try:
    from app.models import (  # noqa: F401
        SUPPORTED_ATTRIBUTES,
        SUPPORTED_OBJECTS,
        Attribute,
        Camera,
        CompileResult,
        Rule,
        Verdict,
        Zone,
    )
except ModuleNotFoundError as exc:
    if exc.name not in ("app", "app.models"):
        raise

    from typing import Literal

    from pydantic import BaseModel

    SUPPORTED_OBJECTS = ["person", "backpack", "handbag", "suitcase", "chair", "camera"]
    SUPPORTED_ATTRIBUTES = {"transparent": ["backpack", "handbag", "suitcase"], "professional": ["camera"]}

    class Camera(BaseModel):
        id: str
        name: str
        source: str

    class Zone(BaseModel):
        id: str
        name: str
        camera_id: str
        polygon: list[list[float]]

    class Attribute(BaseModel):
        name: Literal["transparent", "professional"]
        expected: bool

    class Rule(BaseModel):
        id: str
        name: str
        type: Literal["object_attribute", "persistent_object"]
        objects: list[str]
        zone: str
        attribute: Attribute | None = None
        duration_seconds: float = 1.0
        severity: Literal["info", "review", "urgent"]
        enabled: bool = True

    class CompileResult(BaseModel):
        rules: list[Rule]
        warnings: list[str]
        unsupported: list[str]

    class Verdict(BaseModel):
        answer: bool | None
        confidence: float
        reason: str
