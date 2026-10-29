# DA Services roles in the DA registry

This page covers what a DA Services user can do in the DA registry staff API,
and which DAs they can see.

- **What they can do** comes from registry roles. These are Keycloak client
  roles on `da-registry-staff-portal`.
- **Which DAs they see** comes from data policies. A data policy is a filter on
  DA records, held as a client role `DP_<mnemonic>`.

## 1. Roles

Each DA Services role is a Keycloak group in the `staff` realm. A user joins the
group of their role, and the group carries the registry roles.
`docker/local-dev/keycloak-init.sh` creates these groups on the local stack.

| DA Services role (group) | Registry roles |
|---|---|
| `DA Services - Development Agent` | Data Editor |
| `DA Services - Supervisor` | Intake Officer, Intake Validator, Data Editor, Data Validator, Data Supervisor |
| `DA Services - Executive` | Data Supervisor |
| `DA Services - OAN Administrator` | Operations Administrator + all Supervisor roles |
| `DA Services - Communications Officer` | none (no registry access) |

These are the staff API calls DA Services uses, with the permission each one
needs:

| Staff API call | Permission |
|---|---|
| `register-data/search_in_a_register`, `get_subject_record` | `register:view` |
| `intake-form-data/save_intake_form_submission`, `finalize_...`, `search_in_intake_form_submissions` | `intakeSubmission:edit` |
| `change-requests/create_change_request` | `changeRequest:create` |
| `change-requests/search_in_change_request` | `changeRequest:view` |
| `register-data/get_export_queue_records` (the register list screen polls it) | `register:export` |

### Who approves a DA

Every submitted DA and every change request goes through the platform's
two-level approval: Stage 1 Officers, then Stage 2 Officers. Each stage is
completed by any one of its approvers (mode `any-n`, one decision). The
repository seeds the same approvers in every OAN registry (`awe_meta_data/`):
Stage 1 = `alex.carter` or `admin`, Stage 2 = `nina.patel` or `admin`; the two
officers are created by `docker/local-dev/keycloak-init.sh`.

Who approves in a real environment is configuration, not code (decision of
27-28 Oct 2026, Faiz / Asmit): after deployment an administrator edits the
two DA policies in the AWE admin portal and replaces the example users, for
instance with a `role` rule (a Keycloak client role such as Operations
Administrator or Intake Validator on `da-registry-staff-portal`; AWE's service
account needs `view-users` and `view-clients`) or with named users. Routing a
Woreda's submissions to its own supervisor is the same kind of
configuration once the approver roles exist per Woreda.

Bulk import (file) and the DA Services push go through the same two stages.
The worker has no user token, so it opens the approval request with a Keycloak
client-credentials token (`DA_AWE_TOKEN_URL`, `DA_AWE_CLIENT_ID`,
`DA_AWE_CLIENT_SECRET`; by default the process's Master Data client
`da-registry-backend`), see `register_domain/services/awe_service_token.py`.
Imports are approved manually, like every other record; no setting approves
them automatically, and no role (the Operations Administrator included)
approves a submission or a change request directly: the direct-approval
endpoints answer `AWE_APPROVAL_REQUIRED`. Decision (23 Oct 2026, Faiz and
Shikha).

## 3. Local test result (16 Oct 2026)

The local stack had 604 DAs. Test users were put one per group; the Supervisor
was scoped to Woreda ET010101 and the Executive to Region ET04.

| User | Search DAs | DA in ET010101 | DA in ET040301 | Submissions | Start form | Change requests |
|---|---|---|---|---|---|---|
| Development Agent | 604 | allow | allow | 403 | 403 | allow |
| Supervisor (ET010101) | 43 | allow | REG-ERR-012 | 58 of 588 | allow | 4 (all in ET010101) |
| Executive (ET04) | 109 | REG-ERR-012 | allow | 403 | 403 | 0 |
| OAN Administrator | 604 | allow | allow | 588 | allow | 4 |
| Communications Officer | 403 | 403 | 403 | 403 | 403 | 403 |

## 4. Limits and open points

- **A Development Agent does not sign in to the registry.** DA Services
  serves a DA their own profile through its service account (section 5). The
  `DA Services - Development Agent` group is for staff who act as a DA in the
  registry portal, not for the DAs themselves; a DA user with only Data
  Editor would see every DA.
- **Login:** these roles work with a staff Keycloak token. How DA Services
  users sign in (OAN auth service or Keycloak) is still open.
- **Approver routing:** who approves a Woreda's submissions is the approval
  workflow's job, not the data policies'.
- A Woreda code is unique, but Woreda names are not (23 names repeat). Always
  scope by code.

## 5. A Development Agent's own profile (self-service through DA Services)

Requirement (Shikha, 7 Oct 2026): a DA may update their own profile; the change
is approved in the registry by the same approval as any other. Architecture
(Faiz, 7 Oct 2026): DA Services wraps the registry's staff API, it does not
copy the data.

A DA signs in to **DA Services only**, never to the registry. DA Services
knows which DA the signed-in user is (its own user ↔ DA-ID mapping) and calls
the registry **server to server with its service account**:

| Step | Staff API call | Note |
|---|---|---|
| Find the DA | `POST /register-data/search_in_a_register` with `search_text` = the DA-ID | keep only the item whose `functional_record_id` equals the DA-ID (`search_text` is partial) |
| Show the profile | `POST /register-data/get_tab_records` (`da_details_tab`) | |
| Request a change | `POST /change-requests/create_change_request` on that record | DA Services allows only the contact (`da_contact_section_04`), service (`da_service_section_02`) and location (`da_location_section_03`) sections; never identity (name, Fayda ID) |
| Show the status | `POST /change-requests/get_change_request` | `PENDING` until both approval stages decide |

- **Service account:** a confidential Keycloak client in realm `staff` with
  service accounts on (local: `da-services-backend`, secret
  `dev-da-services-secret`, created by `keycloak-init.sh`); its service-account
  user gets the client role `Data Editor` on `da-registry-staff-portal`
  (view the register, create and view change requests, nothing else; it cannot
  approve). Token: `POST /realms/staff/protocol/openid-connect/token` with
  `grant_type=client_credentials`.
- **Who may see or change which record is DA Services' rule**, not the
  registry's: the registry trusts the service account, so DA Services must
  never pass a DA-ID the signed-in user does not own. The registry records the
  change request as created by the service (`created_by`), so DA Services keeps
  its own log of which DA asked.
- **Approval** is unchanged: two stages in the approval workflow, approvers as
  configured in AWE (section 2). The DA cannot approve their own change.

Verified locally (29 Oct 2026, `da_services_selfservice_probe.py`): the
service-account token found one DA by DA-ID, read its details tab, created a
phone change request; admin approved stage 1 and stage 2; the register showed
the new phone number.

Earlier design, removed on 29 Oct 2026: the DA signed in to the registry with a
Keycloak attribute `da_id` and the registry limited that token to one record
through an override of the platform's data-policy middleware. It needed a
platform override and a Keycloak scope per realm; enforcing it in DA Services
needs neither.
