-- =====================================================================
-- InternLink Uganda - File 07: scale test (NFR09, NFR01)
-- Generates 10,000 students and 2,000 open listings in a COPY of the database and
-- times fn_recommendations. Run it on a scratch database, never on production:
--   createdb internlink_load -T internlink   (or load 01-05 into a new database)
--   psql -d internlink_load -f 07_load_test.sql
-- =====================================================================
\set ON_ERROR_STOP on
SELECT setseed(0.42);
INSERT INTO users (email, password_hash, full_name, role, status, email_verified_at)
SELECT 'load' || g || '@std.must.ac.ug', repeat('x', 60), 'Load Student ' || g, 'student', 'active', now()
FROM generate_series(1, 10000) g;
INSERT INTO student_profiles (user_id, university_id, department_id, programme_id, student_number, year_of_study,
                              preferred_location, willing_to_relocate, verified, verified_by)
SELECT u.user_id, 1, 1 + (u.user_id % 4), 1 + (u.user_id % 4), 'LOAD/' || u.user_id, 1 + (random() * 3)::int,
       (ARRAY['Kampala','Mbarara','Gulu','Mbale','Jinja'])[1 + (random() * 4)::int], random() < 0.5, true, 3
FROM users u WHERE u.email LIKE 'load%';
INSERT INTO student_skills (student_id, skill_id)
SELECT s.student_id, k.skill_id FROM student_profiles s
CROSS JOIN LATERAL (SELECT skill_id FROM skills ORDER BY random() LIMIT 4) k WHERE s.student_number LIKE 'LOAD/%';
INSERT INTO student_interests (student_id, interest_id)
SELECT s.student_id, k.interest_id FROM student_profiles s
CROSS JOIN LATERAL (SELECT interest_id FROM interests ORDER BY random() LIMIT 2) k WHERE s.student_number LIKE 'LOAD/%';

INSERT INTO listings (company_id, posted_by, title, description, sector, location, duration_weeks, slots, application_deadline, status)
SELECT 1, 5, 'Load listing ' || g, 'Generated internship listing number ' || g,
       (ARRAY['Software','Data','Finance','Telecommunications','Agriculture'])[1 + (random() * 4)::int],
       (ARRAY['Kampala','Mbarara','Gulu','Mbale','Jinja'])[1 + (random() * 4)::int], 8, 3, CURRENT_DATE + 30, 'open'
FROM generate_series(1, 2000) g;
INSERT INTO listing_skills (listing_id, skill_id)
SELECT l.listing_id, k.skill_id FROM listings l CROSS JOIN LATERAL (SELECT skill_id FROM skills ORDER BY random() LIMIT 3) k WHERE l.title LIKE 'Load listing%';
INSERT INTO listing_programmes (listing_id, programme_id)
SELECT l.listing_id, k.programme_id FROM listings l CROSS JOIN LATERAL (SELECT programme_id FROM programmes WHERE programme_id <= 4 ORDER BY random() LIMIT 2) k WHERE l.title LIKE 'Load listing%';
INSERT INTO listing_interests (listing_id, interest_id)
SELECT l.listing_id, k.interest_id FROM listings l CROSS JOIN LATERAL (SELECT interest_id FROM interests ORDER BY random() LIMIT 1) k WHERE l.title LIKE 'Load listing%';
ANALYZE;

SELECT (SELECT count(*) FROM student_profiles) AS students, (SELECT count(*) FROM listings WHERE status = 'open') AS open_listings;

-- Time 50 different students (single user, one query at a time)
CREATE TEMP TABLE timings (student_id BIGINT, ms NUMERIC);
DO $$
DECLARE r RECORD; t0 TIMESTAMPTZ; n INT;
BEGIN
  FOR r IN SELECT student_id FROM student_profiles WHERE student_number LIKE 'LOAD/%' ORDER BY student_id LIMIT 50 LOOP
    t0 := clock_timestamp();
    SELECT count(*) INTO n FROM fn_recommendations(r.student_id, 10);
    INSERT INTO timings VALUES (r.student_id, extract(epoch FROM clock_timestamp() - t0) * 1000);
  END LOOP;
END $$;
SELECT round(min(ms)) AS min_ms, round(percentile_cont(0.5) WITHIN GROUP (ORDER BY ms)::numeric) AS median_ms,
       round(percentile_cont(0.95) WITHIN GROUP (ORDER BY ms)::numeric) AS p95_ms, round(max(ms)) AS max_ms,
       (max(ms) < 5000) AS under_5_seconds FROM timings;
