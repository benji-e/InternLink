-- =====================================================================
-- InternLink Uganda - File 06: automated database tests
-- Run AFTER 01-05 (needs the seed data). Everything runs in one transaction that
-- is rolled back, so the database is left unchanged.
--   psql -v ON_ERROR_STOP=1 -d internlink -f 06_tests.sql
-- Exit code is non-zero if any test fails.
-- =====================================================================
\set QUIET on
BEGIN;
CREATE TEMP TABLE test_results (seq SERIAL, id TEXT, description TEXT, passed BOOLEAN, detail TEXT);
GRANT ALL ON test_results TO PUBLIC;
GRANT ALL ON SEQUENCE test_results_seq_seq TO PUBLIC;

CREATE FUNCTION pg_temp.t_fail(p_id TEXT, p_desc TEXT, p_sql TEXT, p_expect TEXT) RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
    BEGIN
        EXECUTE p_sql;
        INSERT INTO test_results (id, description, passed, detail) VALUES (p_id, p_desc, FALSE, 'no error was raised');
    EXCEPTION WHEN OTHERS THEN
        INSERT INTO test_results (id, description, passed, detail)
        VALUES (p_id, p_desc, position(p_expect IN SQLERRM) > 0, left(SQLERRM, 110));
    END;
END $$;
CREATE FUNCTION pg_temp.t_pass(p_id TEXT, p_desc TEXT, p_sql TEXT) RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
    BEGIN
        EXECUTE p_sql;
        INSERT INTO test_results (id, description, passed, detail) VALUES (p_id, p_desc, TRUE, 'ok');
    EXCEPTION WHEN OTHERS THEN
        INSERT INTO test_results (id, description, passed, detail) VALUES (p_id, p_desc, FALSE, left(SQLERRM, 110));
    END;
END $$;
CREATE FUNCTION pg_temp.t_eq(p_id TEXT, p_desc TEXT, p_query TEXT, p_expected TEXT) RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE v TEXT;
BEGIN
    BEGIN
        EXECUTE p_query INTO v;
        INSERT INTO test_results (id, description, passed, detail) VALUES (p_id, p_desc, v IS NOT DISTINCT FROM p_expected, 'got ' || coalesce(v, 'NULL') || ', expected ' || p_expected);
    EXCEPTION WHEN OTHERS THEN
        INSERT INTO test_results (id, description, passed, detail) VALUES (p_id, p_desc, FALSE, left(SQLERRM, 110));
    END;
END $$;
CREATE FUNCTION pg_temp.app(p_sid BIGINT, p_lid BIGINT) RETURNS BIGINT LANGUAGE sql AS $$ SELECT application_id FROM applications WHERE student_id = p_sid AND listing_id = p_lid $$;
CREATE FUNCTION pg_temp.plc(p_sid BIGINT, p_lid BIGINT) RETURNS BIGINT LANGUAGE sql AS $$ SELECT placement_id FROM placements WHERE application_id = pg_temp.app(p_sid, p_lid) $$;

DO $do$
BEGIN
-- ===== M: matching function (Matching Algorithm Design, sections 4-5) =====
PERFORM pg_temp.t_eq('M01','Worked example A: Software Developer Intern scores 79 for Nakato', $q$SELECT score::text FROM fn_recommendations(1,10,0) WHERE listing_id=1$q$, '79');
PERFORM pg_temp.t_eq('M02','Worked example B: Data Analyst Intern scores 38', $q$SELECT score::text FROM fn_recommendations(1,10,0) WHERE listing_id=2$q$, '38');
PERFORM pg_temp.t_eq('M03','Worked example C: Accounting Intern (score 10) is below the minimum and is dropped', $q$SELECT count(*)::text FROM fn_recommendations(1) WHERE listing_id=3$q$, '0');
PERFORM pg_temp.t_eq('M04','Worked example C: its raw score is 10', $q$SELECT score::text FROM fn_recommendations(1,10,0) WHERE listing_id=3$q$, '10');
PERFORM pg_temp.t_eq('M05','Best match is ranked first', $q$SELECT listing_id::text FROM fn_recommendations(1) WHERE rank=1$q$, '1');
PERFORM pg_temp.t_eq('M06','Same inputs give identical output (reproducible)', $q$SELECT (array(SELECT row(r.*)::text FROM fn_recommendations(1) r) = array(SELECT row(r.*)::text FROM fn_recommendations(1) r))::text$q$, 'true');
PERFORM pg_temp.t_eq('M07','All scores are between 0 and 100', $q$SELECT bool_and(r.score BETWEEN 0 AND 100)::text FROM student_profiles s CROSS JOIN LATERAL fn_recommendations(s.student_id,100,0) r$q$, 'true');
PERFORM pg_temp.t_eq('M08','Applied flag is true for a listing the student applied to', $q$SELECT applied::text FROM fn_recommendations(1,10,0) WHERE listing_id=1$q$, 'true');
PERFORM pg_temp.t_eq('M09','The limit parameter is respected', $q$SELECT count(*)::text FROM fn_recommendations(1,2,0)$q$, '2');
PERFORM pg_temp.t_eq('M10','Skills-only weights: 2 of 3 required skills = 67', $q$SELECT score::text FROM fn_recommendations(1,10,0,0,1,0,0) WHERE listing_id=1$q$, '67');
PERFORM pg_temp.t_eq('M11','Closed listing (id 8) is never recommended', $q$SELECT count(*)::text FROM fn_recommendations(5,100,0) WHERE listing_id=8$q$, '0');
PERFORM pg_temp.t_eq('M12','Draft listing (id 7) is never recommended', $q$SELECT count(*)::text FROM fn_recommendations(2,100,0) WHERE listing_id=7$q$, '0');
PERFORM pg_temp.t_eq('M13','Remote listing gets full location score', $q$SELECT l::text FROM fn_recommendations(1,100,0) WHERE listing_id=9$q$, '1.0');
PERFORM pg_temp.t_pass('M14','Add a matching skill (React) to Nakato', $q$INSERT INTO student_skills VALUES (1,4)$q$);
PERFORM pg_temp.t_eq('M15','More overlap never lowers the score (79 -> 93)', $q$SELECT score::text FROM fn_recommendations(1,10,0) WHERE listing_id=1$q$, '93');
PERFORM pg_temp.t_pass('M16','Remove the test skill again', $q$DELETE FROM student_skills WHERE student_id=1 AND skill_id=4$q$);
PERFORM pg_temp.t_pass('M17','Student without a location preference', $q$UPDATE student_profiles SET preferred_location=NULL WHERE student_id=1$q$);
PERFORM pg_temp.t_eq('M18','Location left out: weights rescaled (79 -> 77)', $q$SELECT score::text FROM fn_recommendations(1,10,0) WHERE listing_id=1$q$, '77');
PERFORM pg_temp.t_pass('M19','Restore preferred location', $q$UPDATE student_profiles SET preferred_location='Kampala' WHERE student_id=1$q$);

