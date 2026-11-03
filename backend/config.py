"""
config.py - loads settings from backend/.env and exposes them as constants.
No third-party library is used to read the .env file.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent          # .../internlink-student/backend
PROJECT_DIR = BASE_DIR.parent                       # .../internlink-student
FRONTEND_DIR = PROJECT_DIR / "frontend"             # .../internlink-student/frontend


def _load_env_file(path: Path) -> None:
    """Read KEY=VALUE lines from .env into os.environ (existing variables win)."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_env_file(BASE_DIR / ".env")


def _bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


# ---- Core settings ----
SECRET_KEY = os.environ.get("SECRET_KEY", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))

# ---- Behaviour switches ----
AUTO_VERIFY_EMAIL = _bool("AUTO_VERIFY_EMAIL", True)

# ---- CV uploads (schema: pdf or docx, at most 5 MB) ----
_upload_dir = Path(os.environ.get("UPLOAD_DIR", "uploads/cvs"))
UPLOAD_DIR = _upload_dir if _upload_dir.is_absolute() else BASE_DIR / _upload_dir
MAX_CV_BYTES = int(os.environ.get("MAX_CV_BYTES", "5242880"))
ALLOWED_CV_EXTENSIONS = (".pdf", ".docx")

# ---- Security rules (from your schema comments) ----
BCRYPT_ROUNDS = 12            # users.password_hash comment: bcrypt cost 12
MAX_FAILED_LOGINS = 5         # users.failed_login_count comment: 5-attempt lockout
LOCK_MINUTES = 15
SESSION_HOURS = 8
SESSION_COOKIE = "internlink_session"
MIN_PASSWORD_LENGTH = 8

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing. Add it to backend/.env")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY is missing. Add it to backend/.env")