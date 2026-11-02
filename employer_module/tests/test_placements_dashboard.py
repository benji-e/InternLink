"""Placement completion, dashboard and notification tests (SR11)."""

import unittest
from datetime import date, timedelta

from internlink_employer.errors import ModuleError
from internlink_employer.services import (
    complete_placement,
    employer_dashboard,
    list_my_placements,
    list_notifications,
    mark_notification_read,
)
from tests.support import (
    add_application,
    add_employer,
    add_employer_account,
    add_listing,
    add_placement,
    add_student,
    make_context,
    seed_reference,
    session_for,
    student_user_id,
)


class PlacementSetup(unittest.TestCase):
    def setUp(self):
        self.h = make_context()
        self.refs = seed_reference(self.h.db)
        self.company_id, self.user_id = add_employer_account(self.h.db)
        self.session, self.token = session_for(self.h, self.user_id)
        self.listing_id = add_listing(
            self.h.db, self.company_id, self.user_id, self.refs, slots=5
        )

        self.confirmed_student = add_student(
            self.h.db, self.refs, full_name="Confirmed Student"
        )
        self.confirmed_app = add_application(
            self.h.db, self.listing_id, self.confirmed_student, status="accepted"
        )
        self.confirmed_placement = add_placement(
            self.h.db,
            self.confirmed_app,
            status="confirmed",
            start_date=date.today() - timedelta(days=60),
            end_date=date.today() - timedelta(days=1),
        )

        self.pending_student = add_student(self.h.db, self.refs, full_name="Pending Student")
        self.pending_app = add_application(
            self.h.db, self.listing_id, self.pending_student, status="accepted"
        )
        self.pending_placement = add_placement(
            self.h.db, self.pending_app, status="pending"
        )

        self.completed_student = add_student(
            self.h.db, self.refs, full_name="Completed Student"
        )
        self.completed_app = add_application(
            self.h.db, self.listing_id, self.completed_student, status="accepted"
        )
        self.completed_placement = add_placement(
            self.h.db, self.completed_app, status="completed"
        )

        self.future_student = add_student(self.h.db, self.refs, full_name="Future Student")
        self.future_app = add_application(
            self.h.db, self.listing_id, self.future_student, status="accepted"
        )
        self.future_placement = add_placement(
            self.h.db,
            self.future_app,
            status="confirmed",
            start_date=date.today() - timedelta(days=10),
            end_date=date.today() + timedelta(days=10),
        )

    def tearDown(self):
        self.h.db.close()


class PlacementListTests(PlacementSetup):
    def test_lists_pending_confirmed_and_completed_with_flags(self):
        rows = list_my_placements(self.h.db, self.session)
        self.assertEqual(len(rows), 4)
        by_id = {row["placement_id"]: row for row in rows}
        self.assertTrue(by_id[self.confirmed_placement]["can_complete"])
        self.assertFalse(by_id[self.confirmed_placement]["awaiting_approval"])
        self.assertFalse(by_id[self.pending_placement]["can_complete"])
        self.assertTrue(by_id[self.pending_placement]["awaiting_approval"])
        self.assertFalse(by_id[self.completed_placement]["can_complete"])
        self.assertFalse(by_id[self.future_placement]["can_complete"])

        pending = list_my_placements(self.h.db, self.session, status="pending")
        self.assertEqual([row["placement_id"] for row in pending], [self.pending_placement])
        with self.assertRaises(ModuleError):
            list_my_placements(self.h.db, self.session, status="cancelled")
        with self.assertRaises(ModuleError):
            list_my_placements(self.h.db, self.session, status={})

    def test_other_company_placements_are_excluded(self):
        other_company, other_user = add_employer_account(
            self.h.db, name="Placement Other", email="placement-other@example.com"
        )
        other_student = add_student(self.h.db, self.refs, full_name="Foreign Student")
        other_listing = add_listing(self.h.db, other_company, other_user, self.refs)
        other_app = add_application(
            self.h.db, other_listing, other_student, status="accepted"
        )
        foreign_placement = add_placement(self.h.db, other_app, status="confirmed")
        ids = {row["placement_id"] for row in list_my_placements(self.h.db, self.session)}
        self.assertNotIn(foreign_placement, ids)


