"""Interview stage, decline reasons and the richer applicant detail."""

from datetime import datetime, timedelta, timezone

from internlink_employer.errors import ModuleError
from internlink_employer.services import decide_application, list_applicants, send_message, view_applicant
from tests.test_applications import ApplicantSetup


def future(hours=48):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


class InterviewStageTests(ApplicantSetup):
    def test_shortlisted_candidate_can_be_invited_then_offered(self):
        result = decide_application(
            self.h.db, self.session, self.bob_app, "interview",
            interview_at=future(), interview_note="Kampala office, bring your CV",
        )
        self.assertEqual(result["status"], "interview")
        row = self.h.db.query_one(
            "SELECT status, interview_at, interview_note FROM applications WHERE application_id = %s", [self.bob_app]
        )
        self.assertEqual(row["status"], "interview")
        self.assertIsNotNone(row["interview_at"])
        self.assertEqual(row["interview_note"], "Kampala office, bring your CV")
        # Messaging stays open at the interview stage.
        self.assertTrue(send_message(self.h.db, self.session, self.bob_app, "See you then")["sent"])
        board = list_applicants(self.h.db, self.session, self.listing_id)
        bob = next(item for item in board["applicants"] if item["application_id"] == self.bob_app)
        self.assertEqual(bob["status"], "interview")
        self.assertIsNotNone(bob["interview_at"])
        self.assertEqual(decide_application(self.h.db, self.session, self.bob_app, "accept")["status"], "accepted")

    def test_interview_needs_a_future_time_and_a_shortlist(self):
        for bad in (None, "", "next tuesday", future(-2)):
            with self.assertRaises(ModuleError):
                decide_application(self.h.db, self.session, self.bob_app, "interview", interview_at=bad)
        with self.assertRaises(ModuleError) as error:
            decide_application(self.h.db, self.session, self.alice_app, "interview", interview_at=future())
        self.assertEqual(error.exception.category, "conflict")

    def test_reject_reason_is_stored_and_limited(self):
        with self.assertRaises(ModuleError):
            decide_application(self.h.db, self.session, self.alice_app, "reject", reason="x" * 501)
        decide_application(self.h.db, self.session, self.alice_app, "reject", reason="We needed more SQL experience")
        row = self.h.db.query_one("SELECT status, decision_note FROM applications WHERE application_id = %s", [self.alice_app])
        self.assertEqual(row["status"], "rejected")
        self.assertEqual(row["decision_note"], "We needed more SQL experience")

    def test_detail_lists_listing_skills_against_the_candidate(self):
        detail = view_applicant(self.h.db, self.session, self.carol_app)
        self.assertEqual(detail["application_id"], self.carol_app)
        self.assertTrue(detail["has_cv"])
        self.assertIsInstance(detail["listing_skills"], list)
        for skill in detail["listing_skills"]:
            self.assertEqual(set(skill), {"name", "required", "has"})
