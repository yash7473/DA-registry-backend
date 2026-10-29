# DA registry: everything that touches the platform

Yash Sontakke · 28 October 2026 · registry-platform `1.2.2-rc.557`, branch `feature/da-on-refactor`

What Aruna asked for on 27 October: one list of every place where the DA
extension overrides, wraps or otherwise depends on the OpenG2P platform's
internals, so that a platform upgrade (or an upstream fix) tells us what to
re-check or remove. No platform image or file is patched; everything below
lives inside the extension (`da-extension/src/openg2p_registry_da_extension/`)
and is installed at start-up by `app.py`. Each entry is idempotent (a marker
stops a double install) and covered by a unit test that skips when the
platform is not importable.

How to use this file: on every platform version bump, run the extension's
tests inside the new images (section "Re-check on upgrade"), then walk the
table; when an upstream fix lands, delete the entry and its code.

## 1. Temporary overrides (kept on the user's decision of 29 Oct 2026)

Two live in `register_domain/temporary_platform_overrides.py`, installed by one call in `app.py`. Each has a docstring block with the bug, the platform version checked (1.2.2-rc.557), what breaks without it and "remove when OpenG2P fixes it". None of these classes is a registered component and none of the behaviours is a setting on rc.557, so there is no subclass or configuration alternative. The fourth, the DataPolicyMiddleware own-record policy, is row D3 below. (should go upstream, then be deleted)

The partner-API ingest reply (a `datetime` in the header made every `POST /partner/ingest_data` answer 500) is no longer worked around in code: every data model in `meta_data/data-models/data_models.sql` carries the DCI response template, which makes the platform serialise the reply.

Removed 29 Oct 2026: the celery worker NullPool engine (a 12-row import measured the same with and without it: all rows in approval in ~116 s, two `attached to a different loop` errors the platform retries; the error comes from elsewhere in the platform, to report upstream), and the FilterBuilder override for `"true"`/`"false"` strings. No DA filter is boolean (the register metadata and the platform define none), so it never applied.

| # | Where | Platform anchor | What it does | Why | Upstream status |
|---|---|---|---|---|---|
| P1 | `register_domain/temporary_platform_overrides.py` `install_scoped_permission_lookup` | `iam_core...ResolvePermissionMiddleware.dispatch` and `_fetch_permissions_for_roles` (wrapped) | resolves a user's permissions for this registry's own IAM application only (`/user-access/get_application_permissions_for_user?application_mnemonic=<client>`) | IAM matched role names across every registry on the shared Keycloak, so a farmer-registry role could grant DA permissions and vice versa | not reported yet |

## 2. DA behaviour the platform has no hook for (overrides by design; candidates for platform features)

