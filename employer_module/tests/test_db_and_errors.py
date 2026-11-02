"""Tests for the database adapters, transactions and error translation."""

import json
import unittest

from internlink_employer.db import MySQLDatabase, SQLiteDatabase
from internlink_employer.errors import DatabaseIntegrityError, translate_db_error
from tests.support import add_company, seed_reference


class SQLiteAdapterTests(unittest.TestCase):
    def setUp(self):
        self.db = SQLiteDatabase(":memory:")

    def tearDown(self):
        self.db.close()

    def test_schema_view_and_reference_tables_exist(self):
        row = self.db.query_one("SELECT count(*) AS n FROM v_employer_applicants")
        self.assertEqual(row["n"], 0)
        tables = {
            row["name"]
            for row in self.db.query_all(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        for name in (
            "companies",
            "users",
            "listings",
            "applications",
            "placements",
            "messages",
            "notifications",
            "audit_log",
            "student_skills",
        ):
            self.assertIn(name, tables)

    def test_insert_returning_ids_and_queries(self):
        company_id = add_company(self.db)
        self.assertGreater(company_id, 0)
        row = self.db.query_one(
            "SELECT name FROM companies WHERE company_id = %s", [company_id]
        )
        self.assertIn("Company", row["name"])
        self.assertIsNone(self.db.query_one("SELECT * FROM companies WHERE company_id = 999"))

    def test_transaction_commits_and_rolls_back(self):
        with self.db.transaction():
            company_id = add_company(self.db, "Committed Co")
        self.assertEqual(
            self.db.query_one("SELECT name FROM companies WHERE company_id = %s", [company_id])[
                "name"
            ],
            "Committed Co",
        )

        with self.assertRaises(RuntimeError):
            with self.db.transaction():
                add_company(self.db, "Rolled Back Co")
                raise RuntimeError("boom")
        self.assertIsNone(
            self.db.query_one("SELECT * FROM companies WHERE name = %s", ["Rolled Back Co"])
        )

    def test_nested_transaction_joins_outer_transaction(self):
        with self.assertRaises(RuntimeError):
            with self.db.transaction():
                with self.db.transaction():
                    add_company(self.db, "Nested Co")
                raise RuntimeError("abort outer")
        self.assertIsNone(
            self.db.query_one("SELECT * FROM companies WHERE name = %s", ["Nested Co"])
        )

    def test_count_existing_deduplicates_and_rejects_unknown_table(self):
        refs = seed_reference(self.db)
        ids = [refs["skill_python"], refs["skill_python"], refs["skill_sql"]]
        self.assertEqual(self.db.count_existing("skills", ids), 2)
        self.assertEqual(self.db.count_existing("skills", []), 0)
        with self.assertRaises(ValueError):
            self.db.count_existing("users", [1])

    def test_unsafe_identifiers_are_rejected(self):
        with self.assertRaises(ValueError):
            self.db.insert("companies; DROP TABLE users", {"name": "x"})
        with self.assertRaises(ValueError):
            self.db.insert("companies", {"name; DROP": "x"})

    def test_unique_and_check_constraints_are_normalised(self):
        add_company(self.db, "Unique Co")
        with self.assertRaises(DatabaseIntegrityError) as caught:
            add_company(self.db, "Unique Co")
        self.assertEqual(caught.exception.constraint_name, "uq_companies_name")
        self.assertEqual(translate_db_error(caught.exception).category, "conflict")

        company_id = self.db.query_one(
            "SELECT company_id FROM companies WHERE name = %s", ["Unique Co"]
        )["company_id"]
        with self.assertRaises(DatabaseIntegrityError) as caught:
            self.db.execute(
                "UPDATE companies SET verification_status = 'nonsense' WHERE company_id = %s",
                [company_id],
            )
        self.assertEqual(caught.exception.constraint_name, "ck_companies_verification")
        error = translate_db_error(caught.exception)
        self.assertEqual(error.category, "invalid")
        self.assertIn("outside the allowed range", error.message)

    def test_log_event_uses_actor_and_serialises_details(self):
        company_id = add_company(self.db)
        user_id = self.db.insert_returning_id(
            "users",
            {
                "email": "audit@example.com",
                "password_hash": "x",
                "full_name": "Auditor",
                "role": "employer",
                "status": "active",
                "company_id": company_id,
            },
        )
        self.db.set_actor(user_id)
        self.db.log_event(
            "test_action", "companies", company_id, result="success", details={"x": 1}
        )
        row = self.db.query_one("SELECT * FROM audit_log ORDER BY event_id DESC LIMIT 1")
        self.assertEqual(row["actor_user_id"], user_id)
        self.assertEqual(row["action"], "test_action")
        self.assertEqual(row["entity_id"], str(company_id))
        self.assertEqual(json.loads(row["details"]), {"x": 1})
        self.db.set_actor(None)
        self.db.log_event("anonymous_action")
        row = self.db.query_one("SELECT * FROM audit_log ORDER BY event_id DESC LIMIT 1")
        self.assertIsNone(row["actor_user_id"])

    def test_rule_code_in_database_message_translates(self):
        error = translate_db_error(
            DatabaseIntegrityError("RULE_SR08_DEADLINE_PAST: deadline is old")
        )
        self.assertEqual(error.category, "invalid")
        self.assertIn("today or later", error.message)
        unknown = translate_db_error(DatabaseIntegrityError("some other failure"))
        self.assertEqual(unknown.category, "conflict")


class MySQLAdapterTests(unittest.TestCase):
    def test_mysql_adapter_has_clear_optional_dependency_error(self):
        try:
            import pymysql  # noqa: F401
        except ImportError:
            with self.assertRaises(RuntimeError) as caught:
                MySQLDatabase(user="root", database="internlink")
            self.assertIn("PyMySQL", str(caught.exception))
        else:  # pragma: no cover - environment dependent
            self.skipTest("PyMySQL is installed; live database is not configured")

    def test_mysql_unique_key_error_names_are_normalised(self):
        error = MySQLDatabase._normalise_integrity_error(
            Exception(
                1062,
                "Duplicate entry 'Acme' for key 'companies.uq_companies_name'",
            )
        )
        self.assertEqual(error.constraint_name, "uq_companies_name")
        self.assertEqual(translate_db_error(error).category, "conflict")

    def test_mysql_check_and_foreign_key_errors_are_normalised(self):
        check = MySQLDatabase._normalise_integrity_error(
            Exception("Check constraint 'ck_listings_slots' is violated.")
        )
        self.assertEqual(check.constraint_name, "ck_listings_slots")
        self.assertEqual(translate_db_error(check).category, "invalid")

        foreign_key = MySQLDatabase._normalise_integrity_error(
            Exception(
                1452,
                "Cannot add or update a child row: a foreign key constraint fails "
                "(`internlink`.`listings`, CONSTRAINT `fk_listings_company` "
                "FOREIGN KEY (`company_id`) REFERENCES `companies` (`company_id`))",
            )
        )
        self.assertEqual(foreign_key.constraint_name, "fk_listings_company")
        self.assertEqual(translate_db_error(foreign_key).category, "invalid")


if __name__ == "__main__":
    unittest.main()
