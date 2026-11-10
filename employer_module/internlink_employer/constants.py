"""Shared constants for the InternLink employer module (WBS 4.4.1-4.4.5)."""

PAGE_SIZE = 20
MAX_MESSAGE_LEN = 5000
MAX_COMPLETION_NOTE_LEN = 2000
MAX_REQUEST_BYTES = 1024 * 1024

SLOTS_RANGE = (1, 500)          # listings.slots
WEEKS_RANGE = (1, 52)           # listings.duration_weeks

LISTING_STATUSES = {"draft", "open", "closed", "hidden"}
APPLICATION_STATUSES = {"submitted", "under_review", "shortlisted", "interview", "accepted", "rejected"}
# Statuses where the employer and candidate can message each other (SR10).
MESSAGING_STATUSES = ("shortlisted", "interview", "accepted")
MAX_DECISION_NOTE_LEN = 500
PLACEMENT_STATUSES = {"pending", "confirmed", "completed"}

# SR04 - transitions the employer is allowed to make.
EMPLOYER_APP_TRANSITIONS = {
    "submitted": {"under_review", "shortlisted", "rejected"},
    "under_review": {"shortlisted", "rejected"},
    "shortlisted": {"interview", "accepted", "rejected"},
    "interview": {"accepted", "rejected"},
}

LISTING_TRANSITIONS = {
    "draft": {"open", "hidden"},
    "open": {"closed", "hidden"},
    "closed": {"open", "hidden"},
    "hidden": {"open", "closed"},
}

# Whitelist of columns callers may sort applicants by. Never interpolate raw input.
SORT_WHITELIST = {
    "match_score": "match_score",
    "submitted_at": "submitted_at",
    "name": "applicant_name",
    "year": "year_of_study",
}

ACTION_TO_STATUS = {
    "shortlist": "shortlisted",
    "reject": "rejected",
    "accept": "accepted",
    "interview": "interview",
    "under_review": "under_review",
}

CATEGORY_HTTP_STATUS = {
    "invalid": 400,
    "unauthenticated": 401,
    "forbidden": 403,
    "not_found": 404,
    "conflict": 409,
    "server": 500,
}
