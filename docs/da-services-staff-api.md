# DA Services ↔ DA Registry: staff API

For the DA Services (Frappe) team. How DA Services lets a signed-in person add
one DA through a form, approve or reject it, and search and view DAs, using the
registry's **staff API**.

The partner API (bulk import and push status) is in
[da-services-api-contract.md](da-services-api-contract.md). The difference:

| | Partner API | Staff API (this document) |
|---|---|---|
| Who calls | The DA Services system | A person, through the Frappe backend |
| Auth | Partner signature | The person's Keycloak token |
| Used for | Bulk import, push status, DCI search | Single DA form, approval, search and view |
| Approval | Two-level approval in the registry (stage 1, stage 2), same as the form | Two-level approval in the registry |
| Recorded as | `system` / partner | The person's name |

Every call below was run end to end against the local stack on
registry-platform `1.2.2-rc.557`; the JSON is taken from those runs and trimmed.

| | Local stack | Deployment |
|---|---|---|
| Staff API | `http://localhost:8101` | TODO(devops) |
| Master Data API (Kebele picker) | `http://localhost:8142` | TODO(devops) |
| Keycloak | `http://localhost:8090`, realm `staff` | Common Keycloak (to be confirmed) |

---

## 1. Calling the staff API

### Token

Every call carries the signed-in person's Keycloak access token:
`Authorization: Bearer <token>`. The registry reads the person's name, roles
and (later) Woreda scope from it. DA Services should obtain this token when the
user signs in through Keycloak and pass it through; it must come from the same
realm the registry trusts.

For local testing only, a token can be fetched with the password grant:

```
POST http://localhost:8090/realms/staff/protocol/openid-connect/token
Content-Type: application/x-www-form-urlencoded

grant_type=password&client_id=iam-staff-portal&client_secret=dev-iam-staff-secret&username=admin&password=admin
```

Local users: `admin / admin` (staff admin, can approve), `staff / staff`.

### CSRF

The staff API checks a double-submit CSRF token on every POST. Send any random
value both as a header and as a cookie with the same name:

```
X-CSRF-Token: 4c1f0e9a7b2d4e65a0c3b8f1d2e7a6c9
Cookie: X-CSRF-Token=4c1f0e9a7b2d4e65a0c3b8f1d2e7a6c9
```

A missing or mismatched pair answers `G2P-AUT-403 Forbidden. CSRF token missing or invalid.`

### Request and response envelope

All calls are `POST` with this body:

```json
{
  "request_header": {
    "request_id": "6b0f2c…",
    "request_timestamp": "2026-10-13T09:00:00",
    "sender_app_mnemonic": "da-services",
    "sender_app_url": "https://da-services.example"
  },
  "request_body": {
    "request_payload": { "…": "call-specific" },
    "pagination_request": {"current_page": 1, "page_size": 20, "search_text": "", "sort_by": "", "filter_by": ""}
  }
}
```

`pagination_request` is only needed on list and search calls. Every response:

```json
{
  "response_header": {"request_id": "6b0f2c…", "response_status": "SUCCESS",
                      "response_error_code": "", "response_error_message": "", "response_timestamp": "…"},
  "response_body": {"pagination_response": {"number_of_items": 1, "number_of_pages": 1},
                    "response_payload": { "…": "call-specific" }}
}
```

Check `response_header.response_status`, not only the HTTP code: a rejected
field comes back as HTTP 200 with `"response_status": "ERROR"` and the reason,
for example `REQ-VAL-001 Fayda ID (FAN) must be exactly 16 digits`.

### Fixed ids

| Name | Value |
|---|---|
| `register_id` (DA register) | `6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90` |
| `form_id` (DA intake form) | `6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f91` |

---

## 2. Single DA form

```
render_intake_form → save_intake_form_submission (one call per section) → finalize_intake_form_submission
```

### 2.1 Get the form layout

```
POST /intake-form-metadata/render_intake_form
request_payload: {"form_id": "6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f91"}
```

