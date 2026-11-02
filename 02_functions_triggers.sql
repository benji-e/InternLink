-- =====================================================================
-- InternLink Uganda - File 02: business rules (functions + triggers)
-- Every rule raises SQLSTATE 23000 with a message that starts with a
-- stable code such as RULE_SR07_COMPANY_NOT_VERIFIED so the Flask API
-- can map it to a friendly error.
-- =====================================================================
SET client_min_messages = warning;

-- ---------- helpers ---------------------------------------------------
-- The API sets the signed-in user for each request/transaction:
--   SELECT set_config('app.user_id', '<id>', true);
CREATE FUNCTION app_user_id() RETURNS BIGINT LANGUAGE sql STABLE AS $$
    SELECT u.user_id FROM users u
    WHERE u.user_id = NULLIF(current_setting('app.user_id', true), '')::BIGINT
$$;

CREATE FUNCTION fn_set_updated_at() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at := now(); RETURN NEW; END $$;

CREATE FUNCTION fn_status_label(p_status TEXT) RETURNS TEXT LANGUAGE sql IMMUTABLE AS $$
    SELECT initcap(replace(p_status, '_', ' '))
$$;

CREATE FUNCTION fn_notify(p_user BIGINT, p_type TEXT, p_title TEXT, p_message TEXT,
                          p_rel_type TEXT, p_rel_id BIGINT, p_email BOOLEAN DEFAULT TRUE)
RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO notifications (user_id, type, title, message, related_type, related_id, channel, delivery_status, sent_at)
    VALUES (p_user, p_type, p_title, p_message, p_rel_type, p_rel_id, 'in_app', 'sent', now());
    IF p_email THEN
        INSERT INTO notifications (user_id, type, title, message, related_type, related_id, channel, delivery_status)
        VALUES (p_user, p_type, p_title, p_message, p_rel_type, p_rel_id, 'email', 'pending');
    END IF;
END $$;

-- Convenience for the API (login events, access denied, exports ...)  SR19
CREATE FUNCTION log_event(p_action TEXT, p_resource_type TEXT DEFAULT NULL, p_resource_id TEXT DEFAULT NULL,
                          p_result TEXT DEFAULT 'success', p_details JSONB DEFAULT NULL, p_ip INET DEFAULT NULL)
RETURNS BIGINT LANGUAGE plpgsql AS $$
DECLARE v_actor BIGINT := app_user_id(); v_id BIGINT;
BEGIN
    INSERT INTO audit_logs (actor_user_id, actor_role, action, resource_type, resource_id, ip_address, result, details)
    VALUES (v_actor, (SELECT role FROM users WHERE user_id = v_actor), p_action, p_resource_type, p_resource_id, p_ip, p_result, p_details)
    RETURNING log_id INTO v_id;
    RETURN v_id;
END $$;

-- ---------- audit: append-only + automatic status-change logging -------
CREATE FUNCTION fn_audit_block_changes() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'RULE_SR19_AUDIT_APPEND_ONLY: audit_logs cannot be changed or deleted' USING ERRCODE = 'integrity_constraint_violation'; END $$;
CREATE TRIGGER trg_audit_no_update BEFORE UPDATE OR DELETE ON audit_logs FOR EACH ROW EXECUTE FUNCTION fn_audit_block_changes();
CREATE TRIGGER trg_audit_no_truncate BEFORE TRUNCATE ON audit_logs FOR EACH STATEMENT EXECUTE FUNCTION fn_audit_block_changes();

