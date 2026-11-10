"""Internships a student saved to look at or apply for later."""

from __future__ import annotations

from psycopg.rows import dict_row

from .service import StudentError

MAX_SAVED = 200


def list_saved(conn, student_id: int) -> list[dict]:
    """Saved internships, soonest deadline first. Closed ones stay listed, marked as closed."""
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            """
            SELECT l.listing_id, l.title, c.name AS company_name, l.sector, l.location, l.is_remote,
                   l.duration_weeks, l.application_deadline, s.saved_at,
                   EXISTS (SELECT 1 FROM v_open_listings v WHERE v.listing_id = l.listing_id) AS is_open,
                   a.status AS application_status
            FROM saved_listings s
            JOIN listings l ON l.listing_id = s.listing_id
            JOIN companies c ON c.company_id = l.company_id
            LEFT JOIN applications a ON a.listing_id = l.listing_id AND a.student_id = s.student_id
            WHERE s.student_id = %s
            ORDER BY is_open DESC, l.application_deadline, l.listing_id
            """,
            (student_id,),
        ).fetchall()


def save(conn, student_id: int, listing_id: int) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        if not cur.execute("SELECT 1 FROM v_open_listings WHERE listing_id = %s", (listing_id,)).fetchone():
            raise StudentError(404, "LISTING_NOT_FOUND", "This internship is closed or no longer available.")
        count = cur.execute("SELECT count(*) AS n FROM saved_listings WHERE student_id = %s", (student_id,)).fetchone()["n"]
        if count >= MAX_SAVED:
            raise StudentError(409, "TOO_MANY_SAVED", f"You can save up to {MAX_SAVED} internships. Remove some first.")
        cur.execute(
            "INSERT INTO saved_listings (student_id, listing_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (student_id, listing_id),
        )
    return {"listing_id": listing_id, "saved": True}


def unsave(conn, student_id: int, listing_id: int) -> dict:
    conn.execute("DELETE FROM saved_listings WHERE student_id = %s AND listing_id = %s", (student_id, listing_id))
    return {"listing_id": listing_id, "saved": False}
