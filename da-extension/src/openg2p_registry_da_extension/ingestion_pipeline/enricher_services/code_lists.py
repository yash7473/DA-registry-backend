"""Code lists for the DA import enrichers, read from Master Data.

Which list a field uses comes from the register metadata: each dropdown widget
names its Master Data attribute (widget-data-source.params.attribute_id), the
same declaration the form reads its values from. The values come from the
Master Data API (`/attributes/get_attribute_values`) with the worker's client
credentials (master_data_api.py), never from its database. Nothing
is listed here; a value added to the openg2p-data pack is accepted on the next
import without a code change.

A file or a DA Services message may carry the code (DIPLOMA), the display
("Diploma") or a translated display; matching is case-insensitive. Anything
else is rejected with the list's display values, so the person fixing the row
sees what is allowed.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Any

from openg2p_registry_core.services.g2p_attribute_value_validator import G2PAttributeValueValidator

from . import master_data_api

_logger = logging.getLogger("da-code-lists")

DA_REGISTER_ID = "6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90"
CACHE_SECONDS = 300

_lock = threading.Lock()
_field_cache: tuple[float, dict[str, str], dict[str, str]] | None = None   # (expires, field->attribute, field->label)
_value_cache: dict[str, tuple[float, dict[str, str]]] = {}                 # attribute -> (expires, code->display)


def _label_map(schema: Any) -> dict[str, str]:
    """{field: widget label} from a section schema, for error messages."""
    out: dict[str, str] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            path = node.get("widget-data-path")
            if isinstance(path, str) and "." in path:
                out.setdefault(path.rsplit(".", 1)[-1], str(node.get("widget-label") or ""))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(schema)
    return out


def field_attributes(session) -> tuple[dict[str, str], dict[str, str]]:
    """({field: attribute_id}, {field: label}) for the DA register, cached."""
    global _field_cache
    with _lock:
        if _field_cache and _field_cache[0] > time.monotonic():
            return _field_cache[1], _field_cache[2]
    from openg2p_registry_core.models import G2PRegisterSection
    from sqlalchemy import select

    attributes: dict[str, str] = {}
    labels: dict[str, str] = {}
    for schema in session.execute(
        select(G2PRegisterSection.section_ui_schema).where(G2PRegisterSection.register_id == DA_REGISTER_ID)
    ).scalars().all():
        if isinstance(schema, str):
            schema = json.loads(schema)
        for field, attribute_id in G2PAttributeValueValidator.field_map_from_ui_schema(schema).items():
            attributes.setdefault(field, attribute_id)
        for field, label in _label_map(schema).items():
            labels.setdefault(field, label)
    with _lock:
        _field_cache = (time.monotonic() + CACHE_SECONDS, attributes, labels)
    return attributes, labels


def _values_from_api(attribute_id: str) -> dict[str, str]:
    payload = master_data_api.post(
        "/attributes/get_attribute_values", {"attribute_id": attribute_id},
        {"current_page": 1, "page_size": 1000},
    ) or {}
    rows = payload.get("attribute_values") if isinstance(payload, dict) else payload
    out: dict[str, str] = {}
    for row in rows or []:
        value_id = row.get("value_id")
        if not value_id:
            continue
        out[value_id] = row.get("value_display") or row.get("value_code") or value_id
        out.setdefault("__i18n__" + value_id, json.dumps(row.get("display_name_i18n") or row.get("display_i18n") or {}))
        if row.get("value_code") and row["value_code"] != value_id:
            out.setdefault("__code__" + row["value_code"], value_id)
    return out


def attribute_values(attribute_id: str) -> dict[str, str]:
    """{value_id: display} for a Master Data list, cached. Entries prefixed
    __code__ and __i18n__ carry alternate codes and translated displays."""
    with _lock:
        hit = _value_cache.get(attribute_id)
        if hit and hit[0] > time.monotonic():
            return hit[1]
    values = _values_from_api(attribute_id)
    with _lock:
        _value_cache[attribute_id] = (time.monotonic() + CACHE_SECONDS, values)
    return values


def invalidate() -> None:
    global _field_cache
    with _lock:
        _field_cache = None
        _value_cache.clear()


def _norm(text: Any) -> str:
    return re.sub(r"[\s_\-\.]+", " ", str(text or "")).strip().lower()


def resolve_code(field: str, value: str | None, session) -> str | None:
    """The Master Data code for what a file or message says in `field`."""
    if value is None or str(value).strip() == "":
        return None
    attributes, labels = field_attributes(session)
    attribute_id = attributes.get(field)
    if not attribute_id:
        return str(value).strip()  # not a coded field in the form metadata
    values = attribute_values(attribute_id)
    wanted = _norm(value)
    ids = [k for k in values if not k.startswith("__")]
    for value_id in ids:
        if _norm(value_id) == wanted or _norm(values[value_id]) == wanted:
            return value_id
        for translated in json.loads(values.get("__i18n__" + value_id) or "{}").values():
            if _norm(translated) == wanted:
                return value_id
    for key, value_id in values.items():
        if key.startswith("__code__") and _norm(key[len("__code__"):]) == wanted:
            return value_id
    label = labels.get(field) or field.replace("_", " ").title()
    allowed = ", ".join(values[v] for v in ids)
    raise ValueError(f"{label} '{value}' is not one of: {allowed}")
