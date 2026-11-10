-- =====================================================================
-- InternLink Uganda - File 09: interview stage, decline reasons, saved internships
-- Run after 01-04 and 08. Safe to run more than once.
--
-- Application flow becomes:
--   submitted -> under_review -> shortlisted -> interview -> accepted (offer)
--   (an employer can still go straight from shortlisted to accepted, and can
--    reject at any stage; the student can withdraw at any stage)
-- =====================================================================

-- ---------- applications: interview stage and a reason shared with the student ----------
ALTER TABLE applications ADD COLUMN IF NOT EXISTS interview_at   TIMESTAMPTZ;
ALTER TABLE applications ADD COLUMN IF NOT EXISTS interview_note TEXT;
ALTER TABLE applications ADD COLUMN IF NOT EXISTS decision_note  TEXT;

ALTER TABLE applications DROP CONSTRAINT IF EXISTS ck_applications_status;
ALTER TABLE applications ADD CONSTRAINT ck_applications_status
    CHECK (status IN ('submitted','under_review','shortlisted','interview','accepted','rejected','withdrawn'));
ALTER TABLE applications DROP CONSTRAINT IF EXISTS ck_applications_interview;
ALTER TABLE applications ADD CONSTRAINT ck_applications_interview
    CHECK (status <> 'interview' OR interview_at IS NOT NULL);
ALTER TABLE applications DROP CONSTRAINT IF EXISTS ck_applications_notes;
ALTER TABLE applications ADD CONSTRAINT ck_applications_notes
    CHECK (coalesce(length(interview_note), 0) <= 500 AND coalesce(length(decision_note), 0) <= 500);

CREATE OR REPLACE FUNCTION fn_status_label(p_status TEXT) RETURNS TEXT LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE p_status
        WHEN 'interview' THEN 'at the interview stage'
        WHEN 'accepted'  THEN 'Accepted (offer made)'
        ELSE initcap(replace(p_status, '_', ' ')) END
$$;

-- Same rules as 02_functions_triggers.sql, plus the interview stage.
CREATE OR REPLACE FUNCTION fn_applications_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE v_listing listings%ROWTYPE; v_verified BOOLEAN; v_user_status TEXT; v_ok BOOLEAN;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'submitted' THEN
            RAISE EXCEPTION 'RULE_SR04_INITIAL_STATUS: a new application must have status submitted' USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        SELECT * INTO v_listing FROM listings WHERE listing_id = NEW.listing_id;
        IF v_listing.status <> 'open' THEN
            RAISE EXCEPTION 'RULE_SR04_LISTING_CLOSED: the listing is not open for applications' USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        IF v_listing.application_deadline < CURRENT_DATE THEN
            RAISE EXCEPTION 'RULE_SR04_DEADLINE_PASSED: the application deadline has passed' USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        SELECT sp.verified, u.status INTO v_verified, v_user_status
        FROM student_profiles sp JOIN users u ON u.user_id = sp.user_id WHERE sp.student_id = NEW.student_id;
        IF NOT v_verified THEN
            RAISE EXCEPTION 'RULE_SR12_STUDENT_NOT_VERIFIED: the student has not been verified by a coordinator' USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        IF v_user_status <> 'active' THEN
            RAISE EXCEPTION 'RULE_ACCOUNT_NOT_ACTIVE: the student account is not active' USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.student_id <> OLD.student_id OR NEW.listing_id <> OLD.listing_id THEN
        RAISE EXCEPTION 'RULE_SR17_IMMUTABLE_KEYS: student and listing of an application cannot change' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.status <> OLD.status THEN
        v_ok := CASE OLD.status
            WHEN 'submitted'    THEN NEW.status IN ('under_review','shortlisted','rejected','withdrawn')
            WHEN 'under_review' THEN NEW.status IN ('shortlisted','rejected','withdrawn')
            WHEN 'shortlisted'  THEN NEW.status IN ('interview','accepted','rejected','withdrawn')
            WHEN 'interview'    THEN NEW.status IN ('accepted','rejected','withdrawn')
            WHEN 'accepted'     THEN NEW.status IN ('withdrawn')
            ELSE FALSE END;
        IF NOT v_ok THEN
            RAISE EXCEPTION 'RULE_SR04_TRANSITION: an application cannot go from % to %', OLD.status, NEW.status USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        IF OLD.status = 'accepted' AND NEW.status = 'withdrawn' THEN
            IF EXISTS (SELECT 1 FROM placements WHERE application_id = OLD.application_id AND status IN ('confirmed','completed')) THEN
                RAISE EXCEPTION 'RULE_SR13_PLACEMENT_ACTIVE: the placement is already confirmed and cannot be withdrawn here' USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            DELETE FROM placements WHERE application_id = OLD.application_id AND status = 'pending';
        END IF;
        NEW.status_changed_at := now();
    END IF;
    RETURN NEW;
