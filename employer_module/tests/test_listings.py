"""Listing lifecycle, validation, discovery and scheduled-job tests."""

import unittest
from datetime import date, timedelta
from unittest.mock import patch

from internlink_employer.constants import PAGE_SIZE
from internlink_employer.errors import ModuleError
from internlink_employer.handler import handle
from internlink_employer.services import (
    change_listing_status,
    create_listing,
    daily_listing_job,
    get_listing_detail,
    list_my_listings,
    update_listing,
)
from tests.support import (
    add_application,
    add_company,
    add_employer,
    add_employer_account,
    add_listing,
    add_student,
    make_context,
    seed_reference,
    session_for,
)


def listing_form(**overrides):
    form = {
        "title": "Software Engineering Intern",
        "description": "Work on the InternLink platform.",
        "sector": "Technology",
        "location": "Kampala",
        "is_remote": False,
        "duration_weeks": 12,
        "slots": 3,
        "application_deadline": (date.today() + timedelta(days=30)).isoformat(),
    }
    form.update(overrides)
    return form


class ListingSetup(unittest.TestCase):
    def setUp(self):
        self.h = make_context()
        self.refs = seed_reference(self.h.db)
        self.company_id, self.user_id = add_employer_account(self.h.db)
        self.session, self.token = session_for(self.h, self.user_id)

    def tearDown(self):
        self.h.db.close()


