"""Standard-library HTTP API for matching-engine recommendations.

Run locally:
    set INTERNLINK_DSN=postgresql://postgres@localhost:5432/internlink
    set INTERNLINK_JWT_SECRET=<same secret the login service signs tokens with>
    python -m matching_engine.api --port 8000
"""
import argparse
import json
import logging
import os
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import jwt
import psycopg
from psycopg_pool import ConnectionPool

from matching_engine.config import DEFAULT_CONFIG, ServiceConfig
from matching_engine.service import (
    MatchingUnavailable,
    ProfileIncomplete,
    recommend_for_student,
    student_id_for_user,
)

log = logging.getLogger(__name__)
RECOMMENDATIONS_PATH = "/api/v1/students/me/recommendations"


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def _json_default(value):
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def create_server(
    dsn: str | None = None,
    jwt_secret: str | None = None,
    cfg: ServiceConfig = DEFAULT_CONFIG,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> ThreadingHTTPServer:
    """Create the recommendation HTTP server and open its database pool."""
    dsn = dsn or os.environ["INTERNLINK_DSN"]
    jwt_secret = jwt_secret or os.environ["INTERNLINK_JWT_SECRET"]
    pool = ConnectionPool(dsn, min_size=2, max_size=cfg.pool_size, open=False)

    class RequestHandler(BaseHTTPRequestHandler):
        def _send_json(self, status: int, payload: dict):
            body = json.dumps(payload, default=_json_default).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_api_error(self, error: ApiError):
            self._send_json(
                error.status,
                {"error": {"code": error.code, "message": error.message}},
            )

        def _send_http_error(self, status: int, detail: str, *, authenticate: bool = False):
            if authenticate:
                self.send_response(status)
                self.send_header("WWW-Authenticate", "Bearer")
                body = json.dumps({"detail": detail}).encode("utf-8")
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self._send_json(status, {"detail": detail})

        def do_GET(self):
            parsed_path = urlsplit(self.path)
            if parsed_path.path != RECOMMENDATIONS_PATH:
                self._send_http_error(404, "Not Found")
                return

            authorization = self.headers.get("Authorization", "")
            scheme, separator, credentials = authorization.partition(" ")
            if scheme.lower() != "bearer" or not separator or not credentials:
                self._send_http_error(401, "Not logged in", authenticate=True)
                return

            try:
                claims = jwt.decode(
                    credentials,
                    jwt_secret,
                    algorithms=["HS256"],
                    options={"require": ["exp", "sub", "role"]},
                )
            except jwt.PyJWTError:
                self._send_http_error(401, "Invalid or expired token", authenticate=True)
                return

            if claims["role"] != "student":
                self._send_http_error(403, "Only students can get recommendations")
                return

            try:
                user_id = int(claims["sub"])
            except (TypeError, ValueError, OverflowError):
                self._send_http_error(401, "Invalid or expired token", authenticate=True)
                return

            query = parse_qs(parsed_path.query, keep_blank_values=True)
            raw_limit = query.get("limit", [str(cfg.default_k)])[0]
            try:
                limit = int(raw_limit)
            except ValueError:
                self._send_http_error(422, "Invalid limit")
                return
            if not 1 <= limit <= cfg.max_k:
                self._send_http_error(422, "Invalid limit")
                return

            try:
                with pool.connection() as conn:
                    student_id = student_id_for_user(conn, user_id)
                    if student_id is None:
                        raise ProfileIncomplete("No student profile")
                    result = recommend_for_student(conn, student_id, k=limit, cfg=cfg)
            except ProfileIncomplete:
                self._send_api_error(
                    ApiError(
                        422,
                        "PROFILE_INCOMPLETE",
                        "Add your programme and at least one skill to get recommendations",
                    )
                )
                return
            except MatchingUnavailable:
                self._send_api_error(
                    ApiError(
                        503,
                        "MATCHING_UNAVAILABLE",
                        "Couldn't load recommendations. Please retry.",
                    )
                )
                return
            except psycopg.Error:
                log.warning("Recommendation profile lookup failed for user %s", user_id, exc_info=True)
                self._send_api_error(
                    ApiError(
                        503,
                        "MATCHING_UNAVAILABLE",
                        "Couldn't load recommendations. Please retry.",
                    )
                )
                return

            self._send_json(
                200,
                {
                    "algorithm": result.algorithm,
                    "count": result.count,
                    "results": [vars(recommendation) for recommendation in result.results],
                },
            )

        def log_message(self, format, *args):
            log.info("%s - %s", self.address_string(), format % args)

    class RecommendationServer(ThreadingHTTPServer):
        daemon_threads = True

        def server_close(self):
            try:
                super().server_close()
            finally:
                pool.close()

    try:
        pool.open(wait=True)
        return RecommendationServer((host, port), RequestHandler)
    except Exception:
        pool.close()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    server = create_server(host=args.host, port=args.port)
    log.info("InternLink matching API listening on %s:%s", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
