-- =====================================================================
-- InternLink Uganda - Database schema (PostgreSQL 16)
-- File 01: tables, constraints, indexes, comments
-- Group E, MUST - WBS 3.2 / 4.2.2
-- Run order: 01_schema -> 02_functions_triggers -> 03_views_functions -> 04_roles -> 05_seed
-- =====================================================================
SET client_min_messages = warning;

-- ---------------------------------------------------------------------
-- Reference / organisation tables
-- ---------------------------------------------------------------------
CREATE TABLE universities (
    university_id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name             TEXT        NOT NULL,
    location         TEXT        NOT NULL,
    email_domain     TEXT        NOT NULL,
    status           TEXT        NOT NULL DEFAULT 'pending',
    verified_by      BIGINT,
    verified_at      TIMESTAMPTZ,
    rejection_reason TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_universities_status CHECK (status IN ('pending','verified','rejected','suspended')),
    CONSTRAINT ck_universities_domain CHECK (email_domain = lower(email_domain) AND email_domain ~ '^[a-z0-9]([a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}$'),
    CONSTRAINT ck_universities_name   CHECK (length(btrim(name)) > 0),
    CONSTRAINT ck_universities_reject CHECK (status <> 'rejected' OR length(btrim(coalesce(rejection_reason,''))) > 0),
    CONSTRAINT ck_universities_verif  CHECK (status <> 'verified' OR verified_at IS NOT NULL)
);
CREATE UNIQUE INDEX uq_universities_name   ON universities (lower(name));
CREATE UNIQUE INDEX uq_universities_domain ON universities (lower(email_domain));

CREATE TABLE departments (
    department_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    university_id BIGINT NOT NULL REFERENCES universities(university_id) ON DELETE RESTRICT,
    name          TEXT   NOT NULL,
    CONSTRAINT ck_departments_name CHECK (length(btrim(name)) > 0),
    CONSTRAINT uq_departments_dept_univ UNIQUE (department_id, university_id)
);
CREATE UNIQUE INDEX uq_departments_univ_name ON departments (university_id, lower(name));

CREATE TABLE programmes (
    programme_id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    department_id   BIGINT NOT NULL REFERENCES departments(department_id) ON DELETE RESTRICT,
    name            TEXT   NOT NULL,
    programme_group TEXT   NOT NULL,
    CONSTRAINT ck_programmes_name  CHECK (length(btrim(name)) > 0),
    CONSTRAINT ck_programmes_group CHECK (programme_group = lower(programme_group) AND length(btrim(programme_group)) > 0),
    CONSTRAINT uq_programmes_prog_dept UNIQUE (programme_id, department_id)
);
CREATE UNIQUE INDEX uq_programmes_dept_name ON programmes (department_id, lower(name));
CREATE INDEX ix_programmes_group ON programmes (programme_group);

CREATE TABLE companies (
    company_id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                TEXT        NOT NULL,
    sector              TEXT        NOT NULL,
    location            TEXT        NOT NULL,
    description         TEXT,
    contact_email       TEXT        NOT NULL,
    website             TEXT,
    verification_status TEXT        NOT NULL DEFAULT 'pending',
    verified_by         BIGINT,
    verified_at         TIMESTAMPTZ,
    rejection_reason    TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_companies_status  CHECK (verification_status IN ('pending','verified','rejected','suspended')),
    CONSTRAINT ck_companies_name    CHECK (length(btrim(name)) > 0),
    CONSTRAINT ck_companies_email   CHECK (contact_email ~* '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'),
    CONSTRAINT ck_companies_reject  CHECK (verification_status <> 'rejected' OR length(btrim(coalesce(rejection_reason,''))) > 0),
    CONSTRAINT ck_companies_verif   CHECK (verification_status <> 'verified' OR verified_at IS NOT NULL)
);
CREATE UNIQUE INDEX uq_companies_name ON companies (lower(name));
CREATE INDEX ix_companies_status ON companies (verification_status);