-- ===== V: view snapshots before any change =====
PERFORM pg_temp.t_eq('V01','Admin queue shows the pending university and company', $q$SELECT count(*)::text FROM v_admin_pending_registrations$q$, '2');
PERFORM pg_temp.t_eq('V02','Approval queue shows the one pending placement', $q$SELECT count(*)::text FROM v_pending_placements$q$, '1');
PERFORM pg_temp.t_eq('V03','Complete profile = 100%', $q$SELECT completeness_pct::text FROM v_student_profile_status WHERE student_id=1$q$, '100');
PERFORM pg_temp.t_eq('V04','Profile without CV = 80%', $q$SELECT completeness_pct::text FROM v_student_profile_status WHERE student_id=8$q$, '80');
PERFORM pg_temp.t_eq('V05','Employer applicant table for TechCo has 5 rows', $q$SELECT count(*)::text FROM v_employer_applicants WHERE company_id=1$q$, '5');
PERFORM pg_temp.t_eq('V06','Export lists confirmed and completed placements only', $q$SELECT count(*)::text FROM v_placement_export$q$, '2');
PERFORM pg_temp.t_eq('V07','Dashboard percentages add up to 100', $q$SELECT bool_and(abs(placed_pct+pending_pct+unplaced_pct-100) < 0.001)::text FROM v_department_placement_stats WHERE enrolled>0$q$, 'true');
PERFORM pg_temp.t_eq('V08','Open listings view excludes the closed listing', $q$SELECT count(*)::text FROM v_open_listings WHERE listing_id=8$q$, '0');
PERFORM pg_temp.t_eq('V09','Unverified student is not counted as enrolled', $q$SELECT sum(enrolled)::text FROM v_department_placement_stats WHERE university_id=1$q$, '6');

