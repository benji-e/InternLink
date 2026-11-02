"""Storage containment, JSON serialisation and unexpected-error tests."""

import tempfile
import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from internlink_employer.adapters import LocalFileStorage
from internlink_employer.api import to_jsonable
from internlink_employer.handler import ACTIONS, handle
from tests.support import add_employer_account, make_context, session_for


class LocalFileStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "cvs"
        self.root.mkdir()
        (self.root / "nested").mkdir()
        (self.root / "nested" / "cv.pdf").write_bytes(b"pdf bytes")
        (Path(self.temp.name) / "secret.txt").write_bytes(b"secret")
        self.storage = LocalFileStorage(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_reads_files_inside_root(self):
        self.assertEqual(self.storage.read_bytes("nested/cv.pdf"), b"pdf bytes")

    def test_blocks_traversal_and_absolute_paths(self):
        with self.assertRaises(PermissionError):
            self.storage.read_bytes("../secret.txt")
        with self.assertRaises(PermissionError):
            self.storage.read_bytes(str(Path(self.temp.name) / "secret.txt"))

    def test_missing_file_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            self.storage.read_bytes("missing.pdf")


class JsonSerialisationTests(unittest.TestCase):
    def test_nested_dates_decimals_and_bytes(self):
        payload = {
            "day": date(2026, 11, 2),
            "timestamp": datetime(2026, 11, 2, 10, 30, 5),
            "amount": Decimal("10.50"),
            "file": b"abc",
            "rows": [{"flag": True, "value": None}],
        }
        encoded = to_jsonable(payload)
        self.assertEqual(encoded["day"], "2026-11-02")
        self.assertEqual(encoded["timestamp"], "2026-11-02T10:30:05")
        self.assertEqual(encoded["amount"], 10.5)
        self.assertEqual(encoded["file"], "YWJj")
        self.assertEqual(encoded["rows"], [{"flag": True, "value": None}])


class HandlerUnexpectedErrorTests(unittest.TestCase):
    def setUp(self):
        self.h = make_context()
        self.company_id, self.user_id = add_employer_account(self.h.db)
        _, self.token = session_for(self.h, self.user_id)

    def tearDown(self):
        self.h.db.close()

    def test_unexpected_exception_is_logged_and_hidden(self):
        def boom(ctx, payload):
            raise RuntimeError("database exploded")

        with patch.dict(ACTIONS, {"get_company": boom}):
            with self.assertLogs("internlink_employer.handler", level="ERROR"):
                response = handle(self.h.ctx, self.token, "get_company", {})
        self.assertEqual(
            response,
            {
                "ok": False,
                "category": "server",
                "message": "Something went wrong.",
                "fields": {},
            },
        )


if __name__ == "__main__":
    unittest.main()
