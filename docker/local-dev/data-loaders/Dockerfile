# LOCAL DEVELOPMENT ONLY. Not built by the Jenkinsfile and not part of any
# deployable image.
#
# Loads reference data into the local compose stack: the code lists into the
# local Master Data database (the sample Development Agents are submitted by
# the db-seed image's load_sample_data.py). On a cluster this is done by the Master Data db-seed image and
# by openg2p-data; the loaders here are the copies that are to move to
# openg2p-data (docs/refactor/moves-to-openg2p-data/README.md).
#
# The data is the COSS openg2p-data fork at a pinned commit (OPENG2P_DATA_REF
# is a commit SHA, never a branch), or a local checkout mounted by
# OPENG2P_DATA_PATH (see docker-compose.yml).
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
COPY docs/refactor/moves-to-openg2p-data/load_codelists_mdm.py /local/load_codelists_mdm.py
