#!/bin/sh

set -eu

: "${POSTGRES_IMAGE:?POSTGRES_IMAGE is required}"
: "${GRAFANA_IMAGE:?GRAFANA_IMAGE is required}"
: "${GRAFANA_VERSION:?GRAFANA_VERSION is required}"

python_bin="${PYTHON_BIN:-python}"
postgres_container="pipelens-recovery-smoke-postgres-source"
postgres_volume="pipelens-recovery-smoke-postgres-source-data"
grafana_container="pipelens-recovery-smoke-grafana-source"
grafana_volume="pipelens-recovery-smoke-grafana-source-data"
database="pipelens_recovery_smoke"
database_user="pipelens"
database_password="pipelens-recovery-smoke-password"
grafana_admin_user="pipelens-recovery-admin"
grafana_admin_password="pipelens-recovery-smoke-password"
source_revision="ci-$(git rev-parse --short HEAD)"
smoke_dir=""

POSTGRES_IMAGE="$POSTGRES_IMAGE" GRAFANA_IMAGE="$GRAFANA_IMAGE" \
    GRAFANA_VERSION="$GRAFANA_VERSION" "$python_bin" -c '
import os
import re

checks = (
    ("POSTGRES_IMAGE", r"postgres:[^@\s]+@sha256:[0-9a-f]{64}"),
    ("GRAFANA_IMAGE", r"grafana/grafana:[^@\s]+@sha256:[0-9a-f]{64}"),
    ("GRAFANA_VERSION", r"[0-9]+\.[0-9]+\.[0-9]+"),
)
for name, pattern in checks:
    if re.fullmatch(pattern, os.environ[name]) is None:
        raise SystemExit(f"{name} has an unsafe or unsupported format")
'

assert_absent() {
    kind="$1"
    name="$2"
    if docker "$kind" inspect "$name" >/dev/null 2>&1; then
        echo "refusing to replace existing Docker $kind: $name" >&2
        exit 1
    fi
}

remove_container() {
    name="$1"
    if docker container inspect "$name" >/dev/null 2>&1; then
        docker rm --force "$name" >/dev/null
    fi
}

remove_volume() {
    name="$1"
    if docker volume inspect "$name" >/dev/null 2>&1; then
        docker volume rm "$name" >/dev/null
    fi
}

cleanup() {
    remove_container "$grafana_container"
    remove_container "$postgres_container"
    remove_volume "$grafana_volume"
    remove_volume "$postgres_volume"
    if test -n "$smoke_dir" && test -d "$smoke_dir"; then
        rm -rf "$smoke_dir"
    fi
}

wait_for_postgres() {
    for attempt in $(seq 1 60); do
        if docker exec "$postgres_container" \
                pg_isready -U "$database_user" -d "$database" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    docker logs "$postgres_container"
    return 1
}

wait_for_grafana() {
    origin="$1"
    for attempt in $(seq 1 60); do
        if health="$(curl --silent --show-error --fail "$origin/api/health" 2>/dev/null)" \
            && HEALTH="$health" EXPECTED_VERSION="$GRAFANA_VERSION" "$python_bin" -c '
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
    docker logs "$grafana_container"
    return 1
}

timestamp_pair() {
    "$python_bin" -c '
from datetime import UTC, datetime, timedelta

now = datetime.now(UTC)
print((now - timedelta(seconds=2)).isoformat())
print((now - timedelta(seconds=1)).isoformat())
'
}

assert_absent container "$postgres_container"
assert_absent volume "$postgres_volume"
assert_absent container "$grafana_container"
assert_absent volume "$grafana_volume"
smoke_dir="$(mktemp -d)"
trap cleanup EXIT INT TERM
umask 077
printf '%s\n' "$database_password" >"$smoke_dir/postgres-password"
printf '%s\n' "$grafana_admin_password" >"$smoke_dir/grafana-password"

docker pull "$POSTGRES_IMAGE" >/dev/null
docker volume create "$postgres_volume" >/dev/null
docker run --detach --name "$postgres_container" \
    --publish 127.0.0.1::5432 \
    --env POSTGRES_DB="$database" \
    --env POSTGRES_USER="$database_user" \
    --env POSTGRES_PASSWORD="$database_password" \
    --mount "type=volume,source=$postgres_volume,target=/var/lib/postgresql" \
    "$POSTGRES_IMAGE" >/dev/null
wait_for_postgres
postgres_port="$(docker port "$postgres_container" 5432/tcp | sed 's/.*://')"
PIPELENS_DATABASE_URL="postgresql+psycopg://$database_user:$database_password@127.0.0.1:$postgres_port/$database" \
    "$python_bin" -m alembic upgrade head >/dev/null
docker exec "$postgres_container" psql --username "$database_user" --dbname "$database" \
    --set ON_ERROR_STOP=1 \
    --command "CREATE TABLE recovery_smoke_probe (value text PRIMARY KEY); INSERT INTO recovery_smoke_probe VALUES ('restored');" \
    >/dev/null
docker exec "$postgres_container" pg_dump --username "$database_user" --dbname "$database" \
    --format custom --file /tmp/pipelens-recovery-smoke.dump
docker cp "$postgres_container:/tmp/pipelens-recovery-smoke.dump" \
    "$smoke_dir/postgres.dump"
