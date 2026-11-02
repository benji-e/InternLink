"""Shortlist-only messaging and inbox tests (SR10)."""

import unittest
from unittest.mock import patch

from internlink_employer.errors import ModuleError
from internlink_employer.services import get_thread, list_conversations, send_message
from tests.support import (
    add_application,
    add_employer_account,
    add_listing,
    add_student,
    make_context,
    seed_reference,
    session_for,
    student_user_id,
)


class MessagingSetup(unittest.TestCase):
    def setUp(self):
        self.h = make_context()
        self.refs = seed_reference(self.h.db)
        self.company_id, self.user_id = add_employer_account(self.h.db)
        self.session, self.token = session_for(self.h, self.user_id)
        self.listing_id = add_listing(self.h.db, self.company_id, self.user_id, self.refs)
        self.student_id = add_student(
            self.h.db, self.refs, full_name="Message Student"
        )
        self.student_user = student_user_id(self.h.db, self.student_id)
        self.application_id = add_application(
            self.h.db, self.listing_id, self.student_id, status="shortlisted"
        )

    def tearDown(self):
        self.h.db.close()


class SendMessageTests(MessagingSetup):
    def test_send_message_records_row_notification_and_audit(self):
        result = send_message(self.h.db, self.session, self.application_id, "  Hello there  ")
        self.assertEqual(result, {"sent": True})
        message = self.h.db.query_one("SELECT * FROM messages")
        self.assertEqual(message["body"], "Hello there")
        self.assertEqual(message["sender_id"], self.user_id)
        self.assertEqual(message["recipient_id"], self.student_user)
        self.assertEqual(message["application_id"], self.application_id)

        notification = self.h.db.query_one("SELECT * FROM notifications")
        self.assertEqual(notification["user_id"], self.student_user)
        self.assertEqual(notification["type"], "message")
        self.assertIn("Software Engineering Intern", notification["message"])
        self.assertNotIn("Hello there", notification["message"])

        audit = self.h.db.query_one("SELECT * FROM audit_log WHERE action = 'message_sent'")
        self.assertEqual(audit["actor_user_id"], self.user_id)

    def test_message_validation_and_status_rule(self):
        sample = [
            "",
            "   ",
            None,
            123,
            "x" * 5001,
        ]
        for body in sample:
            with self.assertRaises(ModuleError) as caught:
                send_message(self.h.db, self.session, self.application_id, body)
            self.assertEqual(caught.exception.category, "invalid")

        submitted_application = add_application(
            self.h.db,
            self.listing_id,
            add_student(self.h.db, self.refs, full_name="Submitted Student"),
        )
        with self.assertRaises(ModuleError) as caught:
            send_message(
                self.h.db, self.session, submitted_application, "Too early"
            )
        self.assertEqual(caught.exception.category, "conflict")
        self.assertIn("shortlisted", caught.exception.message)

        accepted_application = add_application(
            self.h.db,
            self.listing_id,
            add_student(self.h.db, self.refs, full_name="Accepted Student"),
            status="accepted",
        )
        self.assertTrue(
            send_message(self.h.db, self.session, accepted_application, "Welcome")["sent"]
        )

    def test_status_is_rechecked_inside_the_transaction(self):
        submitted = add_application(
            self.h.db,
            self.listing_id,
            add_student(self.h.db, self.refs, full_name="Race Student"),
        )
        stale = dict(
            self.h.db.query_one(
                "SELECT * FROM applications WHERE application_id = %s", [submitted]
            )
        )
        stale["status"] = "shortlisted"
        with patch(
            "internlink_employer.services.messaging.own_application",
            return_value=stale,
        ):
            with self.assertRaises(ModuleError) as caught:
                send_message(self.h.db, self.session, submitted, "Too late")
        self.assertEqual(caught.exception.category, "conflict")
        self.assertIsNone(
            self.h.db.query_one(
                "SELECT * FROM messages WHERE application_id = %s", [submitted]
            )
        )

    def test_cannot_message_other_companys_application(self):
        other_company, other_user = add_employer_account(
            self.h.db, name="Message Thief", email="message-thief@example.com"
        )
        other_student = add_student(self.h.db, self.refs, full_name="Other Student")
        other_listing = add_listing(self.h.db, other_company, other_user, self.refs)
        foreign_application = add_application(
            self.h.db, other_listing, other_student, status="shortlisted"
        )
        with self.assertRaises(ModuleError) as caught:
            send_message(self.h.db, self.session, foreign_application, "Sneaky")
        self.assertEqual(caught.exception.category, "not_found")