The response lists `tabs[].sections[]`; each section has a `section_id` and a
`section_ui_schema` with its widgets (`widget-id` = field name,
`widget-required`, `widget-readonly`, and for drop-downs
`widget-data-source.options`). Draw the form from it, so a field added in the
registry shows up without a Frappe change. Today the DA form has four sections:

| `section_id` | Fields (required in **bold**) |
|---|---|
| `da_identity_section_01` | `prefix`, **`first_name`** (Name), **`middle_name`** (Father's name), `last_name` (Grandfather's name), **`foundational_id`** (Fayda FAN, 16 digits), **`gender`**, **`marital_status`**, **`birth_month_ec`** (1–13), **`birth_year_ec`** (EC, not in the future) |
| `da_contact_section_04` | **`mobile_number`**, `telegram_number`, `alternate_number`, **`email`** |
| `da_service_section_02` | **`education_level`**, **`specialisation`**, **`position`**, `joined_date` (`YYYY-MM-DD`), `source` (read-only) |
| `da_location_section_03` | **`da_geo_hierarchy`**: Region / Zone / Woreda / Kebele, saved as `geo_lowest_level_value_id` + `geo_code_hierarchy_json` |

Drop-down codes (send the code, not the label):

The coded fields take a `value_id` of the Master Data list the widget
declares (§2.2b); read the lists from Master Data rather than copying them.
As seeded today:

| Field | Master Data list | Values today |
|---|---|---|
| `prefix` | `PREFIX` | `MR`, `MRS`, `MISS`, `MS`, `DR` |
| `gender` | `GENDER` | `MALE`, `FEMALE`, `OTHER`, `UNKNOWN` |
| `marital_status` | `MARITAL_STATUS` | `SINGLE`, `MARRIED`, `WIDOWED`, `DIVORCED`, `SEPARATED`, `UNKNOWN` |
| `education_level` | `DA_EDUCATION_LEVEL` | `CERTIFICATE`, `DIPLOMA`, `DEGREE`, `MASTERS` |
| `specialisation` | `DA_SPECIALISATION` | `CROP_PRODUCTION`, `LIVESTOCK`, `NATURAL_RESOURCES`, `AGRONOMY`, `HORTICULTURE`, `OTHER` |
| `position` | `DA_POSITION` | `DEVELOPMENT_AGENT`, `SENIOR_DA` |

A value that is not in the list answers `response_status: ERROR` with
`record 0: position='X' is not a value of DA_POSITION (permitted: ...)`.

Phone numbers are Ethiopian (`0911234567` or `+251911234567`).

### 2.2 The Kebele picker

The location values come from the Master Data API (same token and CSRF pair):

```
POST /geo/get_all_geo_levels        request_payload: {}
POST /geo/get_geo_level_values      request_payload: {"level_id": "level-region", "parent_level_value_id": ""}
```

Call `get_geo_level_values` level by level (`level-region` → `level-zone` →
`level-woreda` → `level-kebele`), passing the chosen value as
`parent_level_value_id`. Save the chosen chain like this:

```json
{
  "geo_lowest_level_value_id": "kebele-ET010101101001",
  "geo_code_hierarchy_json": {
    "lowest_level_value_id": "kebele-ET010101101001",
    "hierarchy": [
      {"level": "region", "level_id": "level-region", "level_mnemonic": "region", "level_value_id": "region-ET01",            "level_value_mnemonic": "Tigray"},
      {"level": "zone",   "level_id": "level-zone",   "level_mnemonic": "zone",   "level_value_id": "zone-ET0101",           "level_value_mnemonic": "North Western"},
      {"level": "woreda", "level_id": "level-woreda", "level_mnemonic": "woreda", "level_value_id": "woreda-ET010101",       "level_value_mnemonic": "Tahtay Adiyabo"},
      {"level": "kebele", "level_id": "level-kebele", "level_mnemonic": "kebele", "level_value_id": "kebele-ET010101101001", "level_value_mnemonic": "Adi Hageray"}
    ]
  }
}
```

### 2.2b Dropdown values (code lists)

Every dropdown on the form reads Master Data too, same token and CSRF pair.
The lists live in the openg2p-data country pack (`ETH-OAN`), nothing is
hardcoded in the registry; a value is added or renamed there, never in code.

