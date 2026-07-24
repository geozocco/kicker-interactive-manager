#!/usr/bin/env python3
"""Serve normalized news snapshots to a small authenticated internal group.

Terminate TLS in front of this process. The optimizer deliberately refuses
unencrypted remote feed URLs.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from news_snapshot import NewsSnapshotError, canonical_sha256, load_snapshot


SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class NewsFeedHandler(BaseHTTPRequestHandler):
    server_version = "KickerNewsFeed/1"

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        expected = self.server.feed_token  # type: ignore[attr-defined]
        if not expected:
            return True
        supplied = self.headers.get("Authorization", "")
        prefix = "Bearer "
        return supplied.startswith(prefix) and hmac.compare_digest(
            supplied[len(prefix) :],
            expected,
        )

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            self._json(HTTPStatus.OK, {"status": "ok"})
            return
        prefix = "/v1/news/"
        suffix = ".json"
        if not self.path.startswith(prefix) or not self.path.endswith(suffix):
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        slug = self.path[len(prefix) : -len(suffix)]
        if not SAFE_NAME.fullmatch(slug):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_snapshot_name"})
            return
        root = self.server.snapshot_root  # type: ignore[attr-defined]
        path = root / f"{slug}.json"
        try:
            payload = load_snapshot(path)
        except FileNotFoundError:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        except (NewsSnapshotError, OSError) as error:
            self._json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"error": "snapshot_unavailable", "detail": str(error)},
            )
            return
        etag = f'"{canonical_sha256(payload)}"'
        if self.headers.get("If-None-Match") == etag:
            self.send_response(HTTPStatus.NOT_MODIFIED)
            self.send_header("ETag", etag)
            self.end_headers()
            return
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "private, max-age=300")
        self.send_header("ETag", etag)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        print(
            json.dumps(
                {
                    "client": self.client_address[0],
                    "message": format % args,
                }
            )
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--token-env", default="KICKER_NEWS_FEED_TOKEN")
    parser.add_argument(
        "--allow-unauthenticated-local",
        action="store_true",
        help="Allow missing token only while binding to localhost",
    )
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    return args


def main() -> int:
    args = parse_args()
    token = os.environ.get(args.token_env, "").strip()
    localhost = args.host in {"127.0.0.1", "::1", "localhost"}
    if not token and not (localhost and args.allow_unauthenticated_local):
        raise SystemExit(
            f"{args.token_env} is required unless an explicitly unauthenticated "
            "localhost-only development server is requested"
        )
    root = args.root.resolve()
    if not root.is_dir():
        raise SystemExit(f"snapshot root does not exist: {root}")
    server = ThreadingHTTPServer((args.host, args.port), NewsFeedHandler)
    server.snapshot_root = root  # type: ignore[attr-defined]
    server.feed_token = token  # type: ignore[attr-defined]
    print(
        json.dumps(
            {
                "status": "listening",
                "host": args.host,
                "port": args.port,
                "root": str(root),
                "authenticated": bool(token),
            }
        ),
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
