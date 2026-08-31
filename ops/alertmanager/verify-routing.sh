#!/usr/bin/env bash
set -euo pipefail

: "${ALERTMANAGER_IMAGE:?ALERTMANAGER_IMAGE must be an immutable digest reference}"
: "${PROMETHEUS_IMAGE:?PROMETHEUS_IMAGE must be an immutable digest reference}"

digest_reference='^.+@sha256:[0-9a-f]{64}$'
if [[ ! "$ALERTMANAGER_IMAGE" =~ $digest_reference ]]; then
  echo "ALERTMANAGER_IMAGE must be pinned by digest" >&2
  exit 1
fi
if [[ ! "$PROMETHEUS_IMAGE" =~ $digest_reference ]]; then
  echo "PROMETHEUS_IMAGE must be pinned by digest" >&2
  exit 1
fi

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fixture_dir="$project_root/ops/alertmanager/fixtures"
result_dir="$(mktemp -d)"
chmod 0755 "$result_dir"
payload_path="$result_dir/alertmanager-webhook.json"
receiver_ready_path="$result_dir/receiver-ready"
prometheus_config_path="$result_dir/prometheus.yml"
network_name="pipelens-alert-routing-$$"
alertmanager_container="pipelens-alertmanager-routing-$$"
prometheus_container="pipelens-prometheus-routing-$$"
receiver_pid=""

cleanup() {
  docker rm --force "$prometheus_container" "$alertmanager_container" >/dev/null 2>&1 || true
  docker network rm "$network_name" >/dev/null 2>&1 || true
  if [[ -n "$receiver_pid" ]]; then
    kill "$receiver_pid" >/dev/null 2>&1 || true
    wait "$receiver_pid" >/dev/null 2>&1 || true
  fi
  rm -rf "$result_dir"
}
trap cleanup EXIT

docker run --rm --entrypoint amtool \
  --volume "$project_root/ops/alertmanager/alertmanager.yml:/etc/alertmanager.yml:ro" \
  "$ALERTMANAGER_IMAGE" check-config /etc/alertmanager.yml
docker run --rm --entrypoint amtool \
  --volume "$fixture_dir/alertmanager.yml:/etc/alertmanager.yml:ro" \
  "$ALERTMANAGER_IMAGE" check-config /etc/alertmanager.yml
docker run --rm --entrypoint promtool \
  --volume "$fixture_dir:/etc/prometheus:ro" \
  "$PROMETHEUS_IMAGE" check config /etc/prometheus/prometheus.yml
docker run --rm --entrypoint promtool \
  --volume "$fixture_dir:/etc/prometheus:ro" \
  "$PROMETHEUS_IMAGE" check config /etc/prometheus/prometheus-bootstrap.yml

cp "$fixture_dir/prometheus-bootstrap.yml" "$prometheus_config_path"
cp "$fixture_dir/probe.yml" "$result_dir/probe.yml"

python "$project_root/ops/alertmanager/test_receiver.py" \
  --output "$payload_path" \
  --ready-file "$receiver_ready_path" \
  --timeout 180 &
receiver_pid=$!

for attempt in {1..10}; do
  if [[ -f "$receiver_ready_path" ]]; then
    break
  fi
  if [[ "$attempt" == 10 ]]; then
    echo "webhook receiver did not become ready" >&2
    kill "$receiver_pid" >/dev/null 2>&1 || true
    wait "$receiver_pid" || true
    exit 1
  fi
  sleep 1
done

docker network create "$network_name" >/dev/null
docker run --detach --rm \
  --name "$alertmanager_container" \
  --network "$network_name" \
  --network-alias alertmanager \
  --add-host host.docker.internal:host-gateway \
  --publish 19093:9093 \
  --volume "$fixture_dir/alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro" \
  "$ALERTMANAGER_IMAGE" \
  --config.file=/etc/alertmanager/alertmanager.yml \
  --storage.path=/alertmanager \
  --cluster.listen-address= \
  --enable-feature=utf8-strict-mode >/dev/null