```
POST /attributes/get_attribute_values
request_payload: {"attribute_id": "DA_SPECIALISATION"}
pagination_request: {"current_page": 1, "page_size": 500, "search_text": "", "sort_by": "", "filter_by": ""}
```

| Form field (saved as) | `attribute_id` |
|---|---|
| `prefix` | `PREFIX` |
| `gender` | `GENDER` |
| `marital_status` | `MARITAL_STATUS` |
| `education_level` (qualification) | `DA_EDUCATION_LEVEL` |
| `specialisation` | `DA_SPECIALISATION` |
| `position` | `DA_POSITION` |
| `source` | `DA_SOURCE` |

Each item has `value_id` (what you save), `value_display` (what you show) and
`sort_order`. Fetch the lists once per session; they change only through a
Master Data change request.

### 2.3 Save each section

```
POST /intake-form-data/save_intake_form_submission
```

The first call creates the submission and the DA record:

```json
{
  "submission_id": null,
  "section_id": "da_identity_section_01",
  "section_register_id": "6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90",
  "form_id": "6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f91",
  "register_id": "6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90",
  "section_payload": [{
    "edit_action": "ADD", "internal_record_id": "", "link_internal_record_id": "",
    "prefix": "DR", "first_name": "Selam", "middle_name": "Tesfaye", "last_name": "Gebru",
    "foundational_id": "889065919921", "gender": "FEMALE", "marital_status": "MARRIED",
    "birth_month_ec": 4, "birth_year_ec": 1987
  }]
}
```

Response (trimmed): keep `submission_id` and the record's `internal_record_id`.

```json
{
  "submission_id": "385e2322-226d-49b4-8c11-e77ca017bcc8",
  "application_reference": "2026OCT13-12690-5460",
  "draft_status": "DRAFT", "approval_status": "PENDING",
  "submission_source": "STAFF_PORTAL", "created_by": "Staff Admin",
  "section_payloads": [{"section_id": "da_identity_section_01",
    "records": [{"internal_record_id": "0cafd44c-bf23-4d4b-aad2-67d4672f5456", "functional_record_id": null, "…": "…"}]}]
}
```

**Every following section updates the same record**: pass the
`submission_id`, `"edit_action": "UPDATE"` and that `internal_record_id`.
Sending `ADD` again creates a second, empty DA record in the submission.

```json
{
  "submission_id": "385e2322-226d-49b4-8c11-e77ca017bcc8",
  "section_id": "da_contact_section_04",
  "section_register_id": "6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90",
  "form_id": "6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f91",
  "register_id": "6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90",
  "section_payload": [{
    "edit_action": "UPDATE", "internal_record_id": "0cafd44c-bf23-4d4b-aad2-67d4672f5456", "link_internal_record_id": "",
    "mobile_number": "0913919921", "email": "selam.9921@example.org"
  }]
}
```

Each save validates its section and answers `ERROR` with the reason if a
field is wrong, so errors can be shown next to the section the user just filled.

The identity section is also refused when the Fayda ID already belongs to
another DA, so the user learns it before the form goes to approval:

```
REQ-VAL-001  Fayda ID 860312139936 is already registered as DA-9298471467.
REQ-VAL-001  Fayda ID 412345678901 is already in submission 2026OCT05-091557.
```

Saving the same submission again with its own Fayda ID is fine.

What a save checks (all answer HTTP 200 with `response_status: ERROR` and the
reason in `response_error_message`):

- A **new** record (`edit_action: ADD`) must carry every required field of
  that section; a required field left out or blank answers
  `Required: Name, Father Name, ...` (the labels of the section's `*` fields,
  from the form metadata). An `UPDATE` may carry only the fields that change;
  a required field sent blank is still refused.
- Formats: Fayda ID 16 digits and not already registered, Ethiopian phone
  numbers, email, month 1–13, year not in the future.
- Coded fields must hold a Master Data value (§2.2b).

### 2.4 Submit for approval