-- TG_ARGV[0] = id column, TG_ARGV[1] = status column
CREATE FUNCTION fn_audit_status_change() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE v_old TEXT; v_new TEXT; v_actor BIGINT := app_user_id();
BEGIN
    v_new := to_jsonb(NEW) ->> TG_ARGV[1];
    IF TG_OP = 'UPDATE' THEN
        v_old := to_jsonb(OLD) ->> TG_ARGV[1];
        IF v_old IS NOT DISTINCT FROM v_new THEN RETURN NULL; END IF;
    END IF;
    INSERT INTO audit_logs (actor_user_id, actor_role, action, resource_type, resource_id, result, details)
    VALUES (v_actor, (SELECT role FROM users WHERE user_id = v_actor),
            TG_TABLE_NAME || CASE TG_OP WHEN 'INSERT' THEN '.created' ELSE '.status_changed' END,
            TG_TABLE_NAME, to_jsonb(NEW) ->> TG_ARGV[0], 'success',
            jsonb_build_object('old', v_old, 'new', v_new));
    RETURN NULL;
END $$;

-- ---------- users: privilege-escalation guard (SR17) -------------------
CREATE FUNCTION fn_users_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE v_override BOOLEAN := coalesce(current_setting('app.allow_role_change', true), 'off') = 'on';
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.role = 'admin' AND NOT v_override THEN
            RAISE EXCEPTION 'RULE_SR17_ADMIN_CREATE: administrator accounts cannot be self-registered' USING ERRCODE = 'integrity_constraint_violation';
        END IF;
    ELSE
        IF (NEW.role <> OLD.role OR NEW.company_id IS DISTINCT FROM OLD.company_id
            OR NEW.university_id IS DISTINCT FROM OLD.university_id) AND NOT v_override THEN
            RAISE EXCEPTION 'RULE_SR17_ROLE_IMMUTABLE: role and organisation of an account cannot be changed here' USING ERRCODE = 'integrity_constraint_violation';
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_01_guard BEFORE INSERT OR UPDATE ON users FOR EACH ROW EXECUTE FUNCTION fn_users_guard();
CREATE TRIGGER trg_02_updated BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
CREATE TRIGGER trg_90_audit AFTER INSERT OR UPDATE ON users FOR EACH ROW EXECUTE FUNCTION fn_audit_status_change('user_id', 'status');

-- ---------- organisation verification (SR07, SR18) ---------------------
CREATE FUNCTION fn_company_before() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.verification_status = 'verified' AND (TG_OP = 'INSERT' OR OLD.verification_status <> 'verified') THEN
        NEW.verified_at := coalesce(NEW.verified_at, now());
        NEW.verified_by := coalesce(NEW.verified_by, app_user_id());
    ELSIF NEW.verification_status <> 'verified' THEN
        NEW.verified_at := NULL; NEW.verified_by := NULL;
    END IF;
    IF NEW.verified_by IS NOT NULL AND NOT EXISTS (SELECT 1 FROM users WHERE user_id = NEW.verified_by AND role = 'admin') THEN
        RAISE EXCEPTION 'RULE_SR18_VERIFIER: only an administrator can verify an organisation' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE FUNCTION fn_company_after() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE r RECORD; v_msg TEXT;
BEGIN
    IF NEW.verification_status = OLD.verification_status THEN RETURN NULL; END IF;
    v_msg := CASE NEW.verification_status
        WHEN 'verified'  THEN 'Your organisation "' || NEW.name || '" has been verified. You can now post internship listings.'
        WHEN 'rejected'  THEN 'Your organisation "' || NEW.name || '" was not verified. Reason: ' || coalesce(NEW.rejection_reason, 'not stated')
        WHEN 'suspended' THEN 'Your organisation "' || NEW.name || '" has been suspended.'
        ELSE 'The status of your organisation "' || NEW.name || '" is now ' || NEW.verification_status || '.' END;
    FOR r IN SELECT user_id FROM users WHERE company_id = NEW.company_id LOOP
        PERFORM fn_notify(r.user_id, 'registration_decision', 'Organisation registration decision', v_msg, 'companies', NEW.company_id);
    END LOOP;
    IF NEW.verification_status = 'rejected'  THEN UPDATE users SET status = 'rejected'  WHERE company_id = NEW.company_id AND status IN ('pending','active'); END IF;
    IF NEW.verification_status = 'suspended' THEN UPDATE users SET status = 'suspended' WHERE company_id = NEW.company_id AND status = 'active'; END IF;
    IF NEW.verification_status = 'verified' AND OLD.verification_status = 'suspended' THEN
        UPDATE users SET status = 'active' WHERE company_id = NEW.company_id AND status = 'suspended' AND email_verified_at IS NOT NULL;
    END IF;
    RETURN NULL;
