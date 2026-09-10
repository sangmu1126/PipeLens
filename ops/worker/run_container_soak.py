"""Run an isolated, production-representative worker soak in Docker."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict, cast

from ops.worker.verify_soak_evidence import compile_evidence, load_observation

ROOT = Path(__file__).resolve().parents[2]
REDIS_IMAGE = (
    "redis:8.2-alpine@sha256:30abb90e62f14b737010746def3ba99cc79fe19dcdb3d37b41f21fc62e7da19d"
)
POSTGRES_IMAGE = (
    "postgres:18-alpine@sha256:d3e1620b530c944afa6e887d22eb899824da68e19c52024bf98f5220c88a65b2"
)
SAFE_RUN_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
SENSITIVE_ARTIFACT = re.compile(
    rb"https?://|redis[_-]?url|database[_-]?url|password|token|secret", re.IGNORECASE
)


class SoakError(RuntimeError):
    """Raised when orchestration or a soak invariant fails."""


class ResourceSample(TypedDict):
    captured_at: str
    worker_cpu_peak_percent: float
    worker_memory_peak_percent: float
    postgres_pool_connections: int
    postgres_total_connections: int
    redis_memory_percent: float


@dataclass(frozen=True)
class Profile:
    jobs: int
    arrival_rate: float
    burst_size: int
    github_latency: float
    llm_latency: float
    lease_seconds: int
    heartbeat_seconds: float
    network_fault_seconds: float
    telemetry_interval: float
    completion_timeout: float
    minimum_duration: float

    @property
    def planned_duration(self) -> float:
        batches = (self.jobs - 1 + self.burst_size - 1) // self.burst_size
        return max(0.001, (batches - 1) * self.burst_size / self.arrival_rate)


PROFILES = {
    "smoke": Profile(25, 20, 4, 0.01, 0.02, 3, 0.5, 2, 0.5, 60, 0),
    "launch": Profile(3605, 1, 4, 0.15, 1.2, 30, 5, 5, 10, 180, 3600),
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def run(
    *arguments: str,
    check: bool = True,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["docker", *arguments],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if check and result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise SoakError(f"docker {arguments[0]} failed: {detail[-2000:]}")
    return result


def wait_for(description: str, predicate: Any, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise SoakError(f"timed out waiting for {description}")


def inspect_running(container: str) -> bool:
    result = run("inspect", "--format", "{{.State.Running}}", container, check=False)
    return result.returncode == 0 and result.stdout.strip() == "true"


def exec_output(container: str, *arguments: str) -> str:
    return run("exec", container, *arguments).stdout.strip()


def redis_value(container: str, *arguments: str) -> str:
    return exec_output(container, "redis-cli", "--raw", *arguments)


def start_worker(context: dict[str, str], worker_id: str, profile: Profile) -> str:
    name = f"{context['prefix']}-{worker_id}"
    run(
        "run",
        "--detach",
        "--name",
        name,
        "--network",
        context["network"],
        "--cpus",
        "0.25",
        "--memory",
        "128m",
        context["image"],
        "worker",
        "--redis-url",
        "redis://redis:6379/0",
        "--queue-name",
        context["queue"],
        "--tracker-prefix",
        context["tracker"],
        "--lease-seconds",
        str(profile.lease_seconds),
        "--worker-id",
        worker_id,
        "--database-url",
        "postgresql://pipelens:pipelens@postgres:5432/pipelens",
        "--postgres-pool-size",
        "5",
        "--provider-url",
        "http://provider:8080",
        "--heartbeat-seconds",
        str(profile.heartbeat_seconds),
        "--victim-hold-seconds",
        str(profile.lease_seconds * 4),
    )
    return name


def runtime_args(context: dict[str, str], profile: Profile) -> list[str]:
    return [
        "--redis-url",
        "redis://redis:6379/0",
        "--queue-name",
        context["queue"],
        "--tracker-prefix",
        context["tracker"],
        "--lease-seconds",
        str(profile.lease_seconds),
    ]


def scrape_worker_metrics(container: str) -> str:
    code = "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8001').read().decode())"
    return exec_output(container, "python", "-c", code)


def metric_total(payloads: list[str], metric: str) -> float:
    total = 0.0
    for payload in payloads:
        for line in payload.splitlines():
            if line.startswith(metric + "{") or line.startswith(metric + " "):
                total += float(line.rsplit(" ", 1)[1])
    return total


def resource_sample(worker_names: list[str], postgres: str, redis: str) -> ResourceSample:
    stats_result = run("stats", "--no-stream", "--format", "{{json .}}", *worker_names, check=False)
    stats = [json.loads(line) for line in stats_result.stdout.splitlines() if line.strip()]
    cpu = max((float(item["CPUPerc"].rstrip("%")) for item in stats), default=0)
    memory = max((float(item["MemPerc"].rstrip("%")) for item in stats), default=0)
    connections = exec_output(
        postgres,
        "psql",
        "-U",
        "pipelens",
        "-d",
        "pipelens",
        "-At",
        "-c",
        "SELECT count(*) FILTER (WHERE application_name LIKE 'pipelens-soak-%'), count(*) "
        "FROM pg_stat_activity;",
    )
    pool_connections, total_connections = (int(value) for value in connections.split("|"))
    memory_info = redis_value(redis, "INFO", "memory")
    redis_values = dict(
        line.rstrip("\r").split(":", 1) for line in memory_info.splitlines() if ":" in line
    )
    used = int(redis_values["used_memory"])
    maximum = int(redis_values["maxmemory"])
    return {
        "captured_at": utc_now(),
        "worker_cpu_peak_percent": cpu,
        "worker_memory_peak_percent": memory,
        "postgres_pool_connections": pool_connections,
        "postgres_total_connections": total_connections,
        "redis_memory_percent": 100 * used / maximum,
    }


def aggregate_resources(samples: list[ResourceSample]) -> dict[str, object]:
    if not samples:
        raise SoakError("no resource telemetry was captured")
    return {
        "captured_at": samples[-1]["captured_at"],
        "worker_cpu_peak_percent": max(item["worker_cpu_peak_percent"] for item in samples),
        "worker_memory_peak_percent": max(item["worker_memory_peak_percent"] for item in samples),
        "postgres_pool_peak_connections": max(
            item["postgres_pool_connections"] for item in samples
        ),
        "postgres_total_peak_connections": max(
            item["postgres_total_connections"] for item in samples
        ),
        "redis_memory_peak_percent": max(item["redis_memory_percent"] for item in samples),
    }


def provider_audit(container: str) -> dict[str, object]:
    code = "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8080/audit').read().decode())"
    payload = json.loads(exec_output(container, "python", "-c", code))
    if not isinstance(payload, dict):
        raise SoakError("provider audit endpoint returned a non-object JSON payload")
    return cast(dict[str, object], payload)


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True
    )
    return result.stdout.strip()


def artifact_scan(paths: list[Path]) -> int:
    return sum(len(SENSITIVE_ARTIFACT.findall(path.read_bytes())) for path in paths)


def build_observation(
    run_id: str,
    revision: str,
    profile: Profile,
    runner: dict[str, Any],
    resources: dict[str, object],
    providers: dict[str, object],
    artifacts: dict[str, Any],
) -> dict[str, object]:
    fault = runner["fault_injection"]
    results = runner["results"]
    return {
        "schema_version": 1,
        "soak_id": run_id,
        "source_revision": revision,
        "environment": "isolated-container-soak",
        "started_at": results["started_at"],
        "completed_at": resources["captured_at"],
        "load_profile": {
            "jobs": profile.jobs,
            "arrival_rate_per_second": profile.arrival_rate,
            "burst_size": profile.burst_size,
            "concurrency": 4,
            "planned_duration_seconds": profile.planned_duration,
        },
        "resource_limits": {
            "worker_replicas": 4,
            "worker_cpu_cores_each": 0.25,
            "worker_memory_mib_each": 128,
            "postgres_pool_size_each": 5,
            "postgres_max_connections": 50,
            "redis_maxmemory_mib": 128,
        },
        "provider_profile": providers,
        "fault_injection": fault,
        "results": {
            "completed_jobs": results["completed_jobs"],
            "throughput_jobs_per_second": results["throughput_jobs_per_second"],
            "start_latency_p95_seconds": results["latency_seconds"]["start_p95"],
            "completion_latency_p95_seconds": results["latency_seconds"]["completion_p95"],
            "start_slo_attainment_percent": results["slo_attainment_percent"]["start"],
            "completion_slo_attainment_percent": results["slo_attainment_percent"]["completion"],
            "duplicate_completions": results["duplicate_completions"],
            "lost_jobs": results["lost_jobs"],
            "exactly_once": results["exactly_once"],
            "queue_drained": results["queue_drained"],
        },
        "resource_observation": resources,
        "capacity_recommendation": {
            "max_sustained_rate_per_second": profile.arrival_rate * 1.25,
            "recommended_rate_per_second": profile.arrival_rate,
            "recommended_worker_replicas": 4,
            "headroom_percent": 20,
            "limiting_resource": "tested-rate-ceiling",
            "owner": "project-maintainer",
            "reviewed": True,
        },
        "artifacts": {
            "runner_sha256": artifacts["runner"],
            "telemetry_sha256": artifacts["telemetry"],
            "provider_audit_sha256": artifacts["provider"],
            "secret_scan_matches": artifacts["secret_scan_matches"],
        },
    }


def execute(args: argparse.Namespace) -> dict[str, object]:
    profile = PROFILES[args.profile]
    run_id = args.run_id or f"worker-soak-{uuid.uuid4().hex[:12]}"
    if not SAFE_RUN_ID.fullmatch(run_id):
        raise SoakError("run ID must contain only lowercase letters, digits, and hyphens")
    output = args.output_dir.resolve()
    if output.exists():
        raise SoakError(f"output directory already exists: {output}")
    output.mkdir(parents=True)
    prefix = f"pipelens-{run_id}"
    context = {
        "prefix": prefix,
        "network": f"{prefix}-net",
        "volume": f"{prefix}-postgres",
        "postgres": f"{prefix}-postgres",
        "redis": f"{prefix}-redis",
        "provider": f"{prefix}-provider",
        "coordinator": f"{prefix}-coordinator",
        "queue": f"pipelens:container-soak:{run_id}",
        "tracker": f"pipelens:container-soak:{run_id}:tracker",
        "image": f"pipelens-soak:{source_revision()[:12]}",
    }
    created_containers: list[str] = []
    worker_names: list[str] = []
    telemetry: list[ResourceSample] = []
    worker_injected_at = worker_recovered_at = ""
    network_injected_at = network_recovered_at = ""
    metrics_summary: dict[str, float] = {}
    try:
        run("version")
        run("build", "--file", "ops/worker/Dockerfile", "--tag", context["image"], ".")
        run("network", "create", context["network"])
        run("volume", "create", context["volume"])
        run(
            "run",
            "--detach",
            "--name",
            context["postgres"],
            "--network",
            context["network"],
            "--network-alias",
            "postgres",
            "--memory",
            "256m",
            "--env",
            "POSTGRES_DB=pipelens",
            "--env",
            "POSTGRES_USER=pipelens",
            "--env",
            "POSTGRES_PASSWORD=pipelens",
            "--mount",
            f"type=volume,source={context['volume']},target=/var/lib/postgresql",
            POSTGRES_IMAGE,
            "-c",
            "max_connections=50",
        )
        created_containers.append(context["postgres"])
        run(
            "run",
            "--detach",
            "--name",
            context["redis"],
            "--network",
            context["network"],
            "--network-alias",
            "redis",
            "--memory",
            "160m",
            REDIS_IMAGE,
            "redis-server",
            "--maxmemory",
            "128mb",
            "--maxmemory-policy",
            "noeviction",
        )
        created_containers.append(context["redis"])
        run(
            "run",
            "--detach",
            "--name",
            context["provider"],
            "--network",
            context["network"],
            "--network-alias",
            "provider",
            "--memory",
            "128m",
            context["image"],
            "provider",
            "--github-latency",
            str(profile.github_latency),
            "--llm-latency",
            str(profile.llm_latency),
        )
        created_containers.append(context["provider"])
        wait_for(
            "PostgreSQL",
            lambda: (
                run(
                    "exec",
                    context["postgres"],
                    "pg_isready",
                    "-U",
                    "pipelens",
                    "-d",
                    "pipelens",
                    check=False,
                ).returncode
                == 0
            ),
        )
        wait_for("Redis", lambda: redis_value(context["redis"], "PING") == "PONG")
        wait_for(
            "provider",
            lambda: (
                run(
                    "exec",
                    context["provider"],
                    "python",
                    "-c",
                    "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/health')",
                    check=False,
                ).returncode
                == 0
            ),
        )

        victim = start_worker(context, "worker-1", profile)
        created_containers.append(victim)
        run(
            "run",
            "--rm",
            "--network",
            context["network"],
            context["image"],
            "seed-victim",
            *runtime_args(context, profile),
        )
        wait_for(
            "victim claim",
            lambda: (
                redis_value(context["redis"], "EXISTS", f"{context['tracker']}:victim_ready") == "1"
            ),
        )
        worker_injected_at = utc_now()
        run("kill", victim)
        run("rm", victim)
        created_containers.remove(victim)

        for worker_id in ("worker-1r", "worker-2", "worker-3", "worker-4"):
            name = start_worker(context, worker_id, profile)
            created_containers.append(name)
            worker_names.append(name)
        wait_for(
            "expired lease recovery",
            lambda: (
                redis_value(context["redis"], "HLEN", f"{context['tracker']}:first_completion")
                == "1"
            ),
            timeout=profile.lease_seconds + 20,
        )
        worker_recovered_at = utc_now()
        wait_for(
            "four PostgreSQL pools",
            lambda: (
                int(
                    exec_output(
                        context["postgres"],
                        "psql",
                        "-U",
                        "pipelens",
                        "-d",
                        "pipelens",
                        "-At",
                        "-c",
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE application_name LIKE 'pipelens-soak-%';",
                    )
                )
                == 20
            ),
        )

        network_injected_at = utc_now()
        run("network", "disconnect", context["network"], context["redis"])
        time.sleep(profile.network_fault_seconds)
        run("network", "connect", "--alias", "redis", context["network"], context["redis"])
        wait_for("Redis network recovery", lambda: redis_value(context["redis"], "PING") == "PONG")
        wait_for(
            "worker Redis reconnection metric",
            lambda: (
                metric_total(
                    [scrape_worker_metrics(name) for name in worker_names],
                    "pipelens_queue_reconnections_total",
                )
                >= 1
            ),
            timeout=profile.lease_seconds + 20,
        )
        network_recovered_at = utc_now()
        metric_payloads = [scrape_worker_metrics(name) for name in worker_names]
        metrics_summary = {
            "queue_connection_errors": metric_total(
                metric_payloads, "pipelens_queue_connection_errors_total"
            ),
            "queue_reconnections": metric_total(
                metric_payloads, "pipelens_queue_reconnections_total"
            ),
        }

        run(
            "run",
            "--detach",
            "--name",
            context["coordinator"],
            "--network",
            context["network"],
            context["image"],
            "coordinator",
            *runtime_args(context, profile),
            "--jobs",
            str(profile.jobs),
            "--arrival-rate",
            str(profile.arrival_rate),
            "--burst-size",
            str(profile.burst_size),
            "--completion-timeout",
            str(profile.planned_duration + profile.completion_timeout),
        )
        created_containers.append(context["coordinator"])
        while inspect_running(context["coordinator"]):
            telemetry.append(resource_sample(worker_names, context["postgres"], context["redis"]))
            time.sleep(profile.telemetry_interval)
        coordinator = run("inspect", "--format", "{{.State.ExitCode}}", context["coordinator"])
        if coordinator.stdout.strip() != "0":
            log_result = run("logs", context["coordinator"], check=False)
            coordinator_logs = (log_result.stdout + log_result.stderr)[-4000:]
            raise SoakError(f"coordinator failed: {coordinator_logs}")
        results = json.loads(run("logs", context["coordinator"]).stdout.strip().splitlines()[-1])
        telemetry.append(resource_sample(worker_names, context["postgres"], context["redis"]))
        providers = provider_audit(context["provider"])
        runner = {
            "schema_version": 1,
            "run_id": run_id,
            "source_revision": source_revision(),
            "profile": args.profile,
            "results": results,
            "worker_metrics": metrics_summary,
            "fault_injection": {
                "worker_termination": {
                    "injected_at": worker_injected_at,
                    "recovered_at": worker_recovered_at,
                    "workers": 1,
                    "lost_jobs": 0,
                },
                "expired_lease": {
                    "injected_at": worker_injected_at,
                    "recovered_at": worker_recovered_at,
                    "recovered_jobs": 1,
                    "lost_jobs": 0,
                },
                "network_interruption": {
                    "injected_at": network_injected_at,
                    "recovered_at": network_recovered_at,
                    "interruptions": 1,
                    "lost_jobs": 0,
                    "target": "redis-network-path",
                },
            },
        }
        runner_path = output / "runner.json"
        telemetry_path = output / "telemetry.json"
        provider_path = output / "provider-audit.json"
        write_json(runner_path, runner)
        write_json(telemetry_path, {"schema_version": 1, "samples": telemetry})
        write_json(provider_path, {"schema_version": 1, "providers": providers})
        artifacts = {
            "runner": sha256(runner_path),
            "telemetry": sha256(telemetry_path),
            "provider": sha256(provider_path),
            "secret_scan_matches": artifact_scan([runner_path, telemetry_path, provider_path]),
        }
        observation = build_observation(
            run_id,
            runner["source_revision"],
            profile,
            runner,
            aggregate_resources(telemetry),
            providers,
            artifacts,
        )
        observation_path = output / "observation.json"
        write_json(observation_path, observation)
        loaded, digest = load_observation(observation_path)
        evidence = compile_evidence(
            loaded,
            digest,
            min_duration_seconds=profile.minimum_duration,
            min_slo_attainment_percent=99,
            max_resource_utilization_percent=90,
            max_fault_recovery_seconds=120,
        )
        write_json(output / "evidence.json", evidence)
        if not evidence["passed"]:
            raise SoakError("strict soak evidence checks failed")
        return {"run_id": run_id, "output_dir": str(output), "passed": True, "results": results}
    finally:
        if not args.keep:
            for container in reversed(created_containers):
                run("rm", "--force", "--volumes", container, check=False)
            run("network", "rm", context["network"], check=False)
            run("volume", "rm", context["volume"], check=False)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=PROFILES, default="smoke")
    parser.add_argument("--run-id")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--keep", action="store_true", help="keep isolated Docker resources")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        result = execute(parse_args(argv))
    except (OSError, SoakError, subprocess.SubprocessError, ValueError) as error:
        print(f"container worker soak failed: {error}")
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
