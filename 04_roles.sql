-- =====================================================================
-- InternLink Uganda - File 04: database roles and privileges (Security design, least privilege)
-- Requires a role that may CREATE ROLE. On a managed free tier you may not be allowed
-- to; then create the app user in the provider's console and run only the GRANT part.
-- Passwords are NOT stored in this file; pass them as psql variables:
--   psql -v app_password='...' -v readonly_password='...' -f 04_roles.sql
-- =====================================================================
SELECT format('CREATE ROLE internlink_app LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'internlink_app') \gexec
SELECT format('CREATE ROLE internlink_readonly LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE', :'readonly_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'internlink_readonly') \gexec

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM internlink_app, internlink_readonly;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO internlink_app, internlink_readonly;

-- Application: data changes only, no DDL
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO internlink_app;
REVOKE UPDATE, DELETE, TRUNCATE ON audit_logs FROM internlink_app;       -- audit log is append-only (SR19)
REVOKE DELETE ON users, companies, universities, listings, applications, student_profiles FROM internlink_app; -- suspend, never delete
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO internlink_app;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO internlink_app;

-- Read-only reporting user: views only (no raw password hashes or tokens)
GRANT SELECT ON v_open_listings, v_student_profile_status, v_employer_applicants, v_pending_placements,
                v_student_placement_state, v_department_placement_stats, v_unplaced_students,
                v_placement_export, v_admin_pending_registrations, v_placement_timeline TO internlink_readonly;
GRANT EXECUTE ON FUNCTION fn_recommendations(BIGINT, INT, INT, NUMERIC, NUMERIC, NUMERIC, NUMERIC) TO internlink_readonly;

ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE ON TABLES TO internlink_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO internlink_app;
