"""Turn one row of a DA import file (CSV / XLSX) into DA register fields.

The platform's import worker hands every row over as {header: string}. This
enricher, named in incoming_model_semantic_patterns.raw_payload_enricher_class,
runs before the Jinja template (import_file_to_openg2p_da.json.j2) and:

- maps the file's column headers to DA field names, tolerating case, extra
  spaces, a trailing "*" and a few common spellings;
- turns labels into Master Data codes ("Diploma" -> DIPLOMA), reading the lists the
  form's dropdowns use (code_lists.py), so a value added in openg2p-data is accepted;
- cleans what spreadsheets do to numbers (a lost leading 0 on a phone number,
  "4.0" for a month, "2024-01-05 00:00:00" for a date);
- resolves Region / Zone / Woreda / Kebele names to the Master Data kebele (through
  the Master Data API) and builds the same geo hierarchy the intake form's geo
  widget saves.

A row that cannot be used raises ValueError with a readable message; the
platform records it against that row and carries on with the rest of the file.
Format rules (Fayda ID, phone, email, age) are checked afterwards by the DA
domain service, the same as for the web intake form.

The platform calls enrich() synchronously from the transformation worker, so it
must stay a plain def.
"""

import logging
import re
from datetime import datetime
from typing import Dict

from openg2p_registry_core.interfaces import G2PPayloadEnricherInterface
from sqlalchemy.orm import Session

from ...geo_codes import geo_codes
from ...register_domain.services.required_fields import incomplete_reason, load_sections_sync
from . import code_lists, master_data_api

_logger = logging.getLogger("g2p-payload-enricher-service")

SOURCE_CSV_IMPORT = "CSV_IMPORT"

# Accepted header spellings, after normalising (lower case, single spaces, no "*").
COLUMN_ALIASES = {
    "prefix": ("salutation", "title"),
    "first_name": ("name", "first name", "given name"),
    "middle_name": ("father name", "father's name", "fathers name"),
    "last_name": ("grandfather name", "grandfather's name", "grandfathers name", "grand father name"),
    "foundational_id": ("fayda id", "fayda id (fan)", "fayda fan", "fan", "fayda id (fin)", "fayda fin", "fin", "fayda"),
    "gender": ("gender", "sex"),
    "marital_status": ("marital status",),
    "birth_month_ec": ("month of birth (ec)", "birth month (ec)", "month of birth", "birth month"),
    "birth_year_ec": ("year of birth (ec)", "birth year (ec)", "year of birth", "birth year"),
    "mobile_number": ("phone number", "phone", "mobile number", "mobile"),
    "telegram_number": ("telegram number", "telegram"),
    "alternate_number": ("alternate number", "alternate phone", "alternative number"),
    "email": ("email", "email address", "e-mail"),
    "education_level": ("education level", "education"),
    "specialisation": ("specialisation", "specialization"),
    "position": ("position", "designation"),
    "joined_date": ("joining date", "joined date", "date of joining"),
    "region": ("region",),
    "zone": ("zone",),
    "woreda": ("woreda",),
    "kebele": ("kebele",),
}
_HEADER_TO_FIELD = {alias: field for field, aliases in COLUMN_ALIASES.items() for alias in aliases}

# Coded fields (salutation, gender, marital status, qualification, specialisation,
# position) are resolved against Master Data; see code_lists.py.
# Needed to place and identify a DA at all. Other blanks are left to the
# approver; format checks still apply to whatever is filled in.
IMPORT_REQUIRED = {
    "first_name": "Name", "middle_name": "Father Name", "foundational_id": "Fayda ID",
    "region": "Region", "zone": "Zone", "woreda": "Woreda", "kebele": "Kebele",
}

GEO_LEVELS = ("region", "zone", "woreda", "kebele")


def _normalise_header(header) -> str:
    text = str(header or "").replace("*", " ").strip().lower()
    return re.sub(r"\s+", " ", text)


def _clean(value) -> str:
    return re.sub(r"\s+", " ", str(value if value is not None else "")).strip()


def _integer(value: str, label: str) -> int | None:
    if not value:
        return None
    text = value[:-2] if value.endswith(".0") else value
    if not text.isdigit():
        raise ValueError(f"{label} '{value}' must be a whole number")
    return int(text)


def _digits(value: str) -> str | None:
    """Fayda ID: digits only. A spreadsheet number may come back as "1234.0"."""
    if not value:
        return None
    text = value[:-2] if value.endswith(".0") else value
    return re.sub(r"[\s-]", "", text)


def _phone(value: str) -> str | None:
    if not value:
        return None
    text = re.sub(r"[\s()-]", "", value)
    if text.endswith(".0"):
        text = text[:-2]
    # A phone typed into a numeric spreadsheet cell loses its leading 0.
    if re.fullmatch(r"[1-9][0-9]{8}", text):
        text = "0" + text
    return text


