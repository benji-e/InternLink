-- =====================================================================
-- InternLink Uganda - File 11: company logos and "suggest a company"
-- Run after 01-04 and 08-10. Safe to run more than once.
-- =====================================================================

-- ---------- logos ----------
-- Public images, so SVG is not allowed (it can carry scripts).
CREATE TABLE IF NOT EXISTS company_logos (
    company_id   BIGINT      PRIMARY KEY REFERENCES companies(company_id) ON DELETE CASCADE,
    content_type TEXT        NOT NULL,
    size_bytes   INTEGER     NOT NULL,
    data         BYTEA       NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_company_logos_type CHECK (content_type IN ('image/png', 'image/jpeg', 'image/webp')),
    CONSTRAINT ck_company_logos_size CHECK (size_bytes BETWEEN 1 AND 1048576 AND size_bytes = octet_length(data))
);
COMMENT ON TABLE company_logos IS 'Company logo images (PNG, JPEG or WebP, at most 1 MB), shown publicly.';

-- ---------- students suggesting a company ----------
CREATE TABLE IF NOT EXISTS company_requests (
    request_id      BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_name    TEXT        NOT NULL,
    website         TEXT,
    requester_email TEXT        NOT NULL,
    status          TEXT        NOT NULL DEFAULT 'open',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_company_requests_name   CHECK (length(btrim(company_name)) BETWEEN 1 AND 160),
    CONSTRAINT ck_company_requests_status CHECK (status IN ('open', 'invited', 'declined'))
);
-- One suggestion per person per company.
CREATE UNIQUE INDEX IF NOT EXISTS uq_company_requests_person
    ON company_requests (lower(company_name), requester_email);
COMMENT ON TABLE company_requests IS 'Companies students would like on InternLink. The admin reviews and invites them.';

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'internlink_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON company_logos TO internlink_app;
        GRANT SELECT, INSERT, UPDATE ON company_requests TO internlink_app;
    END IF;
END $$;
