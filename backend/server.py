"""
server.py - starts the InternLink student web server.

Run from the backend folder (with the venv active):
    python server.py
Then open http://127.0.0.1:8000 (or the HOST/PORT you set in .env).
"""
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config
import db
from router import MAX_BODY_BYTES, MAX_JSON_BYTES, HttpError, Request, error_response, router

# Importing these files registers their routes with the router.
import handlers_auth           # noqa: F401  sign-up, login, logout, me
import handlers_meta           # noqa: F401  dropdown lists
import handlers_profile        # noqa: F401  profile, skills, interests, CV
import handlers_opportunities  # noqa: F401  find opportunities, apply, recommendations
import handlers_applications   # noqa: F401  track applications, withdraw, dashboard

BODY_METHODS = ("POST", "PUT", "PATCH", "DELETE")


class Handler(BaseHTTPRequestHandler):
    server_version = "InternLink"
    sys_version = ""
    timeout = 30                      # drop connections that stay silent (protects against stalled clients)

    # ----- one entry point for every HTTP method -----
    def _handle(self):
        try:
            response = self._build_response()
        except Exception as exc:
            print("Unexpected error while reading the request:", repr(exc))
            response = error_response(HttpError(500, "Something went wrong on the server."))
        self._send(response)

    def _build_response(self):
        raw_body = b""
        if self.command in BODY_METHODS:
            if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
                return error_response(HttpError(411, "Chunked uploads are not supported."))

            length_text = (self.headers.get("Content-Length") or "0").strip()
            if not (length_text.isascii() and length_text.isdigit()):
                return error_response(HttpError(400, "Invalid Content-Length."))
            length = int(length_text)

            is_upload = "multipart/form-data" in (self.headers.get("Content-Type") or "").lower()
            limit = MAX_BODY_BYTES if is_upload else MAX_JSON_BYTES
            if length > limit:
                self.close_connection = True       # refuse WITHOUT reading the huge body
                return error_response(HttpError(413, "The request is too large."))

            if length:
                raw_body = self.rfile.read(length)
                if len(raw_body) != length:
                    return error_response(HttpError(400, "The request body was incomplete."))

        request = Request(self.command, self.path, self.headers, raw_body, self.client_address[0])
        return router.dispatch(request)

    def _send(self, response):
        body = response.body
        try:
            self.send_response(response.status)
            for name, value in response.headers:
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass                                    # the browser went away; nothing to do

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _handle

    # ----- logging: path only (no query string, no body) -----
    def log_request(self, code="-", size="-"):
        path = self.path.split("?", 1)[0]
        print(f"[{time.strftime('%H:%M:%S')}] {self.client_address[0]} {self.command} {path} -> {code}")


def main():
    # 1. Database must be reachable.
    try:
        db.init_pool()
        db.fetch_one("SELECT 1 AS ok")
    except Exception as exc:
        reason = str(exc).strip().splitlines()[0] if str(exc).strip() else repr(exc)
        print("Cannot connect to the database:", reason)
        print("Check DATABASE_URL in backend/.env, then run  python db.py  to test it.")
        sys.exit(1)

    # 2. Folders.
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    if not config.FRONTEND_DIR.is_dir():
        print(f"WARNING: the frontend folder was not found at {config.FRONTEND_DIR}")

    # 3. Start listening.
    try:
        server = ThreadingHTTPServer((config.HOST, config.PORT), Handler)
    except OSError as exc:
        print(f"Cannot start on {config.HOST}:{config.PORT}: {exc}")
        print("Another program may be using that port. Change PORT in backend/.env and try again.")
        db.close_pool()
        sys.exit(1)

    print("InternLink student module is running.")
    print(f"  Open:  http://{config.HOST}:{config.PORT}")
    print("  Stop:  press Ctrl+C")
    if config.AUTO_VERIFY_EMAIL:
        print("  Note:  AUTO_VERIFY_EMAIL=true (new accounts are activated immediately - development only)")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        server.server_close()
        db.close_pool()


if __name__ == "__main__":
    main()