-- ===== A: users, roles and student profiles (SR01, SR17, NFR06) =====
PERFORM pg_temp.t_fail('A01','Duplicate email rejected', $q$INSERT INTO users(email,password_hash,full_name,role) VALUES ('admin@internlink.ug',repeat('x',30),'Dup','student')$q$, 'uq_users_email');
PERFORM pg_temp.t_fail('A02','Email must be stored in lower case', $q$INSERT INTO users(email,password_hash,full_name,role) VALUES ('Foo@Bar.com',repeat('x',30),'Foo','student')$q$, 'ck_users_email');
PERFORM pg_temp.t_fail('A03','Student cannot belong to a company', $q$INSERT INTO users(email,password_hash,full_name,role,company_id) VALUES ('a1@x.com',repeat('x',30),'A','student',1)$q$, 'ck_users_company_scope');
PERFORM pg_temp.t_fail('A04','Employer must belong to a company', $q$INSERT INTO users(email,password_hash,full_name,role) VALUES ('a2@x.com',repeat('x',30),'A','employer')$q$, 'ck_users_company_scope');
PERFORM pg_temp.t_fail('A05','Coordinator must belong to a university', $q$INSERT INTO users(email,password_hash,full_name,role) VALUES ('a3@x.com',repeat('x',30),'A','coordinator')$q$, 'ck_users_univ_scope');
PERFORM pg_temp.t_fail('A06','Account cannot be Active before email verification', $q$INSERT INTO users(email,password_hash,full_name,role,status) VALUES ('a4@x.com',repeat('x',30),'A','student','active')$q$, 'ck_users_active_email');
PERFORM pg_temp.t_fail('A07','Administrator cannot be self-registered', $q$INSERT INTO users(email,password_hash,full_name,role) VALUES ('evil@x.com',repeat('x',30),'Evil','admin')$q$, 'RULE_SR17_ADMIN_CREATE');
PERFORM pg_temp.t_fail('A08','A student cannot promote themselves to admin', $q$UPDATE users SET role='admin' WHERE user_id=10$q$, 'RULE_SR17_ROLE_IMMUTABLE');
PERFORM pg_temp.t_fail('A09','An employer cannot switch to another company', $q$UPDATE users SET company_id=2 WHERE user_id=5$q$, 'RULE_SR17_ROLE_IMMUTABLE');
PERFORM set_config('app.allow_role_change','on',true);
PERFORM pg_temp.t_pass('A10','Admin creation works when explicitly allowed (seeding / admin console)', $q$INSERT INTO users(email,password_hash,full_name,role) VALUES ('admin2@internlink.ug',repeat('x',30),'Second Admin','admin')$q$);
PERFORM set_config('app.allow_role_change','off',true);
PERFORM pg_temp.t_pass('A11','Create a student account with a Gmail address', $q$INSERT INTO users(email,password_hash,full_name,role) VALUES ('x@gmail.com',repeat('x',30),'X','student')$q$);
PERFORM pg_temp.t_fail('A12','Student profile needs a university email domain', $q$INSERT INTO student_profiles(user_id,university_id,department_id,programme_id,student_number,year_of_study) VALUES ((SELECT user_id FROM users WHERE email='x@gmail.com'),1,1,1,'T-001',2)$q$, 'RULE_SR01_EMAIL_DOMAIN');
PERFORM pg_temp.t_pass('A13','Create a student account with a MUST address', $q$INSERT INTO users(email,password_hash,full_name,role) VALUES ('new.student@std.must.ac.ug',repeat('x',30),'New Student','student')$q$);
PERFORM pg_temp.t_fail('A14','Duplicate student number (case-insensitive) rejected', $q$INSERT INTO student_profiles(user_id,university_id,department_id,programme_id,student_number,year_of_study) VALUES ((SELECT user_id FROM users WHERE email='new.student@std.must.ac.ug'),1,1,1,'2024/bse/201/ps',2)$q$, 'uq_student_number');
PERFORM pg_temp.t_fail('A15','Programme must belong to the chosen department', $q$INSERT INTO student_profiles(user_id,university_id,department_id,programme_id,student_number,year_of_study) VALUES ((SELECT user_id FROM users WHERE email='new.student@std.must.ac.ug'),1,1,4,'T-002',2)$q$, 'fk_student_prog');
PERFORM pg_temp.t_fail('A16','Department must belong to the chosen university', $q$INSERT INTO student_profiles(user_id,university_id,department_id,programme_id,student_number,year_of_study) VALUES ((SELECT user_id FROM users WHERE email='new.student@std.must.ac.ug'),1,5,5,'T-003',2)$q$, 'fk_student_dept');
PERFORM pg_temp.t_fail('A17','Only a student user can have a student profile', $q$INSERT INTO student_profiles(user_id,university_id,department_id,programme_id,student_number,year_of_study) VALUES (2,1,1,1,'T-004',2)$q$, 'fk_student_user');
PERFORM pg_temp.t_fail('A18','Year of study must be 1 to 6', $q$UPDATE student_profiles SET year_of_study=7 WHERE student_id=1$q$, 'ck_student_year');
PERFORM pg_temp.t_fail('A19','CV must be PDF or DOCX', $q$UPDATE student_profiles SET cv_path='cv/virus.exe' WHERE student_id=1$q$, 'ck_student_cv_ext');
PERFORM pg_temp.t_fail('A20','CV larger than 5 MB rejected', $q$UPDATE student_profiles SET cv_size_bytes=6000000 WHERE student_id=1$q$, 'ck_student_cv_size');
PERFORM pg_temp.t_pass('A21','Valid student profile is accepted', $q$INSERT INTO student_profiles(user_id,university_id,department_id,programme_id,student_number,year_of_study) VALUES ((SELECT user_id FROM users WHERE email='new.student@std.must.ac.ug'),1,1,1,'T-005',2)$q$);
PERFORM pg_temp.t_eq('A22','New profile starts unverified', $q$SELECT verified::text FROM student_profiles WHERE student_number='T-005'$q$, 'false');
PERFORM pg_temp.t_fail('A23','Coordinator of another university cannot verify a student', $q$UPDATE student_profiles SET verified=true, verified_by=4 WHERE student_number='T-005'$q$, 'RULE_SR12_VERIFIER');
PERFORM pg_temp.t_pass('A24','Coordinator of the same university verifies the student', $q$UPDATE student_profiles SET verified=true, verified_by=3 WHERE student_number='T-005'$q$);
PERFORM pg_temp.t_eq('A25','verified_at is filled automatically', $q$SELECT (verified_at IS NOT NULL)::text FROM student_profiles WHERE student_number='T-005'$q$, 'true');
PERFORM pg_temp.t_pass('A26','Try to back-date updated_at manually', $q$UPDATE student_profiles SET updated_at='2000-01-01' WHERE student_number='T-005'$q$);
PERFORM pg_temp.t_eq('A27','The trigger overrides a manual updated_at value', $q$SELECT (updated_at > '2020-01-01')::text FROM student_profiles WHERE student_number='T-005'$q$, 'true');