END $$;
CREATE TRIGGER trg_01_guard   BEFORE INSERT OR UPDATE ON companies FOR EACH ROW EXECUTE FUNCTION fn_company_before();
CREATE TRIGGER trg_02_updated BEFORE UPDATE ON companies FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
CREATE TRIGGER trg_10_notify  AFTER UPDATE OF verification_status ON companies FOR EACH ROW EXECUTE FUNCTION fn_company_after();
CREATE TRIGGER trg_90_audit   AFTER INSERT OR UPDATE ON companies FOR EACH ROW EXECUTE FUNCTION fn_audit_status_change('company_id', 'verification_status');

CREATE FUNCTION fn_university_before() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status = 'verified' AND (TG_OP = 'INSERT' OR OLD.status <> 'verified') THEN
        NEW.verified_at := coalesce(NEW.verified_at, now());
        NEW.verified_by := coalesce(NEW.verified_by, app_user_id());
    ELSIF NEW.status <> 'verified' THEN
        NEW.verified_at := NULL; NEW.verified_by := NULL;
    END IF;
    IF NEW.verified_by IS NOT NULL AND NOT EXISTS (SELECT 1 FROM users WHERE user_id = NEW.verified_by AND role = 'admin') THEN
        RAISE EXCEPTION 'RULE_SR18_VERIFIER: only an administrator can verify an organisation' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE FUNCTION fn_university_after() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE r RECORD; v_msg TEXT;
BEGIN
    IF NEW.status = OLD.status THEN RETURN NULL; END IF;
    v_msg := CASE NEW.status
        WHEN 'verified'  THEN 'Your institution "' || NEW.name || '" has been verified.'
        WHEN 'rejected'  THEN 'Your institution "' || NEW.name || '" was not verified. Reason: ' || coalesce(NEW.rejection_reason, 'not stated')
        WHEN 'suspended' THEN 'Your institution "' || NEW.name || '" has been suspended.'
        ELSE 'The status of your institution "' || NEW.name || '" is now ' || NEW.status || '.' END;
    FOR r IN SELECT user_id FROM users WHERE university_id = NEW.university_id LOOP
        PERFORM fn_notify(r.user_id, 'registration_decision', 'Institution registration decision', v_msg, 'universities', NEW.university_id);
    END LOOP;
    IF NEW.status = 'rejected'  THEN UPDATE users SET status = 'rejected'  WHERE university_id = NEW.university_id AND status IN ('pending','active'); END IF;
    IF NEW.status = 'suspended' THEN UPDATE users SET status = 'suspended' WHERE university_id = NEW.university_id AND status = 'active'; END IF;
    IF NEW.status = 'verified' AND OLD.status = 'suspended' THEN
        UPDATE users SET status = 'active' WHERE university_id = NEW.university_id AND status = 'suspended' AND email_verified_at IS NOT NULL;
    END IF;
    RETURN NULL;
END $$;
CREATE TRIGGER trg_01_guard   BEFORE INSERT OR UPDATE ON universities FOR EACH ROW EXECUTE FUNCTION fn_university_before();
CREATE TRIGGER trg_02_updated BEFORE UPDATE ON universities FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
CREATE TRIGGER trg_10_notify  AFTER UPDATE OF status ON universities FOR EACH ROW EXECUTE FUNCTION fn_university_after();
CREATE TRIGGER trg_90_audit   AFTER INSERT OR UPDATE ON universities FOR EACH ROW EXECUTE FUNCTION fn_audit_status_change('university_id', 'status');

