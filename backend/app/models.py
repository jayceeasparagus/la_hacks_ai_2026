"""Approved shared data contracts for PolicyLens (Pydantic v2)."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Coordinate = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Point = tuple[Coordinate, Coordinate]
BBox = tuple[Coordinate, Coordinate, Coordinate, Coordinate]
ObjectName = Literal['person', 'backpack', 'handbag', 'suitcase', 'chair', 'camera']
Severity = Literal['review', 'urgent']
Decision = Literal['confirmed', 'dismissed', 'unclear']

SUPPORTED_OBJECTS = ('person', 'backpack', 'handbag', 'suitcase', 'chair', 'camera')
SUPPORTED_ATTRIBUTES = {
    'backpack': ('transparent',),
    'handbag': ('transparent',),
    'suitcase': ('transparent',),
    'camera': ('professional',),
    'person': (),
    'chair': (),
}


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Camera(Model):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    source: str = Field(min_length=1)


class Zone(Model):
    id: str = Field(min_length=1)
    camera_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    polygon: list[Point] = Field(min_length=3)


class Attribute(Model):
    name: Literal['transparent', 'professional']
    expected: bool = Field(strict=True)


class Rule(Model):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    type: Literal['persistent_object', 'object_attribute']
    objects: list[ObjectName] = Field(min_length=1)
    zone: str = Field(min_length=1)
    attribute: Attribute | None = None
    duration_seconds: float = Field(ge=0.5, le=600)
    severity: Severity
    enabled: bool = True

    @model_validator(mode='after')
    def check_rule(self):
        if len(set(self.objects)) != len(self.objects):
            raise ValueError('Rule objects must be unique')
        if self.type == 'object_attribute':
            if self.attribute is None:
                raise ValueError('Attribute rule requires an attribute')
            if any(self.attribute.name not in SUPPORTED_ATTRIBUTES[obj] for obj in self.objects):
                raise ValueError('Attribute not supported for every rule object')
        else:
            if self.attribute is not None:
                raise ValueError('Persistent rules do not accept attributes in the MVP')
            if any(obj not in ('backpack', 'handbag', 'suitcase', 'chair') for obj in self.objects):
                raise ValueError('Persistent MVP rules support bags and chairs only')
        return self


class CompileResult(Model):
    rules: list[Rule] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    unsupported: list[str] = Field(default_factory=list)


class Track(Model):
    track_id: int = Field(ge=0, strict=True)
    object_class: ObjectName
    bbox: BBox
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode='after')
    def check_bbox(self):
        x1, y1, x2, y2 = self.bbox
        if x1 >= x2 or y1 >= y2:
            raise ValueError('Bounding box must have positive width and height')
        return self


class TrackFrame(Model):
    camera_id: str = Field(min_length=1)
    ts: float = Field(ge=0)
    tracks: list[Track] = Field(default_factory=list)

    @model_validator(mode='after')
    def unique_tracks(self):
        ids = [track.track_id for track in self.tracks]
        if len(set(ids)) != len(ids):
            raise ValueError('Duplicate track_id in the same frame')
        return self


class Verdict(Model):
    answer: bool | None = Field(strict=True)
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1)


class RuleState(Model):
    camera_id: str
    rule_id: str
    track_id: int
    incident_id: str
    ts: float = Field(ge=0)
    elapsed_seconds: float = Field(ge=0)
    duration_seconds: float = Field(ge=0.5, le=600)
    phase: Literal['timing', 'verifying', 'alerted', 'compliant', 'cleared']


class Alert(Model):
    id: str
    incident_id: str
    camera_id: str
    rule_id: str
    rule_name: str
    zone_id: str
    track_id: int
    object_class: ObjectName
    bbox: BBox
    ts: float = Field(ge=0)
    created_at: str  # UTC RFC3339; distinct from source-relative ts
    elapsed_seconds: float = Field(ge=0)
    severity: Severity
    title: str
    observation: str
    confidence: float = Field(ge=0, le=1)
    rule_snapshot: Rule
    evidence_status: Literal['pending', 'ready', 'unavailable'] = 'pending'
    evidence_image_url: str | None = None
    evidence_clip_url: str | None = None
    status: Literal['open', 'reviewed'] = 'open'
    decision: Decision | None = None
    decided_at: str | None = None