-- ---------------------------------------------------------------------
-- Users and authentication
-- ---------------------------------------------------------------------
CREATE TABLE users (
    user_id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email              TEXT        NOT NULL,
    password_hash      TEXT        NOT NULL,
    full_name          TEXT        NOT NULL,
    phone              TEXT,
    role               TEXT        NOT NULL,
    status             TEXT        NOT NULL DEFAULT 'pending',
    company_id         BIGINT      REFERENCES companies(company_id)       ON DELETE RESTRICT,
    university_id      BIGINT      REFERENCES universities(university_id) ON DELETE RESTRICT,
    department_id      BIGINT,
    email_verified_at  TIMESTAMPTZ,
    failed_login_count INTEGER     NOT NULL DEFAULT 0,
    locked_until       TIMESTAMPTZ,
    last_login_at      TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_users_role     CHECK (role IN ('student','employer','coordinator','admin')),
    CONSTRAINT ck_users_status   CHECK (status IN ('pending','active','rejected','suspended')),
    CONSTRAINT ck_users_email    CHECK (email ~* '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$' AND email = lower(email)),
    CONSTRAINT ck_users_name     CHECK (length(btrim(full_name)) > 0),
    CONSTRAINT ck_users_hash     CHECK (length(password_hash) >= 20),
    CONSTRAINT ck_users_failed   CHECK (failed_login_count >= 0),
    -- Role scope: employers belong to a company, coordinators to a university, others to neither (SR17, NFR06)
    CONSTRAINT ck_users_company_scope CHECK ((role = 'employer')    = (company_id    IS NOT NULL)),
    CONSTRAINT ck_users_univ_scope    CHECK ((role = 'coordinator') = (university_id IS NOT NULL)),
    CONSTRAINT ck_users_dept_scope    CHECK (department_id IS NULL OR role = 'coordinator'),
    -- An account can only be Active after its email is verified (Security design 5.1)
    CONSTRAINT ck_users_active_email  CHECK (status <> 'active' OR email_verified_at IS NOT NULL),
    CONSTRAINT uq_users_user_role    UNIQUE (user_id, role),
    CONSTRAINT uq_users_user_company UNIQUE (user_id, company_id),
    CONSTRAINT uq_users_user_univ    UNIQUE (user_id, university_id),
    CONSTRAINT fk_users_department FOREIGN KEY (department_id, university_id)
        REFERENCES departments (department_id, university_id) ON DELETE RESTRICT
);
CREATE UNIQUE INDEX uq_users_email ON users (lower(email));
CREATE INDEX ix_users_company ON users (company_id) WHERE company_id IS NOT NULL;
CREATE INDEX ix_users_university ON users (university_id) WHERE university_id IS NOT NULL;
CREATE INDEX ix_users_role_status ON users (role, status);

ALTER TABLE universities ADD CONSTRAINT fk_universities_verified_by FOREIGN KEY (verified_by) REFERENCES users(user_id) ON DELETE RESTRICT;
ALTER TABLE companies    ADD CONSTRAINT fk_companies_verified_by    FOREIGN KEY (verified_by) REFERENCES users(user_id) ON DELETE RESTRICT;

CREATE TABLE auth_tokens (
    token_id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     BIGINT      NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    purpose     TEXT        NOT NULL,
    token_hash  TEXT        NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    used_at     TIMESTAMPTZ,
    revoked_at  TIMESTAMPTZ,
    ip_address  INET,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_auth_tokens_purpose CHECK (purpose IN ('refresh','password_reset','email_verify')),
    CONSTRAINT ck_auth_tokens_expiry  CHECK (expires_at > created_at),
    CONSTRAINT uq_auth_tokens_hash UNIQUE (token_hash)
);
CREATE INDEX ix_auth_tokens_user ON auth_tokens (user_id, purpose);
CREATE INDEX ix_auth_tokens_expiry ON auth_tokens (expires_at);

-- ---------------------------------------------------------------------
-- Student profile and controlled vocabularies
-- ---------------------------------------------------------------------
CREATE TABLE skills (
    skill_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name     TEXT NOT NULL,
    CONSTRAINT ck_skills_name CHECK (length(btrim(name)) > 0)
);
CREATE UNIQUE INDEX uq_skills_name ON skills (lower(name));

CREATE TABLE skill_synonyms (
    synonym  TEXT PRIMARY KEY,
    skill_id BIGINT NOT NULL REFERENCES skills(skill_id) ON DELETE CASCADE,
    CONSTRAINT ck_skill_synonyms_lower CHECK (synonym = lower(btrim(synonym)) AND length(synonym) > 0)
);
CREATE INDEX ix_skill_synonyms_skill ON skill_synonyms (skill_id);

