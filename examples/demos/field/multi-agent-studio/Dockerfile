# syntax=docker/dockerfile:1

# SPDX-License-Identifier: Apache-2.0

FROM ghcr.io/nvidia/openshell/gateway@sha256:bdb4fe248070032c88be78f029dad9325cb698480e90486e1413a674a5d8edc8 AS gateway
FROM rust:1.96.1-slim-trixie@sha256:31ee7fc65186be7e0e0ccb3f2ca305f14e4739e7642a1ae65753aa5d7b874523 AS switchyard
RUN apt-get update && apt-get install -y --no-install-recommends cmake make \
    && rm -rf /var/lib/apt/lists/*
RUN cargo install --locked switchyard-server --version 0.3.0
FROM debian:trixie-slim@sha256:a99cfc517144bc59b1978475ec53b46ecabec7e43635402ee5b77cc54cd1b20a AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates python3 curl openssh-client rsync poppler-utils tini \
    && rm -rf /var/lib/apt/lists/*
COPY --from=gateway /usr/local/bin/openshell-gateway /usr/local/bin/openshell-gateway
COPY --from=switchyard /usr/local/cargo/bin/switchyard-server /usr/local/bin/switchyard-server
COPY docker/runtime-lock.json docker/install_runtime.py /opt/bac/build/
ARG TARGETARCH
RUN python3 /opt/bac/build/install_runtime.py "$TARGETARCH"
ENV PATH="/opt/bac/runtime/node/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
COPY docker/runtime/package*.json /opt/bac/runtime/package/
RUN cd /opt/bac/runtime/package && npm ci --omit=dev --no-audit --no-fund && npm cache clean --force
RUN groupadd --gid 10001 bac && useradd --uid 10001 --gid bac --home-dir /var/lib/bac/home --no-create-home bac

COPY Dockerfile /opt/bac/source/Dockerfile
COPY docker/ /opt/bac/source/docker/
COPY docker/bootstrap.py /opt/bac/bootstrap.py
RUN python3 /opt/bac/bootstrap.py --stamp && rm -rf /opt/bac/source \
    && mkdir -p /opt/bac/app && chown 10001:10001 /opt/bac/app
ENV BAC_CONTAINER=1 BAC_DATA_DIR=/var/lib/bac \
    BAC_OPENCLAW_PORT=28689 BAC_OPENSHELL_PORT=28680 BAC_OPENSHELL_HEALTH_PORT=28681 \
    HOME=/var/lib/bac/home XDG_CONFIG_HOME=/var/lib/bac/home/.config \
    XDG_DATA_HOME=/var/lib/bac/home/.local/share OPENSHELL_GATEWAY=bac-demo \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /opt/bac/app
COPY LICENSE ./
USER 10001:10001
ENTRYPOINT ["/usr/bin/tini", "--", "python3", "/opt/bac/bootstrap.py"]
CMD ["serve"]

FROM runtime AS app
USER 0
LABEL org.opencontainers.image.title="Multi-Agent Studio" \
      com.nvidia.bac.component="studio"
WORKDIR /opt/bac/app
COPY scripts/ scripts/
COPY src/ src/
COPY skills/ skills/
COPY runtime/research-guard/ runtime/research-guard/
COPY docker/ docker/
COPY Dockerfile Dockerfile
COPY README.md VERSION RELEASE_NOTES.md api.json.example ./
COPY scenario/ scenario/

RUN mkdir -p app && python3 scripts/build.py
USER 10001:10001
ENTRYPOINT ["/usr/bin/tini", "--", "python3", "/opt/bac/app/scripts/container_runtime.py"]
CMD ["serve"]

FROM runtime AS release
LABEL org.opencontainers.image.title="Multi-Agent Studio" \
      com.nvidia.bac.component="studio"
