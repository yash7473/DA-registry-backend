# Follow-ups to fix or review later

Open items found while bringing the DA registry in line with the OpenG2P standards (29 October 2026). None of them blocks building and pushing the images; the dev deploy stays off (`DEPLOY_TO_DEV`, default false) until the open deployment items are done and the chart pin is filled in.

## Deployment (before turning the dev deploy on)

| Item | Status | What to do |
|---|---|---|
| Release target | Done by this change. The pipeline upgrades the existing release `da-registry` in namespace `da-registry` (never an install). | Nothing. |
| Chart and platform pin | Done by this change and oan-helm #39 and #41. The chart `openg2p-da-registry` 1.0.0-dev.18 is on registry-platform rc.557, the same as the images, with appVersion 1.2.2-rc.557; `ci/deploy/oan-chart.json` pins its archive and the dev values (oan-helm 5d01cdc) by SHA-256. | None. |
| Values | Done by this change and oan-helm #39. Public values are pinned in oan-helm (`environments/dev/values/da.yaml`) and applied with `--reset-values`; `deploy/dev/values-da.yaml` and the repository's chart copy are removed. | Nothing. |
| Keycloak client | Done by oan-helm #40. Imports and DA Services pushes take their approval token from `<release>-staff-portal`, the client the chart's keycloak-init already creates, with its Secret of the same name, as Crop Sown and Livestock do. No `da-registry-backend` client is needed. | None. |
| DA Services service account | A Development Agent's own profile is served by DA Services through a service account (`docs/rbac-registry-roles.md` §5); the registry no longer needs the `da-self-service` scope or the `da_id` attribute. | Create a confidential client with service accounts in realm `staff`, give its service-account user the client role Data Editor on `<release>-staff-portal`, hand the secret to DA Services. |
| Master Data lists | The form's dropdowns read `DA_EDUCATION_LEVEL`, `DA_SPECIALISATION`, `DA_POSITION`, `DA_SOURCE`. | Merge openg2p-data PR 22 and re-run the Master Data seed (`PACK_DOMAINS=agriculture`). |

## Sample data (decision of 29 October 2026) - done

`docker/db-seed/load_sample_data.py` again, run by the platform entrypoint only when `loadSampleData=true`, with the COSS openg2p-data fork baked into the db-seed image at a pinned commit (`OPENG2P_DATA_REF`). It submits each sample DA through the intake API (four section saves and finalize) with the registry client's service account, the settings the platform chart's db-seed job already sets (`STAFF_*`, `MDS_*`); it never signs in as an approver and never approves, so sample records wait for the approvers. A DA whose Fayda ID is already registered or in a live submission is skipped. The entrypoint seeds the AWE policies after the sample step, so the loader applies the same idempotent AWE seed files first. The client's service-account user needs the client role Intake Officer on the staff portal client. `load_codelists_mdm.py` stays local-only (`docker/local-dev/data-loaders`).

## Code to review

| Item | Note |
|---|---|
| Temporary platform overrides | One override kept by decision until OpenG2P fixes the platform, in `register_domain/temporary_platform_overrides.py`: IAM permissions per application (IAM 1.4.2 still looks a role up by name only). Raise each with OpenG2P and remove it once fixed; re-check on every platform upgrade (`docs/refactor/platform-overrides.md`). |
| Full-stack check | The service-token approval start for imports and the direct-approval refusal are covered by unit tests only. Run them once on a stack with Keycloak, the approval workflow engine and Postgres. |
| Package name | `openg2p_registry_da_extension` matches the OpenG2P docs. Spelling out `development_agent` would change the package, release, namespace and database; a candidate for a naming window only. |
