-- =====================================================================
-- InternLink Uganda - File 10: CV uploads, job alerts, coordinator invites
-- Run after 01-04, 08 and 09. Safe to run more than once.
-- =====================================================================

-- ---------- CVs ----------
-- Stored in the database so they stay private behind sign-in and need no
-- extra file service. student_profiles.cv_path points at them as
-- 'db/<student_id>.pdf' (or .docx), which the existing checks accept.
CREATE TABLE IF NOT EXISTS student_cvs (
    student_id   BIGINT      PRIMARY KEY REFERENCES student_profiles(student_id) ON DELETE CASCADE,
    filename     TEXT        NOT NULL,
    content_type TEXT        NOT NULL,
    size_bytes   INTEGER     NOT NULL,
    data         BYTEA       NOT NULL,
    uploaded_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_student_cvs_type CHECK (content_type IN (
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document')),
    CONSTRAINT ck_student_cvs_size CHECK (size_bytes BETWEEN 1 AND 4194304 AND size_bytes = octet_length(data)),
    CONSTRAINT ck_student_cvs_name CHECK (length(btrim(filename)) BETWEEN 1 AND 200)
);
COMMENT ON TABLE student_cvs IS 'Uploaded CV files (PDF or DOCX, at most 4 MB). Only the student and employers they applied to can download them.';

-- ---------- job alerts ----------
CREATE TABLE IF NOT EXISTS job_alerts (
    alert_id        BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    student_id      BIGINT      NOT NULL REFERENCES student_profiles(student_id) ON DELETE CASCADE,
    filters         JSONB       NOT NULL,
    label           TEXT        NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Internships posted after this moment are "new" for the next email.
    last_checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_sent_at    TIMESTAMPTZ,
    CONSTRAINT ck_job_alerts_label CHECK (length(btrim(label)) BETWEEN 1 AND 200),
    CONSTRAINT uq_job_alerts_student_filters UNIQUE (student_id, filters)
);
CREATE INDEX IF NOT EXISTS ix_job_alerts_checked ON job_alerts (last_checked_at);
COMMENT ON TABLE job_alerts IS 'Saved searches. A daily job emails students the new internships that match.';

-- ---------- coordinator invites ----------
-- An invite is a pending coordinator account plus a one-time link.
ALTER TABLE auth_tokens DROP CONSTRAINT IF EXISTS ck_auth_tokens_purpose;
ALTER TABLE auth_tokens ADD CONSTRAINT ck_auth_tokens_purpose
    CHECK (purpose IN ('refresh','password_reset','email_verify','coordinator_invite'));

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'internlink_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON student_cvs, job_alerts TO internlink_app;
    END IF;
END $$;
