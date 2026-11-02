"""Applicant review, CV, decision and bulk-action tests."""

import unittest

from internlink_employer.errors import ModuleError
from internlink_employer.services import (
    bulk_decide,
    decide_application,
    download_applicant_cv,
    list_applicants,
    view_applicant,
)
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


class ApplicantSetup(unittest.TestCase):
    def setUp(self):
        self.h = make_context({"cvs/carol.pdf": b"%PDF-1.4 test cv"})
        self.refs = seed_reference(self.h.db)
        self.company_id, self.user_id = add_employer_account(self.h.db)
        self.session, self.token = session_for(self.h, self.user_id)
        self.listing_id = add_listing(
            self.h.db, self.company_id, self.user_id, self.refs, slots=2
        )
        self.alice = add_student(self.h.db, self.refs, full_name="Alice Applicant")
        self.bob = add_student(self.h.db, self.refs, full_name="Bob Candidate")
        self.carol = add_student(
            self.h.db,
            self.refs,
            full_name="Carol Graduate",
            cv_path="cvs/carol.pdf",
        )
        self.alice_app = add_application(
            self.h.db, self.listing_id, self.alice, match_score=90.0
        )
        self.bob_app = add_application(
            self.h.db, self.listing_id, self.bob, status="shortlisted", match_score=50.0
        )
        self.carol_app = add_application(
            self.h.db, self.listing_id, self.carol, match_score=75.0
        )

    def tearDown(self):
        self.h.db.close()


class ApplicantListTests(ApplicantSetup):
    def test_filter_sort_counts_and_cv_flag(self):
        result = list_applicants(self.h.db, self.session, self.listing_id)
        self.assertEqual([row["application_id"] for row in result["applicants"]], [
            self.alice_app,
            self.carol_app,
            self.bob_app,
        ])
        self.assertTrue(result["applicants"][1]["has_cv"])
        self.assertFalse(result["applicants"][0]["has_cv"])
        self.assertEqual(
            {row["status"]: row["n"] for row in result["counts_by_status"]},
            {"submitted": 2, "shortlisted": 1},
        )

        submitted = list_applicants(
            self.h.db, self.session, self.listing_id, status="submitted"
        )
        self.assertEqual(len(submitted["applicants"]), 2)

        by_name = list_applicants(
            self.h.db, self.session, self.listing_id, sort="name", desc=False
        )
        self.assertEqual(
            [row["applicant_name"] for row in by_name["applicants"]],
            ["Alice Applicant", "Bob Candidate", "Carol Graduate"],
        )

        fallback = list_applicants(
            self.h.db,
            self.session,
            self.listing_id,
            sort="match_score; DROP TABLE users",
        )
        self.assertEqual([row["application_id"] for row in fallback["applicants"]], [
            self.alice_app,
            self.carol_app,
            self.bob_app,
        ])

        with self.assertRaises(ModuleError):
            list_applicants(self.h.db, self.session, self.listing_id, status="nope")
        with self.assertRaises(ModuleError):
            list_applicants(self.h.db, self.session, self.listing_id, status={})
        with self.assertRaises(ModuleError):
            list_applicants(self.h.db, self.session, self.listing_id, page=0)
        with self.assertRaises(ModuleError):
            list_applicants(self.h.db, self.session, self.listing_id, page=1.5)
        with self.assertRaises(ModuleError):
            view_applicant(self.h.db, self.session, self.alice_app + 0.5)

        fallback_sort = list_applicants(
            self.h.db, self.session, self.listing_id, sort={}
        )
        self.assertEqual([row["application_id"] for row in fallback_sort["applicants"]], [
            self.alice_app,
            self.carol_app,
            self.bob_app,
        ])

    def test_other_company_cannot_list_our_applicants(self):
        _, other_user = add_employer_account(
            self.h.db, name="Other Co", email="other-owner@example.com"
        )
        other_session, _ = session_for(self.h, other_user)
        with self.assertRaises(ModuleError) as caught:
            list_applicants(self.h.db, other_session, self.listing_id)
        self.assertEqual(caught.exception.category, "not_found")


