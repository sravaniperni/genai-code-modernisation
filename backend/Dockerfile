# syntax=docker/dockerfile:1.7
# Image for the API server and task workers.
#   docker build -t modernisation-backend backend/
# Options:
#   --build-arg BASE_REGISTRY=mirror.gcr.io/library      when Docker Hub rate-limits anonymous pulls
#   --secret id=ca_bundle,src=/path/to/ca.pem             trust an extra CA (TLS-intercepting corporate proxy)
#   --build-arg APT_HTTPS=1                               use HTTPS Debian mirrors (proxies that only allow CONNECT)
ARG BASE_REGISTRY=docker.io/library

FROM ${BASE_REGISTRY}/python:3.12-slim AS build
ARG HTTPS_PROXY
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=secret,id=ca_bundle,required=false \
    if [ -f /run/secrets/ca_bundle ]; then export PIP_CERT=/run/secrets/ca_bundle SSL_CERT_FILE=/run/secrets/ca_bundle; fi \
 && pip install --no-cache-dir "uv==0.11.*" \
 && uv sync --frozen --no-dev --no-install-project

FROM ${BASE_REGISTRY}/python:3.12-slim
ARG HTTPS_PROXY
ARG APT_HTTPS=0
# git: repository mirrors and workspaces; bubblewrap: sandbox for untrusted repository code
RUN --mount=type=secret,id=ca_bundle,required=false \
    if [ -f /run/secrets/ca_bundle ]; then cp /run/secrets/ca_bundle /usr/local/share/ca-certificates/extra-ca.crt \
       && update-ca-certificates >/dev/null; fi \
 && if [ "$APT_HTTPS" = "1" ]; then sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources; fi \
 && apt-get update \
 && apt-get install -y --no-install-recommends git bubblewrap ca-certificates \
 && rm -rf /var/lib/apt/lists/* /usr/local/share/ca-certificates/extra-ca.crt \
 && update-ca-certificates --fresh >/dev/null \
 && groupadd --system --gid 9100 modsandbox \
 && useradd --system --uid 9100 --gid 9100 --no-create-home --shell /usr/sbin/nologin modsandbox \
 && groupadd --system --gid 10001 modernisation \
 && useradd --system --uid 10001 --gid 10001 --home /app --shell /usr/sbin/nologin modernisation \
 && mkdir -p /data && chown modernisation:modernisation /data && chmod 755 /data
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    MODERNISATION_DATA_DIR=/data \
    MODERNISATION_SANDBOX_PYTHON=/usr/local/bin/python3.12
EXPOSE 8000
# The API runs unprivileged. Workers override the user with root (see docker-compose.yml) because they must
# drop to the dedicated sandbox uid before entering bubblewrap; the container itself is not privileged.
USER modernisation
CMD ["python", "-m", "modernisation.cli", "api", "--host", "0.0.0.0", "--port", "8000"]
