-- InternLink Uganda - SQLite reference schema for local development & tests.
-- MySQL deployments should use schema.mysql.sql.
--
-- This is the subset owned/consumed by the Employer module (WBS 4.4).  Tables
-- such as student_profiles, applications, placements, messages and
-- notifications are shared with the Student, Admin and Notifications modules.
-- Cross-module side effects (audit rows, notifications, slots_filled) are
-- applied transactionally by the service layer so the module remains portable
-- and does not depend on database triggers.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS companies (
    company_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL,
    sector              TEXT NOT NULL,
    location            TEXT NOT NULL,
    description         TEXT,
    contact_email       TEXT NOT NULL,
    website             TEXT,
    verification_status TEXT NOT NULL DEFAULT 'pending'
                        CONSTRAINT ck_companies_verification
                        CHECK (verification_status IN ('pending', 'verified', 'rejected', 'suspended')),
    rejection_reason    TEXT,
    verified_by         INTEGER,
    verified_at         TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    CONSTRAINT uq_companies_name UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS users (
    user_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email            TEXT NOT NULL,
    password_hash    TEXT NOT NULL,
    full_name        TEXT NOT NULL,
    phone            TEXT,
    role             TEXT NOT NULL
                     CONSTRAINT ck_users_role
                     CHECK (role IN ('student', 'employer', 'admin', 'coordinator')),
    status           TEXT NOT NULL DEFAULT 'pending'
                     CONSTRAINT ck_users_status
                     CHECK (status IN ('pending', 'active', 'suspended')),
    company_id       INTEGER REFERENCES companies(company_id),
    email_verified_at TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    CONSTRAINT uq_users_email UNIQUE (email),
    CONSTRAINT ck_users_employer_company
        CHECK (role <> 'employer' OR company_id IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS auth_tokens (
    token_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(user_id),
    purpose     TEXT NOT NULL
                CONSTRAINT ck_auth_tokens_purpose
                CHECK (purpose IN ('email_verify', 'password_reset')),
    token_hash  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    used_at     TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    CONSTRAINT uq_auth_tokens_hash UNIQUE (token_hash)
);

CREATE TABLE IF NOT EXISTS skills (
    skill_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT NOT NULL,
    CONSTRAINT uq_skills_name UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS programmes (
    programme_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    CONSTRAINT uq_programmes_name UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS interests (
    interest_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    CONSTRAINT uq_interests_name UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS universities (
    university_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    CONSTRAINT uq_universities_name UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS student_profiles (
    student_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id            INTEGER NOT NULL REFERENCES users(user_id),
    programme_id       INTEGER NOT NULL REFERENCES programmes(programme_id),
    university_id      INTEGER NOT NULL REFERENCES universities(university_id),
    year_of_study      INTEGER NOT NULL
                       CONSTRAINT ck_student_profiles_year CHECK (year_of_study BETWEEN 1 AND 7),
    preferred_location TEXT,
    willing_to_relocate INTEGER NOT NULL DEFAULT 0
                       CONSTRAINT ck_student_profiles_relocate
                       CHECK (willing_to_relocate IN (0, 1)),
    cv_path            TEXT,
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    CONSTRAINT uq_student_profiles_user UNIQUE (user_id)
);

CREATE TABLE IF NOT EXISTS student_skills (
    student_id INTEGER NOT NULL REFERENCES student_profiles(student_id),
    skill_id   INTEGER NOT NULL REFERENCES skills(skill_id),
    PRIMARY KEY (student_id, skill_id)
);

CREATE TABLE IF NOT EXISTS student_interests (
    student_id  INTEGER NOT NULL REFERENCES student_profiles(student_id),
    interest_id INTEGER NOT NULL REFERENCES interests(interest_id),
    PRIMARY KEY (student_id, interest_id)
);

CREATE TABLE IF NOT EXISTS listings (
    listing_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id           INTEGER NOT NULL REFERENCES companies(company_id),
    posted_by            INTEGER NOT NULL REFERENCES users(user_id),
    title                TEXT NOT NULL,
    description          TEXT NOT NULL,
    sector               TEXT NOT NULL,
    location             TEXT NOT NULL,
    is_remote            INTEGER NOT NULL DEFAULT 0
                         CONSTRAINT ck_listings_remote CHECK (is_remote IN (0, 1)),
    duration_weeks       INTEGER NOT NULL
                         CONSTRAINT ck_listings_duration_weeks
                         CHECK (duration_weeks BETWEEN 1 AND 52),
    slots                INTEGER NOT NULL
                         CONSTRAINT ck_listings_slots
                         CHECK (slots BETWEEN 1 AND 500),
    slots_filled         INTEGER NOT NULL DEFAULT 0
                         CONSTRAINT ck_listings_slots_filled
                         CHECK (slots_filled >= 0 AND slots_filled <= slots),
    application_deadline TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'draft'
                         CONSTRAINT ck_listings_status
                         CHECK (status IN ('draft', 'open', 'closed', 'hidden')),
    posted_at            TEXT,
    closed_at            TEXT,
    created_at           TEXT NOT NULL DEFAULT (datetime('now')),
    CONSTRAINT fk_listings_company FOREIGN KEY (company_id) REFERENCES companies(company_id),
    CONSTRAINT fk_listings_posted_by FOREIGN KEY (posted_by) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS listing_skills (
    listing_id INTEGER NOT NULL REFERENCES listings(listing_id),
    skill_id   INTEGER NOT NULL REFERENCES skills(skill_id),
    is_required INTEGER NOT NULL DEFAULT 1
                CONSTRAINT ck_listing_skills_required CHECK (is_required IN (0, 1)),
    PRIMARY KEY (listing_id, skill_id)
);

CREATE TABLE IF NOT EXISTS listing_programmes (
    listing_id   INTEGER NOT NULL REFERENCES listings(listing_id),
    programme_id INTEGER NOT NULL REFERENCES programmes(programme_id),
    PRIMARY KEY (listing_id, programme_id)
);

CREATE TABLE IF NOT EXISTS listing_interests (
    listing_id  INTEGER NOT NULL REFERENCES listings(listing_id),
    interest_id INTEGER NOT NULL REFERENCES interests(interest_id),
    PRIMARY KEY (listing_id, interest_id)
);

CREATE TABLE IF NOT EXISTS applications (
    application_id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id     INTEGER NOT NULL REFERENCES listings(listing_id),
    student_id     INTEGER NOT NULL REFERENCES student_profiles(student_id),
    cover_note     TEXT,
    match_score    REAL,
    status         TEXT NOT NULL DEFAULT 'submitted'
                   CONSTRAINT ck_applications_status
                   CHECK (status IN ('submitted', 'under_review', 'shortlisted', 'accepted', 'rejected')),
    submitted_at   TEXT NOT NULL DEFAULT (datetime('now')),
    decided_at     TEXT,
    CONSTRAINT uq_applications_listing_student UNIQUE (listing_id, student_id)
);

CREATE TABLE IF NOT EXISTS placements (
    placement_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id  INTEGER NOT NULL REFERENCES applications(application_id),
    status          TEXT NOT NULL DEFAULT 'pending'
                    CONSTRAINT ck_placements_status
                    CHECK (status IN ('pending', 'confirmed', 'completed')),
    start_date      TEXT,
    end_date        TEXT,
    completion_note TEXT,
    completed_by    INTEGER REFERENCES users(user_id),
    completed_at    TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    CONSTRAINT uq_placements_application UNIQUE (application_id),
    CONSTRAINT ck_placements_dates
        CHECK (start_date IS NULL OR end_date IS NULL OR end_date >= start_date)
);

CREATE TABLE IF NOT EXISTS messages (
    message_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES applications(application_id),
    sender_id      INTEGER NOT NULL REFERENCES users(user_id),
    recipient_id   INTEGER NOT NULL REFERENCES users(user_id),
    body           TEXT NOT NULL
                   CONSTRAINT ck_messages_body CHECK (length(body) BETWEEN 1 AND 5000),
    sent_at        TEXT NOT NULL DEFAULT (datetime('now')),
    is_read        INTEGER NOT NULL DEFAULT 0
                   CONSTRAINT ck_messages_is_read CHECK (is_read IN (0, 1))
);

CREATE TABLE IF NOT EXISTS notifications (
    notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(user_id),
    type            TEXT NOT NULL,
    title           TEXT NOT NULL,
    message         TEXT NOT NULL,
    channel         TEXT NOT NULL DEFAULT 'in_app'
                    CONSTRAINT ck_notifications_channel CHECK (channel IN ('in_app', 'email')),
    related_type    TEXT,
    related_id      INTEGER,
    is_read         INTEGER NOT NULL DEFAULT 0
                    CONSTRAINT ck_notifications_is_read CHECK (is_read IN (0, 1)),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audit_log (
    event_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_user_id INTEGER REFERENCES users(user_id),
    action        TEXT NOT NULL,
    entity_type   TEXT,
    entity_id     TEXT,
    result        TEXT,
    details       TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_users_company ON users(company_id);
CREATE INDEX IF NOT EXISTS ix_listings_company_status ON listings(company_id, status);
CREATE INDEX IF NOT EXISTS ix_applications_listing_status ON applications(listing_id, status);
CREATE INDEX IF NOT EXISTS ix_placements_application ON placements(application_id);
CREATE INDEX IF NOT EXISTS ix_messages_application ON messages(application_id, sent_at);
CREATE INDEX IF NOT EXISTS ix_notifications_user ON notifications(user_id, is_read);

-- One row per application, enriched with the company and student labels the
-- employer applicant list needs.  Ownership is still enforced in the service.
CREATE VIEW IF NOT EXISTS v_employer_applicants AS
SELECT a.application_id,
       a.listing_id,
       l.company_id,
       a.student_id,
       u.full_name       AS applicant_name,
       p.name            AS programme,
       sp.year_of_study  AS year_of_study,
       un.name           AS university,
       a.match_score,
       a.status,
       a.submitted_at,
       sp.cv_path
FROM applications a
JOIN listings l         ON l.listing_id = a.listing_id
JOIN student_profiles sp ON sp.student_id = a.student_id
JOIN users u            ON u.user_id = sp.user_id
JOIN programmes p       ON p.programme_id = sp.programme_id
JOIN universities un    ON un.university_id = sp.university_id;
