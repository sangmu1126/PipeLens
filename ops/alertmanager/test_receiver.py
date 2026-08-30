"""Capture one Alertmanager webhook payload for the routing drill."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

MAX_PAYLOAD_BYTES = 1024 * 1024


class AlertHandler(BaseHTTPRequestHandler):
    output_path: Path

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/alerts":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(400)
            return
        if not 0 < length <= MAX_PAYLOAD_BYTES:
            self.send_error(413)
            return
        try:
            payload = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_error(400)
            return
        self.output_path.write_text(json.dumps(payload), encoding="utf-8")
        self.send_response(200)
        self.end_headers()

    def log_message(self, _format: str, *_args: object) -> None:
        return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18080)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 1 <= args.port <= 65535:
        raise SystemExit("port must be between 1 and 65535")
    AlertHandler.output_path = args.output
    server = HTTPServer(("0.0.0.0", args.port), AlertHandler)
    server.timeout = 60
    server.handle_request()
    server.server_close()
    if not args.output.exists():
        raise SystemExit("no Alertmanager webhook received within 60 seconds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
