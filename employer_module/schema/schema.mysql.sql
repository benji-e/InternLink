-- InternLink Uganda - MySQL reference schema for the Employer module.
-- Requires MySQL 8.0.16+ for enforced CHECK constraints.  Run this once in a
-- fresh database or compare it with the shared project migrations.  The service
-- layer applies audit/notification/slot updates itself, so no triggers are
-- required; remove duplicated trigger logic if the shared deployment already
-- maintains these tables.

CREATE TABLE IF NOT EXISTS companies (
    company_id          BIGINT NOT NULL AUTO_INCREMENT,
    name                VARCHAR(150) NOT NULL,
    sector              VARCHAR(100) NOT NULL,
    location            VARCHAR(150) NOT NULL,
    description         TEXT,
    contact_email       VARCHAR(254) NOT NULL,
    website             VARCHAR(500),
    verification_status VARCHAR(20) NOT NULL DEFAULT 'pending',
    rejection_reason    TEXT,
    verified_by         BIGINT,
    verified_at         DATETIME,
    created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (company_id),
    CONSTRAINT uq_companies_name UNIQUE (name),
    CONSTRAINT ck_companies_verification
        CHECK (verification_status IN ('pending', 'verified', 'rejected', 'suspended'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS users (
    user_id           BIGINT NOT NULL AUTO_INCREMENT,
    email             VARCHAR(254) NOT NULL,
    password_hash     VARCHAR(255) NOT NULL,
    full_name         VARCHAR(150) NOT NULL,
    phone             VARCHAR(30),
    role              VARCHAR(20) NOT NULL,
    status            VARCHAR(20) NOT NULL DEFAULT 'pending',
    company_id        BIGINT,
    email_verified_at DATETIME,
    created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id),
    CONSTRAINT uq_users_email UNIQUE (email),
    CONSTRAINT fk_users_company FOREIGN KEY (company_id) REFERENCES companies(company_id),
    CONSTRAINT ck_users_role
        CHECK (role IN ('student', 'employer', 'admin', 'coordinator')),
    CONSTRAINT ck_users_status
        CHECK (status IN ('pending', 'active', 'suspended')),
    CONSTRAINT ck_users_employer_company
        CHECK (role <> 'employer' OR company_id IS NOT NULL),
    KEY ix_users_company (company_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS auth_tokens (
    token_id   BIGINT NOT NULL AUTO_INCREMENT,
    user_id    BIGINT NOT NULL,
    purpose    VARCHAR(50) NOT NULL,
    token_hash CHAR(64) NOT NULL,
    expires_at DATETIME NOT NULL,
    used_at    DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (token_id),
    CONSTRAINT uq_auth_tokens_hash UNIQUE (token_hash),
    CONSTRAINT fk_auth_tokens_user FOREIGN KEY (user_id) REFERENCES users(user_id),
    CONSTRAINT ck_auth_tokens_purpose
        CHECK (purpose IN ('email_verify', 'password_reset'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS skills (
    skill_id BIGINT NOT NULL AUTO_INCREMENT,
    name     VARCHAR(100) NOT NULL,
    PRIMARY KEY (skill_id),
    CONSTRAINT uq_skills_name UNIQUE (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS programmes (
    programme_id BIGINT NOT NULL AUTO_INCREMENT,
    name         VARCHAR(150) NOT NULL,
    PRIMARY KEY (programme_id),
    CONSTRAINT uq_programmes_name UNIQUE (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS interests (
    interest_id BIGINT NOT NULL AUTO_INCREMENT,
    name        VARCHAR(100) NOT NULL,
    PRIMARY KEY (interest_id),
    CONSTRAINT uq_interests_name UNIQUE (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS universities (
    university_id BIGINT NOT NULL AUTO_INCREMENT,
    name          VARCHAR(150) NOT NULL,
    PRIMARY KEY (university_id),
    CONSTRAINT uq_universities_name UNIQUE (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS student_profiles (
    student_id          BIGINT NOT NULL AUTO_INCREMENT,
    user_id             BIGINT NOT NULL,
    programme_id        BIGINT NOT NULL,
    university_id       BIGINT NOT NULL,
    year_of_study       INTEGER NOT NULL,
    preferred_location  VARCHAR(150),
    willing_to_relocate BOOLEAN NOT NULL DEFAULT FALSE,
    cv_path             VARCHAR(500),
    created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (student_id),
    CONSTRAINT uq_student_profiles_user UNIQUE (user_id),
    CONSTRAINT fk_student_profiles_user FOREIGN KEY (user_id) REFERENCES users(user_id),
    CONSTRAINT fk_student_profiles_programme
        FOREIGN KEY (programme_id) REFERENCES programmes(programme_id),
    CONSTRAINT fk_student_profiles_university
        FOREIGN KEY (university_id) REFERENCES universities(university_id),
    CONSTRAINT ck_student_profiles_year CHECK (year_of_study BETWEEN 1 AND 7)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS student_skills (
    student_id BIGINT NOT NULL,
    skill_id   BIGINT NOT NULL,
    PRIMARY KEY (student_id, skill_id),
    CONSTRAINT fk_student_skills_student
        FOREIGN KEY (student_id) REFERENCES student_profiles(student_id),
    CONSTRAINT fk_student_skills_skill FOREIGN KEY (skill_id) REFERENCES skills(skill_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS student_interests (
    student_id  BIGINT NOT NULL,
    interest_id BIGINT NOT NULL,
    PRIMARY KEY (student_id, interest_id),
    CONSTRAINT fk_student_interests_student
        FOREIGN KEY (student_id) REFERENCES student_profiles(student_id),
    CONSTRAINT fk_student_interests_interest
        FOREIGN KEY (interest_id) REFERENCES interests(interest_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS listings (
    listing_id           BIGINT NOT NULL AUTO_INCREMENT,
    company_id           BIGINT NOT NULL,
    posted_by            BIGINT NOT NULL,
    title                VARCHAR(150) NOT NULL,
    description          TEXT NOT NULL,
    sector               VARCHAR(100) NOT NULL,
    location             VARCHAR(150) NOT NULL,
    is_remote            BOOLEAN NOT NULL DEFAULT FALSE,
    duration_weeks       INTEGER NOT NULL,
    slots                INTEGER NOT NULL,
    slots_filled         INTEGER NOT NULL DEFAULT 0,
    application_deadline DATE NOT NULL,
    status               VARCHAR(20) NOT NULL DEFAULT 'draft',
    posted_at            DATETIME,
    closed_at            DATETIME,
    created_at           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (listing_id),
    CONSTRAINT fk_listings_company FOREIGN KEY (company_id) REFERENCES companies(company_id),
    CONSTRAINT fk_listings_posted_by FOREIGN KEY (posted_by) REFERENCES users(user_id),
    CONSTRAINT ck_listings_duration_weeks CHECK (duration_weeks BETWEEN 1 AND 52),
    CONSTRAINT ck_listings_slots CHECK (slots BETWEEN 1 AND 500),
    CONSTRAINT ck_listings_slots_filled
        CHECK (slots_filled >= 0 AND slots_filled <= slots),
    CONSTRAINT ck_listings_status
        CHECK (status IN ('draft', 'open', 'closed', 'hidden')),
    KEY ix_listings_company_status (company_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS listing_skills (
    listing_id  BIGINT NOT NULL,
    skill_id    BIGINT NOT NULL,
    is_required BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (listing_id, skill_id),
    CONSTRAINT fk_listing_skills_listing
        FOREIGN KEY (listing_id) REFERENCES listings(listing_id),
    CONSTRAINT fk_listing_skills_skill FOREIGN KEY (skill_id) REFERENCES skills(skill_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS listing_programmes (
    listing_id   BIGINT NOT NULL,
    programme_id BIGINT NOT NULL,
    PRIMARY KEY (listing_id, programme_id),
    CONSTRAINT fk_listing_programmes_listing
        FOREIGN KEY (listing_id) REFERENCES listings(listing_id),
    CONSTRAINT fk_listing_programmes_programme
        FOREIGN KEY (programme_id) REFERENCES programmes(programme_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS listing_interests (
    listing_id  BIGINT NOT NULL,
    interest_id BIGINT NOT NULL,
    PRIMARY KEY (listing_id, interest_id),
    CONSTRAINT fk_listing_interests_listing
        FOREIGN KEY (listing_id) REFERENCES listings(listing_id),
    CONSTRAINT fk_listing_interests_interest
        FOREIGN KEY (interest_id) REFERENCES interests(interest_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS applications (
    application_id BIGINT NOT NULL AUTO_INCREMENT,
    listing_id     BIGINT NOT NULL,
    student_id     BIGINT NOT NULL,
    cover_note     TEXT,
    match_score    DOUBLE,
    status         VARCHAR(20) NOT NULL DEFAULT 'submitted',
    submitted_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    decided_at     DATETIME,
    PRIMARY KEY (application_id),
    CONSTRAINT uq_applications_listing_student UNIQUE (listing_id, student_id),
    CONSTRAINT fk_applications_listing FOREIGN KEY (listing_id) REFERENCES listings(listing_id),
    CONSTRAINT fk_applications_student
        FOREIGN KEY (student_id) REFERENCES student_profiles(student_id),
    CONSTRAINT ck_applications_status
        CHECK (status IN ('submitted', 'under_review', 'shortlisted', 'accepted', 'rejected')),
    KEY ix_applications_listing_status (listing_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS placements (
    placement_id    BIGINT NOT NULL AUTO_INCREMENT,
    application_id  BIGINT NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    start_date      DATE,
    end_date        DATE,
    completion_note TEXT,
    completed_by    BIGINT,
    completed_at    DATETIME,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (placement_id),
    CONSTRAINT uq_placements_application UNIQUE (application_id),
    CONSTRAINT fk_placements_application
        FOREIGN KEY (application_id) REFERENCES applications(application_id),
    CONSTRAINT fk_placements_completed_by
        FOREIGN KEY (completed_by) REFERENCES users(user_id),
    CONSTRAINT ck_placements_status
        CHECK (status IN ('pending', 'confirmed', 'completed')),
    CONSTRAINT ck_placements_dates
        CHECK (start_date IS NULL OR end_date IS NULL OR end_date >= start_date),
    KEY ix_placements_application (application_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS messages (
    message_id     BIGINT NOT NULL AUTO_INCREMENT,
    application_id BIGINT NOT NULL,
    sender_id      BIGINT NOT NULL,
    recipient_id   BIGINT NOT NULL,
    body           TEXT NOT NULL,
    sent_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_read        BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (message_id),
    CONSTRAINT fk_messages_application
        FOREIGN KEY (application_id) REFERENCES applications(application_id),
    CONSTRAINT fk_messages_sender FOREIGN KEY (sender_id) REFERENCES users(user_id),
    CONSTRAINT fk_messages_recipient FOREIGN KEY (recipient_id) REFERENCES users(user_id),
    CONSTRAINT ck_messages_body CHECK (char_length(body) BETWEEN 1 AND 5000),
    KEY ix_messages_application (application_id, sent_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS notifications (
    notification_id BIGINT NOT NULL AUTO_INCREMENT,
    user_id         BIGINT NOT NULL,
    type            VARCHAR(50) NOT NULL,
    title           VARCHAR(255) NOT NULL,
    message         TEXT NOT NULL,
    channel         VARCHAR(20) NOT NULL DEFAULT 'in_app',
    related_type    VARCHAR(50),
    related_id      BIGINT,
    is_read         BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (notification_id),
    CONSTRAINT fk_notifications_user FOREIGN KEY (user_id) REFERENCES users(user_id),
    CONSTRAINT ck_notifications_channel CHECK (channel IN ('in_app', 'email')),
    KEY ix_notifications_user (user_id, is_read)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS audit_log (
    event_id      BIGINT NOT NULL AUTO_INCREMENT,
    actor_user_id BIGINT,
    action        VARCHAR(100) NOT NULL,
    entity_type   VARCHAR(100),
    entity_id     VARCHAR(255),
    result        VARCHAR(50),
    details       TEXT,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (event_id),
    CONSTRAINT fk_audit_log_actor
        FOREIGN KEY (actor_user_id) REFERENCES users(user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE OR REPLACE SQL SECURITY INVOKER VIEW v_employer_applicants AS
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
