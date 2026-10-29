# Moves to openg2p-data

These files are data and loaders. (`load_sample_data.py` is back in `docker/db-seed/`: it submits the pack's sample DAs through the intake API, see `docs/refactor/follow-ups.md`.) They belong in
[openg2p-data](https://github.com/Centre-for-Open-Societal-Systems/openg2p-data)
and are no longer run by any DA image: `docker/db-seed/Dockerfile` copies the
extension's configuration only (`meta_data`, `awe_meta_data`, `templates`).

| File | What it does | Goes to openg2p-data as |
| --- | --- | --- |
| `load_codelists_mdm.py` | upserts the pack's code lists (`packs/<PACK>/codelists`, the `agriculture` domain's `DA_*` lists) into a Master Data database | already covered on clusters by the Master Data db-seed (`PACK_LOAD=codelists`); only the local compose stack needs this copy |
| `seed-data/geo/` | the earlier Ethiopia geo hierarchy JSON that `LOAD_GEO_DATA` read | superseded by the pack's geography; delete once the local stack uses the pack |

Until they move, the local compose stack runs them through
`docker/local-dev/data-loaders/` (a local-only image, never pushed). The
Jenkins build and the Helm chart do not use them.