```
POST /intake-form-data/finalize_intake_form_submission
request_payload: {"submission_id": "385e2322-226d-49b4-8c11-e77ca017bcc8"}
```

The submission becomes `draft_status: FINAL`, `approval_status: PENDING`, and
the registry opens an approval request (`awe_request_id`). There is no DA-ID yet.

A submission with a section missing, or a required field still empty in any
section, is refused: `Cannot submit for approval. Required: Phone Number,
Email, Education Level, Specialisation, Position, Region / Zone / Woreda /
Kebele` (whatever is missing). Save every section first.

To read a submission at any time:

```
POST /intake-form-data/get_intake_form_submission
request_payload: {"submission_id": "385e2322-226d-49b4-8c11-e77ca017bcc8"}
```

To list submissions (for example the "My submissions" screen):

```
POST /intake-form-data/search_in_intake_form_submissions
request_payload: {"register_id": "6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90", "form_id": "6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f91"}
pagination_request: {"current_page": 1, "page_size": 20, "search_text": "", "sort_by": "", "filter_by": ""}
```

---

## 3. Approval

Approval runs in the registry's approval engine (AWE). The Approve and Reject
buttons in DA Services call these endpoints with the approver's token; the
decision is recorded under the approver's name.

```
list_my_tasks → (show the submission and its duplicates) → claim_task → submit_task_decision
```

### 3.1 The approver's queue

```
POST /awe/list_my_tasks
request_payload: {"status": "open"}
```

```json
{"data": {"items": [{
  "id": "96b93006-db57-4792-a874-80509e4bd37e",
  "request_id": "86f86621-58dd-4817-b6c9-3cf2fc1fc96c",
  "stage_order": 1, "status": "open", "kind": "approver", "assignee": "admin",
  "artifact_type": "registry.intake_form",
  "context": {"record_name": "Selam Tesfaye Gebru", "intake_form_mnemonic": "DA Intake",
              "register_mnemonic": "DA", "submission_id": "385e2322-226d-49b4-8c11-e77ca017bcc8"},
  "created_at": "2026-10-13T03:31:36.035606Z"
}]}}
```

`context.submission_id` links the task to the submission: open it with
`get_intake_form_submission`. The tasks of one submission are also available
with `POST /awe/list_tasks_for_request` and `{"request_id": "<awe_request_id>"}`.

### 3.2 Show duplicates before approving

```
POST /intake-form-data/get_deduplication_intake_form_register_results
request_payload: {"submission_id": "385e2322-226d-49b4-8c11-e77ca017bcc8"}
```

An empty list means no match. A match looks like this:

```json
[{"internal_record_id": "089127e9-e914-4981-965c-89d0e7b3b5b8", "match_score": 100.0,
  "field_matches": {"foundational_id": {"incoming": "960214350002", "candidate": "960214350002",
                                         "similarity": 1.0, "match_type": "EXACT"}}}]
```

The same match can appear more than once; show each `internal_record_id` once.
Do not let an approver approve a 100% match on `foundational_id`: the registry
holds one active DA per Fayda ID, so that approval would never produce a DA.

### 3.3 Approve or reject

Claim the task, then submit the decision:

```
POST /awe/claim_task
request_payload: {"task_id": "96b93006-db57-4792-a874-80509e4bd37e"}

POST /awe/submit_task_decision
request_payload: {
  "task_id": "96b93006-db57-4792-a874-80509e4bd37e",
  "action": "approve",
  "comment": "Checked against the Fayda card",
  "artifact_id": "385e2322-226d-49b4-8c11-e77ca017bcc8",
  "artifact_type": "registry.intake_form",
  "current_stage": 1
}
```

`action` is `approve` or `reject` (a reason in `comment` is expected for a
rejection). `current_stage` is the task's `stage_order`. There is no "send
back for changes" action; a rejected DA is entered again as a new submission.

`approve_intake_form_submission` (without AWE) is refused because the form
requires a verification step; use the task decision above.

### 3.4 After the decision