class ThreadAndInboxTests(MessagingSetup):
    def test_thread_marks_incoming_messages_read_and_flags_mine(self):
        send_message(self.h.db, self.session, self.application_id, "First from employer")
        self.h.db.insert(
            "messages",
            {
                "application_id": self.application_id,
                "sender_id": self.student_user,
                "recipient_id": self.user_id,
                "body": "Reply from student",
                "sent_at": "2030-01-01 12:00:00",
            },
        )
        before = list_conversations(self.h.db, self.session)
        self.assertEqual(before[0]["unread"], 1)

        messages = get_thread(self.h.db, self.session, self.application_id)
        self.assertEqual([message["body"] for message in messages], [
            "First from employer",
            "Reply from student",
        ])
        self.assertEqual([message["mine"] for message in messages], [True, False])
        self.assertNotIn("sender_id", messages[0])
        self.assertTrue(messages[1]["is_read"])
        self.assertFalse(messages[0]["is_read"])  # recipient is the student

        after = list_conversations(self.h.db, self.session)
        self.assertEqual(after[0]["unread"], 0)

    def test_thread_is_scoped_to_company(self):
        other_company, other_user = add_employer_account(
            self.h.db, name="Thread Thief", email="thread-thief@example.com"
        )
        other_student = add_student(self.h.db, self.refs, full_name="Thread Other")
        other_listing = add_listing(self.h.db, other_company, other_user, self.refs)
        foreign_application = add_application(
            self.h.db, other_listing, other_student, status="shortlisted"
        )
        with self.assertRaises(ModuleError) as caught:
            get_thread(self.h.db, self.session, foreign_application)
        self.assertEqual(caught.exception.category, "not_found")

    def test_inbox_shows_latest_conversations_and_company_scope(self):
        send_message(self.h.db, self.session, self.application_id, "Latest one")
        second_student = add_student(self.h.db, self.refs, full_name="Second Student")
        second_application = add_application(
            self.h.db, self.listing_id, second_student, status="shortlisted"
        )
        self.h.db.insert(
            "messages",
            {
                "application_id": second_application,
                "sender_id": second_student,
                "recipient_id": self.user_id,
                "body": "Older conversation",
                "sent_at": "2025-01-01 00:00:00",
            },
        )
        rows = list_conversations(self.h.db, self.session)
        self.assertEqual([row["application_id"] for row in rows], [
            self.application_id,
            second_application,
        ])
        self.assertEqual(rows[1]["unread"], 1)
        self.assertEqual(rows[0]["applicant_name"], "Message Student")

        other_company, other_user = add_employer_account(
            self.h.db, name="Inbox Other", email="inbox-other@example.com"
        )
        other_student = add_student(self.h.db, self.refs, full_name="Inbox Other Student")
        other_listing = add_listing(self.h.db, other_company, other_user, self.refs)
        foreign_application = add_application(
            self.h.db, other_listing, other_student, status="shortlisted"
        )
        self.h.db.insert(
            "messages",
            {
                "application_id": foreign_application,
                "sender_id": other_user,
                "recipient_id": student_user_id(self.h.db, other_student),
                "body": "Not mine",
            },
        )
        rows = list_conversations(self.h.db, self.session)
        self.assertNotIn(
            foreign_application, [row["application_id"] for row in rows]
        )


if __name__ == "__main__":
    unittest.main()
