# DA Registry on your laptop (for DA Services developers)

How to run the DA Registry locally and call it from DA Services, until it is
deployed on develop. Ten minutes on a laptop that already has Docker.

## 1. Start it

Requirements: Docker Desktop (on Windows, with WSL integration on for your
distro), about 8 GB of free memory and 10 GB of disk.

```bash
git clone https://github.com/Centre-for-Open-Societal-Systems/DA-registry-backend.git
cd DA-registry-backend
git checkout develop          # until PR #1 is merged: the PR branch
docker compose up --build -d
```

The first start pulls the platform images (registry-platform `1.2.2-rc.557`)
and takes 5–10 minutes. It is ready when the staff API answers:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8101/docs   # 200
```

The seed loads the Ethiopia geo hierarchy and the dropdown code lists, and
submits the **sample DAs** of the openg2p-data pack (`packs/ETH-OAN`) through the
intake form; they wait for approval (stage 1 `alex.carter` or `admin`, stage 2
`nina.patel` or `admin`) and get their DA-ID when approved. No real personal
data is used.

Stop with `docker compose stop`; `docker compose down -v` also deletes the data.

## 2. Addresses and users

| What | Address |
|---|---|
| Staff portal (registry UI) | http://localhost:3101 |
| Staff API (form, approval, search) | http://localhost:8101 |
| Partner API (push, status, DCI search) | http://localhost:8106 |
| Master Data API (Kebele picker) | http://localhost:8142 |
| Keycloak (realm `staff`) | http://localhost:8090 |

| User / password | Use |
|---|---|
| `admin` / `admin` | Staff admin: fills forms and approves |
| `staff` / `staff` | Staff user |

Ports are chosen not to clash with a local Frappe bench (8000) and to avoid
TCP 9000.

## 3. What to call

| Need in DA Services | API | Document |
|---|---|---|
| Bulk import (Excel) | Partner `POST /partner/ingest_data` | [contract §1](da-services-api-contract.md#1-push-an-approved-da) |
| Result of each pushed DA | Partner `GET /partner/da/status` | [contract §3](da-services-api-contract.md#3-status-of-a-push) |
| Look DAs up (DA-ID, Fayda ID, name, Woreda) | Partner `POST /dci/sync/search` | [contract §2](da-services-api-contract.md#2-read-das-dci-search) and §4 below |
| Single DA form, approval, search and view as a user | Staff API | [da-services-staff-api.md](da-services-staff-api.md) |

On the local stack the partner API does not check signatures or consent, so
any non-empty `signature` and `sender_id` work. In deployments DA Services is
onboarded as a partner and signs its requests.

The Postman collection
[`postman/da-registry-local.postman_collection.json`](postman/da-registry-local.postman_collection.json)
has every call below, ready to run against these addresses.

## 4. DCI search: three examples

`POST http://localhost:8106/dci/sync/search`, `Content-Type: application/json`.
Only `search_criteria.query` (and `pagination`) change between the three.

```json
{
  "signature": "local-dev",
  "header": {"version": "1.0.0", "message_id": "0f9c…", "message_ts": "2026-10-13T04:30:00Z", "action": "search",
             "sender_id": "da-services", "receiver_id": "da-registry"},
  "message": {
    "transaction_id": "7a1e…",
    "search_request": [{
      "reference_id": "q1", "timestamp": "2026-10-13T04:30:00Z", "locale": "eng",
      "search_criteria": {
        "version": "1.0.0", "reg_type": "DA", "reg_record_type": "DA", "query_type": "expression",
        "query": {"type": "expression", "value": {"expression": {"query": {"search_text": {"$eq": "DA-3700000001"}}}}}
      }
    }]
  }
}
```

| Search by | `query` | `pagination` | Result on the local seed |
|---|---|---|---|
| DA-ID | `{"search_text": {"$eq": "DA-3700000001"}}` | (default 10) | 1 record, DA-3700000001 |
| Fayda ID | `{"search_text": {"$eq": "9311502628318720"}}` | (default 10) | 1 record, DA-3700000001 |
| Woreda | `{"woreda_code": {"$eq": "ET010101"}}` | `{"page_size": 2, "page_number": 1}` | 2 records, `total_count` 41 |

