"""Add Ugandan universities, departments and programmes so students can sign up.

Safe to run more than once: it only adds what is missing and never changes or
deletes existing rows. A university that already exists (matched by name or
email domain) keeps its status; only missing departments and programmes are
added to it. New universities are added as verified.

Coordinators can add more departments and programmes from the app afterwards
(University workspace -> Departments & programmes).

Usage:
    INTERNLINK_DSN=postgresql://... python scripts/seed_catalog.py [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import sys

import psycopg
from psycopg.rows import dict_row

# (name, location, email_domain, {department: [(programme, programme_group), ...]})
# Students must register with an email on the university's domain (or a
# subdomain such as std.must.ac.ug), so only add universities whose domain is known.
CATALOG: list[tuple[str, str, str, dict[str, list[tuple[str, str]]]]] = [
    ("Mbarara University of Science and Technology", "Mbarara", "must.ac.ug", {
        "Software Engineering": [("BSc Software Engineering", "computing")],
        "Computer Science": [("BSc Computer Science", "computing")],
        "Information Technology": [("BSc Information Technology", "computing")],
        "Electrical and Electronics Engineering": [("BSc Electrical and Electronics Engineering", "engineering")],
        "Civil Engineering": [("BSc Civil Engineering", "engineering")],
        "Biomedical Engineering": [("BSc Biomedical Engineering", "engineering")],
        "Accounting and Finance": [("Bachelor of Accounting and Finance", "business")],
        "Business Administration": [("Bachelor of Business Administration", "business")],
        "Economics": [("BSc Economics", "business")],
        "Nursing": [("Bachelor of Nursing Science", "health")],
        "Pharmacy": [("Bachelor of Pharmacy", "health")],
        "Medical Laboratory Science": [("Bachelor of Medical Laboratory Science", "health")],
        "Medicine": [("Bachelor of Medicine and Bachelor of Surgery", "health")],
        "Biology": [("BSc Biology", "science")],
        "Education": [("Bachelor of Science with Education", "education")],
        "Development Studies": [("Bachelor of Development Studies", "social_sciences")],
    }),
    ("Makerere University", "Kampala", "mak.ac.ug", {
        "Computer Science": [("BSc Computer Science", "computing")],
        "Information Technology": [("BSc Information Technology", "computing")],
        "Software Engineering": [("BSc Software Engineering", "computing")],
        "Information Systems": [("Bachelor of Information Systems and Technology", "computing")],
        "Electrical and Computer Engineering": [
            ("BSc Electrical Engineering", "engineering"),
            ("BSc Computer Engineering", "engineering"),
            ("BSc Telecommunications Engineering", "engineering"),
        ],
        "Civil and Environmental Engineering": [("BSc Civil Engineering", "engineering")],
        "Mechanical Engineering": [("BSc Mechanical Engineering", "engineering")],
        "Accounting": [("Bachelor of Commerce", "business")],
        "Business Administration": [("Bachelor of Business Administration", "business")],
        "Economics": [("Bachelor of Arts in Economics", "business")],
        "Statistics": [("Bachelor of Science in Statistics", "science")],
        "Agriculture": [("BSc Agriculture", "agriculture")],
        "Agribusiness": [("BSc Agribusiness Management", "agriculture")],
        "Nursing": [("Bachelor of Nursing", "health")],
        "Medicine": [("Bachelor of Medicine and Bachelor of Surgery", "health")],
        "Law": [("Bachelor of Laws", "law")],
        "Mass Communication": [("Bachelor of Arts in Journalism and Communication", "arts")],
        "Education": [("Bachelor of Education", "education")],
        "Social Work": [("Bachelor of Social Work and Social Administration", "social_sciences")],
    }),
    ("Kyambogo University", "Kampala", "kyu.ac.ug", {
        "Computer Science": [("BSc Computer Science", "computing")],
        "Information Technology": [("Bachelor of Information Technology and Computing", "computing")],
        "Electrical and Electronics Engineering": [("BEng Electrical Engineering", "engineering")],
        "Civil and Building Engineering": [("BEng Civil and Building Engineering", "engineering")],
        "Mechanical and Production Engineering": [("BEng Mechanical and Manufacturing Engineering", "engineering")],
        "Accounting and Finance": [("Bachelor of Accounting and Finance", "business")],
        "Business Administration": [("Bachelor of Business Administration", "business")],
        "Education": [("Bachelor of Education", "education")],
        "Special Needs Education": [("Bachelor of Special Needs Education", "education")],
    }),
    ("Gulu University", "Gulu", "gu.ac.ug", {
        "Computer Science": [("BSc Computer Science", "computing")],
        "Information Technology": [("Bachelor of Information Technology", "computing")],
        "Business Administration": [("Bachelor of Business Administration", "business")],
        "Agriculture": [("BSc Agriculture", "agriculture")],
        "Medicine": [("Bachelor of Medicine and Bachelor of Surgery", "health")],
        "Nursing": [("Bachelor of Nursing Science", "health")],
        "Education": [("Bachelor of Science with Education", "education")],
        "Development Studies": [("Bachelor of Development Studies", "social_sciences")],
    }),
    ("Busitema University", "Tororo", "busitema.ac.ug", {
        "Computer Engineering": [("BSc Computer Engineering", "engineering")],
        "Mechanical Engineering": [("BSc Agricultural Mechanisation and Irrigation Engineering", "engineering")],
        "Water Resources Engineering": [("BSc Water Resources Engineering", "engineering")],
        "Agriculture": [("BSc Agriculture", "agriculture")],
        "Business Administration": [("Bachelor of Business Administration", "business")],
        "Education": [("Bachelor of Science with Education", "education")],
    }),
    ("Uganda Christian University", "Mukono", "ucu.ac.ug", {
        "Computing and Technology": [
            ("BSc Computer Science", "computing"),
            ("BSc Information Technology", "computing"),
        ],
        "Engineering": [("BSc Civil Engineering", "engineering"), ("BSc Electrical Engineering", "engineering")],
        "Business Administration": [("Bachelor of Business Administration", "business")],
        "Accounting and Finance": [("Bachelor of Science in Accounting and Finance", "business")],
        "Law": [("Bachelor of Laws", "law")],
        "Journalism and Communication": [("Bachelor of Arts in Mass Communication", "arts")],
        "Nursing": [("Bachelor of Science in Nursing", "health")],
        "Education": [("Bachelor of Arts with Education", "education")],
        "Social Work": [("Bachelor of Social Work and Social Administration", "social_sciences")],
    }),
    ("Kampala International University", "Kampala", "kiu.ac.ug", {
        "Computer Science": [("BSc Computer Science", "computing")],
        "Information Technology": [("Bachelor of Information Technology", "computing")],
        "Software Engineering": [("BSc Software Engineering", "computing")],
        "Electrical Engineering": [("BSc Electrical Engineering", "engineering")],
        "Civil Engineering": [("BSc Civil Engineering", "engineering")],
        "Accounting and Finance": [("Bachelor of Accounting and Finance", "business")],
        "Business Administration": [("Bachelor of Business Administration", "business")],
        "Medicine": [("Bachelor of Medicine and Bachelor of Surgery", "health")],
        "Pharmacy": [("Bachelor of Pharmacy", "health")],
        "Nursing": [("Bachelor of Nursing Science", "health")],
        "Law": [("Bachelor of Laws", "law")],
        "Education": [("Bachelor of Education", "education")],
    }),
    ("Uganda Martyrs University", "Nkozi", "umu.ac.ug", {
        "Computer Science": [("BSc Computer Science", "computing")],
        "Business Administration": [("Bachelor of Business Administration and Management", "business")],
        "Accounting and Finance": [("Bachelor of Accounting and Finance", "business")],
        "Agriculture": [("BSc Agriculture", "agriculture")],
        "Nursing": [("Bachelor of Nursing Science", "health")],
        "Education": [("Bachelor of Arts with Education", "education")],
        "Development Studies": [("Bachelor of Arts in Development Studies", "social_sciences")],
    }),
    ("Kabale University", "Kabale", "kab.ac.ug", {
        "Computer Science": [("BSc Computer Science", "computing")],
        "Information Technology": [("Bachelor of Information Technology", "computing")],
        "Engineering": [("BSc Civil Engineering", "engineering"), ("BSc Electrical Engineering", "engineering")],
        "Business Administration": [("Bachelor of Business Administration", "business")],
        "Agriculture": [("BSc Agriculture", "agriculture")],
        "Medicine": [("Bachelor of Medicine and Bachelor of Surgery", "health")],
        "Nursing": [("Bachelor of Nursing Science", "health")],
        "Education": [("Bachelor of Arts with Education", "education")],
    }),
    ("Muni University", "Arua", "muni.ac.ug", {
        "Computer Science": [("BSc Computer Science", "computing")],
        "Information Technology": [("Bachelor of Information Technology", "computing")],
        "Agriculture": [("BSc Agriculture", "agriculture")],
        "Nursing": [("Bachelor of Nursing Science", "health")],
        "Education": [("Bachelor of Science with Education", "education")],
        "Management": [("Bachelor of Business Management", "business")],
    }),
]


def _admin_id(conn) -> int | None:
    row = conn.execute(
        "SELECT user_id FROM users WHERE role = 'admin' AND status = 'active' ORDER BY user_id LIMIT 1"
    ).fetchone()
    return int(row["user_id"]) if row else None


def ensure_university(conn, name: str, location: str, domain: str, admin_id: int | None) -> tuple[int, bool]:
    row = conn.execute(
        "SELECT university_id FROM universities WHERE lower(name) = lower(%s) OR lower(email_domain) = lower(%s)",
        (name, domain),
    ).fetchone()
    if row:
        return int(row["university_id"]), False
    row = conn.execute(
        """
        INSERT INTO universities (name, location, email_domain, status, verified_by, verified_at)
        VALUES (%s, %s, %s, 'verified', %s, now()) RETURNING university_id
        """,
        (name, location, domain, admin_id),
    ).fetchone()
    return int(row["university_id"]), True


def ensure_department(conn, university_id: int, name: str) -> tuple[int, bool]:
    row = conn.execute(
        "SELECT department_id FROM departments WHERE university_id = %s AND lower(name) = lower(%s)",
        (university_id, name),
    ).fetchone()
    if row:
        return int(row["department_id"]), False
    row = conn.execute(
        "INSERT INTO departments (university_id, name) VALUES (%s, %s) RETURNING department_id",
        (university_id, name),
    ).fetchone()
    return int(row["department_id"]), True


def ensure_programme(conn, department_id: int, name: str, group: str) -> bool:
    if conn.execute(
        "SELECT 1 FROM programmes WHERE department_id = %s AND lower(name) = lower(%s)",
        (department_id, name),
    ).fetchone():
        return False
    conn.execute(
        "INSERT INTO programmes (department_id, name, programme_group) VALUES (%s, %s, %s)",
        (department_id, name, group),
    )
    return True


def seed(conn) -> dict[str, int]:
    counts = {"universities": 0, "departments": 0, "programmes": 0}
    admin_id = _admin_id(conn)
    if admin_id is not None:
        conn.execute("SELECT set_config('app.user_id', %s, true)", (str(admin_id),))
    for name, location, domain, departments in CATALOG:
        university_id, created = ensure_university(conn, name, location, domain, admin_id)
        counts["universities"] += created
        for department, programmes in departments.items():
            department_id, created = ensure_department(conn, university_id, department)
            counts["departments"] += created
            for programme, group in programmes:
                counts["programmes"] += ensure_programme(conn, department_id, programme, group)
    return counts


class _DryRun(Exception):
    pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Show what would be added, then roll back.")
    args = parser.parse_args()
    dsn = os.environ.get("INTERNLINK_DSN")
    if not dsn:
        parser.error("Set INTERNLINK_DSN to the hosted PostgreSQL connection string first.")

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        try:
            with conn.transaction():
                counts = seed(conn)
                if args.dry_run:
                    raise _DryRun
        except _DryRun:
            pass
    verb = "Would add" if args.dry_run else "Added"
    print(f"{verb} {counts['universities']} universities, {counts['departments']} departments "
          f"and {counts['programmes']} programmes.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, psycopg.Error) as error:
        print(f"Catalog seed failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