-- ---------- student profile (SR01, SR12) --------------------------------
CREATE FUNCTION fn_student_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE v_email TEXT; v_domain TEXT; v_uni_domain TEXT; v_uni_status TEXT;
BEGIN
    IF TG_OP = 'INSERT' OR NEW.user_id <> OLD.user_id OR NEW.university_id <> OLD.university_id THEN
        SELECT email INTO v_email FROM users WHERE user_id = NEW.user_id;
        SELECT email_domain, status INTO v_uni_domain, v_uni_status FROM universities WHERE university_id = NEW.university_id;
        v_domain := split_part(v_email, '@', 2);
        IF NOT (v_domain = v_uni_domain OR v_domain LIKE '%.' || v_uni_domain) THEN
            RAISE EXCEPTION 'RULE_SR01_EMAIL_DOMAIN: student email must belong to the university domain (%)', v_uni_domain USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        IF TG_OP = 'INSERT' AND v_uni_status <> 'verified' THEN
            RAISE EXCEPTION 'RULE_SR01_UNIVERSITY_NOT_VERIFIED: the university is not verified yet' USING ERRCODE = 'integrity_constraint_violation';
        END IF;
    END IF;
    IF NEW.verified THEN
        IF TG_OP = 'INSERT' OR NOT OLD.verified THEN
            NEW.verified_by := coalesce(NEW.verified_by, app_user_id());
            IF NOT EXISTS (SELECT 1 FROM users WHERE user_id = NEW.verified_by AND role = 'coordinator' AND university_id = NEW.university_id) THEN
                RAISE EXCEPTION 'RULE_SR12_VERIFIER: a coordinator of the same university must verify the student' USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            NEW.verified_at := coalesce(NEW.verified_at, now());
        END IF;
    ELSE
        NEW.verified_by := NULL; NEW.verified_at := NULL;
    END IF;
    IF NEW.cv_path IS NOT NULL AND NEW.cv_uploaded_at IS NULL THEN NEW.cv_uploaded_at := now(); END IF;
    IF NEW.cv_path IS NULL THEN NEW.cv_uploaded_at := NULL; NEW.cv_size_bytes := NULL; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_01_guard   BEFORE INSERT OR UPDATE ON student_profiles FOR EACH ROW EXECUTE FUNCTION fn_student_guard();
CREATE TRIGGER trg_02_updated BEFORE UPDATE ON student_profiles FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

-- ---------- listings (SR07, SR08) ----------------------------------------
CREATE FUNCTION fn_listings_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE v_company_status TEXT;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF NEW.company_id <> OLD.company_id THEN
            RAISE EXCEPTION 'RULE_SR17_OWNERSHIP: the owning company of a listing cannot be changed' USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        IF NEW.status <> OLD.status AND NOT (
              (OLD.status = 'draft'  AND NEW.status IN ('open','hidden'))
           OR (OLD.status = 'open'   AND NEW.status IN ('closed','hidden'))
           OR (OLD.status = 'closed' AND NEW.status IN ('open','hidden'))
           OR (OLD.status = 'hidden' AND NEW.status IN ('open','closed'))) THEN
            RAISE EXCEPTION 'RULE_LISTING_TRANSITION: a listing cannot go from % to %', OLD.status, NEW.status USING ERRCODE = 'integrity_constraint_violation';
        END IF;
    END IF;
    IF NEW.status = 'open' AND (TG_OP = 'INSERT' OR OLD.status <> 'open') THEN
        SELECT verification_status INTO v_company_status FROM companies WHERE company_id = NEW.company_id;
        IF v_company_status <> 'verified' THEN
            RAISE EXCEPTION 'RULE_SR07_COMPANY_NOT_VERIFIED: only a verified company can open a listing' USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        IF NEW.application_deadline < CURRENT_DATE THEN
            RAISE EXCEPTION 'RULE_SR08_DEADLINE_PAST: the application deadline is already in the past' USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        NEW.posted_at := coalesce(NEW.posted_at, now());
        NEW.closed_at := NULL;
    END IF;
    IF NEW.status = 'closed' AND (TG_OP = 'INSERT' OR OLD.status <> 'closed') THEN NEW.closed_at := coalesce(NEW.closed_at, now()); END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_01_guard   BEFORE INSERT OR UPDATE ON listings FOR EACH ROW EXECUTE FUNCTION fn_listings_guard();