remove_container "$postgres_container"
remove_volume "$postgres_volume"
set -- $(timestamp_pair)
postgres_freeze_at="$1"
postgres_backup_at="$2"
"$python_bin" ops/postgres/verify_restore.py \
    --image "$POSTGRES_IMAGE" \
    --backup "$smoke_dir/postgres.dump" \
    --password-file "$smoke_dir/postgres-password" \
    --database "$database" \
    --database-user "$database_user" \
    --source-revision "$source_revision" \
    --write-freeze-at "$postgres_freeze_at" \
    --backup-created-at "$postgres_backup_at" \
    --backup-duration-seconds 1 \
    --rto-seconds 120 \
    --rpo-seconds 60 \
    --observed-rpo-seconds 1 \
    --expect-min-count recovery_smoke_probe=1 \
    --run-id live-smoke \
    --output "$smoke_dir/postgres-evidence.json" >/dev/null

docker pull "$GRAFANA_IMAGE" >/dev/null
docker volume create "$grafana_volume" >/dev/null
docker run --detach --name "$grafana_container" \
    --publish 127.0.0.1::3000 \
    --env GF_SECURITY_ADMIN_USER="$grafana_admin_user" \
    --env GF_SECURITY_ADMIN_PASSWORD="$grafana_admin_password" \
    --env GF_AUTH_ANONYMOUS_ENABLED=true \
    --env GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer \
    --env GF_AUTH_DISABLE_LOGIN_FORM=true \
    --env GF_ANALYTICS_REPORTING_ENABLED=false \
    --env GF_ANALYTICS_CHECK_FOR_UPDATES=false \
    --mount "type=volume,source=$grafana_volume,target=/var/lib/grafana" \
    --mount "type=bind,source=$PWD/ops/grafana/provisioning,target=/etc/grafana/provisioning,readonly" \
    --mount "type=bind,source=$PWD/ops/grafana/dashboards,target=/var/lib/grafana/dashboards,readonly" \
    "$GRAFANA_IMAGE" >/dev/null
grafana_port="$(docker port "$grafana_container" 3000/tcp | sed 's/.*://')"
grafana_origin="http://127.0.0.1:$grafana_port"
wait_for_grafana "$grafana_origin"
curl --silent --show-error --fail \
    --user "$grafana_admin_user:$grafana_admin_password" \
    --header 'Content-Type: application/json' \
    --data '{"uid":"recovery-smoke-folder","title":"Recovery Smoke"}' \
    "$grafana_origin/api/folders" >/dev/null
curl --silent --show-error --fail \
    --user "$grafana_admin_user:$grafana_admin_password" \
    --header 'Content-Type: application/json' \
    --data '{"dashboard":{"id":null,"uid":"recovery-smoke-dashboard","title":"Recovery Smoke Dashboard","schemaVersion":41,"version":0,"panels":[]},"folderUid":"recovery-smoke-folder","overwrite":false}' \
    "$grafana_origin/api/dashboards/db" >/dev/null
remove_container "$grafana_container"
docker run --rm --user 0 --entrypoint tar \
    --mount "type=volume,source=$grafana_volume,target=/source,readonly" \
    --mount "type=bind,source=$smoke_dir,target=/backup" \
    "$GRAFANA_IMAGE" -czf /backup/grafana-data.tgz -C /source .
remove_volume "$grafana_volume"
set -- $(timestamp_pair)
grafana_freeze_at="$1"
grafana_backup_at="$2"
"$python_bin" ops/grafana/verify_restore.py \
    --image "$GRAFANA_IMAGE" \
    --expected-version "$GRAFANA_VERSION" \
    --backup "$smoke_dir/grafana-data.tgz" \
    --admin-user "$grafana_admin_user" \
    --admin-password-file "$smoke_dir/grafana-password" \
    --provisioning-dir ops/grafana/provisioning \
    --dashboards-dir ops/grafana/dashboards \
    --source-revision "$source_revision" \
    --write-freeze-at "$grafana_freeze_at" \
    --backup-created-at "$grafana_backup_at" \
    --backup-duration-seconds 1 \
    --rto-seconds 120 \
    --rpo-seconds 60 \
    --observed-rpo-seconds 1 \
    --expect-dashboard 'pipelens-operations=PipeLens Operations' \
    --expect-dashboard 'recovery-smoke-dashboard=Recovery Smoke Dashboard' \
    --expect-folder 'recovery-smoke-folder=Recovery Smoke' \
    --expect-datasource 'prometheus=prometheus,http://prometheus:9090' \
    --anonymous-role Viewer \
    --run-id live-smoke \
    --output "$smoke_dir/grafana-evidence.json" >/dev/null

"$python_bin" - "$smoke_dir/postgres-evidence.json" \
    "$smoke_dir/grafana-evidence.json" "$GRAFANA_VERSION" <<'PY'
import json
import sys
from pathlib import Path

postgres = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
grafana = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
assert postgres["source"]["revision"] == grafana["source"]["revision"]
assert postgres["restore"]["postgres_major"] == 18
assert postgres["restore"]["rto_met"] and postgres["restore"]["rpo_met"]
assert postgres["integrity"]["representative_counts"]["recovery_smoke_probe"]["met"]
assert grafana["restore"]["grafana_version"] == sys.argv[3]
assert grafana["restore"]["rto_met"] and grafana["restore"]["rpo_met"]
assert grafana["integrity"]["dashboards"]["recovery-smoke-dashboard"]["present"]
assert not grafana["integrity"]["dashboards"]["recovery-smoke-dashboard"]["provisioned"]
assert grafana["integrity"]["folders"]["recovery-smoke-folder"]["present"]
assert grafana["integrity"]["datasources"]["prometheus"]["present"]
assert postgres["target_preserved"] is False
assert grafana["target_preserved"] is False
print("live recovery smoke passed: PostgreSQL 18 and Grafana restore evidence verified")
PY
