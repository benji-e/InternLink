-- InternLink Uganda - PostgreSQL reference schema for the Employer module.
-- Run this once in a fresh database or compare it with the shared project
-- schema.  The service layer applies audit/notification/slot updates itself,
-- so no triggers are required; remove duplicated trigger logic if the shared
-- deployment already maintains these tables.

CREATE TABLE IF NOT EXISTS companies (
    company_id          BIGSERIAL PRIMARY KEY,
    name                TEXT NOT NULL,
    sector              TEXT NOT NULL,
    location            TEXT NOT NULL,
    description         TEXT,
    contact_email       TEXT NOT NULL,
    website             TEXT,
    verification_status TEXT NOT NULL DEFAULT 'pending',
    rejection_reason    TEXT,
    verified_by         BIGINT,
    verified_at         TIMESTAMP,
    created_at          TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_companies_name UNIQUE (name),
    CONSTRAINT ck_companies_verification
        CHECK (verification_status IN ('pending', 'verified', 'rejected', 'suspended'))
);

CREATE TABLE IF NOT EXISTS users (
    user_id           BIGSERIAL PRIMARY KEY,
    email             TEXT NOT NULL,
    password_hash     TEXT NOT NULL,
    full_name         TEXT NOT NULL,
    phone             TEXT,
    role              TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'pending',
    company_id        BIGINT REFERENCES companies(company_id),
    email_verified_at TIMESTAMP,
    created_at        TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_users_email UNIQUE (email),
    CONSTRAINT ck_users_role
        CHECK (role IN ('student', 'employer', 'admin', 'coordinator')),
    CONSTRAINT ck_users_status
        CHECK (status IN ('pending', 'active', 'suspended')),
    CONSTRAINT ck_users_employer_company
        CHECK (role <> 'employer' OR company_id IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS auth_tokens (
    token_id   BIGSERIAL PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES users(user_id),
    purpose    TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    used_at    TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_auth_tokens_hash UNIQUE (token_hash),
    CONSTRAINT ck_auth_tokens_purpose
        CHECK (purpose IN ('email_verify', 'password_reset'))
);

CREATE TABLE IF NOT EXISTS skills (
    skill_id BIGSERIAL PRIMARY KEY,
    name     TEXT NOT NULL,
    CONSTRAINT uq_skills_name UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS programmes (
    programme_id BIGSERIAL PRIMARY KEY,
    name         TEXT NOT NULL,
    CONSTRAINT uq_programmes_name UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS interests (
    interest_id BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    CONSTRAINT uq_interests_name UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS universities (
    university_id BIGSERIAL PRIMARY KEY,
    name          TEXT NOT NULL,
    CONSTRAINT uq_universities_name UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS student_profiles (
    student_id          BIGSERIAL PRIMARY KEY,
    user_id             BIGINT NOT NULL REFERENCES users(user_id),
    programme_id        BIGINT NOT NULL REFERENCES programmes(programme_id),
    university_id       BIGINT NOT NULL REFERENCES universities(university_id),
    year_of_study       INTEGER NOT NULL,
    preferred_location  TEXT,
    willing_to_relocate BOOLEAN NOT NULL DEFAULT FALSE,
    cv_path             TEXT,
    created_at          TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_student_profiles_user UNIQUE (user_id),
    CONSTRAINT ck_student_profiles_year CHECK (year_of_study BETWEEN 1 AND 7)
);

CREATE TABLE IF NOT EXISTS student_skills (
    student_id BIGINT NOT NULL REFERENCES student_profiles(student_id),
    skill_id   BIGINT NOT NULL REFERENCES skills(skill_id),
    PRIMARY KEY (student_id, skill_id)
);

CREATE TABLE IF NOT EXISTS student_interests (
    student_id  BIGINT NOT NULL REFERENCES student_profiles(student_id),
    interest_id BIGINT NOT NULL REFERENCES interests(interest_id),
    PRIMARY KEY (student_id, interest_id)
);

CREATE TABLE IF NOT EXISTS listings (
    listing_id           BIGSERIAL PRIMARY KEY,
    company_id           BIGINT NOT NULL REFERENCES companies(company_id),
    posted_by            BIGINT NOT NULL REFERENCES users(user_id),
    title                TEXT NOT NULL,
    description          TEXT NOT NULL,
    sector               TEXT NOT NULL,
    location             TEXT NOT NULL,
    is_remote            BOOLEAN NOT NULL DEFAULT FALSE,
    duration_weeks       INTEGER NOT NULL,
    slots                INTEGER NOT NULL,
    slots_filled         INTEGER NOT NULL DEFAULT 0,
    application_deadline DATE NOT NULL,
    status               TEXT NOT NULL DEFAULT 'draft',
    posted_at            TIMESTAMP,
    closed_at            TIMESTAMP,
    created_at           TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT ck_listings_duration_weeks CHECK (duration_weeks BETWEEN 1 AND 52),
    CONSTRAINT ck_listings_slots CHECK (slots BETWEEN 1 AND 500),
    CONSTRAINT ck_listings_slots_filled CHECK (slots_filled >= 0 AND slots_filled <= slots),
    CONSTRAINT ck_listings_status
        CHECK (status IN ('draft', 'open', 'closed', 'hidden'))
);

CREATE TABLE IF NOT EXISTS listing_skills (
    listing_id  BIGINT NOT NULL REFERENCES listings(listing_id),
    skill_id    BIGINT NOT NULL REFERENCES skills(skill_id),
    is_required BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (listing_id, skill_id)
);

CREATE TABLE IF NOT EXISTS listing_programmes (
    listing_id   BIGINT NOT NULL REFERENCES listings(listing_id),
    programme_id BIGINT NOT NULL REFERENCES programmes(programme_id),
    PRIMARY KEY (listing_id, programme_id)
);

CREATE TABLE IF NOT EXISTS listing_interests (
    listing_id  BIGINT NOT NULL REFERENCES listings(listing_id),
    interest_id BIGINT NOT NULL REFERENCES interests(interest_id),
    PRIMARY KEY (listing_id, interest_id)
);

CREATE TABLE IF NOT EXISTS applications (
    application_id BIGSERIAL PRIMARY KEY,
    listing_id     BIGINT NOT NULL REFERENCES listings(listing_id),
    student_id     BIGINT NOT NULL REFERENCES student_profiles(student_id),
    cover_note     TEXT,
    match_score    DOUBLE PRECISION,
    status         TEXT NOT NULL DEFAULT 'submitted',
    submitted_at   TIMESTAMP NOT NULL DEFAULT now(),
    decided_at     TIMESTAMP,
    CONSTRAINT uq_applications_listing_student UNIQUE (listing_id, student_id),
    CONSTRAINT ck_applications_status
        CHECK (status IN ('submitted', 'under_review', 'shortlisted', 'accepted', 'rejected'))
);

CREATE TABLE IF NOT EXISTS placements (
    placement_id    BIGSERIAL PRIMARY KEY,
    application_id  BIGINT NOT NULL REFERENCES applications(application_id),
    status          TEXT NOT NULL DEFAULT 'pending',
    start_date      DATE,
    end_date        DATE,
    completion_note TEXT,
    completed_by    BIGINT REFERENCES users(user_id),
    completed_at    TIMESTAMP,
    created_at      TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_placements_application UNIQUE (application_id),
    CONSTRAINT ck_placements_status
        CHECK (status IN ('pending', 'confirmed', 'completed')),
    CONSTRAINT ck_placements_dates
        CHECK (start_date IS NULL OR end_date IS NULL OR end_date >= start_date)
);

CREATE TABLE IF NOT EXISTS messages (
    message_id     BIGSERIAL PRIMARY KEY,
    application_id BIGINT NOT NULL REFERENCES applications(application_id),
    sender_id      BIGINT NOT NULL REFERENCES users(user_id),
    recipient_id   BIGINT NOT NULL REFERENCES users(user_id),
    body           TEXT NOT NULL,
    sent_at        TIMESTAMP NOT NULL DEFAULT now(),
    is_read        BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT ck_messages_body CHECK (char_length(body) BETWEEN 1 AND 5000)
);

CREATE TABLE IF NOT EXISTS notifications (
    notification_id BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(user_id),
    type            TEXT NOT NULL,
    title           TEXT NOT NULL,
    message         TEXT NOT NULL,
    channel         TEXT NOT NULL DEFAULT 'in_app',
    related_type    TEXT,
    related_id      BIGINT,
    is_read         BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT ck_notifications_channel CHECK (channel IN ('in_app', 'email'))
);

CREATE TABLE IF NOT EXISTS audit_log (
    event_id      BIGSERIAL PRIMARY KEY,
    actor_user_id BIGINT REFERENCES users(user_id),
    action        TEXT NOT NULL,
    entity_type   TEXT,
    entity_id     TEXT,
    result        TEXT,
    details       TEXT,
    created_at    TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_users_company ON users(company_id);
CREATE INDEX IF NOT EXISTS ix_listings_company_status ON listings(company_id, status);
CREATE INDEX IF NOT EXISTS ix_applications_listing_status ON applications(listing_id, status);
CREATE INDEX IF NOT EXISTS ix_placements_application ON placements(application_id);
CREATE INDEX IF NOT EXISTS ix_messages_application ON messages(application_id, sent_at);
CREATE INDEX IF NOT EXISTS ix_notifications_user ON notifications(user_id, is_read);

CREATE OR REPLACE VIEW v_employer_applicants AS
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
JOIN listings l          ON l.listing_id = a.listing_id
JOIN student_profiles sp ON sp.student_id = a.student_id
JOIN users u             ON u.user_id = sp.user_id
JOIN programmes p        ON p.programme_id = sp.programme_id
JOIN universities un     ON un.university_id = sp.university_id;