for attempt in {1..15}; do
  if curl --fail --silent http://localhost:19093/-/ready >/dev/null; then
    break
  fi
  if [[ "$attempt" == 15 ]]; then
    docker logs "$alertmanager_container"
    exit 1
  fi
  sleep 1
done

docker exec "$alertmanager_container" \
  amtool --alertmanager.url=http://localhost:9093 config show >/dev/null

docker run --detach --rm \
  --name "$prometheus_container" \
  --network "$network_name" \
  --publish 19090:9090 \
  --volume "$result_dir:/etc/prometheus:ro" \
  "$PROMETHEUS_IMAGE" \
  --config.file=/etc/prometheus/prometheus.yml \
  --storage.tsdb.path=/prometheus >/dev/null

for attempt in {1..30}; do
  if curl --fail --silent http://localhost:19090/-/ready >/dev/null; then
    break
  fi
  if [[ "$attempt" == 30 ]]; then
    docker logs "$prometheus_container"
    exit 1
  fi
  sleep 1
done

if ! python "$project_root/ops/alertmanager/wait_for_alert.py" \
  prometheus-alertmanager \
  --url http://localhost:19090/api/v1/alertmanagers \
  --timeout 30; then
  docker logs "$prometheus_container"
  exit 1
fi

cp "$fixture_dir/prometheus.yml" "$prometheus_config_path"
docker kill --signal HUP "$prometheus_container" >/dev/null

if ! python "$project_root/ops/alertmanager/wait_for_alert.py" prometheus \
  --url http://localhost:19090/api/v1/alerts \
  --timeout 30; then
  docker logs "$prometheus_container"
  exit 1
fi

if ! python "$project_root/ops/alertmanager/wait_for_alert.py" alertmanager \
  --url http://localhost:19093/api/v2/alerts \
  --timeout 30; then
  docker logs "$prometheus_container"
  docker logs "$alertmanager_container"
  exit 1
fi

for attempt in {1..60}; do
  if [[ -s "$payload_path" ]]; then
    break
  fi
  if [[ "$attempt" == 60 ]]; then
    docker logs "$prometheus_container"
    docker logs "$alertmanager_container"
    echo "Alertmanager accepted the alert but the webhook payload was not received" >&2
    kill "$receiver_pid" >/dev/null 2>&1 || true
    wait "$receiver_pid" || true
    exit 1
  fi
  sleep 1
done
wait "$receiver_pid"
receiver_pid=""

PAYLOAD_PATH="$payload_path" python - <<'PY'
import json
import os
import urllib.request
from pathlib import Path

payload = json.loads(Path(os.environ["PAYLOAD_PATH"]).read_text())
assert payload["version"] == "4", payload
assert payload["status"] == "firing", payload
assert payload["receiver"] == "ci-webhook", payload
matching = [
    alert
    for alert in payload["alerts"]
    if alert["labels"].get("alertname") == "PipeLensAlertRoutingProbe"
]
assert len(matching) == 1, payload
alert = matching[0]
assert alert["status"] == "firing", alert
assert alert["labels"]["severity"] == "critical", alert
assert alert["labels"]["environment"] == "ci", alert
assert alert["annotations"]["summary"] == "Synthetic Alertmanager routing probe", alert

with urllib.request.urlopen("http://localhost:19090/api/v1/alerts", timeout=5) as response:
    prometheus = json.load(response)
assert prometheus["status"] == "success", prometheus
assert any(
    item["labels"].get("alertname") == "PipeLensAlertRoutingProbe"
    and item["state"] == "firing"
    for item in prometheus["data"]["alerts"]
), prometheus

with urllib.request.urlopen("http://localhost:19093/api/v2/alerts", timeout=5) as response:
    alertmanager = json.load(response)
assert any(
    item["labels"].get("alertname") == "PipeLensAlertRoutingProbe"
    and item["status"]["state"] == "active"
    for item in alertmanager
), alertmanager
PY

echo "Prometheus -> Alertmanager -> webhook routing verified"
