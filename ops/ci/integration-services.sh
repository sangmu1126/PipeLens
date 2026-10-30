#!/usr/bin/env bash
set -euo pipefail

# Starts or stops the Compose-pinned PostgreSQL and Redis images used by integration tests.
postgres_container="pipelens-postgres-integration"
postgres_volume="pipelens-postgres-integration-data"
redis_container="pipelens-redis-integration"

compose_image() {
  docker compose config --format json | python -c '
import json
import sys

print(json.load(sys.stdin)["services"][sys.argv[1]]["image"])
' "$1"
}

start() {
  local postgres_image redis_image
  postgres_image="$(compose_image postgres)"
  redis_image="$(compose_image redis)"

  docker pull "$postgres_image"
  docker volume create "$postgres_volume"
  docker run --detach --name "$postgres_container" --publish 5432:5432 \
    --env POSTGRES_DB=pipelens_test \
    --env POSTGRES_USER=pipelens \
    --env POSTGRES_PASSWORD=pipelens \
    --mount "type=volume,source=$postgres_volume,target=/var/lib/postgresql" \
    "$postgres_image"

  docker pull "$redis_image"
  docker run --detach --name "$redis_container" --publish 6379:6379 "$redis_image"

  local ready=false
  for attempt in {1..30}; do
    if docker exec "$postgres_container" pg_isready -U pipelens -d pipelens_test >/dev/null; then
      ready=true
      break
    fi
    sleep 1
  done
  if [[ "$ready" != true ]]; then
    docker logs "$postgres_container"
    exit 1
  fi

  for attempt in {1..10}; do
    if test "$(docker exec "$redis_container" redis-cli ping 2>/dev/null)" = "PONG"; then
      return 0
    fi
    sleep 1
  done
  docker logs "$redis_container"
  exit 1
}

stop() {
  for container in "$redis_container" "$postgres_container"; do
    if docker container inspect "$container" >/dev/null 2>&1; then
      docker rm --force "$container"
    fi
  done
  if docker volume inspect "$postgres_volume" >/dev/null 2>&1; then
    docker volume rm "$postgres_volume"
  fi
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  *)
    echo "usage: $0 start|stop" >&2
    exit 2
    ;;
esac
