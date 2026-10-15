# syntax=docker/dockerfile:1.7
# Static build of the dashboard served by nginx, which also proxies /api to the backend service.
#   docker build -t modernisation-frontend frontend/
#   --build-arg BASE_REGISTRY=mirror.gcr.io/library  when Docker Hub rate-limits anonymous pulls
#   --secret id=ca_bundle,src=/path/ca.pem            trust an extra CA (TLS-intercepting proxy)
ARG BASE_REGISTRY=docker.io/library

FROM ${BASE_REGISTRY}/node:22-alpine AS build
ARG HTTPS_PROXY
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=secret,id=ca_bundle,required=false \
    if [ -f /run/secrets/ca_bundle ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/ca_bundle; fi \
 && npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM ${BASE_REGISTRY}/nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