-- ===== B: listings (SR07, SR08) =====
PERFORM pg_temp.t_fail('B01','Pending company cannot open a listing (SR07)', $q$UPDATE listings SET status='open' WHERE listing_id=7$q$, 'RULE_SR07_COMPANY_NOT_VERIFIED');
PERFORM pg_temp.t_fail('B02','A listing can only be posted by a user of that company', $q$INSERT INTO listings(company_id,posted_by,title,description,sector,location,duration_weeks,slots,application_deadline) VALUES (1,6,'T','D','S','L',4,1,CURRENT_DATE+5)$q$, 'fk_listings_poster');
PERFORM pg_temp.t_fail('B03','Slots must be at least 1', $q$INSERT INTO listings(company_id,posted_by,title,description,sector,location,duration_weeks,slots,application_deadline) VALUES (1,5,'T','D','S','L',4,0,CURRENT_DATE+5)$q$, 'ck_listings_slots');
PERFORM pg_temp.t_fail('B04','Duration must be 1 to 52 weeks', $q$INSERT INTO listings(company_id,posted_by,title,description,sector,location,duration_weeks,slots,application_deadline) VALUES (1,5,'T','D','S','L',0,1,CURRENT_DATE+5)$q$, 'ck_listings_duration');
PERFORM pg_temp.t_fail('B05','Cannot open a listing whose deadline has passed', $q$INSERT INTO listings(company_id,posted_by,title,description,sector,location,duration_weeks,slots,application_deadline,status) VALUES (1,5,'T','D','S','L',4,1,CURRENT_DATE-1,'open')$q$, 'RULE_SR08_DEADLINE_PAST');
PERFORM pg_temp.t_fail('B06','A draft cannot be closed directly', $q$UPDATE listings SET status='closed' WHERE listing_id=6$q$, 'RULE_LISTING_TRANSITION');
PERFORM pg_temp.t_fail('B07','The owning company of a listing cannot change', $q$UPDATE listings SET company_id=2 WHERE listing_id=1$q$, 'RULE_SR17_OWNERSHIP');
PERFORM pg_temp.t_fail('B08','Filled slots cannot exceed slots', $q$UPDATE listings SET slots_filled=5 WHERE listing_id=2$q$, 'ck_listings_filled');
PERFORM pg_temp.t_pass('B09','Verified company opens a draft listing', $q$UPDATE listings SET status='open' WHERE listing_id=6$q$);
PERFORM pg_temp.t_eq('B10','posted_at is filled when a listing opens', $q$SELECT (posted_at IS NOT NULL)::text FROM listings WHERE listing_id=6$q$, 'true');
PERFORM pg_temp.t_eq('B11','Full-text search finds the Python listing', $q$SELECT count(*)::text FROM listings WHERE search_vector @@ plainto_tsquery('english','python')$q$, '1');
PERFORM pg_temp.t_pass('B12','Close a listing', $q$UPDATE listings SET status='closed' WHERE listing_id=6$q$);
PERFORM pg_temp.t_eq('B13','closed_at is filled when a listing closes', $q$SELECT (closed_at IS NOT NULL)::text FROM listings WHERE listing_id=6$q$, 'true');

-- ===== C: applications (SR04) =====
PERFORM pg_temp.t_fail('C01','Cannot apply to a closed listing', $q$INSERT INTO applications(student_id,listing_id) VALUES (2,8)$q$, 'RULE_SR04_LISTING_CLOSED');
PERFORM pg_temp.t_fail('C02','Cannot apply to a draft listing', $q$INSERT INTO applications(student_id,listing_id) VALUES (2,7)$q$, 'RULE_SR04_LISTING_CLOSED');
PERFORM pg_temp.t_pass('C03','Move the deadline of an open listing into the past', $q$UPDATE listings SET application_deadline=CURRENT_DATE-1 WHERE listing_id=3$q$);
PERFORM pg_temp.t_fail('C04','Cannot apply after the deadline', $q$INSERT INTO applications(student_id,listing_id) VALUES (1,3)$q$, 'RULE_SR04_DEADLINE_PASSED');
PERFORM pg_temp.t_pass('C05','Restore the deadline', $q$UPDATE listings SET application_deadline=CURRENT_DATE+20 WHERE listing_id=3$q$);
PERFORM pg_temp.t_fail('C06','Unverified student cannot apply', $q$INSERT INTO applications(student_id,listing_id) VALUES (7,1)$q$, 'RULE_SR12_STUDENT_NOT_VERIFIED');
PERFORM pg_temp.t_pass('C07','Suspend a student account', $q$UPDATE users SET status='suspended' WHERE user_id=17$q$);
PERFORM pg_temp.t_fail('C08','Suspended student cannot apply', $q$INSERT INTO applications(student_id,listing_id) VALUES (8,1)$q$, 'RULE_ACCOUNT_NOT_ACTIVE');
PERFORM pg_temp.t_pass('C09','Reactivate the account', $q$UPDATE users SET status='active' WHERE user_id=17$q$);
PERFORM pg_temp.t_fail('C10','Same student cannot apply twice to a listing', $q$INSERT INTO applications(student_id,listing_id) VALUES (1,1)$q$, 'uq_applications_student_listing');
PERFORM pg_temp.t_fail('C11','A new application must start as submitted', $q$INSERT INTO applications(student_id,listing_id,status) VALUES (8,1,'accepted')$q$, 'RULE_SR04_INITIAL_STATUS');
PERFORM pg_temp.t_fail('C12','Match score must be between 0 and 100', $q$INSERT INTO applications(student_id,listing_id,match_score) VALUES (8,1,120)$q$, 'ck_applications_score');
PERFORM pg_temp.t_pass('C13','A valid application is accepted', $q$INSERT INTO applications(student_id,listing_id,match_score) VALUES (8,1,60)$q$);
PERFORM pg_temp.t_eq('C14','Company users are told about the new application (in-app only)', $q$SELECT count(*)::text FROM notifications WHERE user_id=5 AND title='New application received' AND related_id=pg_temp.app(8,1)$q$, '1');
PERFORM set_config('app.user_id','5',true);
PERFORM pg_temp.t_fail('C15','Cannot skip stages: submitted -> accepted', $q$UPDATE applications SET status='accepted' WHERE student_id=5 AND listing_id=5$q$, 'RULE_SR04_TRANSITION');
PERFORM pg_temp.t_fail('C16','A rejected application is final', $q$UPDATE applications SET status='shortlisted' WHERE student_id=1 AND listing_id=5$q$, 'RULE_SR04_TRANSITION');
PERFORM pg_temp.t_fail('C17','Student and listing of an application are immutable', $q$UPDATE applications SET listing_id=2 WHERE student_id=1 AND listing_id=1$q$, 'RULE_SR17_IMMUTABLE_KEYS');
PERFORM pg_temp.t_pass('C18','Valid transition: submitted -> under_review', $q$UPDATE applications SET status='under_review' WHERE student_id=5 AND listing_id=5$q$);
PERFORM pg_temp.t_eq('C19','status_changed_at is updated', $q$SELECT (status_changed_at >= submitted_at)::text FROM applications WHERE student_id=5 AND listing_id=5$q$, 'true');
PERFORM pg_temp.t_eq('C20','Student receives an in-app AND an email notification (SR05)', $q$SELECT string_agg(channel, ',' ORDER BY channel) FROM notifications WHERE user_id=14 AND related_type='applications' AND related_id=pg_temp.app(5,5)$q$, 'email,in_app');
PERFORM pg_temp.t_eq('C21','In-app notification is marked sent immediately', $q$SELECT (delivery_status='sent' AND sent_at IS NOT NULL)::text FROM notifications WHERE user_id=14 AND channel='in_app' AND related_id=pg_temp.app(5,5)$q$, 'true');
PERFORM pg_temp.t_eq('C22','Email notification waits in the queue', $q$SELECT delivery_status FROM notifications WHERE user_id=14 AND channel='email' AND related_id=pg_temp.app(5,5)$q$, 'pending');
PERFORM pg_temp.t_pass('C23','Student withdraws', $q$UPDATE applications SET status='withdrawn' WHERE student_id=5 AND listing_id=5$q$);
PERFORM pg_temp.t_eq('C24','Withdrawing does not notify the student again', $q$SELECT count(*)::text FROM notifications WHERE user_id=14 AND related_id=pg_temp.app(5,5)$q$, '2');
PERFORM pg_temp.t_fail('C25','Cannot withdraw once the placement is confirmed', $q$UPDATE applications SET status='withdrawn' WHERE student_id=2 AND listing_id=2$q$, 'RULE_SR13_PLACEMENT_ACTIVE');

