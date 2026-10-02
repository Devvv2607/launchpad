"""JSON-schema helpers shared by adapters and the structured-output policy."""

from __future__ import annotations

import copy
import json
import re
from typing import Any

from pydantic import BaseModel

_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S)


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve local `$ref`s into `$defs` (several providers reject `$ref`)."""
    schema = copy.deepcopy(schema)
    defs = schema.pop("$defs", {})

    def walk(node: Any, seen: frozenset[str]) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                name = ref.split("/")[-1]
                if name in seen:
                    raise ValueError(f"Recursive schema '{name}' cannot be inlined")
                merged = {**defs[name], **{k: v for k, v in node.items() if k != "$ref"}}
                return walk(merged, seen | {name})
            return {k: walk(v, seen) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v, seen) for v in node]
        return node

    result: dict[str, Any] = walk(schema, frozenset())
    return result


def strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Shape a schema for strict/constrained decoding (OpenAI, Groq strict, Anthropic):
    every object lists all properties as required and forbids extra keys. Pydantic still
    validates the result, so optional fields simply come back as null/defaults."""
    schema = inline_refs(schema)

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            node = {k: walk(v) for k, v in node.items() if k not in {"default", "title"}}
            if node.get("type") == "object" and "properties" in node:
                node["required"] = list(node["properties"].keys())
                node["additionalProperties"] = False
            return node
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    result: dict[str, Any] = walk(schema)
    return result


def json_schema_for(model: type[BaseModel]) -> dict[str, Any]:
    return model.model_json_schema()


def extract_json(text: str) -> Any:
    """Parse model output as JSON, tolerating a ```json fence. Raises ValueError."""
    candidate = text.strip()
    fenced = _FENCE.match(candidate)
    if fenced:
        candidate = fenced.group(1)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Output is not valid JSON: {exc.msg} at char {exc.pos}") from exc