`search_text` is a partial match: check that a returned `da_id` or `fayda_id`
is exactly the one searched for. Woreda, Kebele, region, zone and position are
exact filters; combine several in one `query` (AND).
An empty `query` is rejected (`rjct.search_criteria.invalid`); to list every DA
send `{"record_status": {"$eq": "ACTIVE"}}`. The full parameter mapping for
`get_da_list()` is in the contract §2.

Each result carries the location codes (`posting.region_code`, `zone_code`,
`woreda_code`, `kebele_code`). Filter by code rather than name, since names
repeat: `{"woreda_code": {"$eq": "ET010101"}}` (41 DAs on the local seed, paged),
`{"region_code": {"$eq": "ET04"}}`. For the DAs changed since a time:
`{"last_approved_at": {"$gt": "2026-10-13T00:00:00"}}`.

The answer is under `message.search_response[0]`:

```json
{
  "status": "succ",
  "pagination": {"page_size": 10, "page_number": 1, "total_count": 1},
  "data": {"reg_records": [{"da_details": {
    "da_id": "DA-3700000001",
    "internal_record_id": "ec94f841-57cf-59c3-b30e-5d2e778342b8",
    "fayda_id": "9311502628318720",
    "name": {"salutation": "", "given_name": "Solomon", "father_name": "Kassa", "grandfather_name": "Tadesse",
             "full_name": "Solomon Kassa Tadesse"},
    "sex": "male", "marital_status": "SINGLE", "birth_month_ec": 12, "birth_year_ec": 1982,
    "contact": {"phone_number": "0930123375", "telegram_number": "0930123375",
                "alternate_number": "0735262167", "email": "solomon.kassa1@example.org"},
    "education_level": "MASTERS", "specialisation": "LIVESTOCK", "position": "DEVELOPMENT_AGENT",
    "joined_date": "2022-02-20", "source": "CSV_IMPORT",
    "posting": {"region": "Oromia", "zone": "Ilu Aba Bora", "woreda": "Darimu", "kebele": "Meti Guda",
                "region_code": "ET04", "zone_code": "ET0403", "woreda_code": "ET040301",
                "kebele_code": "ET040301888007", "geo_lowest_level_value_id": "kebele-ET040301888007"},
    "record_status": "ACTIVE", "registration_date": "2026-10-01", "last_updated": "2026-10-01T00:00:00"
  }}]}
}
```

## 5. Fields: what the registry has

| Asked for | In the registry |
|---|---|
| DA-ID, full name and name parts, Fayda ID | Yes (`da_id`, `name.*`, `fayda_id`) |
| Region / zone / woreda / kebele names | Yes (`posting.region` … `posting.kebele`) |
| Region / zone / woreda / kebele codes | Yes (`posting.region_code` … `kebele_code`): OCHA P-codes such as `ET04`, `ET0403`, `ET040301`; see the contract §2 |
| Active status | `record_status` (`ACTIVE`); leave, transfer and separation are not built (FSD Part 2) |
| Approval status | Only approved DAs are in the register and in DCI; pending ones are intake submissions (staff API) |
| Phone, email, specialisation, education, joined date | Yes |
| Fayda verification status | No: Fayda verification is out of phase 1 (Option B) |
| Supervisor | No |
| Record version / updated at | `last_updated` only |

## 6. Rules to know

- **One Kebele per DA.** A DA has one current Kebele (`geo_lowest_level_value_id`);
  a transfer replaces it through a change request.
- **One active DA per Fayda ID.** A duplicate is refused when the form is saved,
  and a pushed duplicate ends as `EXCEPTION` / `DUPLICATE_IDENTITY`.
- **Change notifications** (registration, approval, profile change) are not set
  up yet. The platform can publish them over WebSub; until then, poll the status
  API for pushes and DCI search with `last_approved_at` `$gt` your last run.