CREATE TRIGGER trg_02_updated BEFORE UPDATE ON listings FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
CREATE TRIGGER trg_90_audit   AFTER INSERT OR UPDATE ON listings FOR EACH ROW EXECUTE FUNCTION fn_audit_status_change('listing_id', 'status');

-- ---------- applications (SR04) -------------------------------------------
CREATE FUNCTION fn_applications_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
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
    -- UPDATE
    IF NEW.student_id <> OLD.student_id OR NEW.listing_id <> OLD.listing_id THEN
        RAISE EXCEPTION 'RULE_SR17_IMMUTABLE_KEYS: student and listing of an application cannot change' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.status <> OLD.status THEN
        v_ok := CASE OLD.status
            WHEN 'submitted'    THEN NEW.status IN ('under_review','shortlisted','rejected','withdrawn')
            WHEN 'under_review' THEN NEW.status IN ('shortlisted','rejected','withdrawn')
            WHEN 'shortlisted'  THEN NEW.status IN ('accepted','rejected','withdrawn')
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
CREATE FUNCTION fn_applications_after() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE v_title TEXT; v_company TEXT; v_student_user BIGINT; r RECORD;
BEGIN
    SELECT l.title, c.name INTO v_title, v_company FROM listings l JOIN companies c ON c.company_id = l.company_id WHERE l.listing_id = NEW.listing_id;
    IF TG_OP = 'INSERT' THEN
        FOR r IN SELECT u.user_id FROM users u JOIN listings l ON l.company_id = u.company_id WHERE l.listing_id = NEW.listing_id LOOP
            PERFORM fn_notify(r.user_id, 'application_status', 'New application received', 'A student applied for "' || v_title || '".', 'applications', NEW.application_id, FALSE);
        END LOOP;
        RETURN NULL;
    END IF;
    IF NEW.status = OLD.status THEN RETURN NULL; END IF;
    IF NEW.status <> 'withdrawn' THEN
        SELECT user_id INTO v_student_user FROM student_profiles WHERE student_id = NEW.student_id;
        PERFORM fn_notify(v_student_user, 'application_status', 'Application status updated',
            'Your application for "' || v_title || '" at ' || v_company || ' is now ' || fn_status_label(NEW.status) || '.', 'applications', NEW.application_id);
    END IF;
    IF NEW.status = 'accepted' THEN
        INSERT INTO placements (application_id) VALUES (NEW.application_id) ON CONFLICT (application_id) DO NOTHING;
    END IF;
    RETURN NULL;
END $$;
CREATE TRIGGER trg_01_guard   BEFORE INSERT OR UPDATE ON applications FOR EACH ROW EXECUTE FUNCTION fn_applications_guard();
CREATE TRIGGER trg_02_updated BEFORE UPDATE ON applications FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
CREATE TRIGGER trg_10_notify  AFTER INSERT OR UPDATE ON applications FOR EACH ROW EXECUTE FUNCTION fn_applications_after();
CREATE TRIGGER trg_90_audit   AFTER INSERT OR UPDATE ON applications FOR EACH ROW EXECUTE FUNCTION fn_audit_status_change('application_id', 'status');

-- ---------- placements (SR11, SR13) -----------------------------------------
CREATE FUNCTION fn_placements_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE v_app_status TEXT; v_listing_id BIGINT; v_slots INT; v_company BIGINT; v_s_univ BIGINT; v_s_dept BIGINT;
        v_ok BOOLEAN; v_c_univ BIGINT; v_c_dept BIGINT; v_c_role TEXT; v_e_role TEXT; v_e_company BIGINT; v_used INT;
