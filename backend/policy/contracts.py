"""Shared contracts, imported from backend/app/models.py (Person 4).

Until app/models.py is merged into this branch, this falls back to a TEMPORARY mirror of the
approved models on Person 4's branch (origin/person4-integration, backend/app/models.py). Every
policy/ and verify/ module imports contracts from here, so once app/models.py is present the real
models are used with no other change. Delete the mirror below after the merge.
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

    from typing import Annotated, Literal

    from pydantic import BaseModel, ConfigDict, Field, model_validator

    Coordinate = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    Point = tuple[Coordinate, Coordinate]
    ObjectName = Literal["person", "backpack", "handbag", "suitcase", "chair", "camera"]
    Severity = Literal["review", "urgent"]

    SUPPORTED_OBJECTS = ("person", "backpack", "handbag", "suitcase", "chair", "camera")
    # object -> attributes that can be checked on it
    SUPPORTED_ATTRIBUTES = {
        "backpack": ("transparent",),
        "handbag": ("transparent",),
        "suitcase": ("transparent",),
        "camera": ("professional",),
        "person": (),
        "chair": (),
    }

    class _Model(BaseModel):
        model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    class Camera(_Model):
        id: str = Field(min_length=1)
        name: str = Field(min_length=1)
        source: str = Field(min_length=1)

    class Zone(_Model):
        id: str = Field(min_length=1)
        camera_id: str = Field(min_length=1)
        name: str = Field(min_length=1)
        polygon: list[Point] = Field(min_length=3)

    class Attribute(_Model):
        name: Literal["transparent", "professional"]
        expected: bool = Field(strict=True)

    class Rule(_Model):
        id: str = Field(min_length=1)
        name: str = Field(min_length=1)
        type: Literal["persistent_object", "object_attribute"]
        objects: list[ObjectName] = Field(min_length=1)
        zone: str = Field(min_length=1)
        attribute: Attribute | None = None
        duration_seconds: float = Field(ge=0.5, le=600)
        severity: Severity
        enabled: bool = True

        @model_validator(mode="after")
        def check_rule(self):
            if len(set(self.objects)) != len(self.objects):
                raise ValueError("Rule objects must be unique")
            if self.type == "object_attribute":
                if self.attribute is None:
                    raise ValueError("Attribute rule requires an attribute")
                if any(self.attribute.name not in SUPPORTED_ATTRIBUTES[obj] for obj in self.objects):
                    raise ValueError("Attribute not supported for every rule object")
            else:
                if self.attribute is not None:
                    raise ValueError("Persistent rules do not accept attributes in the MVP")
                if any(obj not in ("backpack", "handbag", "suitcase", "chair") for obj in self.objects):
                    raise ValueError("Persistent MVP rules support bags and chairs only")
            return self

    class CompileResult(_Model):
        rules: list[Rule] = Field(default_factory=list)
        warnings: list[str] = Field(default_factory=list)
        unsupported: list[str] = Field(default_factory=list)

    class Verdict(_Model):
        answer: bool | None = Field(strict=True)
        confidence: float = Field(ge=0, le=1)
        reason: str = Field(min_length=1)
