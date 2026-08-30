#!/bin/sh

set -eu

: "${GRAFANA_PREVIOUS_IMAGE:?GRAFANA_PREVIOUS_IMAGE is required}"
: "${GRAFANA_CURRENT_IMAGE:?GRAFANA_CURRENT_IMAGE is required}"
: "${GRAFANA_PREVIOUS_VERSION:?GRAFANA_PREVIOUS_VERSION is required}"
: "${GRAFANA_CURRENT_VERSION:?GRAFANA_CURRENT_VERSION is required}"

previous_container="pipelens-grafana-upgrade-previous"
current_container="pipelens-grafana-upgrade-current"
grafana_volume="pipelens-grafana-upgrade-data"
grafana_port="53001"
admin_user="pipelens-upgrade-admin"
admin_password="pipelens-upgrade-password"

assert_container_absent() {
    if docker container inspect "$1" >/dev/null 2>&1; then
        echo "refusing to replace existing container: $1" >&2
        exit 1
    fi
}

assert_volume_absent() {
    if docker volume inspect "$1" >/dev/null 2>&1; then
        echo "refusing to replace existing volume: $1" >&2
        exit 1
    fi
}

wait_for_grafana() {
    expected_version="$1"
    for attempt in $(seq 1 60); do
        if health="$(curl --silent --show-error --fail \
                "http://127.0.0.1:$grafana_port/api/health" 2>/dev/null)" \
            && HEALTH="$health" EXPECTED_VERSION="$expected_version" python -c '
import json
import os

health = json.loads(os.environ["HEALTH"])
assert health["database"] == "ok", health
assert health["version"] == os.environ["EXPECTED_VERSION"], health
'; then
            return 0
        fi
        sleep 1
    done
    return 1
}

start_grafana() {
    container="$1"
    image="$2"
    docker run --detach --name "$container" \
        --publish "$grafana_port:3000" \
        --env GF_SECURITY_ADMIN_USER="$admin_user" \
        --env GF_SECURITY_ADMIN_PASSWORD="$admin_password" \
        --env GF_AUTH_ANONYMOUS_ENABLED=true \
        --env GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer \
        --env GF_AUTH_DISABLE_LOGIN_FORM=true \
        --env GF_ANALYTICS_REPORTING_ENABLED=false \
        --env GF_ANALYTICS_CHECK_FOR_UPDATES=false \
        --mount "type=volume,source=$grafana_volume,target=/var/lib/grafana" \
        --mount "type=bind,source=$PWD/ops/grafana/provisioning,target=/etc/grafana/provisioning,readonly" \
        --mount "type=bind,source=$PWD/ops/grafana/dashboards,target=/var/lib/grafana/dashboards,readonly" \
        "$image" >/dev/null
}

validate_dashboard() {
    uid="$1"
    expected_title="$2"
    expected_panels="$3"
    for attempt in $(seq 1 30); do
        if dashboard="$(curl --silent --show-error --fail \
                "http://127.0.0.1:$grafana_port/api/dashboards/uid/$uid" 2>/dev/null)" \
            && DASHBOARD="$dashboard" EXPECTED_TITLE="$expected_title" \
                EXPECTED_PANELS="$expected_panels" python -c '
import json
import os

response = json.loads(os.environ["DASHBOARD"])
dashboard = response["dashboard"]
assert dashboard["title"] == os.environ["EXPECTED_TITLE"], dashboard
assert len(dashboard.get("panels", [])) == int(os.environ["EXPECTED_PANELS"]), dashboard
'; then
            return 0
        fi
        sleep 1
    done
    return 1
}

cleanup() {
    if docker container inspect "$current_container" >/dev/null 2>&1; then
        docker rm --force "$current_container" >/dev/null
    fi
    if docker container inspect "$previous_container" >/dev/null 2>&1; then
        docker rm --force "$previous_container" >/dev/null
    fi
    if docker volume inspect "$grafana_volume" >/dev/null 2>&1; then
        docker volume rm "$grafana_volume" >/dev/null
    fi
}

assert_container_absent "$previous_container"
assert_container_absent "$current_container"
assert_volume_absent "$grafana_volume"
trap cleanup EXIT INT TERM

docker pull "$GRAFANA_PREVIOUS_IMAGE"
docker pull "$GRAFANA_CURRENT_IMAGE"
docker volume create "$grafana_volume" >/dev/null

start_grafana "$previous_container" "$GRAFANA_PREVIOUS_IMAGE"
if ! wait_for_grafana "$GRAFANA_PREVIOUS_VERSION"; then
    docker logs "$previous_container"
    exit 1
fi
validate_dashboard "pipelens-operations" "PipeLens Operations" 8

curl --silent --show-error --fail \
    --user "$admin_user:$admin_password" \
    --header "Content-Type: application/json" \
    --data '{"dashboard":{"id":null,"uid":"grafana-upgrade-probe","title":"Grafana upgrade probe","schemaVersion":41,"version":0,"panels":[]},"overwrite":false}' \
    "http://127.0.0.1:$grafana_port/api/dashboards/db" >/dev/null
validate_dashboard "grafana-upgrade-probe" "Grafana upgrade probe" 0

docker rm --force "$previous_container" >/dev/null
start_grafana "$current_container" "$GRAFANA_CURRENT_IMAGE"
if ! wait_for_grafana "$GRAFANA_CURRENT_VERSION"; then
    docker logs "$current_container"
    exit 1
fi

validate_dashboard "grafana-upgrade-probe" "Grafana upgrade probe" 0
validate_dashboard "pipelens-operations" "PipeLens Operations" 8

datasource="$(curl --silent --show-error --fail \
    "http://127.0.0.1:$grafana_port/api/datasources/uid/prometheus")"
DATASOURCE="$datasource" python -c '
import json
import os

datasource = json.loads(os.environ["DATASOURCE"])
assert datasource["uid"] == "prometheus", datasource
assert datasource["type"] == "prometheus", datasource
assert datasource["url"] == "http://prometheus:9090", datasource
'