BEGIN
    SELECT a.status, a.listing_id, sp.university_id, sp.department_id, l.slots, l.company_id
      INTO v_app_status, v_listing_id, v_s_univ, v_s_dept, v_slots, v_company
    FROM applications a JOIN student_profiles sp ON sp.student_id = a.student_id JOIN listings l ON l.listing_id = a.listing_id
    WHERE a.application_id = NEW.application_id;
    IF TG_OP = 'INSERT' THEN
        IF v_app_status <> 'accepted' THEN
            RAISE EXCEPTION 'RULE_SR13_NOT_ACCEPTED: a placement can only be created for an accepted application' USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        IF NEW.status <> 'pending' THEN
            RAISE EXCEPTION 'RULE_SR13_INITIAL_STATUS: a new placement must be pending' USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.application_id <> OLD.application_id THEN
        RAISE EXCEPTION 'RULE_SR17_IMMUTABLE_KEYS: the application of a placement cannot change' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.status <> OLD.status THEN
        v_ok := CASE OLD.status WHEN 'pending' THEN NEW.status IN ('confirmed','rejected') WHEN 'confirmed' THEN NEW.status = 'completed' ELSE FALSE END;
        IF NOT v_ok THEN
            RAISE EXCEPTION 'RULE_SR13_TRANSITION: a placement cannot go from % to %', OLD.status, NEW.status USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        IF OLD.status = 'pending' THEN          -- university decision: scope check
            NEW.reviewed_by := coalesce(NEW.reviewed_by, app_user_id());
            NEW.reviewed_at := coalesce(NEW.reviewed_at, now());
            SELECT role, university_id, department_id INTO v_c_role, v_c_univ, v_c_dept FROM users WHERE user_id = NEW.reviewed_by;
            IF v_c_role IS DISTINCT FROM 'coordinator' OR v_c_univ IS DISTINCT FROM v_s_univ
               OR (v_c_dept IS NOT NULL AND v_c_dept <> v_s_dept) THEN
                RAISE EXCEPTION 'RULE_SR13_SCOPE: only a coordinator of the student''s university and department can decide' USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.status = 'confirmed' THEN
                SELECT count(*) INTO v_used FROM placements p JOIN applications a ON a.application_id = p.application_id
                WHERE a.listing_id = v_listing_id AND p.status IN ('confirmed','completed') AND p.placement_id <> NEW.placement_id;
                IF v_used >= v_slots THEN
                    RAISE EXCEPTION 'RULE_SR13_NO_SLOTS: all slots of this listing are already filled' USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;
        ELSE                                    -- employer completes (SR11)
            NEW.completed_by := coalesce(NEW.completed_by, app_user_id());
            SELECT role, company_id INTO v_e_role, v_e_company FROM users WHERE user_id = NEW.completed_by;
            IF v_e_role IS DISTINCT FROM 'employer' OR v_e_company IS DISTINCT FROM v_company THEN
                RAISE EXCEPTION 'RULE_SR11_NOT_OWNER: only an employer of the host company can complete the placement' USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.end_date > CURRENT_DATE THEN
                RAISE EXCEPTION 'RULE_SR11_NOT_ENDED: the placement can only be completed after its end date' USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            NEW.completed_at := coalesce(NEW.completed_at, now());
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE FUNCTION fn_placements_after() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE v_listing BIGINT; v_student_user BIGINT; v_title TEXT; v_msg TEXT;
BEGIN
    SELECT a.listing_id, sp.user_id, l.title INTO v_listing, v_student_user, v_title
    FROM applications a JOIN student_profiles sp ON sp.student_id = a.student_id JOIN listings l ON l.listing_id = a.listing_id
    WHERE a.application_id = COALESCE(NEW.application_id, OLD.application_id);
    UPDATE listings SET slots_filled = (
        SELECT count(*) FROM placements p JOIN applications a ON a.application_id = p.application_id
        WHERE a.listing_id = v_listing AND p.status IN ('confirmed','completed')) WHERE listing_id = v_listing;
    IF TG_OP = 'UPDATE' AND NEW.status <> OLD.status THEN
        v_msg := CASE NEW.status
            WHEN 'confirmed' THEN 'Your placement for "' || v_title || '" has been approved by your university.'
            WHEN 'rejected'  THEN 'Your placement for "' || v_title || '" was not approved. Reason: ' || NEW.rejection_reason
            WHEN 'completed' THEN 'Your placement for "' || v_title || '" has been marked completed.' END;
        PERFORM fn_notify(v_student_user, 'placement_decision', 'Placement update', v_msg, 'placements', NEW.placement_id);
    END IF;
    RETURN NULL;