-- ===== D: placements (SR11, SR13) =====
PERFORM pg_temp.t_fail('D01','Placement only for an accepted application', $q$INSERT INTO placements(application_id) VALUES (pg_temp.app(3,4))$q$, 'RULE_SR13_NOT_ACCEPTED');
PERFORM pg_temp.t_eq('D02','Accepting an application created a pending placement automatically', $q$SELECT status FROM placements WHERE application_id=pg_temp.app(1,1)$q$, 'pending');
PERFORM set_config('app.user_id','3',true);
PERFORM pg_temp.t_fail('D03','Rejection needs a reason (SR13)', $q$UPDATE placements SET status='rejected' WHERE application_id=pg_temp.app(1,1)$q$, 'ck_placements_reject');
PERFORM pg_temp.t_fail('D04','Confirmation needs start and end dates', $q$UPDATE placements SET status='confirmed' WHERE application_id=pg_temp.app(1,1)$q$, 'ck_placements_confdate');
PERFORM pg_temp.t_fail('D05','End date cannot be before start date', $q$UPDATE placements SET start_date=CURRENT_DATE, end_date=CURRENT_DATE-5 WHERE application_id=pg_temp.app(1,1)$q$, 'ck_placements_dates');
PERFORM set_config('app.user_id','4',true);
PERFORM pg_temp.t_fail('D06','Coordinator of another university cannot decide', $q$UPDATE placements SET status='confirmed', start_date=CURRENT_DATE+10, end_date=CURRENT_DATE+90 WHERE application_id=pg_temp.app(1,1)$q$, 'RULE_SR13_SCOPE');
PERFORM set_config('app.user_id','17',true);
PERFORM pg_temp.t_fail('D07','A student cannot decide a placement', $q$UPDATE placements SET status='confirmed', start_date=CURRENT_DATE+10, end_date=CURRENT_DATE+90 WHERE application_id=pg_temp.app(1,1)$q$, 'RULE_SR13_SCOPE');
PERFORM set_config('app.user_id','6',true);
PERFORM pg_temp.t_pass('D08','Set up: second CS student applies to Data Analyst Intern', $q$INSERT INTO applications(student_id,listing_id) VALUES (8,2)$q$);
PERFORM pg_temp.t_pass('D09','Employer shortlists', $q$UPDATE applications SET status='shortlisted' WHERE student_id=8 AND listing_id=2$q$);
PERFORM pg_temp.t_pass('D10','Employer accepts', $q$UPDATE applications SET status='accepted' WHERE student_id=8 AND listing_id=2$q$);
PERFORM set_config('app.user_id','2',true);
PERFORM pg_temp.t_fail('D11','Coordinator of another DEPARTMENT cannot decide', $q$UPDATE placements SET status='confirmed', start_date=CURRENT_DATE+10, end_date=CURRENT_DATE+90 WHERE application_id=pg_temp.app(8,2)$q$, 'RULE_SR13_SCOPE');
PERFORM pg_temp.t_fail('D12','Check-in only on a confirmed placement', $q$INSERT INTO check_ins(placement_id,coordinator_id,notes) VALUES (pg_temp.plc(8,2),3,'early')$q$, 'RULE_SR14_PLACEMENT_NOT_ACTIVE');
PERFORM pg_temp.t_pass('D13','Department-wide coordinator (office) approves', $q$UPDATE placements SET reviewed_by=3, status='confirmed', start_date=CURRENT_DATE+10, end_date=CURRENT_DATE+90 WHERE application_id=pg_temp.app(8,2)$q$);
PERFORM pg_temp.t_eq('D14','Slots counter updated automatically (1 -> 2)', $q$SELECT slots_filled::text FROM listings WHERE listing_id=2$q$, '2');
PERFORM pg_temp.t_eq('D15','Student notified of the decision', $q$SELECT count(*)::text FROM notifications WHERE user_id=17 AND type='placement_decision'$q$, '2');
PERFORM set_config('app.user_id','6',true);
PERFORM pg_temp.t_pass('D16','Third student applies to the 2-slot listing', $q$INSERT INTO applications(student_id,listing_id) VALUES (1,2)$q$);
PERFORM pg_temp.t_pass('D17','Employer shortlists', $q$UPDATE applications SET status='shortlisted' WHERE student_id=1 AND listing_id=2$q$);
PERFORM pg_temp.t_pass('D18','Employer accepts', $q$UPDATE applications SET status='accepted' WHERE student_id=1 AND listing_id=2$q$);
PERFORM set_config('app.user_id','3',true);
PERFORM pg_temp.t_fail('D19','Cannot confirm more placements than slots', $q$UPDATE placements SET status='confirmed', start_date=CURRENT_DATE+10, end_date=CURRENT_DATE+90 WHERE application_id=pg_temp.app(1,2)$q$, 'RULE_SR13_NO_SLOTS');
PERFORM pg_temp.t_fail('D20','A rejected placement is final', $q$UPDATE placements SET status='confirmed', start_date=CURRENT_DATE, end_date=CURRENT_DATE+30 WHERE application_id=pg_temp.app(4,3)$q$, 'RULE_SR13_TRANSITION');
PERFORM pg_temp.t_eq('D21','Rejection reason reaches the student (in-app + email)', $q$SELECT count(*)::text FROM notifications WHERE user_id=13 AND message LIKE '%examination period%'$q$, '2');
PERFORM pg_temp.t_eq('D22','Confirming the first placement filled the TechCo slots counter', $q$SELECT slots_filled::text FROM listings WHERE listing_id=8$q$, '1');
PERFORM set_config('app.user_id','5',true);
PERFORM pg_temp.t_fail('D23','Employer of another company cannot complete a placement', $q$UPDATE placements SET status='completed', completion_note='x' WHERE application_id=pg_temp.app(2,2)$q$, 'RULE_SR11_NOT_OWNER');
PERFORM set_config('app.user_id','6',true);
PERFORM pg_temp.t_fail('D24','Cannot complete before the end date (SR11)', $q$UPDATE placements SET status='completed', completion_note='x' WHERE application_id=pg_temp.app(2,2)$q$, 'RULE_SR11_NOT_ENDED');
PERFORM pg_temp.t_pass('D25','Move the end date into the past', $q$UPDATE placements SET end_date=CURRENT_DATE-1 WHERE application_id=pg_temp.app(2,2)$q$);
PERFORM pg_temp.t_fail('D26','Completion needs a performance note', $q$UPDATE placements SET status='completed' WHERE application_id=pg_temp.app(2,2)$q$, 'ck_placements_complete');
PERFORM pg_temp.t_pass('D27','Owner employer completes with a note', $q$UPDATE placements SET status='completed', completion_note='Strong analytical work.' WHERE application_id=pg_temp.app(2,2)$q$);
PERFORM pg_temp.t_eq('D28','Completed placement still occupies its slot', $q$SELECT slots_filled::text FROM listings WHERE listing_id=2$q$, '2');

