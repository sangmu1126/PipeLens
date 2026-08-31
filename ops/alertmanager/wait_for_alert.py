"""Wait for the synthetic routing alert to reach one observability API."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

ALERT_NAME = "PipeLensAlertRoutingProbe"


def prometheus_has_firing(payload: Any) -> bool:
    return bool(
        isinstance(payload, dict)
        and payload.get("status") == "success"
        and any(
            alert.get("labels", {}).get("alertname") == ALERT_NAME
            and alert.get("state") == "firing"
            for alert in payload.get("data", {}).get("alerts", [])
        )
    )


def alertmanager_has_active(payload: Any) -> bool:
    return bool(
        isinstance(payload, list)
        and any(
            alert.get("labels", {}).get("alertname") == ALERT_NAME
            and alert.get("status", {}).get("state") == "active"
            for alert in payload
        )
    )


def wait_for_alert(
    url: str,
    predicate: Callable[[Any], bool],
    timeout: float,
    interval: float = 1,
) -> None:
    deadline = time.monotonic() + timeout
    last_detail = "no response"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                payload = json.load(response)
            if predicate(payload):
                return
            last_detail = json.dumps(payload, sort_keys=True)[:2000]
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
            last_detail = str(error)
        time.sleep(interval)
    raise TimeoutError(f"alert state not observed at {url}: {last_detail}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", choices=("prometheus", "alertmanager"))
    parser.add_argument("--url", required=True)
    parser.add_argument("--timeout", type=float, default=30)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.timeout <= 0:
        raise SystemExit("timeout must be greater than zero")
    predicate = {
        "prometheus": prometheus_has_firing,
        "alertmanager": alertmanager_has_active,
    }[args.source]
    try:
        wait_for_alert(args.url, predicate, args.timeout)
    except TimeoutError as error:
        raise SystemExit(str(error)) from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
