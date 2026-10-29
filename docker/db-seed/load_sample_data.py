#!/usr/bin/env python3
"""Submit the sample Development Agents from openg2p-data through the intake API.

Run by the platform's db-seed entrypoint when LOAD_SAMPLE_DATA=true (the
platform owns the hook; this is the DA variant's loader). Nothing is written
to the register tables: every sample DA is entered the way a person enters one
on the web form, through the staff API, and waits for the approvers. The
loader never signs in as an approver, never approves, and uses no password
grant: it calls the staff API with a service account (client credentials).

Data (openg2p-data, the COSS fork baked into the image at a pinned commit, or
a local checkout via OPENG2P_DATA_DIR):
  packs/<PACK>/samples/development_agents.json  DA-ID, Fayda FAN, qualification,
                                                specialisation, position, posting
  packs/<PACK>/samples/individuals.json         the people: names, gender,
                                                marital status, phone
  packs/<PACK>/migration/id_map.csv             pack P-code -> the id a Master
                                                Data seeded before the pack uses

Per DA: save the identity section (creates the submission), then contact,
service and location, then finalize. The DA-ID of the fixture is not sent;
the registry mints one after approval. A DA whose Fayda ID is already held by
a registered DA or a live submission is skipped, so re-running loads nothing
twice.

The platform entrypoint seeds the approval workflow's policies after the
sample step; a submission cannot be finalized before they exist, so this
loader first applies the same idempotent AWE seed files (/seed/awe_meta_data,
upserts) when the AWE database settings are present.

Settings (env): the names the platform chart's db-seed job already sets when
dbSeed.loadSampleData is on, so a deployment needs nothing extra:
  STAFF_API_URL, STAFF_TOKEN_URL, STAFF_CLIENT_ID, STAFF_CLIENT_SECRET
      the staff API and the registry's Keycloak client (global.authClientId);
      its service-account user needs the client role Intake Officer on the
      staff portal client
  MDS_API_URL, MDS_TOKEN_URL, MDS_CLIENT_ID, MDS_CLIENT_SECRET
      Master Data API, read only (geography)
  AWE_PGHOST, AWE_PGPORT, AWE_PGDATABASE, AWE_PGUSER, AWE_PGPASSWORD
  OPENG2P_DATA_DIR (default /openg2p-data), PACK (default ETH-OAN),
  STAFF_API_WAIT_SECONDS (default 600)
"""

import csv
import glob
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone

REGISTER_ID = "6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90"
FORM_ID = "6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f91"
SECTIONS = {
    "identity": "da_identity_section_01",
    "service": "da_service_section_02",
    "location": "da_location_section_03",
    "contact": "da_contact_section_04",
}
GEO_LEVELS = ("region", "zone", "woreda", "kebele")
CSRF = uuid.uuid4().hex


def log(msg: str) -> None:
    print(f"[load-sample-data] {msg}", flush=True)


def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def read_json(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ------------------------------------------------------------------ HTTP


def http(url: str, data: bytes | None = None, headers: dict | None = None, timeout: int = 60):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


class Client:
    def __init__(self):
        self.staff = env("STAFF_API_URL").rstrip("/")
        self.master_data = env("MDS_API_URL").rstrip("/")
        self._tokens: dict[str, tuple[str, float]] = {}

    def token(self, kind: str) -> str:
        cached = self._tokens.get(kind)
        if cached and time.monotonic() < cached[1]:
            return cached[0]
        prefix = "STAFF" if kind == "staff" else "MDS"
        form = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": env(f"{prefix}_CLIENT_ID") or env("STAFF_CLIENT_ID"),
            "client_secret": env(f"{prefix}_CLIENT_SECRET") or env("STAFF_CLIENT_SECRET"),
        }).encode()
        code, body = http(env(f"{prefix}_TOKEN_URL") or env("STAFF_TOKEN_URL"), form,
                          {"Content-Type": "application/x-www-form-urlencoded"})
        if code != 200:
            raise RuntimeError(f"Keycloak refused the {kind} service token ({code}): {body[:200]}")
        data = json.loads(body)
        self._tokens[kind] = (data["access_token"], time.monotonic() + max(int(data.get("expires_in", 60)) - 30, 10))
        return data["access_token"]

    def call(self, base: str, path: str, payload: dict, pagination: dict | None = None):
        envelope = {
            "request_header": {
                "request_id": uuid.uuid4().hex, "request_timestamp": datetime.now(timezone.utc).isoformat(),
                "sender_app_mnemonic": "da-registry-sample-data", "sender_app_url": "http://da-registry",
            },
            "request_body": {"request_payload": payload, "pagination_request": pagination},
        }
        code, body = http(base + path, json.dumps(envelope).encode(), {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + self.token("staff" if base == self.staff else "mds"),
            "X-CSRF-Token": CSRF, "Cookie": f"X-CSRF-Token={CSRF}",
        })
        try:
            data = json.loads(body)
        except ValueError:
            return False, f"HTTP {code}: {body[:200]}", None
        header = data.get("response_header") or {}
        ok = code == 200 and header.get("response_status") == "SUCCESS"
        return ok, header.get("response_error_message") or (f"HTTP {code}" if not ok else ""), \
            (data.get("response_body") or {}).get("response_payload")

    def staff_ready(self, wait_seconds: int) -> bool:
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            try:
                code, _ = http(self.staff + "/docs", timeout=10)
                if code == 200:
                    return True
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(10)
        return False