def _date(value: str, label: str) -> str | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"{label} '{value}' must be a date like 2024-01-05 or 05/01/2024")


class _MasterDataGeo:
    """Resolves a file's or message's location against Master Data, through its
    API (master_data_api.geo_index: every unit of every level, cached): the
    platform's geo service looks units up by id, and a file names them."""

    @staticmethod
    def _entry(node: dict) -> dict:
        level = node["level_mnemonic"]
        return {
            "level": level, "level_id": node["level_id"], "level_mnemonic": level,
            "level_value_id": node["level_value_id"], "level_value_mnemonic": node["level_value_mnemonic"],
        }

    _name_index: tuple[int, dict] | None = None

    @classmethod
    def _by_name(cls, index: dict) -> dict:
        """{(level, lower-case name): [nodes]}, rebuilt when the geo index is."""
        if cls._name_index is None or cls._name_index[0] != id(index):
            by_name: dict = {}
            for node in index.values():
                key = ((node["level_mnemonic"] or "").lower(), node["level_value_mnemonic"].strip().lower())
                by_name.setdefault(key, []).append(node)
            cls._name_index = (id(index), by_name)
        return cls._name_index[1]

    @classmethod
    def resolve(cls, names: Dict[str, str]) -> dict:
        """names: {"region": .., "zone": .., "woreda": .., "kebele": ..}.
        Walks the chain so a kebele name repeated in another woreda never
        matches the wrong one."""
        by_name = cls._by_name(master_data_api.geo_index())
        hierarchy, parent_id, trail = [], None, []
        for level in GEO_LEVELS:
            name = str(names[level] or "").strip().lower()
            rows = [n for n in by_name.get((level, name), []) if parent_id is None or n["parent_level_value_id"] == parent_id]
            where = f" in {' / '.join(trail)}" if trail else ""
            if not rows:
                raise ValueError(f"{level.title()} '{names[level]}' not found{where}")
            if len(rows) > 1:
                raise ValueError(f"{level.title()} '{names[level]}' matches more than one place{where}")
            hierarchy.append(cls._entry(rows[0]))
            trail.append(rows[0]["level_value_mnemonic"])
            parent_id = rows[0]["level_value_id"]
        return {"hierarchy": hierarchy, "lowest_level_value_id": parent_id}

    @classmethod
    def resolve_by_id(cls, kebele_id: str) -> dict:
        """Hierarchy for a Master Data kebele id (e.g. kebele-ET010101101001),
        walking up its parents to the region."""
        index = master_data_api.geo_index()
        chain, current, seen = [], kebele_id, set()
        while current and current not in seen:
            seen.add(current)
            node = index.get(current)
            if node is None:
                if not chain:
                    raise ValueError(f"Location '{kebele_id}' not found in Master Data")
                break
            chain.append(cls._entry(node))
            current = node["parent_level_value_id"]
        if (chain[0]["level_mnemonic"] or "").lower() != "kebele":
            raise ValueError(f"Location '{kebele_id}' is a {chain[0]['level_mnemonic']}, not a kebele")
        chain = [c for c in chain if (c["level_mnemonic"] or "").lower() in GEO_LEVELS]
        chain.reverse()
        return {"hierarchy": chain, "lowest_level_value_id": kebele_id}


def _build_da_record(row: Dict, source: str, geo: dict, session: Session) -> Dict:
    """Canonical DA fields (row keys are DA field names, values strings) ->
    the record the intake template expects. Shared by every ingestion path."""
    out = {
        "prefix": code_lists.resolve_code("prefix", row.get("prefix"), session),
        "first_name": row.get("first_name"),
        "middle_name": row.get("middle_name"),
        "last_name": row.get("last_name") or None,
        "foundational_id": _digits(row.get("foundational_id")),
        "gender": code_lists.resolve_code("gender", row.get("gender"), session),
        "marital_status": code_lists.resolve_code("marital_status", row.get("marital_status"), session),
        "birth_month_ec": _integer(row.get("birth_month_ec"), "Month of Birth (EC)"),
        "birth_year_ec": _integer(row.get("birth_year_ec"), "Year of Birth (EC)"),
        "mobile_number": _phone(row.get("mobile_number")),
        "telegram_number": _phone(row.get("telegram_number")),
        "alternate_number": _phone(row.get("alternate_number")),
        "email": (row.get("email") or "").lower() or None,
        "education_level": code_lists.resolve_code("education_level", row.get("education_level"), session),
        "specialisation": code_lists.resolve_code("specialisation", row.get("specialisation"), session),
        "position": code_lists.resolve_code("position", row.get("position"), session),
        "joined_date": _date(row.get("joined_date"), "Joining Date"),
        "source": source,
        "upstream_reference": row.get("upstream_reference") or None,
        "upstream_approved_by": row.get("upstream_approved_by") or None,
    }
    names = {entry["level_mnemonic"]: entry["level_value_mnemonic"] for entry in geo["hierarchy"]}
    out.update({
        "geo_lowest_level_value_id": geo["lowest_level_value_id"],
        "geo_code_hierarchy_json": geo,
        "region_name": names.get("region"),
        "zone_name": names.get("zone"),
        "woreda_name": names.get("woreda"),
        "kebele_name": names.get("kebele"),
        **geo_codes(geo),
    })
    return out