class ApplicantViewTests(ApplicantSetup):
    def test_view_marks_submitted_application_under_review_once(self):
        result = view_applicant(self.h.db, self.session, self.alice_app)
        self.assertEqual(result["status"], "under_review")
        self.assertFalse(result["can_message"])
        self.assertEqual(result["profile"]["full_name"], "Alice Applicant")
        self.assertEqual(result["profile"]["year_of_study"], 2)
        self.assertFalse(result["profile"]["willing_to_relocate"])
        self.assertEqual([skill["name"] for skill in result["profile"]["skills"]], ["Python"])
        self.assertEqual(
            [interest["name"] for interest in result["profile"]["interests"]], ["Fintech"]
        )
        self.assertEqual(result["cover_note"], "I would love to join.")
        self.assertEqual(result["match_score"], 90.0)

        for private in ("email", "phone", "student_number", "password_hash"):
            self.assertNotIn(private, result["profile"])

        view_applicant(self.h.db, self.session, self.alice_app)
        audits = self.h.db.query_all(
            "SELECT * FROM audit_log WHERE action = 'application_under_review'"
        )
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0]["actor_user_id"], self.user_id)

    def test_shortlisted_applicant_can_be_messaged(self):
        result = view_applicant(self.h.db, self.session, self.bob_app)
        self.assertEqual(result["status"], "shortlisted")
        self.assertTrue(result["can_message"])

    def test_view_other_company_application_is_not_found(self):
        other_company, other_user = add_employer_account(
            self.h.db, name="Other Co 2", email="other-two@example.com"
        )
        other_student = add_student(self.h.db, self.refs, full_name="Other Student")
        other_listing = add_listing(
            self.h.db, other_company, other_user, self.refs
        )
        foreign_application = add_application(
            self.h.db, other_listing, other_student
        )
        with self.assertRaises(ModuleError) as caught:
            view_applicant(self.h.db, self.session, foreign_application)
        self.assertEqual(caught.exception.category, "not_found")


class CvDownloadTests(ApplicantSetup):
    def test_download_returns_bytes_and_writes_audit(self):
        content = download_applicant_cv(
            self.h.db, self.session, self.h.storage, self.carol_app
        )
        self.assertEqual(content, b"%PDF-1.4 test cv")
        audit = self.h.db.query_one(
            "SELECT * FROM audit_log WHERE action = 'cv_downloaded'"
        )
        self.assertEqual(audit["actor_user_id"], self.user_id)
        self.assertEqual(audit["entity_id"], str(self.carol_app))

    def test_missing_cv_and_missing_file_are_not_found(self):
        with self.assertRaises(ModuleError) as caught:
            download_applicant_cv(self.h.db, self.session, self.h.storage, self.alice_app)
        self.assertEqual(caught.exception.category, "not_found")

        self.h.storage.files.pop("cvs/carol.pdf")
        with self.assertRaises(ModuleError) as caught:
            download_applicant_cv(self.h.db, self.session, self.h.storage, self.carol_app)
        self.assertEqual(caught.exception.category, "not_found")
        self.assertIsNone(
            self.h.db.query_one("SELECT * FROM audit_log WHERE action = 'cv_downloaded'")
        )

    def test_other_company_cannot_download(self):
        other_company, other_user = add_employer_account(
            self.h.db, name="CV Thief Co", email="thief@example.com"
        )
        other_student = add_student(self.h.db, self.refs, full_name="Secret Student")
        other_listing = add_listing(self.h.db, other_company, other_user, self.refs)
        foreign_application = add_application(
            self.h.db, other_listing, other_student
        )
        with self.assertRaises(ModuleError) as caught:
            download_applicant_cv(
                self.h.db, self.session, self.h.storage, foreign_application
            )
        self.assertEqual(caught.exception.category, "not_found")


