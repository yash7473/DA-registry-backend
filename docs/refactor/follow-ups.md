# Follow-ups to fix or review later

Open items found while bringing the DA registry in line with the OpenG2P standards (29 October 2026). None of them blocks building and pushing the images; the dev deploy stays off (`DEPLOY_TO_DEV`, default false) until the open deployment items are done and the chart pin is filled in.

## Deployment (before turning the dev deploy on)

| Item | Status | What to do |
|---|---|---|
| Release target | Done by this change. The pipeline upgrades the existing release `da-registry` in namespace `da-registry` (never an install). | Nothing. |
| Chart and platform pin | Done by this change and oan-helm #39 and #41. The chart `openg2p-da-registry` 1.0.0-dev.18 is on registry-platform rc.557, the same as the images, with appVersion 1.2.2-rc.557; `ci/deploy/oan-chart.json` pins its archive and the dev values (oan-helm 5d01cdc) by SHA-256. | None. |
| Values | Done by this change and oan-helm #39. Public values are pinned in oan-helm (`environments/dev/values/da.yaml`) and applied with `--reset-values`; `deploy/dev/values-da.yaml` and the repository's chart copy are removed. | Nothing. |
| Keycloak client | Done by oan-helm #40. Imports and DA Services pushes take their approval token from `<release>-staff-portal`, the client the chart's keycloak-init already creates, with its Secret of the same name, as Crop Sown and Livestock do. No `da-registry-backend` client is needed. | None. |
| Self-service scope | Scope `da-self-service` and attribute `da_id` in the `staff` realm are not created. | Create them before testing a Development Agent's own-record access. |
| Master Data lists | The form's dropdowns read `DA_EDUCATION_LEVEL`, `DA_SPECIALISATION`, `DA_POSITION`, `DA_SOURCE`. | Merge openg2p-data PR 22 and re-run the Master Data seed (`PACK_DOMAINS=agriculture`). |

## Sample data (decision of 29 October 2026)

The db-seed follows the OpenG2P standard exactly: the sample step is `docker/db-seed/load_sample_data.py`, run only when `loadSampleData=true`, and the data comes from our fork of openg2p-data at a pinned commit. A sample loader never approves records by signing in the demo approvers through Keycloak, never turns on direct access grants and never resets passwords; sample records wait for a person to approve them.

- The loader parked in `docs/refactor/moves-to-openg2p-data/` goes back to `docker/db-seed/load_sample_data.py`.
- It currently inserts DA records straight into the register tables. Rewrite it to submit through the intake API (as OpenG2P's reference loaders do) and leave approval to the approvers.
- `load_codelists_mdm.py` is local-only (the dev Master Data is seeded by its own db-seed); keep it out of the deployable image.

## Code to review

| Item | Note |
|---|---|
| Master Data read from its database | `code_lists.py` and the geo lookup read Master Data's Postgres when `REGISTRY_CELERY_WORKERS_MASTER_DATA_DB_*` is set. The standard is the Master Data API (`/attributes/get_attribute_values`, already supported here). Move the import path to the API and drop the database read mode. |
| Temporary platform overrides | Three overrides kept by decision until OpenG2P fixes the platform, in `register_domain/temporary_platform_overrides.py`: IAM permissions per application, worker database pool, a Development Agent seeing only their own record. Raise each with OpenG2P and remove it once fixed; re-check on every platform upgrade (`docs/refactor/platform-overrides.md`). |
| Full-stack check | The service-token approval start for imports and the direct-approval refusal are covered by unit tests only. Run them once on a stack with Keycloak, the approval workflow engine and Postgres. |
| Package name | `openg2p_registry_da_extension` matches the OpenG2P docs. Spelling out `development_agent` would change the package, release, namespace and database; a candidate for a naming window only. |