-- ===== E: check-ins (SR14) =====
PERFORM pg_temp.t_fail('E01','Coordinator of another university cannot record a check-in', $q$INSERT INTO check_ins(placement_id,coordinator_id,notes) VALUES (pg_temp.plc(5,8),4,'x')$q$, 'RULE_SR14_PLACEMENT_NOT_ACTIVE');
PERFORM pg_temp.t_fail('E02','Check-in notes cannot be empty', $q$INSERT INTO check_ins(placement_id,coordinator_id,notes) VALUES (pg_temp.plc(8,2),3,'   ')$q$, 'ck_check_ins_notes');

-- ===== F: messages (SR10) =====
PERFORM pg_temp.t_fail('F01','No messaging for a candidate who is only under review', $q$INSERT INTO messages(application_id,sender_id,recipient_id,body) VALUES (pg_temp.app(3,4),7,12,'hello')$q$, 'RULE_SR10_NOT_SHORTLISTED');
PERFORM pg_temp.t_fail('F02','Employer of another company cannot message the candidate', $q$INSERT INTO messages(application_id,sender_id,recipient_id,body) VALUES (pg_temp.app(1,1),6,10,'hello')$q$, 'RULE_SR10_PARTIES');
PERFORM pg_temp.t_fail('F03','Message must go to the candidate of that application', $q$INSERT INTO messages(application_id,sender_id,recipient_id,body) VALUES (pg_temp.app(1,1),5,11,'hello')$q$, 'RULE_SR10_PARTIES');
PERFORM pg_temp.t_fail('F04','Cannot message yourself', $q$INSERT INTO messages(application_id,sender_id,recipient_id,body) VALUES (pg_temp.app(1,1),5,5,'hello')$q$, 'RULE_SR10_PARTIES');
PERFORM pg_temp.t_pass('F05','Employer messages the accepted candidate', $q$INSERT INTO messages(application_id,sender_id,recipient_id,body) VALUES (pg_temp.app(1,1),5,10,'Please bring your ID on day one.')$q$);
PERFORM pg_temp.t_eq('F06','Recipient gets an in-app notification', $q$SELECT count(*)::text FROM notifications WHERE user_id=10 AND type='message'$q$, '2');
PERFORM pg_temp.t_pass('F07','Mark the message as read', $q$UPDATE messages SET is_read=true WHERE body LIKE 'Please bring%'$q$);
PERFORM pg_temp.t_eq('F08','read_at is filled automatically', $q$SELECT (read_at IS NOT NULL)::text FROM messages WHERE body LIKE 'Please bring%'$q$, 'true');

