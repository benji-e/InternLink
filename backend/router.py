"""
router.py - tiny routing layer (replaces a web framework).

How other files use it:

    from router import route, json_response, HttpError

    @route("GET", "/api/example/<int:item_id>")
    def get_example(req):
        item_id = req.params["item_id"]          # already an int
        q = req.query.get("q", "")               # ?q=...
        body = req.json()                        # parsed JSON body (dict)
        if not body.get("name"):
            raise HttpError(400, "Name is required.")
        return {"ok": True}                      # dict -> JSON, status 200
        # or: return json_response({"id": 1}, 201)

Handlers must be imported in server.py so their @route lines run.
"""
import json
import mimetypes
import re
import traceback
from datetime import date, datetime, time
from decimal import Decimal
from email.parser import BytesParser
from email.policy import HTTP as HTTP_POLICY
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, unquote, urlsplit

import config
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("text/html", ".html")

STATE_CHANGING = ("POST", "PUT", "PATCH", "DELETE")
CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "InternLink"                      # frontend/js/api.js sends this on every call
MAX_JSON_BYTES = 1_000_000                     # 1 MB for normal JSON requests
MAX_BODY_BYTES = config.MAX_CV_BYTES + 1_000_000   # CV size + multipart overhead

SECURITY_HEADERS = [
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "same-origin"),
    ("Content-Security-Policy",
     "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
     "frame-ancestors 'none'; form-action 'self'"),
]


# ---------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------
class HttpError(Exception):
    """Raise this in a handler to send an error response: raise HttpError(400, "message")."""

    def __init__(self, status, message, details=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.details = details


# ---------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------
def _json_default(value):
    """Make database values (dates, decimals) JSON friendly."""
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (set, frozenset)):
        return list(value)
    raise TypeError(f"Cannot serialise {type(value).__name__}")


class Response:
    def __init__(self, body=b"", status=200, content_type="application/json; charset=utf-8", headers=None):
        self.status = status
        self.body = body if isinstance(body, bytes) else str(body).encode("utf-8")
        self.headers = [("Content-Type", content_type)]
        if headers:
            self.headers.extend(headers)

    def add_header(self, name, value):
        self.headers.append((name, value))
        return self

    def set_cookie(self, name, value, max_age=None, http_only=True, same_site="Lax", secure=False, path="/"):
        parts = [f"{name}={value}", f"Path={path}", f"SameSite={same_site}"]
        if http_only:
            parts.append("HttpOnly")
        if secure:
            parts.append("Secure")          # turn on when the site is served over HTTPS
        if max_age is not None:
            parts.append(f"Max-Age={int(max_age)}")
        self.headers.append(("Set-Cookie", "; ".join(parts)))
        return self

    def clear_cookie(self, name, path="/"):
        self.headers.append(("Set-Cookie", f"{name}=; Path={path}; HttpOnly; SameSite=Lax; Max-Age=0"))
        return self


def json_response(data, status=200):
    body = json.dumps(data, default=_json_default, ensure_ascii=False).encode("utf-8")
    return Response(body, status)


def error_response(exc):
    payload = {"error": exc.message}
    if exc.details:
        payload["details"] = exc.details
    return _finalize(json_response(payload, exc.status), is_api=True)


def _finalize(response, is_api):
    """Add security headers (and no-cache for API calls) to every response."""
    for name, value in SECURITY_HEADERS:
        response.add_header(name, value)
    if is_api:
        response.add_header("Cache-Control", "no-store")
    return response


def _to_response(result):
    if isinstance(result, Response):
        return result
    if result is None:
        return json_response({"ok": True})
    if isinstance(result, tuple) and len(result) == 2:
        return json_response(result[0], result[1])
    return json_response(result)