CREATE TABLE interests (
    interest_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        TEXT NOT NULL,
    CONSTRAINT ck_interests_name CHECK (length(btrim(name)) > 0)
);
CREATE UNIQUE INDEX uq_interests_name ON interests (lower(name));

CREATE TABLE student_profiles (
    student_id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id            BIGINT      NOT NULL UNIQUE,
    user_role          TEXT GENERATED ALWAYS AS ('student') STORED,
    university_id      BIGINT      NOT NULL,
    department_id      BIGINT      NOT NULL,
    programme_id       BIGINT      NOT NULL,
    student_number     TEXT        NOT NULL,
    year_of_study      SMALLINT    NOT NULL,
    preferred_location TEXT,
    willing_to_relocate BOOLEAN    NOT NULL DEFAULT false,
    cv_path            TEXT,
    cv_size_bytes      INTEGER,
    cv_uploaded_at     TIMESTAMPTZ,
    verified           BOOLEAN     NOT NULL DEFAULT false,
    verified_by        BIGINT      REFERENCES users(user_id) ON DELETE RESTRICT,
    verified_at        TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_student_user FOREIGN KEY (user_id, user_role) REFERENCES users (user_id, role) ON DELETE CASCADE,
    CONSTRAINT fk_student_dept FOREIGN KEY (department_id, university_id) REFERENCES departments (department_id, university_id) ON DELETE RESTRICT,
    CONSTRAINT fk_student_prog FOREIGN KEY (programme_id, department_id) REFERENCES programmes (programme_id, department_id) ON DELETE RESTRICT,
    CONSTRAINT ck_student_year   CHECK (year_of_study BETWEEN 1 AND 6),
    CONSTRAINT ck_student_number CHECK (length(btrim(student_number)) > 0),
    CONSTRAINT ck_student_cv_ext CHECK (cv_path IS NULL OR cv_path ~* '\.(pdf|docx)$'),
    CONSTRAINT ck_student_cv_size CHECK (cv_size_bytes IS NULL OR cv_size_bytes BETWEEN 1 AND 5242880),
    CONSTRAINT ck_student_cv_pair CHECK ((cv_path IS NULL) = (cv_uploaded_at IS NULL)),
    CONSTRAINT ck_student_verified CHECK (verified = (verified_at IS NOT NULL))
);
CREATE UNIQUE INDEX uq_student_number ON student_profiles (university_id, lower(student_number));
CREATE INDEX ix_student_programme ON student_profiles (programme_id);
CREATE INDEX ix_student_dept ON student_profiles (department_id);

CREATE TABLE student_skills (
    student_id BIGINT NOT NULL REFERENCES student_profiles(student_id) ON DELETE CASCADE,
    skill_id   BIGINT NOT NULL REFERENCES skills(skill_id) ON DELETE RESTRICT,
    PRIMARY KEY (student_id, skill_id)
);
CREATE INDEX ix_student_skills_skill ON student_skills (skill_id);

CREATE TABLE student_interests (
    student_id  BIGINT NOT NULL REFERENCES student_profiles(student_id) ON DELETE CASCADE,
    interest_id BIGINT NOT NULL REFERENCES interests(interest_id) ON DELETE RESTRICT,
    PRIMARY KEY (student_id, interest_id)
);
CREATE INDEX ix_student_interests_interest ON student_interests (interest_id);

