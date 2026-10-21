#!/usr/bin/env python3
"""Dependency-free localhost server for the SurveyPlatform browser dashboard."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import secrets
import threading
import traceback
from typing import Any, Callable
from urllib.parse import urlparse
import uuid
import webbrowser

if __package__:
    from . import services
else:  # Direct script execution.
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from local_browser_app import services


STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_REQUEST_BYTES = 2 * 1024 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class BrowserJob:
    id: str
    name: str
    status: str = "queued"
    created_at: str = field(default_factory=_now)
    started_at: str | None = None
    finished_at: str | None = None
    logs: list[str] = field(default_factory=list)
    result: Any = None
    error: str = ""


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, BrowserJob] = {}
        self._lock = threading.Lock()

    def submit(
        self,
        name: str,
        action: Callable[[dict[str, Any], Callable[[str], None]], Any],
        payload: dict[str, Any],
    ) -> BrowserJob:
        job = BrowserJob(id=uuid.uuid4().hex, name=name)
        with self._lock:
            self._jobs[job.id] = job
            if len(self._jobs) > 100:
                finished = [item for item in self._jobs.values() if item.status in {"complete", "failed"}]
                for stale in sorted(finished, key=lambda item: item.created_at)[:20]:
                    self._jobs.pop(stale.id, None)

        def log(message: str) -> None:
            lines = str(message).splitlines() or [""]
            with self._lock:
                job.logs.extend(lines)
                if len(job.logs) > 2000:
                    del job.logs[:500]

        def worker() -> None:
            with self._lock:
                job.status = "running"
                job.started_at = _now()
            try:
                result = action(payload, log)
            except BaseException as exc:
                with self._lock:
                    job.status = "failed"
                    job.error = str(exc) or exc.__class__.__name__
                    job.logs.append(traceback.format_exc())
                    job.finished_at = _now()
                return
            with self._lock:
                job.result = services.jsonable(result)
                job.status = "complete"
                job.finished_at = _now()

        threading.Thread(target=worker, name=f"browser-job-{job.id[:8]}", daemon=True).start()
        return job

    def get(self, job_id: str) -> BrowserJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def payload(self, job: BrowserJob) -> dict[str, Any]:
        with self._lock:
            return {
                "id": job.id,
                "name": job.name,
                "status": job.status,
                "created_at": job.created_at,
                "started_at": job.started_at,
                "finished_at": job.finished_at,
                "logs": list(job.logs),
                "result": job.result,
                "error": job.error,
            }


SYNC_ROUTES: dict[str, Callable[[dict[str, Any]], Any]] = {
    "/api/table-gen/discover": services.table_discover,
    "/api/sheet-merge/file-info": services.sheet_file_info,
    "/api/sheet-merge/preview": services.sheet_preview,
    "/api/quota/review": services.quota_review,
    "/api/oe/import": services.oe_import,
    "/api/oe/dashboard": services.oe_dashboard,
    "/api/oe/responses": services.oe_responses,
    "/api/oe/assign": services.oe_assign,
    "/api/oe/reset": services.oe_reset,
    "/api/oe/code": services.oe_upsert_code,
    "/api/questions/filters": services.question_filters,
    "/api/questions/search": services.question_search,
}

ASYNC_ROUTES: dict[
    str, tuple[str, Callable[[dict[str, Any], Callable[[str], None]], Any]]
] = {
    "/api/table-gen/run": ("Table Gen", services.table_run),
    "/api/sheet-merge/run": ("Sheet Merge", services.sheet_run),
    "/api/oe/export": ("OE Export", services.oe_export),
    "/api/auto-results/run": ("Auto Results", services.auto_results_run),
}


class SurveyBrowserServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int], token: str) -> None:
        super().__init__(server_address, SurveyBrowserHandler)
        self.token = token
        self.jobs = JobManager()


class SurveyBrowserHandler(BaseHTTPRequestHandler):
    server: SurveyBrowserServer

    def log_message(self, fmt: str, *args: object) -> None:
        # Keep the terminal useful: report only errors, not every polling request.
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(fmt, *args)

    def _json(self, status: int, payload: Any) -> None:
        body = json.dumps(services.jsonable(payload), ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        return secrets.compare_digest(self.headers.get("X-Survey-App-Token", ""), self.server.token)

    def _payload(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("Invalid request length.") from exc
        if length < 0 or length > MAX_REQUEST_BYTES:
            raise ValueError("Request is too large.")
        if not length:
            return {}
        raw = self.rfile.read(length)
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("JSON request body must be an object.")
        return value

    def _static(self, route: str) -> None:
        relative = "index.html" if route in {"", "/"} else route.lstrip("/")
        candidate = (STATIC_DIR / relative).resolve()
        try:
            candidate.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not candidate.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = candidate.read_bytes()
        if candidate.name == "index.html":
            body = body.replace(b"__APP_TOKEN__", self.server.token.encode("ascii"))
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or candidate.suffix in {".js", ".json"}:
            content_type += "; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        route = urlparse(self.path).path
        if route == "/api/health":
            if not self._authorized():
                self._json(HTTPStatus.FORBIDDEN, {"error": "Unauthorized local request."})
                return
            self._json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "platform_root": str(services.PLATFORM_ROOT),
                    "question_db": str(services.QUESTION_DB),
                },
            )
            return
        if route.startswith("/api/jobs/"):
            if not self._authorized():
                self._json(HTTPStatus.FORBIDDEN, {"error": "Unauthorized local request."})
                return
            job_id = route.rsplit("/", 1)[-1]
            job = self.server.jobs.get(job_id)
            if job is None:
                self._json(HTTPStatus.NOT_FOUND, {"error": "Job not found."})
            else:
                self._json(HTTPStatus.OK, self.server.jobs.payload(job))
            return
        self._static(route)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        route = urlparse(self.path).path
        if not self._authorized():
            self._json(HTTPStatus.FORBIDDEN, {"error": "Unauthorized local request."})
            return
        try:
            payload = self._payload()
            if route in SYNC_ROUTES:
                result = SYNC_ROUTES[route](payload)
                self._json(HTTPStatus.OK, {"ok": True, "result": result})
                return
            if route in ASYNC_ROUTES:
                name, action = ASYNC_ROUTES[route]
                job = self.server.jobs.submit(name, action, payload)
                self._json(
                    HTTPStatus.ACCEPTED,
                    {"ok": True, "job": self.server.jobs.payload(job)},
                )
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "API route not found."})
        except (ValueError, FileNotFoundError, PermissionError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:
            self._json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": str(exc) or exc.__class__.__name__},
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SurveyPlatform local browser dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("This app is intentionally limited to a loopback address.")
    token = secrets.token_urlsafe(24)
    server = SurveyBrowserServer((args.host, args.port), token)
    host, port = server.server_address[:2]
    display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    url = f"http://{display_host}:{port}/"
    print(f"Survey Workbench is running at {url}")
    print("Press Ctrl+C to stop it.")
    if not args.no_browser:
        threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nStopping Survey Workbench...")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