class DecisionTests(ApplicantSetup):
    def test_shortlist_and_accept_create_pending_placement_and_notifications(self):
        result = decide_application(self.h.db, self.session, self.alice_app, "shortlist")
        self.assertEqual(result["status"], "shortlisted")
        self.assertIsNone(result["info"])

        result = decide_application(self.h.db, self.session, self.alice_app, "accept")
        self.assertEqual(result["status"], "accepted")
        self.assertIn("university coordinator", result["info"])

        placement = self.h.db.query_one(
            "SELECT * FROM placements WHERE application_id = %s", [self.alice_app]
        )
        self.assertIsNotNone(placement)
        self.assertEqual(placement["status"], "pending")
        listing = self.h.db.query_one(
            "SELECT slots_filled FROM listings WHERE listing_id = %s", [self.listing_id]
        )
        self.assertEqual(listing["slots_filled"], 1)

        notifications = self.h.db.query_all(
            "SELECT * FROM notifications WHERE user_id = %s ORDER BY notification_id",
            [student_user_id(self.h.db, self.alice)],
        )
        self.assertEqual([row["type"] for row in notifications], [
            "application_status",
            "application_status",
        ])
        self.assertEqual(notifications[-1]["related_id"], self.alice_app)
        self.assertFalse(notifications[-1]["is_read"])

        audits = self.h.db.query_all(
            "SELECT * FROM audit_log WHERE action = 'application_decided'"
        )
        self.assertEqual(len(audits), 2)
        self.assertEqual(audits[0]["actor_user_id"], self.user_id)

    def test_invalid_and_illegal_decisions(self):
        with self.assertRaises(ModuleError):
            decide_application(self.h.db, self.session, self.alice_app, "promote")
        with self.assertRaises(ModuleError):
            decide_application(self.h.db, self.session, self.alice_app, {})
        with self.assertRaises(ModuleError) as caught:
            decide_application(self.h.db, self.session, self.alice_app, "accept")
        self.assertEqual(caught.exception.category, "conflict")

        decide_application(self.h.db, self.session, self.alice_app, "shortlist")
        with self.assertRaises(ModuleError) as caught:
            decide_application(self.h.db, self.session, self.alice_app, "shortlist")
        self.assertEqual(caught.exception.category, "conflict")

        with self.assertRaises(ModuleError):
            decide_application(self.h.db, self.session, 99999, "shortlist")

    def test_accept_is_refused_when_all_slots_are_filled(self):
        single_listing = add_listing(
            self.h.db, self.company_id, self.user_id, self.refs, slots=1
        )
        first = add_application(
            self.h.db, single_listing, add_student(self.h.db, self.refs, full_name="First")
        )
        second = add_application(
            self.h.db, single_listing, add_student(self.h.db, self.refs, full_name="Second")
        )
        decide_application(self.h.db, self.session, first, "shortlist")
        decide_application(self.h.db, self.session, first, "accept")
        decide_application(self.h.db, self.session, second, "shortlist")
        with self.assertRaises(ModuleError) as caught:
            decide_application(self.h.db, self.session, second, "accept")
        self.assertEqual(caught.exception.category, "conflict")
        self.assertIn("slots", caught.exception.message)
        self.assertIsNone(
            self.h.db.query_one(
                "SELECT * FROM placements WHERE application_id = %s", [second]
            )
        )

    def test_reject_and_under_review_transitions(self):
        result = decide_application(self.h.db, self.session, self.carol_app, "under_review")
        self.assertEqual(result["status"], "under_review")
        result = decide_application(self.h.db, self.session, self.carol_app, "reject")
        self.assertEqual(result["status"], "rejected")
        self.assertIsNone(
            self.h.db.query_one(
                "SELECT * FROM placements WHERE application_id = %s", [self.carol_app]
            )
        )

    def test_other_company_cannot_decide(self):
        other_company, other_user = add_employer_account(
            self.h.db, name="Decision Thief", email="decision-thief@example.com"
        )
        other_student = add_student(self.h.db, self.refs, full_name="Other Person")
        other_listing = add_listing(self.h.db, other_company, other_user, self.refs)
        foreign_application = add_application(
            self.h.db, other_listing, other_student
        )
        with self.assertRaises(ModuleError) as caught:
            decide_application(
                self.h.db, self.session, foreign_application, "shortlist"
            )
        self.assertEqual(caught.exception.category, "not_found")


class BulkDecisionTests(ApplicantSetup):
    def test_bulk_shortlist_reports_partial_success(self):
        other_company, other_user = add_employer_account(
            self.h.db, name="Bulk Other", email="bulk-other@example.com"
        )
        other_student = add_student(self.h.db, self.refs, full_name="Bulk Other Student")
        other_listing = add_listing(self.h.db, other_company, other_user, self.refs)
        foreign_application = add_application(
            self.h.db, other_listing, other_student
        )
        results = bulk_decide(
            self.h.db,
            self.session,
            [self.alice_app, foreign_application],
            "shortlist",
        )
        self.assertEqual(
            results,
            [
                {"id": self.alice_app, "ok": True},
                {
                    "id": foreign_application,
                    "ok": False,
                    "message": "Application not found.",
                },
            ],
        )
        status = self.h.db.query_one(
            "SELECT status FROM applications WHERE application_id = %s", [self.alice_app]
        )["status"]
        self.assertEqual(status, "shortlisted")

    def test_bulk_validation(self):
        with self.assertRaises(ModuleError):
            bulk_decide(self.h.db, self.session, [], "shortlist")
        with self.assertRaises(ModuleError):
            bulk_decide(self.h.db, self.session, list(range(1, 102)), "shortlist")
        with self.assertRaises(ModuleError):
            bulk_decide(self.h.db, self.session, [self.alice_app], "accept")
        with self.assertRaises(ModuleError):
            bulk_decide(self.h.db, self.session, "not-a-list", "shortlist")
        with self.assertRaises(ModuleError):
            bulk_decide(self.h.db, self.session, [0], "shortlist")


if __name__ == "__main__":
    unittest.main()