-- ---------------------------------------------------------------------
-- Listings
-- ---------------------------------------------------------------------
CREATE TABLE listings (
    listing_id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id           BIGINT      NOT NULL REFERENCES companies(company_id) ON DELETE RESTRICT,
    posted_by            BIGINT      NOT NULL,
    title                TEXT        NOT NULL,
    description          TEXT        NOT NULL,
    sector               TEXT        NOT NULL,
    location             TEXT        NOT NULL,
    is_remote            BOOLEAN     NOT NULL DEFAULT false,
    duration_weeks       SMALLINT    NOT NULL,
    slots                SMALLINT    NOT NULL,
    slots_filled         SMALLINT    NOT NULL DEFAULT 0,
    application_deadline DATE        NOT NULL,
    status               TEXT        NOT NULL DEFAULT 'draft',
    posted_at            TIMESTAMPTZ,
    closed_at            TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    search_vector        TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('english', coalesce(title,'') || ' ' || coalesce(description,'') || ' ' || coalesce(sector,''))
    ) STORED,
    CONSTRAINT fk_listings_poster FOREIGN KEY (posted_by, company_id) REFERENCES users (user_id, company_id) ON DELETE RESTRICT,
    CONSTRAINT ck_listings_status   CHECK (status IN ('draft','open','closed','hidden')),
    CONSTRAINT ck_listings_title    CHECK (length(btrim(title)) > 0 AND length(btrim(description)) > 0),
    CONSTRAINT ck_listings_duration CHECK (duration_weeks BETWEEN 1 AND 52),
    CONSTRAINT ck_listings_slots    CHECK (slots BETWEEN 1 AND 500),
    CONSTRAINT ck_listings_filled   CHECK (slots_filled BETWEEN 0 AND slots)
);
CREATE INDEX ix_listings_open ON listings (application_deadline, listing_id) WHERE status = 'open';
CREATE INDEX ix_listings_company ON listings (company_id, status);
CREATE INDEX ix_listings_sector ON listings (lower(sector)) WHERE status = 'open';
CREATE INDEX ix_listings_location ON listings (lower(location)) WHERE status = 'open';
CREATE INDEX ix_listings_search ON listings USING GIN (search_vector);

CREATE TABLE listing_programmes (
    listing_id   BIGINT NOT NULL REFERENCES listings(listing_id) ON DELETE CASCADE,
    programme_id BIGINT NOT NULL REFERENCES programmes(programme_id) ON DELETE RESTRICT,
    PRIMARY KEY (listing_id, programme_id)
);
CREATE INDEX ix_listing_programmes_prog ON listing_programmes (programme_id);

CREATE TABLE listing_skills (
    listing_id  BIGINT  NOT NULL REFERENCES listings(listing_id) ON DELETE CASCADE,
    skill_id    BIGINT  NOT NULL REFERENCES skills(skill_id) ON DELETE RESTRICT,
    is_required BOOLEAN NOT NULL DEFAULT true,
    PRIMARY KEY (listing_id, skill_id)
);
CREATE INDEX ix_listing_skills_skill ON listing_skills (skill_id);

CREATE TABLE listing_interests (
    listing_id  BIGINT NOT NULL REFERENCES listings(listing_id) ON DELETE CASCADE,
    interest_id BIGINT NOT NULL REFERENCES interests(interest_id) ON DELETE RESTRICT,
    PRIMARY KEY (listing_id, interest_id)
);
CREATE INDEX ix_listing_interests_interest ON listing_interests (interest_id);

-- ---------------------------------------------------------------------
-- Applications, placements, check-ins
-- ---------------------------------------------------------------------
CREATE TABLE applications (
    application_id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    student_id        BIGINT      NOT NULL REFERENCES student_profiles(student_id) ON DELETE RESTRICT,
    listing_id        BIGINT      NOT NULL REFERENCES listings(listing_id) ON DELETE RESTRICT,
    status            TEXT        NOT NULL DEFAULT 'submitted',
    match_score       NUMERIC(5,2),
    cover_note        TEXT,
    submitted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    status_changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_applications_status CHECK (status IN ('submitted','under_review','shortlisted','accepted','rejected','withdrawn')),
    CONSTRAINT ck_applications_score  CHECK (match_score IS NULL OR match_score BETWEEN 0 AND 100),
    CONSTRAINT uq_applications_student_listing UNIQUE (student_id, listing_id)
);
CREATE INDEX ix_applications_listing ON applications (listing_id, status);
CREATE INDEX ix_applications_student ON applications (student_id, status);

CREATE TABLE placements (
    placement_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    application_id   BIGINT      NOT NULL UNIQUE REFERENCES applications(application_id) ON DELETE RESTRICT,
    status           TEXT        NOT NULL DEFAULT 'pending',
    rejection_reason TEXT,
    reviewed_by      BIGINT      REFERENCES users(user_id) ON DELETE RESTRICT,
    reviewed_at      TIMESTAMPTZ,
    start_date       DATE,
    end_date         DATE,
    completion_note  TEXT,
    completed_by     BIGINT      REFERENCES users(user_id) ON DELETE RESTRICT,
    completed_at     TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_placements_status   CHECK (status IN ('pending','confirmed','rejected','completed')),
    CONSTRAINT ck_placements_reject   CHECK (status <> 'rejected' OR length(btrim(coalesce(rejection_reason,''))) > 0),
    CONSTRAINT ck_placements_review   CHECK (status = 'pending' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)),
    CONSTRAINT ck_placements_dates    CHECK (end_date IS NULL OR start_date IS NULL OR end_date >= start_date),
    CONSTRAINT ck_placements_confdate CHECK (status IN ('pending','rejected') OR (start_date IS NOT NULL AND end_date IS NOT NULL)),
    CONSTRAINT ck_placements_complete CHECK (status <> 'completed' OR (completed_by IS NOT NULL AND completed_at IS NOT NULL AND length(btrim(coalesce(completion_note,''))) > 0))
);
CREATE INDEX ix_placements_status ON placements (status);

