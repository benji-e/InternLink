"""Provision initial InternLink accounts in an already-migrated PostgreSQL database."""

from __future__ import annotations

import argparse
import os
import secrets
import sys

import bcrypt
import psycopg
from psycopg.rows import dict_row


ACCOUNTS = (
    ("admin@internlink.ug", "Platform Administrator", "admin"),
    ("coordinator@must.ac.ug", "University Coordinator", "coordinator"),
    ("student@std.must.ac.ug", "InternLink Student", "student"),
    ("employer@internlink.example", "InternLink Employer", "employer"),
)


def password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def generate_passwords() -> dict[str, str]:
    passwords: dict[str, str] = {}
    for email, _name, _role in ACCOUNTS:
        password = secrets.token_urlsafe(20)
        while password in passwords.values():
            password = secrets.token_urlsafe(20)
        passwords[email] = password
    return passwords


def ensure_user(conn, email: str, name: str, role: str, password: str, *, rotate: bool, **scope) -> tuple[int, bool]:
    existing = conn.execute(
        "SELECT user_id, role, status, email_verified_at, company_id, university_id, department_id "
        "FROM users WHERE lower(email) = lower(%s) FOR UPDATE",
        (email,),
    ).fetchone()
    if existing:
        if existing["role"] != role:
            raise RuntimeError(f"{email} already exists with role {existing['role']!r}, expected {role!r}")
        for field, expected in scope.items():
            if existing[field] != expected:
                raise RuntimeError(f"{email} is linked to a different {field}; refusing to change account scope.")
        if existing["status"] != "active" or existing["email_verified_at"] is None:
            if not rotate:
                raise RuntimeError(f"{email} exists but is not active and verified; rerun with --rotate-existing to activate it.")
        if rotate:
            conn.execute(
                "UPDATE users SET password_hash = %s, status = 'active', email_verified_at = coalesce(email_verified_at, now()) WHERE user_id = %s",
                (password_hash(password), existing["user_id"]),
            )
            return int(existing["user_id"]), True
        return int(existing["user_id"]), False

    fields = {
        "email": email,
        "full_name": name,
        "role": role,
        "status": "active",
        "email_verified_at": "now()",
        "password_hash": password_hash(password),
        **scope,
    }
    columns = list(fields)
    expressions = ["now()" if value == "now()" else "%s" for value in fields.values()]
    values = [value for value in fields.values() if value != "now()"]
    row = conn.execute(
        f"INSERT INTO users ({', '.join(columns)}) VALUES ({', '.join(expressions)}) RETURNING user_id",
        values,
    ).fetchone()
    return int(row["user_id"]), True


def ensure_university(conn, admin_id: int) -> int:
    row = conn.execute(
        "SELECT university_id FROM universities WHERE lower(email_domain) = 'must.ac.ug'"
    ).fetchone()
    if row:
        university_id = int(row["university_id"])
        conn.execute(
            """
            UPDATE universities SET status = 'verified', verified_by = %s,
                   verified_at = coalesce(verified_at, now())
            WHERE university_id = %s
            """,
            (admin_id, university_id),
        )
        return university_id
    row = conn.execute(
        """
        INSERT INTO universities (name, location, email_domain, status, verified_by, verified_at)
        VALUES ('Mbarara University of Science and Technology', 'Mbarara', 'must.ac.ug',
                'verified', %s, now())
        RETURNING university_id
        """,
        (admin_id,),
    ).fetchone()
    return int(row["university_id"])


def ensure_department_programme(conn, university_id: int) -> tuple[int, int]:
    row = conn.execute(
        "SELECT department_id FROM departments WHERE university_id = %s AND lower(name) = 'software engineering'",
        (university_id,),
    ).fetchone()
    department_id = int(row["department_id"]) if row else int(
        conn.execute(
            "INSERT INTO departments (university_id, name) VALUES (%s, 'Software Engineering') RETURNING department_id",
            (university_id,),
        ).fetchone()["department_id"]
    )
    row = conn.execute(
        "SELECT programme_id FROM programmes WHERE department_id = %s AND lower(name) = 'bsc software engineering'",
        (department_id,),
    ).fetchone()
    programme_id = int(row["programme_id"]) if row else int(
        conn.execute(
            "INSERT INTO programmes (department_id, name, programme_group) VALUES (%s, 'BSc Software Engineering', 'computing') RETURNING programme_id",
            (department_id,),
        ).fetchone()["programme_id"]
    )
    return department_id, programme_id


def ensure_skills(conn) -> list[int]:
    skill_ids = []
    for name in ("Python", "SQL", "React"):
        row = conn.execute(
            "SELECT skill_id FROM skills WHERE lower(name) = lower(%s)",
            (name,),
        ).fetchone()
        skill_ids.append(
            int(row["skill_id"]) if row else int(
                conn.execute(
                    "INSERT INTO skills (name) VALUES (%s) RETURNING skill_id",
                    (name,),
                ).fetchone()["skill_id"]
            )
        )
    return skill_ids


