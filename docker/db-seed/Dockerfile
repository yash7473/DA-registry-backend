# Native registry seeding with the DA extension's configuration.
#
# The image is the platform's db-seed with the DA extension's metadata, AWE
# policies and templates in place of the reference extension's, plus the DA
# variant's sample loader (load_sample_data.py), which the native entrypoint
# runs only when LOAD_SAMPLE_DATA=true (dbSeed.loadSampleData). The loader
# submits the pack's sample DAs through the intake API; it generates nothing.
# All data (geography, code lists, sample people and DAs) lives in
# openg2p-data: the COSS fork at a pinned commit replaces the upstream copy
# the base image carries (OPENG2P_DATA_REF is a commit SHA, never a branch).
ARG RP_VERSION=1.2.2-rc.557
FROM openg2p/openg2p-registry-db-seed:${RP_VERSION}
ARG OPENG2P_DATA_REPO=https://github.com/Centre-for-Open-Societal-Systems/openg2p-data.git
ARG OPENG2P_DATA_REF=dc7e7bf69087b4684a3608fdd4bf98100aab77a8
RUN rm -rf /openg2p-data \
 && mkdir /openg2p-data && cd /openg2p-data \
 && git init -q \
 && git fetch -q --depth 1 "${OPENG2P_DATA_REPO}" "${OPENG2P_DATA_REF}" \
 && git checkout -q FETCH_HEAD \
 && rm -rf .git
RUN rm -rf /seed/meta_data/* /seed/awe_meta_data/* /seed/templates/* /seed/seed-data/*
COPY da-extension/src/openg2p_registry_da_extension/meta_data/ /seed/meta_data/
COPY da-extension/src/openg2p_registry_da_extension/awe_meta_data/ /seed/awe_meta_data/
COPY da-extension/src/openg2p_registry_da_extension/templates/ /seed/templates/
COPY docker/db-seed/load_sample_data.py /seed/load_sample_data.py
ENTRYPOINT ["/seed/entrypoint.sh"]
