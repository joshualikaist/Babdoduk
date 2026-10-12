# -*- coding: utf-8 -*-
"""The data contracts in schemas/: load a schema and check a value against it.

The schemas are standard JSON Schema (draft 2020-12). The site has no build step and the
content bots install nothing, so the check that runs everywhere is this small subset of the
standard; tests/test_schemas.py checks the same files with the reference implementation
(jsonschema) where it is installed, as in CI, so the two cannot drift. A schema that uses a
keyword outside the subset is refused when it is loaded, never silently half-checked.

    from schema_check import schema_errors
    schema_errors(value, "kaist-menu-day")   # [] or ["$.restaurants[0].id: required"]
"""
from __future__ import annotations

import fnmatch
import json
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"
# Which files each schema governs: (path pattern, schema, family, one value per line?).
# docs/DATA.md is the readable form of this table.
CONTRACTS = (
    ("data/ggongbab/latest.json", "ggongbab-feed", "ggongbab", False),
    ("data/ggongbab/archive/index.json", "ggongbab-archive", "ggongbab", False),
    ("data/ggongbab/news.json", "ggongbab-news", "ggongbab", False),
    ("data/kaist-menu/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].json", "kaist-menu-day", "kaist-menu", False),
    ("data/kaist-menu/latest.json", "kaist-menu-day", "kaist-menu", False),
    ("data/kaist-menu/week.json", "kaist-menu-week", "kaist-menu", False),
    ("data/magazine/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].json", "magazine-edition", "magazine", False),
    ("data/magazine/index.json", "magazine-index", "magazine", False),
    ("research/magazine/candidates.jsonl", "magazine-candidate", "magazine", True),
    ("research/magazine/runs.jsonl", "magazine-run", "magazine", True),
    ("research/magazine/health.json", "magazine-health", "magazine", False),
    ("research/magazine/source-health.json", "magazine-source-health", "magazine", False),
    ("data/foods/catalog.json", "foods-catalog", "authored", False),
    ("data/foods/packs/*.json", "foods-pack", "authored", False),
    ("data/food-log.json", "food-log", "authored", False),
    ("inputs/ggongbab/manual.json", "ggongbab-manual", "authored", False),
    ("inputs/ggongbab/food-news.json", "ggongbab-news-input", "authored", False),
    ("data/content/labels.json", "content-labels", "authored", False),
)
ANNOTATIONS = {"$schema", "$id", "$comment", "title", "description", "examples"}
KEYWORDS = ANNOTATIONS | {"$defs", "$ref", "type", "enum", "const", "properties", "required",
                          "additionalProperties", "patternProperties", "items", "minItems", "maxItems",
                          "uniqueItems", "minimum", "maximum", "minLength", "maxLength", "pattern", "anyOf"}
TYPES = {"object": dict, "array": list, "string": str, "null": type(None)}
MAX_ERRORS = 20


def _audit(schema, where: str) -> None:
    if isinstance(schema, bool):
        return
    if not isinstance(schema, dict):
        raise ValueError(f"{where}: a schema must be an object or a boolean")
    unknown = set(schema) - KEYWORDS
    if unknown:
        raise ValueError(f"{where}: keyword(s) outside the supported subset: {sorted(unknown)}")
    for key in ("properties", "patternProperties", "$defs"):
        for name, sub in (schema.get(key) or {}).items():
            _audit(sub, f"{where}/{key}/{name}")
    for key in ("items", "additionalProperties"):
        if key in schema:
            _audit(schema[key], f"{where}/{key}")
    for index, sub in enumerate(schema.get("anyOf") or []):
        _audit(sub, f"{where}/anyOf/{index}")


@lru_cache(maxsize=None)
def load_schema(name: str) -> dict:
    schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))
    _audit(schema, name)
    return schema


def _is(value, kind: str) -> bool:
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "boolean":
        return isinstance(value, bool)
    return isinstance(value, TYPES[kind])


def _same(a, b) -> bool:
    """JSON equality: true is not 1."""
    return type(a) is type(b) and a == b if isinstance(a, bool) or isinstance(b, bool) else a == b