# ---------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------
class Request:
    def __init__(self, method, target, headers, raw_body, client_ip):
        parts = urlsplit(target)
        self.method = method.upper()
        self.path = unquote(parts.path) or "/"
        self.query = {k: v[0] for k, v in parse_qs(parts.query, keep_blank_values=True).items()}
        self.headers = headers                    # case-insensitive when it comes from http.server
        self.raw_body = raw_body or b""
        self.client_ip = client_ip
        self.params = {}                          # path parameters, filled by the router
        self.user = None                          # filled by auth_utils (logged-in student)
        self.session = None                       # filled by auth_utils
        self.cookies = {}
        cookie_header = self.headers.get("Cookie", "")
        if cookie_header:
            try:
                jar = SimpleCookie()
                jar.load(cookie_header)
                self.cookies = {k: m.value for k, m in jar.items()}
            except Exception:
                self.cookies = {}

    @property
    def content_type(self):
        return (self.headers.get("Content-Type", "") or "").lower()

    def json(self):
        """Parse the body as a JSON object (dict) or answer 400."""
        if not self.raw_body:
            raise HttpError(400, "The request body is empty.")
        try:
            data = json.loads(self.raw_body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise HttpError(400, "The request body must be valid JSON.")
        if not isinstance(data, dict):
            raise HttpError(400, "The JSON body must be an object.")
        return data

    def multipart(self):
        """
        Parse a multipart/form-data body (used for the CV upload).
        Returns (fields, files):
            fields = {"name": "text value"}
            files  = {"cv": {"filename": "...", "content": b"...", "content_type": "..."}}
        """
        content_type = self.headers.get("Content-Type", "") or ""
        if not content_type.lower().startswith("multipart/form-data"):
            raise HttpError(400, "Expected a multipart/form-data upload.")
        raw = (b"Content-Type: " + content_type.encode("latin-1", "replace")
               + b"\r\nMIME-Version: 1.0\r\n\r\n" + self.raw_body)
        try:
            message = BytesParser(policy=HTTP_POLICY).parsebytes(raw)
            fields, files = {}, {}
            for part in message.iter_parts():
                name = part.get_param("name", header="content-disposition")
                if not name:
                    continue
                payload = part.get_payload(decode=True) or b""
                filename = part.get_filename()
                if filename is not None:
                    files[name] = {"filename": filename, "content": payload,
                                   "content_type": part.get_content_type()}
                else:
                    fields[name] = payload.decode("utf-8", "replace")
            return fields, files
        except HttpError:
            raise
        except Exception:
            raise HttpError(400, "The upload could not be read.")


# ---------------------------------------------------------------------
# Static files (the frontend folder)
# ---------------------------------------------------------------------
def serve_static(url_path):
    relative = url_path.lstrip("/") or "index.html"
    if "\x00" in relative or any(part.startswith(".") for part in relative.split("/") if part):
        raise HttpError(404, "Not found.")
    root = config.FRONTEND_DIR.resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):                 # blocks ../ path traversal
        raise HttpError(404, "Not found.")
    if target.is_dir() or not target.exists():
        html_version = target.with_name(target.name + ".html")     # /dashboard -> dashboard.html
        if html_version.is_file():
            target = html_version
        else:
            raise HttpError(404, "Page not found.")
    guessed, _ = mimetypes.guess_type(str(target))
    content_type = guessed or "application/octet-stream"
    if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
        content_type += "; charset=utf-8"
    response = Response(target.read_bytes(), 200, content_type)
    response.add_header("Cache-Control", "no-cache")
    return _finalize(response, is_api=False)


# ---------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------
class Router:
    def __init__(self):
        self._routes = []

    def add(self, method, pattern, handler):
        regex = re.compile("^" + re.sub(r"<int:(\w+)>", r"(?P<\1>\\d{1,18})", pattern) + "$")
        self._routes.append((method.upper(), regex, handler))

    def dispatch(self, req):
        """Turn a Request into a Response. Never raises."""
        try:
            if req.path.startswith("/api/"):
                return _finalize(self._dispatch_api(req), is_api=True)
            if req.method in ("GET", "HEAD"):
                return serve_static(req.path)
            raise HttpError(405, "Method not allowed.")
        except HttpError as exc:
            return error_response(exc)
        except Exception:
            traceback.print_exc()
            return error_response(HttpError(500, "Something went wrong on the server."))

    def _dispatch_api(self, req):
        path_matched = False
        for method, regex, handler in self._routes:
            match = regex.match(req.path)
            if not match:
                continue
            path_matched = True
            if method != req.method:
                continue
            if req.method in STATE_CHANGING:
                if req.headers.get(CSRF_HEADER, "") != CSRF_VALUE:
                    raise HttpError(403, "Missing request header.")
                if "multipart/form-data" not in req.content_type and len(req.raw_body) > MAX_JSON_BYTES:
                    raise HttpError(413, "The request is too large.")
            req.params = {k: int(v) for k, v in match.groupdict().items()}
            return _to_response(handler(req))
        if path_matched:
            raise HttpError(405, "Method not allowed.")
        raise HttpError(404, "API route not found.")


router = Router()


def route(method, pattern):
    """Decorator that registers a handler:  @route("GET", "/api/profile")"""
    def decorator(fn):
        router.add(method, pattern, fn)
        return fn
    return decorator


# Quick self-test:  python router.py
if __name__ == "__main__":
    @route("GET", "/api/ping")
    def _ping(req):
        return {"pong": True}

    @route("GET", "/api/things/<int:thing_id>")
    def _thing(req):
        return {"thing_id": req.params["thing_id"]}

    checks = [
        ("GET", "/api/ping"),
        ("GET", "/api/things/42"),
        ("GET", "/api/things/abc"),
        ("POST", "/api/ping"),
        ("GET", "/../backend/.env"),
    ]
    for method, target in checks:
        result = router.dispatch(Request(method, target, {}, b"", "127.0.0.1"))
        print(f"{method:5} {target:22} -> {result.status}  {result.body[:60]}")