END $$;
CREATE TRIGGER trg_01_guard   BEFORE INSERT OR UPDATE ON placements FOR EACH ROW EXECUTE FUNCTION fn_placements_guard();
CREATE TRIGGER trg_02_updated BEFORE UPDATE ON placements FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
CREATE TRIGGER trg_10_notify  AFTER INSERT OR UPDATE OR DELETE ON placements FOR EACH ROW EXECUTE FUNCTION fn_placements_after();
CREATE TRIGGER trg_90_audit   AFTER INSERT OR UPDATE ON placements FOR EACH ROW EXECUTE FUNCTION fn_audit_status_change('placement_id', 'status');

-- ---------- check-ins (SR14) ----------------------------------------------------
CREATE FUNCTION fn_check_ins_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE v_status TEXT; v_s_univ BIGINT; v_s_dept BIGINT; v_role TEXT; v_c_univ BIGINT; v_c_dept BIGINT; v_c_status TEXT;
BEGIN
    SELECT p.status, sp.university_id, sp.department_id INTO v_status, v_s_univ, v_s_dept
    FROM placements p JOIN applications a ON a.application_id = p.application_id JOIN student_profiles sp ON sp.student_id = a.student_id
    WHERE p.placement_id = NEW.placement_id;
    IF v_status <> 'confirmed' THEN
        RAISE EXCEPTION 'RULE_SR14_PLACEMENT_NOT_ACTIVE: check-ins can only be recorded for a confirmed placement' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    SELECT role, university_id, department_id, status INTO v_role, v_c_univ, v_c_dept, v_c_status FROM users WHERE user_id = NEW.coordinator_id;
    IF v_role IS DISTINCT FROM 'coordinator' OR v_c_univ IS DISTINCT FROM v_s_univ OR (v_c_dept IS NOT NULL AND v_c_dept <> v_s_dept) OR v_c_status <> 'active' THEN
        RAISE EXCEPTION 'RULE_SR14_SCOPE: only an active coordinator of the student''s university and department can record a check-in' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_01_guard BEFORE INSERT ON check_ins FOR EACH ROW EXECUTE FUNCTION fn_check_ins_guard();

-- ---------- messages (SR10) -----------------------------------------------------------
CREATE FUNCTION fn_messages_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
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
    IF v_status NOT IN ('shortlisted','accepted') THEN
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
CREATE FUNCTION fn_messages_after() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    PERFORM fn_notify(NEW.recipient_id, 'message', 'New message', 'You have a new message about an application.', 'messages', NEW.message_id, FALSE);
    RETURN NULL;
END $$;
CREATE TRIGGER trg_01_guard  BEFORE INSERT OR UPDATE ON messages FOR EACH ROW EXECUTE FUNCTION fn_messages_guard();
CREATE TRIGGER trg_10_notify AFTER INSERT ON messages FOR EACH ROW EXECUTE FUNCTION fn_messages_after();

-- ---------- notifications: keep read/sent timestamps consistent -------------------
CREATE FUNCTION fn_notifications_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.channel = 'in_app' THEN NEW.delivery_status := 'sent'; NEW.sent_at := coalesce(NEW.sent_at, now()); END IF;
    IF NEW.delivery_status = 'sent' AND NEW.sent_at IS NULL THEN NEW.sent_at := now(); END IF;
    IF NEW.is_read AND NEW.read_at IS NULL THEN NEW.read_at := now(); END IF;
    IF NOT NEW.is_read THEN NEW.read_at := NULL; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_01_guard BEFORE INSERT OR UPDATE ON notifications FOR EACH ROW EXECUTE FUNCTION fn_notifications_guard();