class CompletePlacementTests(PlacementSetup):
    def test_completion_records_note_actor_notification_and_slot(self):
        before_slots = self.h.db.query_one(
            "SELECT slots_filled FROM listings WHERE listing_id = %s", [self.listing_id]
        )["slots_filled"]
        self.assertEqual(before_slots, 3)  # pending + both confirmed placements

        result = complete_placement(
            self.h.db, self.session, self.confirmed_placement, "Excellent work"
        )
        self.assertEqual(result, {
            "placement_id": self.confirmed_placement,
            "status": "completed",
        })
        placement = self.h.db.query_one(
            "SELECT * FROM placements WHERE placement_id = %s", [self.confirmed_placement]
        )
        self.assertEqual(placement["status"], "completed")
        self.assertEqual(placement["completion_note"], "Excellent work")
        self.assertEqual(placement["completed_by"], self.user_id)
        self.assertIsNotNone(placement["completed_at"])

        after_slots = self.h.db.query_one(
            "SELECT slots_filled FROM listings WHERE listing_id = %s", [self.listing_id]
        )["slots_filled"]
        self.assertEqual(after_slots, 2)

        notification = self.h.db.query_one(
            """
            SELECT * FROM notifications
            WHERE user_id = %s AND type = 'placement_completed'
            """,
            [student_user_id(self.h.db, self.confirmed_student)],
        )
        self.assertIsNotNone(notification)
        audit = self.h.db.query_one(
            "SELECT * FROM audit_log WHERE action = 'placement_completed'"
        )
        self.assertEqual(audit["actor_user_id"], self.user_id)

        with self.assertRaises(ModuleError) as caught:
            complete_placement(
                self.h.db, self.session, self.confirmed_placement, "Again"
            )
        self.assertEqual(caught.exception.category, "conflict")

    def test_completion_rules(self):
        with self.assertRaises(ModuleError) as caught:
            complete_placement(self.h.db, self.session, self.pending_placement, "Note")
        self.assertEqual(caught.exception.category, "conflict")

        with self.assertRaises(ModuleError) as caught:
            complete_placement(self.h.db, self.session, self.future_placement, "Note")
        self.assertEqual(caught.exception.category, "conflict")
        self.assertIn("end date", caught.exception.message)

        for note in (None, "", "   ", 123, "x" * 2001):
            with self.assertRaises(ModuleError) as caught:
                complete_placement(
                    self.h.db, self.session, self.confirmed_placement, note
                )
            self.assertEqual(caught.exception.category, "invalid")
            self.assertIn("completion_note", caught.exception.fields)

    def test_cannot_complete_other_companys_placement(self):
        other_company, other_user = add_employer_account(
            self.h.db, name="Completion Thief", email="completion-thief@example.com"
        )
        other_student = add_student(self.h.db, self.refs, full_name="Thief Target")
        other_listing = add_listing(self.h.db, other_company, other_user, self.refs)
        other_app = add_application(
            self.h.db, other_listing, other_student, status="accepted"
        )
        foreign = add_placement(self.h.db, other_app, status="confirmed")
        with self.assertRaises(ModuleError) as caught:
            complete_placement(self.h.db, self.session, foreign, "Stolen note")
        self.assertEqual(caught.exception.category, "not_found")