# ------------------------------------------------------------- geography


def geo_index(client: Client) -> dict:
    """{level_value_id: node} from the Master Data API (one call per level)."""
    ok, err, levels = client.call(client.master_data, "/geo/get_all_geo_levels", {})
    if not ok:
        raise RuntimeError(f"Master Data geo levels: {err}")
    index = {}
    for level in levels or []:
        ok, err, rows = client.call(client.master_data, "/geo/get_geo_level_values",
                                    {"level_id": level["level_id"], "parent_level_value_id": None})
        if not ok:
            raise RuntimeError(f"Master Data geo values for {level['level_id']}: {err}")
        for row in rows or []:
            index[row["level_value_id"]] = {**row, "level_mnemonic": level.get("level_mnemonic") or ""}
    return index


def location(index: dict, id_map: dict, pcode: str):
    """The location section's geo fields for a pack P-code, or None."""
    for candidate in (pcode, id_map.get(pcode)):
        if candidate and candidate in index:
            chain, current = [], candidate
            while current in index:
                node = index[current]
                if (node["level_mnemonic"] or "").lower() in GEO_LEVELS:
                    chain.append({
                        "level": node["level_mnemonic"], "level_id": node["level_id"],
                        "level_mnemonic": node["level_mnemonic"], "level_value_id": node["level_value_id"],
                        "level_value_mnemonic": node["level_value_mnemonic"],
                    })
                current = node.get("parent_level_value_id")
            chain.reverse()
            return {"geo_lowest_level_value_id": candidate,
                    "geo_code_hierarchy_json": {"lowest_level_value_id": candidate, "hierarchy": chain}}
    return None


# ------------------------------------------------------------ AWE policies


def seed_approval_policies() -> None:
    """Apply /seed/awe_meta_data/*.sql (idempotent upserts) so a submission can
    be finalized: the entrypoint seeds them only after the sample step."""
    host, db = env("AWE_PGHOST"), env("AWE_PGDATABASE")
    if not host or not db:
        log("AWE database settings not set: assuming the approval policies exist.")
        return
    files = sorted(glob.glob("/seed/awe_meta_data/*.sql"))
    run_env = {**os.environ, "PGHOST": host, "PGPORT": env("AWE_PGPORT", "5432"), "PGDATABASE": db,
               "PGUSER": env("AWE_PGUSER"), "PGPASSWORD": env("AWE_PGPASSWORD")}
    for path in files:
        subprocess.run(["psql", "-v", "ON_ERROR_STOP=1", "-q", "-f", path], env=run_env, check=True)
    log(f"approval policies ensured ({len(files)} AWE seed files).")


# ------------------------------------------------------------------- main


def sections_for(da: dict, person: dict) -> dict:
    phone = person.get("phone") or ""
    mobile = da.get("mobile_number") or ("0" + phone[4:] if phone.startswith("+251") else phone or None)
    return {
        "identity": {
            "prefix": da.get("prefix"), "first_name": person.get("given_name") or da.get("first_name"),
            "middle_name": person.get("fathers_name") or da.get("middle_name"), "last_name": da.get("last_name"),
            "foundational_id": da["fayda_fan"], "gender": da.get("gender") or person.get("gender"),
            "marital_status": da.get("marital_status") or person.get("marital_status"),
            "birth_month_ec": da.get("birth_month_ec"), "birth_year_ec": da.get("birth_year_ec"),
        },
        "contact": {"mobile_number": mobile, "email": da.get("email"),
                    "telegram_number": da.get("telegram_number"), "alternate_number": da.get("alternate_number")},
        "service": {"education_level": da.get("education_level"), "specialisation": da.get("specialisation"),
                    "position": da.get("position"), "joined_date": da.get("joined_date")},
    }


