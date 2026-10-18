"""The LLM-facing schema. Simpler than Rule: capability.py fills ids, names and defaults."""

import copy
from typing import Literal

from pydantic import BaseModel, Field

from policy.contracts import Zone
from policy.synonyms import attribute_names

UNKNOWN_ZONE = "UNKNOWN"


class DraftRule(BaseModel):
    source_text: str = Field(description="The exact phrase in the policy this rule came from")
    type: Literal["object_attribute", "persistent_object"] = Field(
        description="object_attribute: check an attribute of an object in a zone. "
        "persistent_object: alert when an object stays in a zone too long."
    )
    objects: list[Literal["backpack", "handbag", "suitcase", "chair", "camera", "person"]] = Field(
        description="Detectable objects this rule applies to"
    )
    zone_id: str = Field(description="Id of the zone this rule applies to, or UNKNOWN if unclear")
    attribute_name: Literal["transparent", "professional", "lying_down"] | None = Field(
        description="Attribute to check for object_attribute rules, otherwise null"
    )
    attribute_expected: bool | None = Field(
        description="The compliant value of the attribute; a violation is when the observed value differs"
    )
    duration_seconds: float | None = Field(description="Time in seconds, or null if the policy gives none")
    severity: Literal["review", "urgent"] | None = Field(
        description="urgent for safety, review for approvals, checks and anything else; null if unclear"
    )


class DraftPolicy(BaseModel):
    rules: list[DraftRule] = Field(description="One rule per distinct, observable requirement")
    unsupported: list[str] = Field(
        description="One short honest sentence per request the cameras cannot observe, starting with \"I can't\""
    )
    ambiguities: list[str] = Field(description="Short notes about anything you had to guess")


def build_draft_schema(zones: list[Zone]) -> dict:
    """JSON schema for DraftPolicy with zone_id restricted to the real zone ids plus UNKNOWN."""
    schema = structured_output_schema(DraftPolicy)
    properties = schema["properties"]["rules"]["items"]["properties"]
    properties["zone_id"]["enum"] = [z.id for z in zones] + [UNKNOWN_ZONE]
    # Offer only the attributes the shared contracts support (lying_down is a stretch goal).
    supported = attribute_names()
    for option in properties["attribute_name"]["anyOf"]:
        if "enum" in option:
            option["enum"] = [name for name in option["enum"] if name in supported]
    return schema


def structured_output_schema(model: type[BaseModel]) -> dict:
    """A Pydantic model's JSON schema in the subset Gemini accepts: $refs inlined, no titles/defaults."""
    return _strip_keys(_inline_refs(model.model_json_schema()), {"title", "default"})


def _inline_refs(schema: dict) -> dict:
    defs = schema.get("$defs", {})

    def resolve(node):
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].split("/")[-1]
                return resolve(copy.deepcopy(defs[name]))
            return {k: resolve(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)


def _strip_keys(node, keys: set[str]):
    if isinstance(node, dict):
        # Keep a property literally named "title"/"default"; only drop schema keywords.
        return {
            k: (_strip_keys(v, keys) if k != "properties" else {pk: _strip_keys(pv, keys) for pk, pv in v.items()})
            for k, v in node.items()
            if k not in keys
        }
    if isinstance(node, list):
        return [_strip_keys(v, keys) for v in node]
    return node