-- ===== G: organisation verification (SR07, SR18) =====
PERFORM pg_temp.t_fail('G01','Only an administrator can verify a company', $q$UPDATE companies SET verification_status='verified', verified_by=5 WHERE company_id=5$q$, 'RULE_SR18_VERIFIER');
PERFORM set_config('app.user_id','1',true);
PERFORM pg_temp.t_pass('G02','Administrator verifies GreenFarm', $q$UPDATE companies SET verification_status='verified' WHERE company_id=5$q$);
PERFORM pg_temp.t_eq('G03','verified_by is filled with the acting administrator', $q$SELECT verified_by::text FROM companies WHERE company_id=5$q$, '1');
PERFORM pg_temp.t_eq('G04','Company users are notified (in-app + email)', $q$SELECT count(*)::text FROM notifications WHERE user_id=9 AND type='registration_decision'$q$, '2');
PERFORM set_config('app.user_id','9',true);
PERFORM pg_temp.t_pass('G05','Now the company can open its listing', $q$UPDATE listings SET status='open' WHERE listing_id=7$q$);
PERFORM set_config('app.user_id','1',true);
PERFORM pg_temp.t_pass('G06','Register a test company', $q$INSERT INTO companies(name,sector,location,contact_email) VALUES ('Zeta Ltd','Retail','Kampala','info@zeta.example')$q$);
PERFORM pg_temp.t_pass('G07','Register its representative', $q$INSERT INTO users(email,password_hash,full_name,role,status,company_id,email_verified_at) VALUES ('hr@zeta.example',repeat('x',30),'Zeta HR','employer','active',(SELECT company_id FROM companies WHERE name='Zeta Ltd'),now())$q$);
PERFORM pg_temp.t_fail('G08','Rejecting a company requires a reason', $q$UPDATE companies SET verification_status='rejected' WHERE name='Zeta Ltd'$q$, 'ck_companies_reject');
PERFORM pg_temp.t_pass('G09','Reject with a reason', $q$UPDATE companies SET verification_status='rejected', rejection_reason='Documents could not be confirmed.' WHERE name='Zeta Ltd'$q$);
PERFORM pg_temp.t_eq('G10','Rejection blocks the representative accounts', $q$SELECT status FROM users WHERE email='hr@zeta.example'$q$, 'rejected');
PERFORM pg_temp.t_pass('G11','Administrator verifies university 3', $q$UPDATE universities SET status='verified' WHERE university_id=3$q$);
PERFORM pg_temp.t_eq('G12','University verified_at is filled', $q$SELECT (verified_at IS NOT NULL)::text FROM universities WHERE university_id=3$q$, 'true');
PERFORM pg_temp.t_pass('G13','Suspend TechCo', $q$UPDATE companies SET verification_status='suspended' WHERE company_id=1$q$);
PERFORM pg_temp.t_eq('G14','Suspension blocks company accounts', $q$SELECT status FROM users WHERE user_id=5$q$, 'suspended');
PERFORM pg_temp.t_pass('G15','Re-verify TechCo', $q$UPDATE companies SET verification_status='verified' WHERE company_id=1$q$);
PERFORM pg_temp.t_eq('G16','Re-verification restores company accounts', $q$SELECT status FROM users WHERE user_id=5$q$, 'active');

-- ===== H: audit log (SR19) =====
PERFORM pg_temp.t_eq('H01','Status change recorded with actor and old/new value', $q$SELECT (actor_user_id=5 AND details->>'new'='accepted' AND details->>'old'='shortlisted')::text FROM audit_logs WHERE resource_type='applications' AND resource_id=pg_temp.app(1,1)::text AND details->>'new'='accepted'$q$, 'true');
PERFORM pg_temp.t_fail('H02','Audit rows cannot be updated', $q$UPDATE audit_logs SET action='hacked'$q$, 'RULE_SR19_AUDIT_APPEND_ONLY');
PERFORM pg_temp.t_fail('H03','Audit rows cannot be deleted', $q$DELETE FROM audit_logs$q$, 'RULE_SR19_AUDIT_APPEND_ONLY');
PERFORM pg_temp.t_fail('H04','Audit table cannot be truncated', $q$TRUNCATE audit_logs$q$, 'RULE_SR19_AUDIT_APPEND_ONLY');
PERFORM log_event('export.csv','placements','dept-1');
PERFORM pg_temp.t_eq('H05','log_event writes a row with the current actor', $q$SELECT actor_role FROM audit_logs WHERE action='export.csv'$q$, 'admin');
PERFORM pg_temp.t_eq('H06','Denied events are stored', $q$SELECT count(*)::text FROM audit_logs WHERE result='denied'$q$, '1');
PERFORM pg_temp.t_fail('H07','Invalid audit result rejected', $q$INSERT INTO audit_logs(action,result) VALUES ('x','maybe')$q$, 'ck_audit_result');
PERFORM pg_temp.t_eq('H08','Company verification was audited', $q$SELECT count(*)::text FROM audit_logs WHERE resource_type='companies' AND resource_id='5' AND details->>'new'='verified'$q$, '1');