def submit(client: Client, fields: dict, geo: dict) -> tuple[str, str]:
    """('submitted' | 'skipped' | 'failed', detail)."""
    def save(section: str, record: dict, submission_id=None, record_id=""):
        action = "ADD" if submission_id is None else "UPDATE"
        payload = {k: v for k, v in record.items() if v not in (None, "")}
        return client.call(client.staff, "/intake-form-data/save_intake_form_submission", {
            "submission_id": submission_id, "section_id": SECTIONS[section], "section_register_id": REGISTER_ID,
            "form_id": FORM_ID, "register_id": REGISTER_ID,
            "section_payload": [{"edit_action": action, "internal_record_id": record_id, "link_internal_record_id": "", **payload}],
        })

    ok, err, created = save("identity", fields["identity"])
    if not ok:
        return ("skipped" if "already" in err.lower() else "failed"), err
    submission_id = created.get("submission_id")
    records = [r for p in created.get("section_payloads") or [] for r in p.get("records") or []]
    record_id = records[0].get("internal_record_id") if records else ""
    for section, record in (("contact", fields["contact"]), ("service", fields["service"]), ("location", geo)):
        ok, err, _ = save(section, record, submission_id, record_id)
        if not ok:
            return "failed", f"{section}: {err}"
    ok, err, _ = client.call(client.staff, "/intake-form-data/finalize_intake_form_submission", {"submission_id": submission_id})
    return ("submitted", submission_id) if ok else ("failed", f"finalize: {err}")


def main() -> int:
    pack_dir = os.path.join(env("OPENG2P_DATA_DIR", "/openg2p-data"), "packs", env("PACK", "ETH-OAN"))
    fixture = os.path.join(pack_dir, "samples", "development_agents.json")
    if not os.path.exists(fixture):
        log(f"no sample DAs in this openg2p-data ({fixture}): nothing to submit.")
        return 0
    missing = [n for n in ("STAFF_API_URL", "STAFF_TOKEN_URL", "STAFF_CLIENT_ID", "MDS_API_URL") if not env(n)]
    if missing:
        log("missing settings " + ", ".join(missing) + ": sample DAs not submitted.")
        return 1
    doc = read_json(fixture)
    das = doc.get("development_agents") if isinstance(doc, dict) else doc
    people = {i["individual_id"]: i for i in read_json(os.path.join(pack_dir, "samples", "individuals.json"))}
    id_map = {}
    map_path = os.path.join(pack_dir, "migration", "id_map.csv")
    if os.path.exists(map_path):
        with open(map_path, encoding="utf-8", newline="") as fh:
            id_map = {row["pack_id"]: row["source_id"] for row in csv.DictReader(fh)}

    client = Client()
    if not client.staff_ready(int(env("STAFF_API_WAIT_SECONDS", "600"))):
        log(f"staff API not reachable at {client.staff}: sample DAs not submitted.")
        return 1
    seed_approval_policies()
    index = geo_index(client)
    tally = {"submitted": 0, "skipped": 0, "failed": 0}
    for da in das or []:
        geo = location(index, id_map, da.get("geo_pcode") or "")
        if geo is None:
            tally["failed"] += 1
            log(f"{da.get('da_id')}: kebele {da.get('geo_pcode')} not in Master Data")
            continue
        outcome, detail = submit(client, sections_for(da, people.get(da.get("individual_id")) or {}), geo)
        tally[outcome] += 1
        log(f"{da.get('da_id')}: {outcome} {detail}")
    log(f"{tally['submitted']} submitted for approval, {tally['skipped']} already present, {tally['failed']} failed "
        f"(of {len(das or [])} in pack {env('PACK', 'ETH-OAN')}).")
    return 1 if tally["failed"] and not tally["submitted"] and not tally["skipped"] else 0


if __name__ == "__main__":
    sys.exit(main())