def ensure_company(conn, admin_id: int) -> int:
    row = conn.execute(
        "SELECT company_id FROM companies WHERE lower(name) = 'internlink demo employer'"
    ).fetchone()
    if row:
        company_id = int(row["company_id"])
        conn.execute(
            """
            UPDATE companies SET verification_status = 'verified', verified_by = %s,
                   verified_at = coalesce(verified_at, now())
            WHERE company_id = %s
            """,
            (admin_id, company_id),
        )
        return company_id
    row = conn.execute(
        """
        INSERT INTO companies (name, sector, location, description, contact_email,
                               verification_status, verified_by, verified_at)
        VALUES ('InternLink Demo Employer', 'Technology', 'Kampala',
                'Initial employer account for InternLink deployment setup.',
                'employer@internlink.example', 'verified', %s, now())
        RETURNING company_id
        """,
        (admin_id,),
    ).fetchone()
    return int(row["company_id"])


def ensure_listing(conn, employer_id: int, company_id: int, programme_id: int, skill_ids: list[int]) -> None:
    existing = conn.execute(
        "SELECT listing_id FROM listings WHERE company_id = %s AND title = 'Software Engineering Intern'",
        (company_id,),
    ).fetchone()
    if existing:
        return
    conn.execute("SELECT set_config('app.user_id', %s, true)", (str(employer_id),))
    listing_id = int(
        conn.execute(
            """
            INSERT INTO listings (company_id, posted_by, title, description, sector, location,
                                  is_remote, duration_weeks, slots, application_deadline, status)
            VALUES (%s, %s, 'Software Engineering Intern',
                    'Build and test web application features with the engineering team.',
                    'Technology', 'Kampala', false, 12, 1, CURRENT_DATE + 30, 'open')
            RETURNING listing_id
            """,
            (company_id, employer_id),
        ).fetchone()["listing_id"]
    )
    conn.execute(
        "INSERT INTO listing_programmes (listing_id, programme_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (listing_id, programme_id),
    )
    for skill_id in skill_ids:
        conn.execute(
            "INSERT INTO listing_skills (listing_id, skill_id, is_required) VALUES (%s, %s, true) ON CONFLICT DO NOTHING",
            (listing_id, skill_id),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rotate-existing",
        action="store_true",
        help="Replace passwords for matching bootstrap email addresses and print the new credentials.",
    )
    args = parser.parse_args()
    dsn = os.environ.get("INTERNLINK_DSN")
    if not dsn:
        parser.error("Set INTERNLINK_DSN to the hosted PostgreSQL connection string first.")

    passwords = generate_passwords()
    created: dict[str, bool] = {}
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        with conn.transaction():
            conn.execute("SELECT set_config('app.allow_role_change', 'on', true)")
            admin_id, created[ACCOUNTS[0][0]] = ensure_user(
                conn, *ACCOUNTS[0], passwords[ACCOUNTS[0][0]], rotate=args.rotate_existing
            )
            conn.execute("SELECT set_config('app.allow_role_change', 'off', true)")
            conn.execute("SELECT set_config('app.user_id', %s, true)", (str(admin_id),))
            university_id = ensure_university(conn, admin_id)
            department_id, programme_id = ensure_department_programme(conn, university_id)
            skill_ids = ensure_skills(conn)

            coordinator_id, created[ACCOUNTS[1][0]] = ensure_user(
                conn,
                *ACCOUNTS[1],
                passwords[ACCOUNTS[1][0]],
                rotate=args.rotate_existing,
                university_id=university_id,
                department_id=department_id,
            )
            student_id, created[ACCOUNTS[2][0]] = ensure_user(
                conn, *ACCOUNTS[2], passwords[ACCOUNTS[2][0]], rotate=args.rotate_existing
            )
            conn.execute("SELECT set_config('app.user_id', %s, true)", (str(coordinator_id),))
            profile = conn.execute(
                "SELECT student_id FROM student_profiles WHERE user_id = %s",
                (student_id,),
            ).fetchone()
            if not profile:
                profile = conn.execute(
                    """
                    INSERT INTO student_profiles
                        (user_id, university_id, department_id, programme_id, student_number,
                         year_of_study, preferred_location, verified, verified_by, verified_at)
                    VALUES (%s, %s, %s, %s, 'DEMO-0001', 3, 'Kampala', true, %s, now())
                    RETURNING student_id
                    """,
                    (student_id, university_id, department_id, programme_id, coordinator_id),
                ).fetchone()
            for skill_id in skill_ids:
                conn.execute(
                    "INSERT INTO student_skills (student_id, skill_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (profile["student_id"], skill_id),
                )

            company_id = ensure_company(conn, admin_id)
            employer_id, created[ACCOUNTS[3][0]] = ensure_user(
                conn,
                *ACCOUNTS[3],
                passwords[ACCOUNTS[3][0]],
                rotate=args.rotate_existing,
                company_id=company_id,
            )
            ensure_listing(conn, employer_id, company_id, programme_id, skill_ids)

    print("Initial InternLink accounts (save these credentials; passwords are shown only for accounts created or rotated now):")
    for email, name, role in ACCOUNTS:
        if created[email]:
            print(f"{role}: {email} / {passwords[email]}")
        else:
            print(f"{role}: {email} (already exists; password retained)")
    print("Also seeded one verified university, coordinator, student profile, employer and open internship.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, psycopg.Error, RuntimeError, ValueError) as error:
        print(f"Bootstrap failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
