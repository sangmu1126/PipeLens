from ops.alertmanager.wait_for_alert import (
    alertmanager_has_active,
    prometheus_has_active_alertmanager,
    prometheus_has_firing,
)


def test_prometheus_has_active_alertmanager() -> None:
    payload = {
        "status": "success",
        "data": {
            "activeAlertmanagers": [
                {"url": "http://alertmanager:9093/api/v2/alerts"}
            ],
            "droppedAlertmanagers": [],
        },
    }

    assert prometheus_has_active_alertmanager(payload)


def test_prometheus_rejects_missing_active_alertmanager() -> None:
    payload = {
        "status": "success",
        "data": {"activeAlertmanagers": [], "droppedAlertmanagers": []},
    }

    assert not prometheus_has_active_alertmanager(payload)


def test_prometheus_has_firing_probe() -> None:
    payload = {
        "status": "success",
        "data": {
            "alerts": [
                {
                    "labels": {"alertname": "PipeLensAlertRoutingProbe"},
                    "state": "firing",
                }
            ]
        },
    }

    assert prometheus_has_firing(payload)


def test_prometheus_rejects_pending_probe() -> None:
    payload = {
        "status": "success",
        "data": {
            "alerts": [
                {
                    "labels": {"alertname": "PipeLensAlertRoutingProbe"},
                    "state": "pending",
                }
            ]
        },
    }

    assert not prometheus_has_firing(payload)


def test_alertmanager_has_active_probe() -> None:
    payload = [
        {
            "labels": {"alertname": "PipeLensAlertRoutingProbe"},
            "status": {"state": "active"},
        }
    ]

    assert alertmanager_has_active(payload)


def test_alertmanager_rejects_suppressed_probe() -> None:
    payload = [
        {
            "labels": {"alertname": "PipeLensAlertRoutingProbe"},
            "status": {"state": "suppressed"},
        }
    ]

    assert not alertmanager_has_active(payload)
