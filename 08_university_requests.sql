-- =====================================================================
-- InternLink Uganda - File 08: students asking for a university that isn't listed
-- Run after 01-04. Safe to run more than once.
-- =====================================================================
CREATE TABLE IF NOT EXISTS university_requests (
    request_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    university_name   TEXT        NOT NULL,
    requester_email   TEXT        NOT NULL,
    coordinator_email TEXT,
    status            TEXT        NOT NULL DEFAULT 'open',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_university_requests_name   CHECK (length(btrim(university_name)) BETWEEN 1 AND 160),
    CONSTRAINT ck_university_requests_status CHECK (status IN ('open', 'added', 'declined'))
);
-- One request per person per university.
CREATE UNIQUE INDEX IF NOT EXISTS uq_university_requests_person
    ON university_requests (lower(university_name), requester_email);

COMMENT ON TABLE university_requests IS 'Universities students asked for at sign-up. The admin reviews these and invites the university.';

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'internlink_app') THEN
        GRANT SELECT, INSERT, UPDATE ON university_requests TO internlink_app;
    END IF;
END $$;