CREATE TABLE check_ins (
    checkin_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    placement_id   BIGINT      NOT NULL REFERENCES placements(placement_id) ON DELETE RESTRICT,
    coordinator_id BIGINT      NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    notes          TEXT        NOT NULL,
    checkin_date   DATE        NOT NULL DEFAULT CURRENT_DATE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_check_ins_notes CHECK (length(btrim(notes)) > 0)
);
CREATE INDEX ix_check_ins_placement ON check_ins (placement_id, checkin_date);

-- ---------------------------------------------------------------------
-- Messaging, notifications, audit
-- ---------------------------------------------------------------------
CREATE TABLE messages (
    message_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    application_id BIGINT      NOT NULL REFERENCES applications(application_id) ON DELETE RESTRICT,
    sender_id      BIGINT      NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    recipient_id   BIGINT      NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    body           TEXT        NOT NULL,
    is_read        BOOLEAN     NOT NULL DEFAULT false,
    sent_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    read_at        TIMESTAMPTZ,
    CONSTRAINT ck_messages_parties CHECK (sender_id <> recipient_id),
    CONSTRAINT ck_messages_body    CHECK (length(btrim(body)) > 0 AND length(body) <= 5000),
    CONSTRAINT ck_messages_read    CHECK (is_read = (read_at IS NOT NULL))
);
CREATE INDEX ix_messages_inbox ON messages (recipient_id, is_read, sent_at DESC);
CREATE INDEX ix_messages_application ON messages (application_id, sent_at);

CREATE TABLE notifications (
    notification_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id         BIGINT      NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    type            TEXT        NOT NULL,
    title           TEXT        NOT NULL,
    message         TEXT        NOT NULL,
    related_type    TEXT,
    related_id      BIGINT,
    channel         TEXT        NOT NULL,
    delivery_status TEXT        NOT NULL DEFAULT 'pending',
    is_read         BOOLEAN     NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at         TIMESTAMPTZ,
    read_at         TIMESTAMPTZ,
    CONSTRAINT ck_notifications_type    CHECK (type IN ('application_status','placement_decision','registration_decision','deadline_reminder','message','system')),
    CONSTRAINT ck_notifications_channel CHECK (channel IN ('in_app','email')),
    CONSTRAINT ck_notifications_delivery CHECK (delivery_status IN ('pending','sent','failed')),
    CONSTRAINT ck_notifications_sent    CHECK (delivery_status <> 'sent' OR sent_at IS NOT NULL),
    CONSTRAINT ck_notifications_read    CHECK (is_read = (read_at IS NOT NULL)),
    CONSTRAINT ck_notifications_inapp   CHECK (channel <> 'in_app' OR delivery_status = 'sent')
);
CREATE INDEX ix_notifications_user ON notifications (user_id, is_read, created_at DESC);
CREATE INDEX ix_notifications_email_queue ON notifications (created_at) WHERE channel = 'email' AND delivery_status = 'pending';

CREATE TABLE audit_logs (
    log_id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_user_id  BIGINT      REFERENCES users(user_id) ON DELETE RESTRICT,
    actor_role     TEXT,
    action         TEXT        NOT NULL,
    resource_type  TEXT,
    resource_id    TEXT,
    ip_address     INET,
    result         TEXT        NOT NULL DEFAULT 'success',
    details        JSONB,
    CONSTRAINT ck_audit_result CHECK (result IN ('success','denied','failure')),
    CONSTRAINT ck_audit_action CHECK (length(btrim(action)) > 0)
);
CREATE INDEX ix_audit_time ON audit_logs (occurred_at DESC);
CREATE INDEX ix_audit_actor ON audit_logs (actor_user_id, occurred_at DESC);
CREATE INDEX ix_audit_denied ON audit_logs (occurred_at DESC) WHERE result = 'denied';
CREATE INDEX ix_audit_resource ON audit_logs (resource_type, resource_id);

