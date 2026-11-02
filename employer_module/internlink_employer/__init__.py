"""InternLink Uganda - Employer module (WBS 4.4.1-4.4.5).

Framework-free service layer, dispatch handler, SQLite/PostgreSQL adapters and
a minimal WSGI JSON API.
"""

from .context import AppContext
from .errors import DatabaseIntegrityError, ModuleError, translate_db_error
from .handler import ACTIONS, PUBLIC_ACTIONS, handle, handle_public
from .security import (
    ReferenceTokenService,
    hash_password,
    hash_token,
    new_token,
    verify_password,
)
from .session import Session, open_session

__all__ = [
    "ACTIONS",
    "AppContext",
    "DatabaseIntegrityError",
    "ModuleError",
    "PUBLIC_ACTIONS",
    "ReferenceTokenService",
    "Session",
    "handle",
    "handle_public",
    "hash_password",
    "hash_token",
    "new_token",
    "open_session",
    "translate_db_error",
    "verify_password",
]

__version__ = "1.0.0"
