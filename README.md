# DA Registry (OpenG2P)

The Development Agent (DA) Registry for OAN Ethiopia, built on the OpenG2P
registry platform. It holds the profile of every Development Agent: name,
Fayda ID, personal details, contact, education and position, and posting
(Region / Zone / Woreda / Kebele). DA workflow lives in the separate Frappe DA
Services, which read DA records from this registry.

This repository only adds the DA domain on top of the platform images; it
follows the same build model as the farmer registry.

## Layout

| Path | What it is |
|---|---|
| `da-extension/` | Python extension: DA model, domain rules, ID prefix, file-import enricher, seed metadata, Jinja templates |
| `docker/*/Dockerfile` | Thin native registry-platform images for the DA APIs, worker/beat, UI and seed job |
| `ui/staff-ui/` | Pinned upstream Staff UI materialization with an empty DA override layer for future UI additions |
| `docker/db-seed/` | db-seed image: the extension's configuration only (metadata, AWE seed, templates) |
| `docker/local-dev/data-loaders/` | Local-only loaders for code lists and sample DAs (not a deployable image; they move to openg2p-data, see `docs/refactor/moves-to-openg2p-data/`) |
| `docker/local-dev/` | Config for the local stack (Keycloak, IAM, AWE, ID generator, Postgres, geo seed) |
| `import-templates/` | Blank CSV and Excel templates for bulk import |
| `docker-compose.yml` | Self-contained local stack |
| `Jenkinsfile` | CI/CD: builds and pushes images to ECR (`openg2p/da-registry`, tag `<component>-<commit>`); on `develop`, when `DEPLOY_TO_DEV` is ticked, also upgrades the existing dev release `da-registry` (namespace `da-registry`) |
| `ci/deploy/` | The pinned central chart: `oan-chart.json` (oan-helm commit, chart version, archive and public-values SHA-256), `oan_chart.py` (download and verification), see `ci/deploy/README.md` |
| `ci/deploy-dev.sh` | The dev deploy the Jenkinsfile runs: verified chart and values, `helm upgrade --reset-values` on the existing release, never an install |
| `test/` | Unit tests of the chart pin consumer |

## The DA register

| | |
|---|---|
| Register mnemonic | `DA` |
| Tables | `g2p_register_das`, `g2p_register_history_das`, `g2p_intake_form_das` |
| DA-ID | `functional_record_id`, `DA-` + 10 digits, from the ID generator pool `da`, on approval |
| Fayda ID (FAN) | `foundational_id`, 16 digits (the number on the Fayda card, as in the farmer registry), required |
| Duplicate check | Fayda ID, exact match (shown to the approver) |
| Data in | Web intake form (one DA); file import, CSV or `.xlsx` (many DAs) |
| Data out | Partner API DCI search, each record under `da_details` (`templates/openg2p_da_to_dci.json.j2`) |

Fields, code lists and validation rules: see the design document
(`DA_Registry_Design_*.pdf`). The server-side rules are in
`register_domain/services/validation_rules.py` and apply to every entry path.

## Bulk import (CSV / Excel)

Staff portal > Development Agents > Create New Submission > Import from file >
DA Import. Start from `import-templates/DA_Import_Template.xlsx` (drop-downs and
a "How to fill" sheet) or `.csv` (UTF-8). Old `.xls` is not supported.

Each row goes through the platform's ingestion pipeline: the
`DAImportFileEnricherService` maps headers to fields, labels to codes and
Region / Zone / Woreda / Kebele names to the Master Data kebele;
`templates/import_file_to_openg2p_da.json.j2` splits it into the intake
sections; the row becomes an intake submission with Source `CSV_IMPORT`.
A row that cannot be used is rejected with a readable reason, recorded in
`incoming_classified_data` (`transformation_latest_error_code` /
`ingestion_latest_error_code`); the other rows carry on.

