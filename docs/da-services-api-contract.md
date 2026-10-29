# DA Services ↔ DA Registry: API contract

For the DA Services (Frappe) team. How DA Services sends a Development Agent to
the DA Registry (OpenG2P) and reads it back.

DA Services talks to the registry in two ways:

- **Partner API** (this document), server to server, signed by DA Services:
  - **Bulk import:** push each DA from the Admin's Excel file. The registry
    validates it, checks the Fayda ID is unique, approves it automatically
    and gives it a DA-ID.
  - **Status of a push**, the **exceptions list** (every stuck DA, for the
    exceptions panel), and **DCI search** to look DAs up by DA-ID, Fayda ID
    or name.
- **Staff API**, with the signed-in user's Keycloak token: the single DA form,
  approving or rejecting a new DA, search and view, and a DA editing their
  profile (change request). Roles and Woreda scope are checked by the
  registry, and approvals happen in the registry. See
  [da-services-staff-api.md](da-services-staff-api.md).

The browser never calls the registry directly; the Frappe backend makes
these calls.

| | Local stack | Deployment |
|---|---|---|
| Partner API | `http://localhost:8106` | TODO(devops) |
| Signature / consent checks | off | on (see [Security](#security)) |

---

## 1. Push an approved DA

```
POST /partner/ingest_data?data_model=DA_SERVICES&register_id=6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90&intake_form_id=6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f91
Content-Type: application/json
```

### Request body

```json
{
  "header": {
    "version": "1.0.0",
    "message_id": "9f0c2e5a1b7d4c3e8a6f2b1c0d9e8f7a",
    "message_ts": "2026-10-06T09:15:00Z",
    "sender_id": "da-services",
    "data_model": "DA_SERVICES"
  },
  "signature": "<signature of header + message>",
  "message": {
    "reference_id": "FR-DA-0001",
    "source": "WEB_INTAKE",
    "approved_by": "Dr. Tewodros M. (Woreda Supervisor, Tahtay Adiyabo)",
    "da": {
      "salutation": "Dr",
      "first_name": "Frehiwot",
      "father_name": "Assefa",
      "grandfather_name": "Bekele",
      "fayda_id": "9311804512345601",
      "gender": "Female",
      "marital_status": "Married",
      "birth_month_ec": 6,
      "birth_year_ec": 1986,
      "phone_number": "0911556677",
      "telegram_number": "0911556677",
      "alternate_number": null,
      "email": "frehiwot.assefa@example.org",
      "education_level": "Masters",
      "specialisation": "Agronomy",
      "position": "Senior DA",
      "joining_date": "2017-09-11",
      "kebele_id": "kebele-ET010101101001"
    }
  }
}
```

`header.message_id` must be unique per request. `sender_id` and `signature`
must be present (non-empty).

### `message`

| Field | Required | Meaning |
|---|---|---|
| `reference_id` | Yes | The DA's record id in DA Services. Stored in the registry (`upstream_reference`) for tracing |
| `source` | No (default `WEB_INTAKE`) | `WEB_INTAKE` (entered on a form) or `CSV_IMPORT` (from a bulk file). With `WEB_INTAKE` every required field below must be filled |
| `approved_by` | Recommended | Who approved it in DA Services. Recorded as the registry approver |
| `da` | Yes | The DA, below |

### `message.da`

Coded fields (salutation, gender, marital status, education level,
specialisation, position) are resolved against the Master Data lists the DA
form uses (openg2p-data pack `ETH-OAN`): send the code (`SENIOR_DA`), the
display (`Senior DA`) or a translated display; case, spaces, `_`, `-` and `.`
do not matter. Anything else is an EXCEPTION with the allowed displays
(`Position 'Manager' is not one of: Development Agent, Senior DA`). A value
added to the Master Data list is accepted from then on; the lists below are
what is seeded today, read them live from Master Data
(`POST /attributes/get_attribute_values`, see the staff API doc §2.2b).

| Field | Required | Format / values |
|---|---|---|
| `salutation` | No | `PREFIX` list: `MR`, `MRS`, `MISS`, `MS`, `DR` |
| `first_name` | **Yes** | Name. Letters (Latin or Ethiopic), spaces, `-`, `'`; max 100 |
| `father_name` | **Yes** | Father's name. Same format |
| `grandfather_name` | No | Grandfather's name. Same format |
| `fayda_id` | **Yes** | Fayda FAN, 16 digits (spaces / dashes are removed). One DA per Fayda ID (also enforced by a unique index on active registered DAs) |
| `gender` | Yes* | `GENDER` list: `MALE`, `FEMALE`, `OTHER`, `UNKNOWN` |
| `marital_status` | Yes* | `MARITAL_STATUS` list: `SINGLE`, `MARRIED`, `WIDOWED`, `DIVORCED`, `SEPARATED`, `UNKNOWN` |
| `birth_month_ec` | Yes* | 1–13 (Ethiopian calendar) |
| `birth_year_ec` | Yes* | 4-digit EC year, not in the future |
| `phone_number` | Yes* | Ethiopian number: `0911234567` or `+251911234567` (a 9-digit number gets its leading 0 back) |
| `telegram_number` | No | Phone number, same format |
| `alternate_number` | No | Phone number, same format |
| `email` | Yes* | Valid email; stored lower case |
| `education_level` | Yes* | `DA_EDUCATION_LEVEL` list: `CERTIFICATE`, `DIPLOMA`, `DEGREE`, `MASTERS` |
| `specialisation` | Yes* | `DA_SPECIALISATION` list: `CROP_PRODUCTION`, `LIVESTOCK`, `NATURAL_RESOURCES`, `AGRONOMY`, `HORTICULTURE`, `OTHER` |
| `position` | Yes* | `DA_POSITION` list: `DEVELOPMENT_AGENT`, `SENIOR_DA` |
| `joining_date` | No | `YYYY-MM-DD` (or `DD/MM/YYYY`); not in the future |
| `kebele_id` | **Yes**, or the four names | Master Data kebele id, e.g. `kebele-ET010101101001` (preferred: names repeat across woredas) |
| `region`, `zone`, `woreda`, `kebele` | Instead of `kebele_id` | Names as in Master Data; resolved region → kebele |

\* Required when `source` is `WEB_INTAKE`. For `CSV_IMPORT` a blank value is
accepted; a filled value must still be valid.

### Response

The registry answers as soon as it has accepted the request. Processing
(validation, duplicate check, approval, DA-ID) happens in the background,
usually within a minute or two.

```json
{
  "message": {
    "ack_status": "ACK",
    "timestamp": "2026-10-29 10:46:07.338021",
    "error": {"code": "", "message": ""},
    "correlation_id": "17fcd9871f1a4bb89467e5dff4e9a656"
  }
}
```

The reply uses the DCI acknowledgement shape (as every partner API reply does
on registry-platform rc.557). `ack_status` is `ACK` when the request was
accepted; anything else carries the reason in `error`. Keep
`message.correlation_id` with the DA in DA Services.

### What happens next

| Case | Registry outcome | How DA Services finds out |
|---|---|---|
| Valid, Fayda ID not yet used | Approved → register → DA-ID (`DA-` + 10 digits) | Status `GENERATED` with `da_id` (§3) |
| Fayda ID already registered, or in another pending submission | Stopped with the reason ("Fayda ID … is already registered as DA-…") | Status `EXCEPTION`, `DUPLICATE_IDENTITY` (§3) |
| Invalid (format, missing required field, unknown kebele) | Stopped with a reason | Status `EXCEPTION` with the reason (§3) |

So **check duplicates before you push** (§2: search by Fayda ID, and look
inside the file for repeats when importing). The registry check is the last
guard, not the place to discover duplicates.

---

## 2. Read DAs (DCI search)

```
POST /dci/sync/search
Content-Type: application/json
```

```json
{
  "signature": "<signature>",
  "header": {"version": "1.0.0", "message_id": "…", "message_ts": "…", "action": "search",
             "sender_id": "da-services", "receiver_id": "da-registry"},
  "message": {
    "transaction_id": "…",
    "search_request": [{
      "reference_id": "q1", "timestamp": "…", "locale": "eng",
      "search_criteria": {
        "version": "1.0.0", "reg_type": "DA", "reg_record_type": "DA",
        "query_type": "expression",
        "query": {"type": "expression",
                  "value": {"expression": {"query": {"search_text": {"$eq": "9311804512345601"}}}}}
      }
    }]
  }
}
```

`search_text` matches DA-ID, Fayda ID, names, phone, email and location
(partial match). Each result is under `reg_records[].da_details`:

```json
{
  "da_id": "DA-6453519520", "internal_record_id": "…", "fayda_id": "9311804512345601",
  "name": {"salutation": "DR", "given_name": "Frehiwot", "father_name": "Assefa",
           "grandfather_name": "Bekele", "full_name": "Frehiwot Assefa Bekele"},
  "sex": "female", "marital_status": "MARRIED", "birth_month_ec": 6, "birth_year_ec": 1986,
  "contact": {"phone_number": "0911556677", "telegram_number": "0911556677",
              "alternate_number": "", "email": "frehiwot.assefa@example.org"},
  "education_level": "MASTERS", "specialisation": "AGRONOMY", "position": "SENIOR_DA",
  "joined_date": "2017-09-11", "source": "WEB_INTAKE",
  "posting": {"region": "Tigray", "zone": "North Western", "woreda": "Tahtay Adiyabo",
              "kebele": "Adi Hageray", "region_code": "ET01", "zone_code": "ET0101",
              "woreda_code": "ET010101", "kebele_code": "ET010101101001",
              "geo_lowest_level_value_id": "kebele-ET010101101001"},
  "record_status": "ACTIVE", "registration_date": "…", "last_updated": "…"
}
```

`search_text` is a partial match, so check that a returned record's
`fayda_id` equals the Fayda ID you searched for before treating it as a
duplicate.

**Location codes.** `region_code`, `zone_code` and `woreda_code` are the OCHA
P-codes Master Data holds for those levels (`ET04` Oromia, `ET0403` Ilu Aba
Bora, `ET040301` Darimu); each code starts with its parent's. Kebeles have no
P-code in Master Data, so `kebele_code` is the Kebele's Master Data id without
its `kebele-` prefix. Do not derive a Woreda from a Kebele code: Kebele ids do
not always carry their parents' codes. Use codes, not names, for scoping:
23 Woreda names and 790 Kebele names repeat across Ethiopia.

### Filter by location, position or change date

Expression queries also take exact filters on these DA fields (several fields
are combined with AND): `region_code`, `zone_code`, `woreda_code`,
`region_name`, `zone_name`, `woreda_name`, `kebele_name`,
`geo_lowest_level_value_id`, `position`, `specialisation`,
`upstream_reference`, and `last_approved_at`. Operators: `$eq`, `$ne`, `$in`,
`$nin` (and `$gt`/`$gte`/`$lt`/`$lte` on numbers and dates). Use the codes, not
`search_text` or names, to scope a Supervisor to their Woreda:

```json
"query": {"type": "expression", "value": {"expression": {"query": {
  "woreda_code": {"$eq": "ET010101"},
  "position": {"$eq": "SENIOR_DA"}
}}}}
```

**Changes since a time.** `last_approved_at` moves when a DA is registered and
when a change to it is approved, and is returned as `last_updated`. To refresh
DA Services' view, ask for the DAs changed after the last run:

```json
"query": {"type": "expression", "value": {"expression": {"query": {
  "last_approved_at": {"$gt": "2026-10-13T00:00:00"}
}}}}
```

`geo_lowest_level_value_id` with `$in` lists the DAs of several Kebeles.
Results are paged, 10 by default; add `"pagination": {"page_size": 50,
"page_number": 1}` to `search_criteria`. Each response carries
`pagination.total_count`.

### Mapping `get_da_list()` to a DCI query

DA Services' client (`DARegistryClient.get_da_list()`) takes
business names; the registry filters on these fields:

| `get_da_list()` parameter | DCI query field | Value |
|---|---|---|
| `woreda` | `woreda_code` | Woreda P-code, e.g. `ET040301` (not `ET04-W01`) |
| `kebele` | `geo_lowest_level_value_id` | Kebele Master Data id, `kebele-` + kebele code, e.g. `kebele-ET040301888007` |
| `active_status` | `record_status` | `ACTIVE` |
| `education_tier` | `education_level` | a `DA_EDUCATION_LEVEL` code (today `CERTIFICATE`, `DIPLOMA`, `DEGREE`, `MASTERS`) |
| `search` | `search_text` | partial match on DA-ID, names, Fayda ID, phone, email |
| `fayda_status` | none | see below |
| page / page size | `search_criteria.pagination` | `page_number` from 1; keep `page_size` at 200 or less (no hard cap, but a 1000-row page dropped the connection on the local stack) |

Rules the client has to follow:

- **Empty filters.** The registry rejects an empty expression query
  (`rjct.search_criteria.invalid`, "expression.query is required and must be
  non-empty"). To list all DAs send `{"record_status": {"$eq": "ACTIVE"}}`.
- **`fayda_status`.** The registry has no such field. In phase 1 the registry
  checks that a Fayda ID is unique, it does not verify it with Fayda (Option B,
  see the local setup guide §5), so every DA in the register has the same
  status. Do not send this filter; if DA Services keeps the parameter, answer
  it on its own side.
- **Several filters** go in one `query` object and are combined with AND.
- **`search` is partial.** Check the returned `da_id` or `fayda_id` before
  treating a hit as an exact match.

The whole mapping in Python:

```python
FIELD = {"woreda": "woreda_code", "kebele": "geo_lowest_level_value_id",
         "active_status": "record_status", "education_tier": "education_level",
         "search": "search_text"}

def dci_query(**filters) -> dict:
    """get_da_list() filters -> search_criteria.query.value.expression.query"""
    query = {}
    for name, value in filters.items():
        if value in (None, "") or name not in FIELD:
            continue
        if name == "kebele" and not str(value).startswith("kebele-"):
            value = f"kebele-{value}"
        query[FIELD[name]] = {"$eq": value}
    return query or {"record_status": {"$eq": "ACTIVE"}}  # empty query is rejected
```

---

## 3. Status of a push

```
GET /partner/da/status?correlation_id=<from the push response>
GET /partner/da/status?reference_id=<your record id>
```

One of the two. With `reference_id` the latest push of that record is
returned. Answers 404 when nothing is found, 400 when neither is given.

```json
{
  "correlation_id": "24507f2839fe49c8946a6d80b94c4ea7",
  "reference_id": "FR-DA-0001",
  "state": "GENERATED",
  "reason": null,
  "exception_type": null,
  "da_id": "DA-3803532319",
  "record_status": "ACTIVE",
  "application_reference": "2026OCT07-25529-1027",
  "received_at": "2026-10-07T07:04:55.793904",
  "updated_at": "2026-10-07T07:05:29.894349"
}
```

| `state` | Meaning | What DA Services does |
|---|---|---|
| `QUEUED` | Received, still being processed | Ask again in 10–30 s |
| `GENERATED` | Registered; `da_id` is set | Save the DA-ID on the DA |
| `EXCEPTION` | Stopped; `reason` says why | Show it to the Admin; send a corrected record |
| `FAILED_RETRY` | An attempt failed and the registry is retrying | Ask again later |

`exception_type` groups the reason for the exceptions panel:

| `exception_type` | Meaning |
|---|---|
| `DUPLICATE_IDENTITY` | The Fayda ID already belongs to an active DA or a live submission |
| `INVALID_KEBELE` | The Kebele (or Region / Zone / Woreda name) is not in Master Data |
| `MISSING_MANDATORY_FIELD` | A required field is empty |
| `INVALID_FIELD` | A field has a wrong format or value |
| `REJECTED` | An approver rejected it |
| `FAILED_SYNC` | The record is fine but the registry failed to process it or write it into the register (database or connection error). The registry retries; no correction needed |

The registry retries every failed step a few times, a validation error
included, so a bad record shows `FAILED_RETRY` (already with its reason) for a
few minutes before it settles as `EXCEPTION`. A valid record usually reaches
`GENERATED` within one to two minutes.

---

## 4. Exceptions list

```
GET /partner/da/exceptions?source=&exception_type=&state=&page_number=1&page_size=50
```

Every DA that is stuck, newest first: DA Services pushes and rows of a file
imported in the registry portal. All filters are optional:

| Parameter | Values |
|---|---|
| `source` | `da_services`, `file_import` |
| `exception_type` | as in §3 |
| `state` | `EXCEPTION`, `FAILED_RETRY` |
| `page_number`, `page_size` | from 1; `page_size` 1–200, default 50 |

```json
{
  "total_count": 2,
  "page_number": 1,
  "page_size": 50,
  "exceptions": [
    {
      "source": "file_import",
      "correlation_id": "0d9ad8dfee1a4efe956a1ca69be39d0f",
      "reference_id": null,
      "fayda_id": "9311412345678901",
      "name": "Abebe Kebede",
      "state": "EXCEPTION",
      "reason": "Location 'Nowhere' not found in Master Data",
      "exception_type": "INVALID_KEBELE",
      "application_reference": null,
      "received_at": "2026-10-14T09:00:00",
      "updated_at": null
    },
    {
      "source": "da_services",
      "correlation_id": "24507f2839fe49c8946a6d80b94c4ea7",
      "reference_id": "FR-DA-0001",
      "fayda_id": "9311804512345611",
      "name": "Tesfaye Bekele",
      "state": "EXCEPTION",
      "reason": "Fayda ID 804512345611 is already registered as DA-5891503619.",
      "exception_type": "DUPLICATE_IDENTITY",
      "application_reference": "2026OCT07-25529-1027",
      "received_at": "2026-10-07T07:04:55.793904",
      "updated_at": "2026-10-07T07:05:29.894349"
    }
  ]
}
```

Each entry reads exactly as `GET /partner/da/status` would report that record.
Only the latest attempt of a record is listed: once DA Services sends the same
`reference_id` again (or a file row with the same Fayda ID is imported again)
and it goes through, the old entry drops off. `correlation_id` works with §3.

Not covered yet: the registry does not record which file and row number an
imported row came from, so a file-import entry is identified by its Fayda ID
and name. A resolve action is not part of the API; the fix is to send a
corrected record.

---

## Security

In deployments the push and the search are checked:

- **Signature:** DA Services must be registered as a partner in Partner
  Management with its signing key, and sign `header` + `message`.
- **Consent (DCI search):** searches need a consent object, or DA Services must
  be allow-listed for searches across subjects.

Both are off in the local stack. TODO(devops): register DA Services as a
partner and agree the consent set-up per environment. The status lookup (§3)
returns no personal data beyond the DA-ID; the exceptions list (§4) returns
Fayda IDs and names. Neither checks a signature, so in deployments both must
only be reachable by DA Services (network policy or gateway).

## Open items

1. **Updates** (a DA edits their profile): these go through the registry staff
   API as change requests, with the DA's Keycloak token, not through this
   partner API. See [da-services-staff-api.md](da-services-staff-api.md).
2. **Bulk import:** push one request per DA and pace them (e.g. 1,000–2,000 at a time).
   Load test (local stack, 500 DAs by file import, default settings): all 500
   got a DA-ID in 49 minutes, about 10 a minute. The pipeline takes 4 records
   per stage every 20 s (`NO_OF_TASKS_TO_PROCESS`, celery beat); raise it
   before a large import.
3. Field names above are the registry's proposal; change requests welcome
   before DA Services builds against them.