-- ---------------------------------------------------------------------
-- Documentation inside the database (used to generate the data dictionary)
-- ---------------------------------------------------------------------
COMMENT ON TABLE universities IS 'Registered universities. A university must be verified by an administrator before its students can register (SR18).';
COMMENT ON TABLE departments IS 'Departments of a university. Coordinators and student statistics are scoped by department (SR15, SR16).';
COMMENT ON TABLE programmes IS 'Degree programmes. programme_group lets the matching engine treat related programmes as half-relevant.';
COMMENT ON TABLE companies IS 'Host organisations. verification_status controls whether the company may open listings (SR07).';
COMMENT ON TABLE users IS 'All accounts: students, employer representatives, coordinators and administrators (SR17). Role and organisation are immutable once set.';
COMMENT ON TABLE auth_tokens IS 'Hashed refresh, password-reset and email-verification tokens. Raw tokens are never stored.';
COMMENT ON TABLE skills IS 'Controlled vocabulary of skills used by profiles and listings.';
COMMENT ON TABLE skill_synonyms IS 'Alternative spellings that the API maps to a canonical skill (for example "reactjs" to React).';
COMMENT ON TABLE interests IS 'Controlled vocabulary of interests; also used as listing tags and to match a listing sector.';
COMMENT ON TABLE student_profiles IS 'One profile per student user: programme, year, location preference, CV and verification state (SR01).';
COMMENT ON TABLE student_skills IS 'Skills a student has (many-to-many).';
COMMENT ON TABLE student_interests IS 'Interests of a student (many-to-many).';
COMMENT ON TABLE listings IS 'Internship opportunities posted by a verified company (SR08).';
COMMENT ON TABLE listing_programmes IS 'Programmes a listing accepts (many-to-many), used for the programme score P.';
COMMENT ON TABLE listing_skills IS 'Skills a listing asks for. Only is_required = true skills count in the skills score S.';
COMMENT ON TABLE listing_interests IS 'Keywords or tags of a listing (many-to-many), used for the interests score I.';
COMMENT ON TABLE applications IS 'A student applying to a listing, with a controlled status life cycle (SR04).';
COMMENT ON TABLE placements IS 'Created automatically when an application is accepted; the university approves or rejects it and the employer completes it (SR11, SR13).';
COMMENT ON TABLE check_ins IS 'Coordinator progress check-ins on a confirmed placement (SR14).';
COMMENT ON TABLE messages IS 'Messages between a host company and a shortlisted or accepted candidate (SR10).';
COMMENT ON TABLE notifications IS 'In-app and email notifications. Email rows wait in a queue (delivery_status = pending) for the mail worker (SR05).';
COMMENT ON TABLE audit_logs IS 'Append-only security and activity log (SR19). Rows can never be changed or deleted.';
COMMENT ON COLUMN universities.email_domain IS 'Domain students must use to register, for example must.ac.ug; sub-domains such as std.must.ac.ug are accepted.';
COMMENT ON COLUMN universities.status IS 'pending, verified, rejected or suspended.';
COMMENT ON COLUMN universities.verified_by IS 'Administrator who verified the university (filled automatically).';
COMMENT ON COLUMN programmes.programme_group IS 'Lower-case group such as computing or business; same group = related programme (score 0.5).';
COMMENT ON COLUMN companies.verification_status IS 'pending, verified, rejected or suspended. Only verified companies can open listings.';
COMMENT ON COLUMN companies.rejection_reason IS 'Mandatory when the status is rejected.';
COMMENT ON COLUMN users.email IS 'Stored in lower case; unique ignoring case.';
COMMENT ON COLUMN users.password_hash IS 'bcrypt hash (cost 12). Plain passwords are never stored (NFR04).';
COMMENT ON COLUMN users.role IS 'student, employer, coordinator or admin. Cannot be changed after creation.';
COMMENT ON COLUMN users.status IS 'pending (awaiting email verification), active, rejected or suspended.';
COMMENT ON COLUMN users.company_id IS 'Set only for employers; the company the user represents.';
COMMENT ON COLUMN users.university_id IS 'Set only for coordinators; their university.';
COMMENT ON COLUMN users.department_id IS 'Optional for coordinators. NULL means the whole university; otherwise only that department.';
COMMENT ON COLUMN users.email_verified_at IS 'Time the email link was opened. Required before status can be active.';
COMMENT ON COLUMN users.failed_login_count IS 'Consecutive failed logins, used for the 5-attempt lockout.';
COMMENT ON COLUMN users.locked_until IS 'Account is locked until this time after too many failed logins.';
COMMENT ON COLUMN auth_tokens.token_hash IS 'SHA-256 (or similar) hash of the token; unique.';
COMMENT ON COLUMN auth_tokens.purpose IS 'refresh, password_reset or email_verify.';
COMMENT ON COLUMN auth_tokens.used_at IS 'Set when a single-use token is consumed.';
COMMENT ON COLUMN student_profiles.user_role IS 'Generated constant student; with the foreign key it guarantees only student users have profiles.';
COMMENT ON COLUMN student_profiles.student_number IS 'University registration number; unique within a university (case-insensitive).';
COMMENT ON COLUMN student_profiles.preferred_location IS 'Optional. When NULL the location score is left out and the other weights are rescaled.';
COMMENT ON COLUMN student_profiles.willing_to_relocate IS 'Gives a location score of 0.5 when the listing is elsewhere.';
COMMENT ON COLUMN student_profiles.cv_path IS 'Storage path of the CV (pdf or docx, at most 5 MB). The file itself is stored outside the database.';
COMMENT ON COLUMN student_profiles.verified IS 'True after a coordinator of the same university verified the student (SR12). Required to apply.';
COMMENT ON COLUMN listings.posted_by IS 'Employer user who posted it; the composite foreign key forces this user to belong to the same company.';
COMMENT ON COLUMN listings.status IS 'draft, open, closed or hidden. Opening requires a verified company and a future deadline.';
COMMENT ON COLUMN listings.slots IS 'Number of intern positions offered (1 to 500).';
COMMENT ON COLUMN listings.slots_filled IS 'Maintained automatically from confirmed and completed placements; never exceeds slots.';
COMMENT ON COLUMN listings.search_vector IS 'Generated full-text search column used by the search box.';
COMMENT ON COLUMN listing_skills.is_required IS 'Optional skills (false) are shown but do not count in the skills score.';
COMMENT ON COLUMN applications.status IS 'submitted, under_review, shortlisted, accepted, rejected or withdrawn; transitions are enforced.';
COMMENT ON COLUMN applications.match_score IS 'Score 0 to 100 at the time of applying (from fn_recommendations).';
COMMENT ON COLUMN applications.status_changed_at IS 'Updated automatically whenever the status changes.';
COMMENT ON COLUMN placements.application_id IS 'One placement per accepted application.';
COMMENT ON COLUMN placements.status IS 'pending, confirmed, rejected or completed.';
COMMENT ON COLUMN placements.rejection_reason IS 'Mandatory when the status is rejected (SR13).';
COMMENT ON COLUMN placements.reviewed_by IS 'Coordinator who decided; must belong to the student university and department scope.';
COMMENT ON COLUMN placements.completed_by IS 'Employer of the host company who marked it completed (SR11).';
COMMENT ON COLUMN placements.completion_note IS 'Short performance note, mandatory on completion.';
COMMENT ON COLUMN check_ins.coordinator_id IS 'Coordinator who recorded the check-in; checked against the student university and department.';
COMMENT ON COLUMN messages.is_read IS 'read_at is filled automatically when this becomes true.';
COMMENT ON COLUMN notifications.type IS 'application_status, placement_decision, registration_decision, deadline_reminder, message or system.';
COMMENT ON COLUMN notifications.channel IS 'in_app (sent immediately) or email (queued).';
COMMENT ON COLUMN notifications.delivery_status IS 'pending, sent or failed. The mail worker updates email rows.';
COMMENT ON COLUMN notifications.related_type IS 'Table name of the related record, for example applications.';
COMMENT ON COLUMN audit_logs.actor_user_id IS 'User who acted; NULL for system events. Set per request with set_config(app.user_id).';
COMMENT ON COLUMN audit_logs.result IS 'success, denied or failure.';
COMMENT ON COLUMN audit_logs.details IS 'JSON with extra context such as old and new status. Never store passwords, tokens or CV contents.';
