"""Student CV upload and download.

Files live in the student_cvs table (see 10_cv_alerts_invites.sql), so they
are only reachable through signed-in API calls. Vercel limits request bodies
to 4.5 MB, so CVs are capped at 4 MB.
"""

from __future__ import annotations

import re

from psycopg.rows import dict_row, tuple_row

from .service import StudentError

MAX_CV_BYTES = 4 * 1024 * 1024
PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_EXTENSION = {PDF: "pdf", DOCX: "docx"}
_UNSAFE = re.compile(r"[^A-Za-z0-9 ._()-]+")


def detect_type(data: bytes) -> str:
    """Work out the file type from its contents, not its name."""
    if data.startswith(b"%PDF-"):
        return PDF
    # A .docx is a zip file that contains word/document.xml.
    if data.startswith(b"PK\x03\x04") and b"word/" in data[:65536]:
        return DOCX
    raise StudentError(415, "UNSUPPORTED_CV", "Upload your CV as a PDF or Word (.docx) file.")


def clean_filename(name: str | None, content_type: str) -> str:
    base = _UNSAFE.sub("", (name or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]).strip(" .")
    base = re.sub(r"\.(pdf|docx?)$", "", base, flags=re.IGNORECASE)[:150] or "CV"
    return f"{base}.{_EXTENSION[content_type]}"


def storage_path(student_id: int, content_type: str) -> str:
    return f"db/{student_id}.{_EXTENSION[content_type]}"


def save_cv(conn, student_id: int, data: bytes, filename: str | None) -> dict:
    if not data:
        raise StudentError(422, "EMPTY_CV", "That file is empty.")
    if len(data) > MAX_CV_BYTES:
        raise StudentError(413, "CV_TOO_LARGE", "Your CV must be 4 MB or smaller.")
    content_type = detect_type(data)
    name = clean_filename(filename, content_type)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO student_cvs (student_id, filename, content_type, size_bytes, data)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (student_id) DO UPDATE
            SET filename = EXCLUDED.filename, content_type = EXCLUDED.content_type,
                size_bytes = EXCLUDED.size_bytes, data = EXCLUDED.data, uploaded_at = now()
            """,
            (student_id, name, content_type, len(data), data),
        )
        cur.execute(
            "UPDATE student_profiles SET cv_path = %s, cv_uploaded_at = now() WHERE student_id = %s",
            (storage_path(student_id, content_type), student_id),
        )
    return cv_info(conn, student_id)


def cv_info(conn, student_id: int) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            "SELECT filename, content_type, size_bytes, uploaded_at FROM student_cvs WHERE student_id = %s",
            (student_id,),
        ).fetchone()
    return {"cv": row}


def delete_cv(conn, student_id: int) -> dict:
    conn.execute(
        "UPDATE student_profiles SET cv_path = NULL, cv_uploaded_at = NULL WHERE student_id = %s",
        (student_id,),
    )
    conn.execute("DELETE FROM student_cvs WHERE student_id = %s", (student_id,))
    return {"cv": None}


def read_cv(conn, student_id: int) -> dict:
    """The student's own CV file."""
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            "SELECT filename, content_type, data FROM student_cvs WHERE student_id = %s",
            (student_id,),
        ).fetchone()
    if row is None:
        raise StudentError(404, "CV_NOT_FOUND", "You haven't uploaded a CV yet.")
    return row


class DatabaseCvStorage:
    """Storage for the employer module: reads 'db/...' CVs from student_cvs.

    Older paths (files on disk) fall back to the previous storage, so nothing
    uploaded before this change stops working.
    """

    _PATH = re.compile(r"^db/(\d+)\.(pdf|docx)$")

    def __init__(self, pool, fallback=None):
        self._pool = pool
        self._fallback = fallback

    def read_bytes(self, path: str) -> bytes:
        match = self._PATH.fullmatch(str(path))
        if match is None:
            if self._fallback is None:
                raise FileNotFoundError(path)
            return self._fallback.read_bytes(path)
        with self._pool.connection() as conn, conn.cursor(row_factory=tuple_row) as cur:
            row = cur.execute("SELECT data FROM student_cvs WHERE student_id = %s", (int(match.group(1)),)).fetchone()
        if row is None:
            raise FileNotFoundError(path)
        return bytes(row[0])
