#!/bin/sh

set -eu

: "${POSTGRES_PREVIOUS_IMAGE:?POSTGRES_PREVIOUS_IMAGE is required}"
: "${POSTGRES_CURRENT_IMAGE:?POSTGRES_CURRENT_IMAGE is required}"

source_container="pipelens-postgres-upgrade-source"
target_container="pipelens-postgres-upgrade-target"
source_volume="pipelens-postgres-upgrade-source-data"
target_volume="pipelens-postgres-upgrade-target-data"
upgrade_network="pipelens-postgres-upgrade"
database="pipelens_upgrade_test"
database_user="pipelens"
database_password="pipelens"

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

wait_for_initialized_postgres() {
    container="$1"
    for attempt in $(seq 1 60); do
        if docker logs "$container" 2>&1 \
                | grep -Fq "PostgreSQL init process complete; ready for start up." \
            && docker exec "$container" \
                pg_isready -U "$database_user" -d "$database" >/dev/null; then
            return 0
        fi
        sleep 1
    done
    docker logs "$container"
    return 1
}

cleanup() {
    if docker container inspect "$target_container" >/dev/null 2>&1; then
        docker rm --force "$target_container" >/dev/null
    fi
    if docker container inspect "$source_container" >/dev/null 2>&1; then
        docker rm --force "$source_container" >/dev/null
    fi
    if docker volume inspect "$target_volume" >/dev/null 2>&1; then
        docker volume rm "$target_volume" >/dev/null
    fi
    if docker volume inspect "$source_volume" >/dev/null 2>&1; then
        docker volume rm "$source_volume" >/dev/null
    fi
    if docker network inspect "$upgrade_network" >/dev/null 2>&1; then
        docker network rm "$upgrade_network" >/dev/null
    fi
}

assert_container_absent "$source_container"
assert_container_absent "$target_container"
assert_volume_absent "$source_volume"
assert_volume_absent "$target_volume"
if docker network inspect "$upgrade_network" >/dev/null 2>&1; then
    echo "refusing to replace existing network: $upgrade_network" >&2
    exit 1
fi

trap cleanup EXIT INT TERM

docker pull "$POSTGRES_PREVIOUS_IMAGE"
docker pull "$POSTGRES_CURRENT_IMAGE"
docker network create "$upgrade_network" >/dev/null
docker volume create "$source_volume" >/dev/null
docker volume create "$target_volume" >/dev/null

docker run --detach --name "$source_container" \
    --network "$upgrade_network" \
    --network-alias postgres17 \
    --publish 55432:5432 \
    --env POSTGRES_DB="$database" \
    --env POSTGRES_USER="$database_user" \
    --env POSTGRES_PASSWORD="$database_password" \
    --mount "type=volume,source=$source_volume,target=/var/lib/postgresql/data" \
    "$POSTGRES_PREVIOUS_IMAGE" >/dev/null
wait_for_initialized_postgres "$source_container"

PIPELENS_DATABASE_URL="postgresql+psycopg://$database_user:$database_password@localhost:55432/$database" \
    alembic upgrade head
docker exec "$source_container" psql --username "$database_user" --dbname "$database" \
    --set ON_ERROR_STOP=1 \
    --command "CREATE TABLE upgrade_probe (value text PRIMARY KEY); INSERT INTO upgrade_probe VALUES ('pipelens-postgres-18');"

docker run --detach --name "$target_container" \
    --network "$upgrade_network" \
    --publish 55433:5432 \
    --env POSTGRES_DB="$database" \
    --env POSTGRES_USER="$database_user" \
    --env POSTGRES_PASSWORD="$database_password" \
    --mount "type=volume,source=$target_volume,target=/var/lib/postgresql" \
    "$POSTGRES_CURRENT_IMAGE" >/dev/null
wait_for_initialized_postgres "$target_container"

docker exec --env PGPASSWORD="$database_password" "$target_container" \
    pg_dump --host postgres17 --username "$database_user" --dbname "$database" \
    --format custom --file /tmp/postgres17.dump
docker exec "$target_container" pg_restore --username "$database_user" --dbname "$database" \
    --no-owner /tmp/postgres17.dump

probe_value="$(docker exec "$target_container" psql --username "$database_user" \
    --dbname "$database" --tuples-only --no-align \
    --command "SELECT value FROM upgrade_probe")"
test "$probe_value" = "pipelens-postgres-18"
docker exec "$target_container" psql --username "$database_user" --dbname "$database" \
    --set ON_ERROR_STOP=1 --command "DROP TABLE upgrade_probe"

PIPELENS_DATABASE_URL="postgresql+psycopg://$database_user:$database_password@localhost:55433/$database" \
    alembic check