class DashboardTests(PlacementSetup):
    def test_dashboard_aggregates_are_scoped_to_company_and_user(self):
        add_application(
            self.h.db,
            self.listing_id,
            add_student(self.h.db, self.refs, full_name="Fresh Applicant"),
            status="submitted",
        )
        add_application(
            self.h.db,
            self.listing_id,
            add_student(self.h.db, self.refs, full_name="Shortlisted Applicant"),
            status="shortlisted",
        )
        self.h.db.insert(
            "messages",
            {
                "application_id": self.confirmed_app,
                "sender_id": student_user_id(self.h.db, self.confirmed_student),
                "recipient_id": self.user_id,
                "body": "Unread employer message",
            },
        )
        self.h.db.insert(
            "notifications",
            {
                "user_id": self.user_id,
                "type": "test",
                "title": "Unread",
                "message": "Unread",
                "channel": "in_app",
                "is_read": False,
            },
        )
        self.h.db.insert(
            "notifications",
            {
                "user_id": self.user_id,
                "type": "test",
                "title": "Read",
                "message": "Read",
                "channel": "in_app",
                "is_read": True,
            },
        )
        self.h.db.insert(
            "notifications",
            {
                "user_id": self.user_id,
                "type": "test",
                "title": "Email",
                "message": "Email",
                "channel": "email",
                "is_read": False,
            },
        )

        dashboard = employer_dashboard(self.h.db, self.session)
        self.assertEqual(dashboard["company_status"], "verified")
        self.assertEqual(dashboard["listings_by_status"], [{"status": "open", "n": 1}])
        self.assertEqual(dashboard["new_applications"], 1)
        self.assertEqual(dashboard["shortlisted"], 1)
        self.assertEqual(
            {row["status"]: row["n"] for row in dashboard["placements_by_status"]},
            {"confirmed": 2, "pending": 1, "completed": 1},
        )
        self.assertEqual(dashboard["unread_messages"], 1)
        self.assertEqual(dashboard["unread_notifications"], 1)

    def test_dashboard_ignores_other_companys_data(self):
        other_company, other_user = add_employer_account(
            self.h.db, name="Dashboard Other", email="dashboard-other@example.com"
        )
        other_listing = add_listing(self.h.db, other_company, other_user, self.refs)
        other_student = add_student(self.h.db, self.refs, full_name="Dashboard Other Student")
        add_application(self.h.db, other_listing, other_student, status="submitted")
        dashboard = employer_dashboard(self.h.db, self.session)
        self.assertEqual(dashboard["new_applications"], 0)
        self.assertEqual(dashboard["listings_by_status"], [{"status": "open", "n": 1}])


class NotificationTests(PlacementSetup):
    def test_list_and_mark_notifications(self):
        own = self.h.db.insert(
            "notifications",
            {
                "user_id": self.user_id,
                "type": "test",
                "title": "Own notification",
                "message": "Hello",
                "channel": "in_app",
                "is_read": False,
            },
        )
        self.h.db.insert(
            "notifications",
            {
                "user_id": self.user_id,
                "type": "test",
                "title": "Email only",
                "message": "Hello",
                "channel": "email",
                "is_read": False,
            },
        )
        other_user = add_employer(
            self.h.db, self.company_id, email="other-notify@example.com"
        )
        foreign = self.h.db.insert(
            "notifications",
            {
                "user_id": other_user,
                "type": "test",
                "title": "Foreign notification",
                "message": "Nope",
                "channel": "in_app",
                "is_read": False,
            },
        )

        rows = list_notifications(self.h.db, self.session)
        self.assertEqual([row["notification_id"] for row in rows], [own])
        self.assertFalse(rows[0]["is_read"])

        result = mark_notification_read(self.h.db, self.session, own)
        self.assertEqual(result, {"notification_id": own, "is_read": True})
        self.assertTrue(
            self.h.db.query_one(
                "SELECT is_read FROM notifications WHERE notification_id = %s", [own]
            )["is_read"]
        )
        self.assertTrue(mark_notification_read(self.h.db, self.session, own)["is_read"])

        with self.assertRaises(ModuleError) as caught:
            mark_notification_read(self.h.db, self.session, foreign)
        self.assertEqual(caught.exception.category, "not_found")
        with self.assertRaises(ModuleError):
            mark_notification_read(self.h.db, self.session, 0)


if __name__ == "__main__":
    unittest.main()