Approval of imports (`register_domain/services/import_approval_workflow.py` and
`awe_service_token.py`): a submission created without a signed-in user (file
import, partner ingestion) is sent to the approval workflow with a Keycloak
client-credentials token (`DA_AWE_TOKEN_URL` / `DA_AWE_CLIENT_ID` /
`DA_AWE_CLIENT_SECRET`, falling back to the process's Master Data client), so it
gets the same two-level approval as a web-form submission (stage 1, then stage
2, see `docs/rbac-registry-roles.md`). Only after the second approval does the
DA reach the register and get a DA-ID. Nothing is approved automatically, and
no role approves a submission or a change request directly: the staff
endpoints that would do so answer `AWE_APPROVAL_REQUIRED`
(`register_domain/services/direct_approval.py`); only the approval task decides.

A Development Agent's own record (`register_domain/services/da_own_record.py`):
a token with the claim `da_id` (Keycloak user attribute, client scope
`da-self-service`) whose only registry roles are the Development Agent ones is
limited to that one DA record: search, details, tab records and change-request
reads see only it, and a change request may target only it and only the
contact, service and location sections. See `docs/rbac-registry-roles.md` §5.

One DA per Fayda ID (`register_domain/services/fayda_uniqueness.py`): every save
of a DA record (web form, file import, DA Services push, change request) is
refused when its Fayda ID already belongs to an active DA or to another live
submission, with the reason ("Fayda ID … is already registered as DA-…"). The
record's own id is left out, so re-saving a section is not a duplicate. Rows of
one file that race each other are caught again at approval (the approver sees
the duplicate in the submission's deduplication results) and finally by the
unique index on active register rows.

## DA Services (Frappe) → registry

DA Services pushes each DA it has approved to the partner API
(`POST /partner/ingest_data?data_model=DA_SERVICES&...`); `DAServicesEnricherService`
maps its JSON to DA fields (location by Master Data `kebele_id` or names), and
the record goes through the same template, validation, duplicate guard and
two-level approval as a file import. The DA Services approver and record id are kept
(`upstream_approved_by`, `upstream_reference`). DA Services reads DAs back with
DCI search. Request format, field rules and open items:
[docs/da-services-api-contract.md](docs/da-services-api-contract.md).

## Run locally

Requires Docker with Compose v2.

```bash
docker compose up --build -d
```

Then open the staff portal at http://localhost:3101 and log in as `admin` /
`admin` (or `staff` / `staff`).

Host ports are chosen to run next to the Frappe DA Service and to avoid TCP
9000:

| Service | Port |
|---|---|
| Staff portal UI | 3101 |
| Staff API | 8101 |
| Partner API (DCI) | 8106 |
| Keycloak | 8090 |
| IAM | 8120 |
| AWE / AWE UI | 8130 / 8131 |
| Master data | 8142 |
| ID generator | 8050 |
| MinIO API / console | 9010 / 9011 |
| Postgres | 5442 |
| Redis | 6389 |

Seeding, in order: the geo-seed job loads the Ethiopia geo hierarchy into
Master Data; the codelist-seed job loads the dropdown code lists from the
openg2p-data pack (`packs/ETH-OAN`: `GENDER`, `MARITAL_STATUS`, `PREFIX` and the
`agriculture` domain's `DA_*` lists) into Master Data; db-seed loads the DA
metadata and AWE seed (configuration only), then the sample-data job loads the
pack's nine sample DAs (`samples/development_agents.json`; skip it with
`LOAD_SAMPLE_DATA=false`). All sample and reference data comes from the COSS
fork of [openg2p-data](https://github.com/Centre-for-Open-Societal-Systems/openg2p-data);
the two local-only jobs (`docker/local-dev/data-loaders`) clone it when they
are built (`OPENG2P_DATA_REF`, a commit SHA pinned in the Dockerfile and compose file, never a branch) and are not part of any
deployable image. Nothing is generated or hardcoded in this repo. No real
personal data is used. To seed from a local openg2p-data checkout (for example
while a data PR is open), point the jobs at it:

```bash
OPENG2P_DATA_PATH=/path/to/openg2p-data OPENG2P_DATA_DIR=/openg2p-data-local \
  docker compose run --rm da-registry-codelist-seed && \
OPENG2P_DATA_PATH=/path/to/openg2p-data OPENG2P_DATA_DIR=/openg2p-data-local \
  docker compose run --rm da-registry-sample-data
```

On a cluster the Master Data db-seed image (openg2p-data's
`docker/master-data-db-seed`, `PACK_LOAD=codelists`, `PACK_DOMAINS=agriculture`)
loads the lists; sample DAs are loaded from the same pack by openg2p-data's
own tooling, not by the registry's db-seed image.

Validation is metadata-driven: required fields are the form's `widget-required`
flags (checked on section save and before a submission can be finalized), and
coded fields are checked against the Master Data lists the widgets declare
(`REGISTRY_STAFF_PORTAL_API_VALIDATE_ATTRIBUTE_VALUES`; imports resolve codes,
displays or translations through `code_lists.py`). Adding a value to a list
or making a field optional is a change in openg2p-data / the register
metadata, not in Python.

Local-only settings in `docker-compose.yml`: Master Data is read from its
database (`*_MASTER_DATA_READ_MODE=db`), and DCI search skips partner signature
and consent checks (`REGISTRY_PARTNER_API_SIGNATURE_VALIDATION_ENABLED` /
`..._CONSENT_ENFORCEMENT_ENABLED=false`) because the stack has no Partner
Management or Consent Manager. Keep both checks on in deployments.

## Tests

The extension tests import the platform, so run them inside an image:

```bash
docker cp da-extension/tests da-registry-staff-api:/tmp/da-tests
docker exec -w /tmp da-registry-staff-api python -m unittest discover -s /tmp/da-tests -t /tmp
```

## Platform version

Platform images come from Docker Hub (`openg2p/openg2p-registry-*`), pinned to
`1.2.2-rc.557`, the same native release used by the refactored crop/livestock
registries. Keep the component Dockerfiles and chart dependency in step:

- `ARG RP_VERSION` in `docker/*/Dockerfile`
- `RP_VERSION` in the `Jenkinsfile`
- the upstream staff-ui source revision in `ui/staff-ui/deps.json`
- `platformVersion` in `ci/deploy/oan-chart.json`, which must equal the `openg2p-registry`
  dependency of the pinned oan-helm chart (CI checks the archive); moving it means a new
  oan-helm chart release and a new pin
- the Master Data image (`openg2p/master-data-api:1.1.0`) and the ID generator image
  (`openg2p/openg2p-id-generator:1.1.2`) in `docker-compose.yml`, as in the livestock registry.
  The 1.2 staff UI reads geo levels through Master Data's `/geo/*` API, which 1.1.0 has.
- Master Data access: on 1.2 the registry services read geo and code lists over the
  Master Data API with a client-credentials token (`*_MASTER_DATA_API_URL`, `_TOKEN_URL`,
  `_CLIENT_ID`, `_CLIENT_SECRET`; locally the `da-registry-backend` Keycloak client). Without
  it the staff form saves DAs with empty Region / Zone / Woreda / Kebele names. In Helm the
  subchart sets these from `global.masterDataApiUrl` and `global.pmSeedClientId`; the DA
  import enricher also reads the Master Data database, so the celery worker gets its
  `*_MASTER_DATA_DB_*` settings in `values.yaml`.

When the version moves, re-check:

- `da-extension/.../register_domain/temporary_platform_overrides.py`: the three
  temporary in-process workarounds (IAM permission lookup across registries,
  worker NullPool, DataPolicyMiddleware own-record policy); the platform image is not modified. Drop each one once
  OpenG2P fixes it in the pinned platform image.