About 15–30 seconds after an approval the registry writes the DA to the
register and issues the DA-ID. For a few seconds the record can show a
placeholder `functional_record_id` starting with `TEMP-`; treat only a value
starting with `DA-` as the DA-ID. `get_intake_form_submission` then shows
`approval_status: APPROVED`, `approved_by` and
`register_ingest_process_status: PROCESSED`. Rely on `approval_status`; the
`awe_request_status_summary` field is not updated after the decision.

The DA keeps the same `internal_record_id` in the register, so fetch the DA-ID with:

```
POST /register-data/get_subject_record
request_payload: {"subject_register_id": "6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90",
                  "subject_record_id": "0cafd44c-bf23-4d4b-aad2-67d4672f5456"}
```

```json
{"internal_record_id": "0cafd44c-bf23-4d4b-aad2-67d4672f5456",
 "functional_record_id": "DA-5187236562",
 "record_status": "ACTIVE", "record_name": "Selam Tesfaye Gebru",
 "foundational_id": "889065919921", "first_name": "Selam", "middle_name": "Tesfaye", "last_name": "Gebru",
 "prefix": "DR", "gender": "FEMALE", "marital_status": "MARRIED", "birth_month_ec": 4, "birth_year_ec": 1987,
 "mobile_number": "0913919921", "email": "selam.9921@example.org",
 "education_level": "DEGREE", "specialisation": "CROP_PRODUCTION", "position": "DEVELOPMENT_AGENT",
 "joined_date": "2018-09-11", "source": "WEB_INTAKE",
 "geo_lowest_level_value_id": "kebele-ET010101101001",
 "last_approved_at": "2026-10-13T03:32:05.810553", "last_approved_by": "Staff Admin"}
```

The approval history (for an audit trail on the screen):

```
POST /awe/get_request_events
request_payload: {"request_id": "86f86621-58dd-4817-b6c9-3cf2fc1fc96c"}
```

returns events in order: `request_created`, `stage_started`,
`stage_completed` (with the `actor`), then `request_approved` or `request_rejected`.

---

## 4. Search and view DAs

```
POST /register-data/search_in_a_register
request_payload: {"register_id": "6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90"}
pagination_request: {"current_page": 1, "page_size": 20, "search_text": "889065919921", "sort_by": "", "filter_by": ""}
```

`search_text` matches DA-ID, Fayda ID, names, phone and email; send `""` to
list all. It must be present, even when empty. Each item has
`internal_record_id`, `functional_record_id` (DA-ID), `foundational_id`,
`record_name`, `last_approved_at` and `display_fields` (DA-ID, Fayda ID, phone,
position, Woreda, Kebele); open one with `get_subject_record` (§3.4).

### 4.1 Filters (list a Woreda's DAs, sync changes)

`filter_by` is a JSON **string** of `{"<field>": {"<operator>": value}}`. Use
codes, not names: 23 Woreda names and 790 Kebele names repeat.

```
"filter_by": "{\"woreda_code\": {\"eq\": \"ET010101\"}}"
"filter_by": "{\"woreda_code\": {\"in\": [\"ET010101\", \"ET010102\"]}}"
"filter_by": "{\"geo_lowest_level_value_id\": {\"eq\": \"kebele-ET010101101001\"}}"
"filter_by": "{\"last_approved_at\": {\"gte\": \"2026-10-27\"}}"
"filter_by": "{\"woreda_code\": {\"eq\": \"ET010101\"}, \"last_approved_at\": {\"gte\": \"2026-10-27\"}}"
```

| Field | Operators | Value |
|---|---|---|
| `region_code`, `zone_code`, `woreda_code` | `eq`, `in` | Master Data P-code (`ET01`, `ET0101`, `ET010101`) |
| `geo_lowest_level_value_id` | `eq`, `in` | Kebele id from the Kebele picker (§2.2) |
| `last_approved_at` | `gt`, `gte`, `lt`, `lte`, `between` | ISO date; **compared by day**, the time part is ignored |
| `record_status` | `eq`, `in` | `ACTIVE` (default when absent), `INACTIVE`, `ARCHIVED` |
| `first_name`, `foundational_id`, `mobile_number`, `region_name`, `woreda_name`, `kebele_name` | `eq`, `contains` | text |
| `education_level`, `specialisation`, `position`, `source` | `eq`, `in` | the dropdown codes |