END $$;

-- Messaging is open from shortlisting onwards, now including the interview stage.
CREATE OR REPLACE FUNCTION fn_messages_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE v_status TEXT; v_student_user BIGINT; v_company BIGINT; v_title TEXT; v_s_role TEXT; v_s_co BIGINT; v_r_role TEXT; v_r_co BIGINT;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF NEW.is_read AND NEW.read_at IS NULL THEN NEW.read_at := now(); END IF;
        IF NOT NEW.is_read THEN NEW.read_at := NULL; END IF;
        RETURN NEW;
    END IF;
    SELECT a.status, sp.user_id, l.company_id, l.title INTO v_status, v_student_user, v_company, v_title
    FROM applications a JOIN student_profiles sp ON sp.student_id = a.student_id JOIN listings l ON l.listing_id = a.listing_id
    WHERE a.application_id = NEW.application_id;
    IF v_status NOT IN ('shortlisted','interview','accepted') THEN
        RAISE EXCEPTION 'RULE_SR10_NOT_SHORTLISTED: messaging is only available for shortlisted or accepted candidates' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    SELECT role, company_id INTO v_s_role, v_s_co FROM users WHERE user_id = NEW.sender_id;
    SELECT role, company_id INTO v_r_role, v_r_co FROM users WHERE user_id = NEW.recipient_id;
    IF NOT ((NEW.sender_id = v_student_user AND v_r_role = 'employer' AND v_r_co = v_company)
         OR (NEW.recipient_id = v_student_user AND v_s_role = 'employer' AND v_s_co = v_company)) THEN
        RAISE EXCEPTION 'RULE_SR10_PARTIES: messages are only allowed between the candidate and the host company' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.is_read THEN NEW.read_at := coalesce(NEW.read_at, now()); END IF;
    RETURN NEW;
END $$;

-- Employer applicant board needs the student's verification and the interview time.
CREATE OR REPLACE VIEW v_employer_applicants AS
SELECT a.application_id, l.company_id, l.listing_id, l.title AS listing_title,
       a.student_id, u.full_name AS applicant_name, pr.name AS programme, sp.year_of_study,
       un.name AS university, a.match_score, a.status, a.submitted_at, sp.cv_path,
       sp.verified AS student_verified, a.interview_at
FROM applications a
JOIN listings l ON l.listing_id = a.listing_id
JOIN student_profiles sp ON sp.student_id = a.student_id
JOIN users u ON u.user_id = sp.user_id
JOIN programmes pr ON pr.programme_id = sp.programme_id
JOIN universities un ON un.university_id = sp.university_id;

-- ---------- saved internships ----------
CREATE TABLE IF NOT EXISTS saved_listings (
    student_id BIGINT      NOT NULL REFERENCES student_profiles(student_id) ON DELETE CASCADE,
    listing_id BIGINT      NOT NULL REFERENCES listings(listing_id) ON DELETE CASCADE,
    saved_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (student_id, listing_id)
);
COMMENT ON TABLE saved_listings IS 'Internships a student saved to apply for later.';

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'internlink_app') THEN
        GRANT SELECT, INSERT, DELETE ON saved_listings TO internlink_app;
        GRANT SELECT ON v_employer_applicants TO internlink_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'internlink_readonly') THEN
        GRANT SELECT ON v_employer_applicants TO internlink_readonly;
    END IF;
END $$;