class ListingCreateUpdateTests(ListingSetup):
    def test_create_listing_is_always_a_draft_and_saves_tags(self):
        form = listing_form(
            required_skill_ids=[self.refs["skill_python"]],
            optional_skill_ids=[self.refs["skill_sql"]],
            programme_ids=[self.refs["programme"]],
            interest_ids=[self.refs["interest"]],
            status="open",
        )
        result = create_listing(self.h.db, self.session, form)
        listing = get_listing_detail(self.h.db, self.session, result["listing_id"])
        self.assertEqual(listing["status"], "draft")
        self.assertIsNone(listing["posted_at"])
        self.assertEqual(listing["company_id"], self.company_id)
        self.assertEqual(listing["posted_by"], self.user_id)
        self.assertEqual([skill["name"] for skill in listing["skills"]], ["Python", "SQL"])
        required = {skill["name"]: skill["is_required"] for skill in listing["skills"]}
        self.assertTrue(required["Python"])
        self.assertFalse(required["SQL"])
        self.assertEqual([row["name"] for row in listing["programmes"]], ["Bachelor of IT"])
        self.assertEqual([row["name"] for row in listing["interests"]], ["Fintech"])

    def test_create_listing_validates_every_field(self):
        invalid_form = {
            "title": "",
            "description": "x" * 10_001,
            "sector": "",
            "location": "",
            "duration_weeks": 53,
            "slots": 501,
            "application_deadline": "not-a-date",
            "required_skill_ids": [99999],
            "optional_skill_ids": "not-a-list",
            "programme_ids": [self.refs["programme"]],
            "interest_ids": [],
        }
        with self.assertRaises(ModuleError) as caught:
            create_listing(self.h.db, self.session, invalid_form)
        fields = caught.exception.fields
        for key in (
            "title",
            "description",
            "sector",
            "location",
            "duration_weeks",
            "slots",
            "application_deadline",
            "required_skill_ids",
            "optional_skill_ids",
        ):
            self.assertIn(key, fields)
        self.assertEqual(self.h.db.query_one("SELECT count(*) AS n FROM listings")["n"], 0)

        with self.assertRaises(ModuleError) as caught:
            create_listing(self.h.db, self.session, listing_form(slots=0, duration_weeks=0))
        self.assertEqual(caught.exception.fields["slots"], "1 to 500")
        self.assertEqual(caught.exception.fields["duration_weeks"], "1 to 52")

        with self.assertRaises(ModuleError) as caught:
            create_listing(
                self.h.db,
                self.session,
                listing_form(
                    slots=1.5,
                    duration_weeks=12.5,
                    required_skill_ids=[self.refs["skill_python"] + 0.5],
                ),
            )
        self.assertEqual(caught.exception.fields["slots"], "Enter a whole number")
        self.assertEqual(caught.exception.fields["duration_weeks"], "Enter a whole number")
        self.assertEqual(caught.exception.fields["required_skill_ids"], "Unknown value")

        with self.assertRaises(ModuleError) as caught:
            create_listing(
                self.h.db,
                self.session,
                listing_form(
                    required_skill_ids=[self.refs["skill_python"]],
                    optional_skill_ids=[self.refs["skill_python"]],
                ),
            )
        self.assertIn("both required and optional", caught.exception.fields["optional_skill_ids"])

        with self.assertRaises(ModuleError):
            create_listing(self.h.db, self.session, [("not", "mapping")])

    def test_other_company_listings_are_invisible(self):
        other_company, other_user = add_employer_account(
            self.h.db, name="Other Company", email="other@example.com"
        )
        other_session, _ = session_for(self.h, other_user)
        listing_id = add_listing(self.h.db, other_company, other_user, self.refs)

        for call in (
            lambda: get_listing_detail(self.h.db, self.session, listing_id),
            lambda: update_listing(
                self.h.db, self.session, listing_id, listing_form(), self.h.cache
            ),
            lambda: change_listing_status(
                self.h.db, self.session, listing_id, "closed", self.h.cache
            ),
        ):
            with self.assertRaises(ModuleError) as caught:
                call()
            self.assertEqual(caught.exception.category, "not_found")

        self.assertEqual(
            list_my_listings(self.h.db, other_session)[0]["listing_id"], listing_id
        )

    def test_update_replaces_tags_and_invalidates_cache(self):
        listing_id = add_listing(
            self.h.db,
            self.company_id,
            self.user_id,
            self.refs,
            required_skills=[self.refs["skill_python"]],
        )
        result = update_listing(
            self.h.db,
            self.session,
            listing_id,
            listing_form(
                title="Data Intern",
                slots=2,
                required_skill_ids=[self.refs["skill_sql"]],
                optional_skill_ids=[self.refs["skill_writing"]],
                programme_ids=[self.refs["programme2"]],
                interest_ids=[self.refs["interest2"]],
                is_remote="yes",
            ),
            self.h.cache,
        )
        self.assertEqual(result["title"], "Data Intern")
        self.assertTrue(result["is_remote"])
        self.assertEqual(
            {skill["name"] for skill in result["skills"]}, {"SQL", "Writing"}
        )
        self.assertEqual(
            [row["name"] for row in result["programmes"]],
            ["BSc Computer Science"],
        )
        self.assertEqual([row["name"] for row in result["interests"]], ["Agritech"])
        self.assertEqual(self.h.cache.invalidations, 1)

    def test_update_cannot_reduce_slots_below_filled_or_use_invalid_data(self):
        listing_id = add_listing(
            self.h.db, self.company_id, self.user_id, self.refs, slots=3
        )
        self.h.db.execute(
            "UPDATE listings SET slots_filled = 2 WHERE listing_id = %s", [listing_id]
        )
        with self.assertRaises(ModuleError) as caught:
            update_listing(
                self.h.db, self.session, listing_id, listing_form(slots=1), self.h.cache
            )
        self.assertEqual(caught.exception.fields["slots"], "Too low")

        with self.assertRaises(ModuleError) as caught:
            update_listing(
                self.h.db,
                self.session,
                listing_id,
                listing_form(application_deadline=""),
                self.h.cache,
            )
        self.assertIn("application_deadline", caught.exception.fields)