| # | Where | Platform anchor | What it does | Why | If the platform changes |
|---|---|---|---|---|---|
| D1 | `register_domain/services/da_intake_guard.py` `install_da_intake_guard` | subclass of `G2PIntakeFormDataService`, instance inserted at the front of `openg2p_fastapi_common.context.component_registry`; overrides `save_intake_form_submission_with_session` and `finalize_submission_with_session`; uses `_get_section_or_error`, `_records_for_validation`, `_get_submission_or_error`, `_resolve_intake_form_class`, `_get_intake_rows`, `_get_form_sections`, `_build_section_payloads` | required fields (metadata `widget-required`) checked for a new record on save and for the whole submission on finalize | the platform validates only the fields a request carries and nothing at finalize; an empty submission reached the approvers | this is the pattern Asmit asked for (subclass ahead in the registry). Suggest upstream: run the required-widget check at finalize in the platform. If the private helpers are renamed, the subclass fails at call time; the unit test `test_required_fields.py::TestGuard` catches the override points |
| D2 | `register_domain/services/import_approval_workflow.py` `install_da_import_approval_workflow` | subclass of `G2PAweIntegrationService`, registered ahead of it in the component registry; overrides `start_intake_submission_workflow` | file imports and DA Services pushes (no user token) start the approval workflow with the worker's Keycloak service token (`awe_service_token.py`); nothing is approved automatically | the platform starts an approval only with a user's bearer token; unattended ingestion had none, so imports were silently left PENDING with no task | supported pattern (subclass ahead in the registry). Suggest upstream: a service-token path for unattended submissions. Align env names with the farmer extension's `REGISTRY_CELERY_WORKERS_AWE_*` |
| D3 | `register_domain/services/da_own_record.py` `install_da_own_record_guard` | `iam_core.user_auth.middleware.data_policy.DataPolicyMiddleware.dispatch` (wrapped, no hook; installed by `temporary_platform_overrides.py` `install_own_record_data_policy`) and a subclass of `G2PRegisterChangerequestControllerService` registered ahead of it (`create_change_request`) | a token with claim `da_id` (a Development Agent) sees and edits only their own record: a synthetic data policy `functional_record_id = da_id` on reads, and change requests only on that record and only in the contact / service / location sections | the platform's data policies are role-based lists, not per-user; no hook on change-request creation | the middleware wrap stays until the platform offers per-user (claim-based) data policies; the change-request check is a supported subclass |
| D3a | `register_domain/services/direct_approval.py`, `da_intake_guard.py` `DAIntakeFormDataService`, `da_change_request.py` `DAChangeRequestService` | subclasses of `G2PIntakeFormDataService` and `G2PRegisterChangeRequestService` registered ahead of the platform's; `approve_submission` and `approve_change_request` raise `AWE_APPROVAL_REQUIRED` | no role, the administrator included, approves a submission or a change request directly; only the approval task decides. The workflow paths (`approve_submission_with_session`, `approve_change_request_from_awe_webhook`, `_approve_change_request_core`) stay open | the platform exposes two staff endpoints that write to the register on one user's say-so, and every register change must go through the two-stage approval | supported pattern; same guard as the other OAN registries |
| D4 | `register_domain/services/g2p_register_domain_service_da.py` | `G2PRegisterDomainService` subclass registered through `G2PRegisterDomainFactory` (the platform's own extension point) | DA validation (Fayda FAN, phones, email, EC dates, one DA per Fayda, flattened geo names/codes) | normal extension code | supported hook; nothing to re-check beyond the tests |
| D5 | `ingestion_pipeline/enricher_services/` | `G2PPayloadEnricherInterface` (the platform's own extension point) | Excel/CSV rows and DA Services messages → DA fields | normal extension code | supported hook |

## 3. Platform internals read without wrapping (break only if the platform renames them)

| # | Where | What is used | Why |
|---|---|---|---|
| R1 | `ingestion_pipeline/enricher_services/code_lists.py` | `G2PAttributeValueValidator.field_map_from_ui_schema` (platform helper, public classmethod) and the Master Data tables `g2p_attributes` / `g2p_attribute_values` (read through the worker's Master Data DB settings when present, the Master Data API otherwise) | the list each dropdown uses and its values, so imports accept exactly what the form accepts |
| R2 | `ingestion_pipeline/enricher_services/g2p_da_enricher_services.py` `_MasterDataGeo` | Master Data tables `g2p_geo_levels` / `g2p_geo_level_values` read directly (worker DB settings) | Kebele lookup by name or id for imports. The platform's geo service looks units up by id only. Dev also configures the DB; if Master Data ever becomes API-only, switch this to the API like `code_lists.py` |
| R3 | `register_domain/services/required_fields.py` | model `G2PRegisterSection.section_ui_schema` and the widget keys `widget-required`, `widget-label`, `widget-data-path` | required fields from the metadata (single source for the UI and the server) |
| R4 | `partner_api/da_status_controller.py`, `register_domain/services/push_status.py`, `exceptions.py` | ingestion tables `incoming_raw_data`, `incoming_classified_data`, `incoming_enriched_transformed_data`, `g2p_intake_form_submissions` read by SQL | `GET /partner/da/status` and `/exceptions` for DA Services |
| R5 | `temporary_platform_overrides.py`, `da_own_record.py`, `import_approval_workflow.py` | `openg2p_registry_core.config.Settings` prefixes (`REGISTRY_STAFF_PORTAL_API_`, `REGISTRY_PARTNER_API_`, `REGISTRY_CELERY_WORKERS_`) and rc.557 setting names (`..._DCI_ALLOWED_SEARCH_FIELDS`, `..._VALIDATE_ATTRIBUTE_VALUES`, `..._AWE_*`, `..._MASTER_DATA_*`) | configuration; rc.544 → rc.557 already renamed one of them (`DCI_EXPRESSION_ALLOWED_FIELDS`) |
| R6 | `meta_data/`, `awe_meta_data/` seeds | platform tables and the register-metadata JSON shapes (`widget-data-source` type `api` / service `attributes`, `filter_schema`, `search_result_schema`), AWE tables `approval_policy` / `approval_stage` / `approver_rule` | configuration; every INSERT has `ON CONFLICT` so a re-seed on a new platform is safe |
| R7 | `ui/staff-ui/` | upstream staff-ui pinned by commit in `deps.json`; `overrides/` is empty | no UI override today. Known platform-UI issue, not fixed here: Next on a section with nothing entered makes no request but shows "Saved"; the server refuses the incomplete save/submit, so no bad data |

## 4. Re-check on upgrade

1. Bump `RP_VERSION` (Dockerfiles, `Jenkinsfile`, `ci/deploy/oan-chart.json` after the oan-helm chart release), build the images.
2. In each image run the extension tests: `python -m pytest /app/da-extension/tests` (staff-api runs all; partner-api `test_temporary_platform_overrides.py`, `test_push_status.py`, `test_code_lists.py`; worker `test_temporary_platform_overrides.py`, `test_awe_service_token.py`, `test_import_approval_workflow.py`, `test_direct_approval.py`, `test_import_enricher.py`, `test_da_services_enricher.py`, `test_code_lists.py`). A missing anchor fails or skips there.
3. Start the stack and read the start-up logs: each `install_*` logs once; `install_da_own_record_guard` raises if its anchor is gone.
4. Re-run the validation list in `pr8-validation-da.md` (form → two-stage approval → DA-ID; change request; search filters; partner push; DCI; import; UI).
5. For every entry in section 1, check the platform's release notes: if the bug is fixed, delete the override and its test.