-- ===== I: tokens and notifications =====
PERFORM pg_temp.t_fail('I01','Token must expire after it is created', $q$INSERT INTO auth_tokens(user_id,purpose,token_hash,expires_at,created_at) VALUES (10,'refresh','h1',now()-interval '1 hour',now())$q$, 'ck_auth_tokens_expiry');
PERFORM pg_temp.t_pass('I02','Store a refresh token hash', $q$INSERT INTO auth_tokens(user_id,purpose,token_hash,expires_at) VALUES (10,'refresh','hash-A',now()+interval '7 days')$q$);
PERFORM pg_temp.t_fail('I03','Token hashes are unique', $q$INSERT INTO auth_tokens(user_id,purpose,token_hash,expires_at) VALUES (11,'refresh','hash-A',now()+interval '7 days')$q$, 'uq_auth_tokens_hash');
PERFORM pg_temp.t_fail('I04','Token purpose is restricted', $q$INSERT INTO auth_tokens(user_id,purpose,token_hash,expires_at) VALUES (10,'magic','hash-B',now()+interval '1 day')$q$, 'ck_auth_tokens_purpose');
PERFORM pg_temp.t_fail('I05','Invalid notification channel rejected', $q$INSERT INTO notifications(user_id,type,title,message,channel) VALUES (10,'system','t','m','sms')$q$, 'ck_notifications_channel');
PERFORM pg_temp.t_fail('I06','Invalid notification type rejected', $q$INSERT INTO notifications(user_id,type,title,message,channel) VALUES (10,'spam','t','m','email')$q$, 'ck_notifications_type');
PERFORM pg_temp.t_pass('I07','Mark a notification as read', $q$UPDATE notifications SET is_read=true WHERE notification_id=(SELECT min(notification_id) FROM notifications WHERE user_id=10 AND channel='in_app')$q$);
PERFORM pg_temp.t_eq('I08','read_at is filled when read', $q$SELECT (read_at IS NOT NULL)::text FROM notifications WHERE notification_id=(SELECT min(notification_id) FROM notifications WHERE user_id=10 AND channel='in_app')$q$, 'true');

-- ===== J: withdraw clean-up (kept last because it removes a placement) =====
PERFORM set_config('app.user_id','10',true);
PERFORM pg_temp.t_pass('J01','Student withdraws an accepted application whose placement is still pending', $q$UPDATE applications SET status='withdrawn' WHERE student_id=1 AND listing_id=1$q$);
PERFORM pg_temp.t_eq('J02','The pending placement was removed', $q$SELECT count(*)::text FROM placements WHERE application_id=pg_temp.app(1,1)$q$, '0');
END
$do$;

-- ===== P: database role privileges (only when 04_roles.sql was run) =====
DO $do$
BEGIN
IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'internlink_app') THEN
  EXECUTE 'SET LOCAL ROLE internlink_app';
  PERFORM pg_temp.t_fail('P01','App role cannot update audit rows', $q$UPDATE audit_logs SET action='x'$q$, 'permission denied');
  PERFORM pg_temp.t_fail('P02','App role cannot delete users', $q$DELETE FROM users$q$, 'permission denied');
  PERFORM pg_temp.t_fail('P03','App role cannot create or drop tables', $q$CREATE TABLE hack(id int)$q$, 'permission denied');
  PERFORM pg_temp.t_fail('P04','App role cannot truncate audit_logs', $q$TRUNCATE audit_logs$q$, 'permission denied');
  PERFORM pg_temp.t_pass('P05','App role can read and write normal data', $q$UPDATE student_profiles SET preferred_location='Kampala' WHERE student_id=1$q$);
  PERFORM pg_temp.t_pass('P06','App role can write audit rows', $q$INSERT INTO audit_logs(action) VALUES ('auth.login')$q$);
  PERFORM pg_temp.t_pass('P07','App role can run a status workflow (triggers work under its privileges)', $q$UPDATE applications SET status='shortlisted' WHERE student_id=3 AND listing_id=4$q$);
  EXECUTE 'RESET ROLE';
END IF;
IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'internlink_readonly') THEN
  EXECUTE 'SET LOCAL ROLE internlink_readonly';
  PERFORM pg_temp.t_fail('P08','Read-only role cannot read raw users (password hashes)', $q$SELECT * FROM users$q$, 'permission denied');
  PERFORM pg_temp.t_pass('P09','Read-only role can read the reporting views', $q$SELECT * FROM v_department_placement_stats$q$);
  PERFORM pg_temp.t_fail('P10','Read-only role cannot insert', $q$INSERT INTO skills(name) VALUES ('Hack')$q$, 'permission denied');
  EXECUTE 'RESET ROLE';
END IF;
END
$do$;

\set QUIET off
SELECT id, CASE WHEN passed THEN 'PASS' ELSE 'FAIL' END AS result, description, CASE WHEN passed THEN '' ELSE detail END AS problem
FROM test_results ORDER BY seq;
SELECT count(*) AS total_tests, count(*) FILTER (WHERE passed) AS passed, count(*) FILTER (WHERE NOT passed) AS failed FROM test_results;
DO $$ BEGIN IF EXISTS (SELECT 1 FROM test_results WHERE NOT passed) THEN RAISE EXCEPTION 'DATABASE TESTS FAILED'; END IF; END $$;
ROLLBACK;