class ListingStatusTests(ListingSetup):
    def test_publish_close_and_reopen_transitions(self):
        listing_id = create_listing(self.h.db, self.session, listing_form())["listing_id"]
        opened = change_listing_status(
            self.h.db, self.session, listing_id, "open", self.h.cache
        )
        self.assertEqual(opened["status"], "open")
        first_posted_at = opened["posted_at"]
        self.assertIsNotNone(first_posted_at)
        self.assertEqual(self.h.cache.invalidations, 1)

        closed = change_listing_status(
            self.h.db, self.session, listing_id, "closed", self.h.cache
        )
        self.assertEqual(closed["status"], "closed")
        self.assertIsNotNone(closed["closed_at"])

        reopened = change_listing_status(
            self.h.db, self.session, listing_id, "open", self.h.cache
        )
        self.assertEqual(reopened["status"], "open")
        self.assertIsNone(reopened["closed_at"])
        self.assertEqual(reopened["posted_at"], first_posted_at)

    def test_illegal_transitions_and_unknown_status(self):
        listing_id = create_listing(self.h.db, self.session, listing_form())["listing_id"]
        with self.assertRaises(ModuleError) as caught:
            change_listing_status(
                self.h.db, self.session, listing_id, "closed", self.h.cache
            )
        self.assertEqual(caught.exception.category, "conflict")

        with self.assertRaises(ModuleError) as caught:
            change_listing_status(
                self.h.db, self.session, listing_id, "published", self.h.cache
            )
        self.assertEqual(caught.exception.category, "invalid")

    def test_publishing_requires_verified_company_and_future_deadline(self):
        pending_company, pending_user = add_employer_account(
            self.h.db,
            name="Pending Co",
            email="pending@example.com",
            verification_status="pending",
        )
        pending_session, _ = session_for(self.h, pending_user)
        pending_listing = add_listing(
            self.h.db,
            pending_company,
            pending_user,
            self.refs,
            status="draft",
        )
        with self.assertRaises(ModuleError) as caught:
            change_listing_status(
                self.h.db, pending_session, pending_listing, "open", self.h.cache
            )
        self.assertEqual(caught.exception.category, "forbidden")
        self.assertEqual(
            self.h.db.query_one(
                "SELECT status FROM listings WHERE listing_id = %s", [pending_listing]
            )["status"],
            "draft",
        )

        expired_listing = add_listing(
            self.h.db,
            self.company_id,
            self.user_id,
            self.refs,
            status="draft",
            deadline=date.today() - timedelta(days=1),
        )
        with self.assertRaises(ModuleError) as caught:
            change_listing_status(
                self.h.db, self.session, expired_listing, "open", self.h.cache
            )
        self.assertEqual(caught.exception.category, "invalid")
        self.assertIn("today or later", caught.exception.message)

    def test_hidden_listing_can_be_opened(self):
        listing_id = add_listing(
            self.h.db, self.company_id, self.user_id, self.refs, status="hidden"
        )
        opened = change_listing_status(
            self.h.db, self.session, listing_id, "open", self.h.cache
        )
        self.assertEqual(opened["status"], "open")
        self.assertIsNotNone(opened["posted_at"])

    def test_stale_status_change_is_rejected(self):
        listing_id = add_listing(self.h.db, self.company_id, self.user_id, self.refs)
        stale = dict(
            self.h.db.query_one(
                "SELECT * FROM listings WHERE listing_id = %s", [listing_id]
            )
        )
        self.h.db.execute(
            "UPDATE listings SET status = 'hidden' WHERE listing_id = %s", [listing_id]
        )
        with patch("internlink_employer.services.listings.own_listing", return_value=stale):
            with self.assertRaises(ModuleError) as caught:
                change_listing_status(
                    self.h.db, self.session, listing_id, "open", self.h.cache
                )
        self.assertEqual(caught.exception.category, "conflict")