Two platform behaviours to code for:

- A field that is not in this list is **ignored, not rejected**: the call
  answers 200 with the unfiltered list (and a WARNING in the registry log), so
  a typo in a field name looks like "no filter". A value the platform cannot
  parse (for example a bad date) answers HTTP 200 with
  `response_header.response_status: "ERROR"`, `response_error_code: "REQ-VAL-000"`
  and the reason in `response_error_message`; always check `response_status`.
- `last_approved_at` is a day filter. For "changed since the last sync", pass
  the date of the last run and skip, on your side, the records whose
  `last_approved_at` (full timestamp in each item) you already have. Approval
  and change-request approval both update `last_approved_at`.

---

## 5. Profile edit (change requests)

A change to a registered DA (new phone number, transfer to another Kebele, a
corrected name) is a change request on one section of the DA record. It goes
through the same approval as a new DA, and the register changes only when it
is approved.

```
POST /change-requests/create_change_request
request_payload: {
  "register_id": "6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90",
  "tab_id": "da_details_tab",
  "section_id": "da_contact_section_04",
  "section_register_id": "6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90",
  "internal_record_id": "ca58485f-5496-487e-8bea-0daf7887fd73",
  "change_payload": [{"internal_record_id": "ca58485f-5496-487e-8bea-0daf7887fd73",
                      "edit_action": "UPDATE", "mobile_number": "0914000222"}]
}
```

`internal_record_id` is the DA's id in the register (§3.4). Send only the
fields that change, in the section they belong to (§2.1); a Kebele transfer
is the location section with a new `geo_lowest_level_value_id` and
`geo_code_hierarchy_json`. The same field rules apply as on the form, including
the Fayda ID check.

Response (trimmed):

```json
{"change_request_id": "9e68d3a3-8f56-496b-85c0-da4177ae3e6e", "approval_status": "PENDING",
 "awe_request_id": "e9c85237-00f2-401a-8bdf-44abe0b91a91", "record_name": "Selam Tesfaye Gebru",
 "section_id": "da_contact_section_04", "created_by": "Staff Admin"}
```

Only one pending change request is allowed per DA and section; a second one
answers `A pending change request already exists for this record and section`.

**Decide it in AWE**, exactly as in §3.3, with the change request as the artifact:

```
POST /awe/submit_task_decision
request_payload: {"task_id": "…", "action": "approve", "comment": "Phone confirmed with the DA",
                  "artifact_id": "9e68d3a3-8f56-496b-85c0-da4177ae3e6e",
                  "artifact_type": "registry.change_request", "current_stage": 1}
```

The task shows in `list_my_tasks` with `artifact_type: registry.change_request`.
On approval the register is updated within a few seconds; on rejection it
stays as it was. Read the result with:

```
POST /change-requests/get_change_request
request_payload: {"change_request_id": "9e68d3a3-8f56-496b-85c0-da4177ae3e6e"}
```

(`approval_status`: `PENDING`, `APPROVED` or `REJECTED`, with `approved_by`.)

Do not use `/change-requests/approve_change_request` or `reject_change_request`
directly: the registry refuses them (`AWE_APPROVAL_REQUIRED`); only the
approval task decides.

### 5.1 A DA editing their own profile

A Development Agent signs in to DA Services, not to the registry. DA Services
makes the calls above with its **service account** (client credentials, role
Data Editor), finds the DA by their DA-ID, and lets them change only their own
record and only the contact, service and location sections. The steps, the
Keycloak client and what DA Services must enforce are in
`docs/rbac-registry-roles.md` section 5.

---

## 6. Not covered yet

- **Approver roles and Woreda scope**: today only registry administrators get
  approval tasks. A Woreda approver role, with rows limited to the approver's
  Woreda, follows once the approver is confirmed.
- **Token**: DA Services signs users in through `oan_auth_service`; the
  registry accepts tokens from its Keycloak `staff` realm. How the two meet
  (shared Keycloak or token exchange) is still to be decided.