def _require_complete(record: Dict, session: Session) -> None:
    """Refuse a record that leaves a required, visible field of the register
    metadata empty (widget-required, the same rule the web form submits under).
    The ValueError carries the readable reason; the platform records it against
    the row, and the DA Services exceptions list shows it as a missing mandatory
    field."""
    reason = incomplete_reason(record, load_sections_sync(session))
    if reason:
        raise ValueError(reason)


class DAImportFileEnricherService(G2PPayloadEnricherInterface):
    def enrich(self, data: Dict, session: Session) -> Dict:
        row = {}
        for header, value in (data or {}).items():
            field = _HEADER_TO_FIELD.get(_normalise_header(header))
            if field:
                row[field] = _clean(value)

        missing = [label for field, label in IMPORT_REQUIRED.items() if not row.get(field)]
        if missing:
            raise ValueError("Missing: " + ", ".join(missing))

        geo = _MasterDataGeo.resolve({level: row[level] for level in GEO_LEVELS})
        out = _build_da_record(row, SOURCE_CSV_IMPORT, geo, session)
        _require_complete(out, session)
        _logger.info("DA import row enriched: Fayda ID %s, kebele %s", out["foundational_id"], out["kebele_name"])
        return out


# DA Services (Frappe) -> registry. Field names of `message.da` in the partner
# ingestion request; docs/da-services-api-contract.md is the reference for
# DA Services.
DA_SERVICES_FIELDS = {
    "salutation": "prefix", "first_name": "first_name", "father_name": "middle_name",
    "grandfather_name": "last_name", "fayda_id": "foundational_id", "gender": "gender",
    "marital_status": "marital_status", "birth_month_ec": "birth_month_ec",
    "birth_year_ec": "birth_year_ec", "phone_number": "mobile_number",
    "telegram_number": "telegram_number", "alternate_number": "alternate_number", "email": "email",
    "education_level": "education_level", "specialisation": "specialisation", "position": "position",
    "joining_date": "joined_date", "region": "region", "zone": "zone", "woreda": "woreda", "kebele": "kebele",
}
DA_SERVICES_SOURCES = {"WEB_INTAKE", "CSV_IMPORT"}
DA_SERVICES_REQUIRED = {"first_name": "first_name", "middle_name": "father_name", "foundational_id": "fayda_id"}


class DAServicesEnricherService(G2PPayloadEnricherInterface):
    """A DA approved in DA Services (Frappe), sent through the partner API.

    `data` is the request's `message`: {"reference_id", "source", "approved_by",
    "da": {...}}. The location is `da.kebele_id` (Master Data id, preferred) or
    `da.region/zone/woreda/kebele` names. The record then goes through the same
    template, validation, duplicate guard and auto-approve as a file import.
    """

    def enrich(self, data: Dict, session: Session) -> Dict:
        message = data or {}
        da = message.get("da") or {}
        if not isinstance(da, dict):
            raise ValueError("message.da must be an object")
        reference = _clean(message.get("reference_id"))
        if not reference:
            raise ValueError("Missing: reference_id")
        source = _clean(message.get("source") or "WEB_INTAKE").upper()
        if source not in DA_SERVICES_SOURCES:
            raise ValueError(f"source '{source}' is not one of: {', '.join(sorted(DA_SERVICES_SOURCES))}")

        row = {DA_SERVICES_FIELDS[k]: _clean(v) for k, v in da.items() if k in DA_SERVICES_FIELDS}
        missing = [name for field, name in DA_SERVICES_REQUIRED.items() if not row.get(field)]
        kebele_id = _clean(da.get("kebele_id"))
        if not kebele_id and not all(row.get(level) for level in GEO_LEVELS):
            missing.append("kebele_id (or region, zone, woreda, kebele)")
        if missing:
            raise ValueError("Missing: " + ", ".join(missing))

        row["upstream_reference"] = reference
        row["upstream_approved_by"] = _clean(message.get("approved_by"))
        geo = (_MasterDataGeo.resolve_by_id(kebele_id) if kebele_id
               else _MasterDataGeo.resolve({level: row[level] for level in GEO_LEVELS}))
        out = _build_da_record(row, source, geo, session)
        _require_complete(out, session)
        _logger.info("DA Services record %s enriched: Fayda ID %s, kebele %s",
                     reference, out["foundational_id"], out["kebele_name"])
        return out