class ListingDiscoveryTests(ListingSetup):
    def test_status_filter_search_and_applicant_counts(self):
        listing_one = add_listing(
            self.h.db,
            self.company_id,
            self.user_id,
            self.refs,
            title="100% Python Intern",
            description="Rare role",
        )
        listing_two = add_listing(
            self.h.db,
            self.company_id,
            self.user_id,
            self.refs,
            title="Data Intern",
            description="SQL reporting",
            status="closed",
        )
        student_id = add_student(self.h.db, self.refs)
        add_application(self.h.db, listing_one, student_id)
        add_application(
            self.h.db, listing_one, add_student(self.h.db, self.refs, full_name="Second"), status="shortlisted"
        )

        open_rows = list_my_listings(self.h.db, self.session, status="open")
        self.assertEqual([row["listing_id"] for row in open_rows], [listing_one])
        self.assertEqual(open_rows[0]["applicants"], 2)
        self.assertEqual(open_rows[0]["new_applicants"], 1)

        closed_rows = list_my_listings(self.h.db, self.session, status="closed")
        self.assertEqual([row["listing_id"] for row in closed_rows], [listing_two])

        self.assertEqual(
            [row["listing_id"] for row in list_my_listings(self.h.db, self.session, search="data")],
            [listing_two],
        )
        self.assertEqual(
            [row["listing_id"] for row in list_my_listings(self.h.db, self.session, search="100%")],
            [listing_one],
        )
        self.assertEqual(
            [row["listing_id"] for row in list_my_listings(self.h.db, self.session, search="RARE")],
            [listing_one],
        )

        with self.assertRaises(ModuleError):
            list_my_listings(self.h.db, self.session, status="unknown")
        with self.assertRaises(ModuleError):
            list_my_listings(self.h.db, self.session, status={})
        with self.assertRaises(ModuleError):
            list_my_listings(self.h.db, self.session, search=123)
        with self.assertRaises(ModuleError):
            list_my_listings(self.h.db, self.session, page=0)

    def test_pagination_uses_fixed_page_size(self):
        for index in range(PAGE_SIZE + 5):
            add_listing(
                self.h.db,
                self.company_id,
                self.user_id,
                self.refs,
                title=f"Intern {index:02d}",
            )
        first = list_my_listings(self.h.db, self.session, page=1)
        second = list_my_listings(self.h.db, self.session, page=2)
        self.assertEqual(len(first), PAGE_SIZE)
        self.assertEqual(len(second), 5)
        self.assertEqual(
            len({row["listing_id"] for row in first + second}), PAGE_SIZE + 5
        )


class DailyJobTests(unittest.TestCase):
    def setUp(self):
        self.h = make_context()
        self.refs = seed_reference(self.h.db)
        self.company_id, self.user_id = add_employer_account(self.h.db)
        add_employer(self.h.db, self.company_id, email="second@example.com")
        add_employer(self.h.db, self.company_id, email="pending@example.com", status="pending")

    def tearDown(self):
        self.h.db.close()

    def test_closes_expired_listings_and_reminds_active_users(self):
        expired = add_listing(
            self.h.db,
            self.company_id,
            self.user_id,
            self.refs,
            deadline=date.today() - timedelta(days=1),
        )
        closing_soon = add_listing(
            self.h.db,
            self.company_id,
            self.user_id,
            self.refs,
            title="Closing soon",
            deadline=date.today() + timedelta(days=2),
        )
        add_listing(
            self.h.db,
            self.company_id,
            self.user_id,
            self.refs,
            title="Later",
            deadline=date.today() + timedelta(days=5),
        )

        result = daily_listing_job(self.h.db, self.h.notifier, self.h.cache)
        self.assertEqual(result, {"closed": 1, "reminders_sent": 2})
        self.assertEqual(self.h.cache.invalidations, 1)
        self.assertEqual(
            self.h.db.query_one(
                "SELECT status FROM listings WHERE listing_id = %s", [expired]
            )["status"],
            "closed",
        )
        self.assertTrue(all(item["related_id"] == closing_soon for item in self.h.notifier.sent))
        self.assertEqual({item["user_id"] for item in self.h.notifier.sent}, {
            self.user_id,
            self.h.db.query_one(
                "SELECT user_id FROM users WHERE email = %s", ["second@example.com"]
            )["user_id"],
        })


class HandlerTests(ListingSetup):
    def test_handle_requires_fields_and_valid_action(self):
        response = handle(self.h.ctx, self.token, "create_listing", {})
        self.assertFalse(response["ok"])
        self.assertEqual(response["category"], "invalid")

        response = handle(self.h.ctx, self.token, "update_listing", {
            "title": "No id",
        })
        self.assertFalse(response["ok"])
        self.assertEqual(response["fields"]["listing_id"], "Required")

        response = handle(self.h.ctx, self.token, "does_not_exist", {})
        self.assertFalse(response["ok"])
        self.assertEqual(response["category"], "invalid")

        response = handle(self.h.ctx, self.token, "create_listing", listing_form())
        self.assertTrue(response["ok"])
        self.assertGreater(response["data"]["listing_id"], 0)

        response = handle(self.h.ctx, None, "get_company", {})
        self.assertFalse(response["ok"])
        self.assertEqual(response["category"], "unauthenticated")

        response = handle(self.h.ctx, self.token, "get_company", ["not", "a", "dict"])
        self.assertFalse(response["ok"])
        self.assertEqual(response["category"], "invalid")


if __name__ == "__main__":
    unittest.main()