def check(value, schema, root: dict, path: str = "$") -> list[str]:
    if schema is True:
        return []
    if schema is False:
        return [f"{path}: not allowed"]
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/$defs/"):
            raise ValueError(f"only local $defs references are supported: {ref}")
        return check(value, root["$defs"][ref[len("#/$defs/"):]], root, path)
    kinds = schema.get("type")
    if kinds is not None:
        kinds = kinds if isinstance(kinds, list) else [kinds]
        if not any(_is(value, kind) for kind in kinds):
            return [f"{path}: expected {' or '.join(kinds)}"]
    errors: list[str] = []
    if "const" in schema and not _same(value, schema["const"]):
        errors.append(f"{path}: must be {schema['const']!r}")
    if "enum" in schema and not any(_same(value, option) for option in schema["enum"]):
        errors.append(f"{path}: not one of the allowed values")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: longer than {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: does not match its pattern")
    if _is(value, "number"):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: below {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: above {schema['maximum']}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: more than {schema['maxItems']} items")
        if schema.get("uniqueItems"):
            seen = [json.dumps(item, sort_keys=True) for item in value]
            if len(set(seen)) != len(seen):
                errors.append(f"{path}: items are not unique")
        if "items" in schema:
            for index, item in enumerate(value):
                errors += check(item, schema["items"], root, f"{path}[{index}]")
    if isinstance(value, dict):
        for key in schema.get("required") or []:
            if key not in value:
                errors.append(f"{path}.{key}: required")
        properties = schema.get("properties") or {}
        patterns = schema.get("patternProperties") or {}
        for key, item in value.items():
            matched = False
            if key in properties:
                matched = True
                errors += check(item, properties[key], root, f"{path}.{key}")
            for pattern, sub in patterns.items():
                if re.search(pattern, key):
                    matched = True
                    errors += check(item, sub, root, f"{path}.{key}")
            if not matched and "additionalProperties" in schema:
                errors += check(item, schema["additionalProperties"], root, f"{path}.{key}")
    if "anyOf" in schema and not any(not check(value, sub, root, path) for sub in schema["anyOf"]):
        errors.append(f"{path}: matches none of the allowed forms")
    return errors


def contract_files(families=None, root: Path = ROOT) -> list[tuple[Path, str, bool]]:
    """(file, schema, per line?) for every existing file a contract governs, in `families`."""
    found = []
    for pattern, name, family, lines in CONTRACTS:
        if families is not None and family not in families:
            continue
        folder = root / Path(pattern).parent
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if path.is_file() and fnmatch.fnmatchcase(path.relative_to(root).as_posix(), pattern):
                found.append((path, name, lines))
    return found


def contract_errors(families=None, root: Path = ROOT) -> list[str]:
    """Every governed file checked against its schema; a JSON Lines file line by line."""
    errors: list[str] = []
    for path, name, lines in contract_files(families, root):
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        values = [(f"{rel}:{n}", line) for n, line in enumerate(text.splitlines(), 1) if line.strip()] if lines \
            else [(rel, text)]
        bad = 0
        for label, raw in values:
            try:
                value = json.loads(raw)
            except ValueError:
                errors.append(f"{label}: not JSON")
                continue
            found = schema_errors(value, name, label)
            if found and lines:
                bad += 1
                if bad > 3:
                    continue           # a store of thousands of lines: the first few say enough
            errors += found
        if bad > 3:
            errors.append(f"{rel}: {bad} lines break schemas/{name}.schema.json in all")
    return errors


def schema_errors(value, name: str, label: str = "") -> list[str]:
    """Contract errors of `value` against schemas/<name>.schema.json, at most MAX_ERRORS of them,
    each prefixed with `label`."""
    schema = load_schema(name)
    errors = check(value, schema, schema)
    prefix = f"{label}: " if label else ""
    shown = [prefix + error for error in errors[:MAX_ERRORS]]
    if len(errors) > MAX_ERRORS:
        shown.append(f"{prefix}... and {len(errors) - MAX_ERRORS} more contract errors")
    return shown
