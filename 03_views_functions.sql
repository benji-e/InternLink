-- =====================================================================
-- InternLink Uganda - File 03: views and the matching function
-- =====================================================================
SET client_min_messages = warning;

-- Listings a student may currently apply for (matching eligibility filters, design section 3)
CREATE VIEW v_open_listings AS
SELECT l.listing_id, l.company_id, c.name AS company_name, l.title, l.description, l.sector, l.location, l.is_remote,
       l.duration_weeks, l.slots, l.slots_filled, (l.slots - l.slots_filled) AS slots_remaining,
       l.application_deadline, l.posted_at,
       COALESCE((SELECT array_agg(s.name ORDER BY s.name) FROM listing_skills ls JOIN skills s USING (skill_id)
                 WHERE ls.listing_id = l.listing_id AND ls.is_required), '{}') AS required_skills,
       COALESCE((SELECT array_agg(p.name ORDER BY p.name) FROM listing_programmes lp JOIN programmes p USING (programme_id)
                 WHERE lp.listing_id = l.listing_id), '{}') AS accepted_programmes,
       l.search_vector
FROM listings l JOIN companies c ON c.company_id = l.company_id
WHERE l.status = 'open' AND l.application_deadline >= CURRENT_DATE
  AND l.slots_filled < l.slots AND c.verification_status = 'verified';

-- Profile completeness used by the "complete your profile" prompt (design section 6)
CREATE VIEW v_student_profile_status AS
SELECT sp.student_id, sp.user_id,
       (SELECT count(*) FROM student_skills ss WHERE ss.student_id = sp.student_id)    AS skills_count,
       (SELECT count(*) FROM student_interests si WHERE si.student_id = sp.student_id) AS interests_count,
       (sp.cv_path IS NOT NULL) AS has_cv,
       sp.verified,
       ( (SELECT count(*) FROM student_skills ss WHERE ss.student_id = sp.student_id) > 0
         AND (SELECT count(*) FROM student_interests si WHERE si.student_id = sp.student_id) > 0
         AND sp.cv_path IS NOT NULL ) AS is_complete,
       ( 40 + 20 * ((SELECT count(*) FROM student_skills ss WHERE ss.student_id = sp.student_id) > 0)::int
            + 20 * ((SELECT count(*) FROM student_interests si WHERE si.student_id = sp.student_id) > 0)::int
            + 20 * (sp.cv_path IS NOT NULL)::int ) AS completeness_pct
FROM student_profiles sp;

-- Employer applicant table (SR09)
CREATE VIEW v_employer_applicants AS
SELECT a.application_id, l.company_id, l.listing_id, l.title AS listing_title,
       a.student_id, u.full_name AS applicant_name, pr.name AS programme, sp.year_of_study,
       un.name AS university, a.match_score, a.status, a.submitted_at, sp.cv_path
FROM applications a
JOIN listings l ON l.listing_id = a.listing_id
JOIN student_profiles sp ON sp.student_id = a.student_id
JOIN users u ON u.user_id = sp.user_id
JOIN programmes pr ON pr.programme_id = sp.programme_id
JOIN universities un ON un.university_id = sp.university_id;

-- Coordinator approval queue (SR13)
CREATE VIEW v_pending_placements AS
SELECT p.placement_id, p.created_at AS queued_at, sp.university_id, sp.department_id, sp.student_id,
       u.full_name AS student_name, sp.student_number, pr.name AS programme,
       c.name AS company_name, l.title AS listing_title, a.application_id
FROM placements p
JOIN applications a ON a.application_id = p.application_id
JOIN student_profiles sp ON sp.student_id = a.student_id
JOIN users u ON u.user_id = sp.user_id
JOIN programmes pr ON pr.programme_id = sp.programme_id
JOIN listings l ON l.listing_id = a.listing_id
JOIN companies c ON c.company_id = l.company_id
WHERE p.status = 'pending';

-- Per-student placement state used by the dashboard (SR16): placed / pending / unplaced
CREATE VIEW v_student_placement_state AS
SELECT sp.student_id, sp.university_id, sp.department_id, sp.programme_id,
       CASE WHEN EXISTS (SELECT 1 FROM placements p JOIN applications a USING (application_id)
                         WHERE a.student_id = sp.student_id AND p.status IN ('confirmed','completed')) THEN 'placed'
            WHEN EXISTS (SELECT 1 FROM placements p JOIN applications a USING (application_id)
                         WHERE a.student_id = sp.student_id AND p.status = 'pending') THEN 'pending'
            ELSE 'unplaced' END AS placement_state
FROM student_profiles sp
WHERE sp.verified;

-- Department dashboard (SR16): counts and percentages add up to 100%
CREATE VIEW v_department_placement_stats AS
SELECT d.university_id, d.department_id, d.name AS department_name,
       count(s.student_id)                                                 AS enrolled,
       count(*) FILTER (WHERE s.placement_state = 'placed')               AS placed,
       count(*) FILTER (WHERE s.placement_state = 'pending')              AS pending,
       count(*) FILTER (WHERE s.placement_state = 'unplaced')             AS unplaced,
       CASE WHEN count(s.student_id) = 0 THEN 0 ELSE round(100.0 * count(*) FILTER (WHERE s.placement_state = 'placed')   / count(s.student_id), 1) END AS placed_pct,
       CASE WHEN count(s.student_id) = 0 THEN 0 ELSE round(100.0 * count(*) FILTER (WHERE s.placement_state = 'pending')  / count(s.student_id), 1) END AS pending_pct,
       CASE WHEN count(s.student_id) = 0 THEN 0
            ELSE 100.0 - round(100.0 * count(*) FILTER (WHERE s.placement_state = 'placed')  / count(s.student_id), 1)
                       - round(100.0 * count(*) FILTER (WHERE s.placement_state = 'pending') / count(s.student_id), 1) END AS unplaced_pct
FROM departments d
LEFT JOIN v_student_placement_state s ON s.department_id = d.department_id
GROUP BY d.university_id, d.department_id, d.name;

-- Verified students with no placement (coordinator follow-up list)
CREATE VIEW v_unplaced_students AS
SELECT sp.student_id, sp.university_id, sp.department_id, u.full_name, sp.student_number, pr.name AS programme, sp.year_of_study
FROM v_student_placement_state s
JOIN student_profiles sp ON sp.student_id = s.student_id
JOIN users u ON u.user_id = sp.user_id
JOIN programmes pr ON pr.programme_id = sp.programme_id
WHERE s.placement_state = 'unplaced';

-- Export of placement and completion records (SR15)
CREATE VIEW v_placement_export AS
SELECT sp.university_id, sp.department_id, d.name AS department, sp.student_number, u.full_name AS student_name,
       pr.name AS programme, c.name AS company, l.title AS listing_title,
       p.start_date, p.end_date, p.status AS placement_status, p.completion_note, p.placement_id
FROM placements p
JOIN applications a ON a.application_id = p.application_id
JOIN student_profiles sp ON sp.student_id = a.student_id
JOIN departments d ON d.department_id = sp.department_id
JOIN users u ON u.user_id = sp.user_id
JOIN programmes pr ON pr.programme_id = sp.programme_id
JOIN listings l ON l.listing_id = a.listing_id
JOIN companies c ON c.company_id = l.company_id
WHERE p.status IN ('confirmed','completed');

-- Single administrator queue for company and university registrations (SR18)
CREATE VIEW v_admin_pending_registrations AS
SELECT 'company'::text AS org_type, c.company_id AS org_id, c.name, c.contact_email AS contact, c.created_at AS submitted_at
FROM companies c WHERE c.verification_status = 'pending'
UNION ALL
SELECT 'university', u.university_id, u.name, 'domain: ' || u.email_domain, u.created_at
FROM universities u WHERE u.status = 'pending';

-- Placement timeline for the student (SR14): check-ins in date order
CREATE VIEW v_placement_timeline AS
SELECT ci.placement_id, a.student_id, ci.checkin_date, ci.notes, cu.full_name AS coordinator_name
FROM check_ins ci
JOIN placements p ON p.placement_id = ci.placement_id
JOIN applications a ON a.application_id = p.application_id
JOIN users cu ON cu.user_id = ci.coordinator_id;

-- ---------------------------------------------------------------------
-- Matching function: reference implementation of the Matching Algorithm Design
--   score = round(100 * (wP*P + wS*S + wI*I + wL*L)); L missing -> weights rescaled
--   eligibility filters, minimum score, ranking and tie-breaks as in the design
-- ---------------------------------------------------------------------
CREATE FUNCTION fn_recommendations(
    p_student_id BIGINT, p_limit INT DEFAULT 10, p_min_score INT DEFAULT 20,
    w_programme NUMERIC DEFAULT 0.35, w_skills NUMERIC DEFAULT 0.40,
    w_interests NUMERIC DEFAULT 0.15, w_location NUMERIC DEFAULT 0.10)
RETURNS TABLE (rank INT, listing_id BIGINT, score INT, p NUMERIC, s NUMERIC, i NUMERIC, l NUMERIC, applied BOOLEAN)
LANGUAGE sql STABLE AS $$
WITH st AS (
    SELECT sp.student_id, sp.programme_id, pr.programme_group, sp.preferred_location, sp.willing_to_relocate,
           (SELECT count(*) FROM student_interests si WHERE si.student_id = sp.student_id) AS n_int
    FROM student_profiles sp JOIN programmes pr ON pr.programme_id = sp.programme_id
    WHERE sp.student_id = p_student_id
), cand AS (                                   -- eligibility filters (design section 3)
    SELECT l.listing_id, l.posted_at, l.sector, l.location, l.is_remote
    FROM listings l JOIN companies c ON c.company_id = l.company_id
    WHERE l.status = 'open' AND l.application_deadline >= CURRENT_DATE
      AND l.slots_filled < l.slots AND c.verification_status = 'verified'
), pc AS (                                     -- P: programme relevance
    SELECT lp.listing_id,
           max(CASE WHEN lp.programme_id = st.programme_id THEN 1.0
                    WHEN p2.programme_group = st.programme_group THEN 0.5 ELSE 0.0 END) AS cp
    FROM listing_programmes lp
    JOIN cand ON cand.listing_id = lp.listing_id
    JOIN programmes p2 ON p2.programme_id = lp.programme_id
    CROSS JOIN st GROUP BY lp.listing_id
), sc AS (                                     -- S: required skills the student has
    SELECT ls.listing_id, count(*)::numeric AS req, count(ss.skill_id)::numeric AS got
    FROM listing_skills ls
    JOIN cand ON cand.listing_id = ls.listing_id
    CROSS JOIN st
    LEFT JOIN student_skills ss ON ss.skill_id = ls.skill_id AND ss.student_id = st.student_id
    WHERE ls.is_required GROUP BY ls.listing_id
), ic AS (                                     -- I: student interests found in sector or tags
    SELECT cand.listing_id, count(DISTINCT si.interest_id)::numeric AS matched
    FROM cand CROSS JOIN st
    JOIN student_interests si ON si.student_id = st.student_id
    JOIN interests it ON it.interest_id = si.interest_id
    WHERE lower(it.name) = lower(cand.sector)
       OR EXISTS (SELECT 1 FROM listing_interests lx WHERE lx.listing_id = cand.listing_id AND lx.interest_id = si.interest_id)
    GROUP BY cand.listing_id
), comp AS (
    SELECT cand.listing_id, cand.posted_at,
           COALESCE(pc.cp, 0.5) AS cp,
           CASE WHEN sc.req IS NULL THEN 0.5 ELSE sc.got / sc.req END AS cs,
           CASE WHEN st.n_int = 0 THEN 0.0 ELSE LEAST(1.0, COALESCE(ic.matched, 0) / st.n_int) END AS ci,
           CASE WHEN st.preferred_location IS NULL THEN NULL
                WHEN cand.is_remote OR lower(cand.location) = lower(st.preferred_location) THEN 1.0
                WHEN st.willing_to_relocate THEN 0.5 ELSE 0.0 END AS cl
    FROM cand CROSS JOIN st
    LEFT JOIN pc ON pc.listing_id = cand.listing_id
    LEFT JOIN sc ON sc.listing_id = cand.listing_id
    LEFT JOIN ic ON ic.listing_id = cand.listing_id
), scored AS (
    SELECT comp.*, round(100 * (w_programme * cp + w_skills * cs + w_interests * ci + COALESCE(w_location * cl, 0))
               / (w_programme + w_skills + w_interests + CASE WHEN cl IS NULL THEN 0 ELSE w_location END))::int AS sc_total
    FROM comp
)
SELECT (row_number() OVER (ORDER BY sc_total DESC, cs DESC, posted_at DESC, scored.listing_id ASC))::int,
       scored.listing_id, sc_total, cp, cs, ci, cl,
       EXISTS (SELECT 1 FROM applications a WHERE a.student_id = p_student_id AND a.listing_id = scored.listing_id)
FROM scored
WHERE sc_total >= p_min_score
ORDER BY 1
LIMIT p_limit
$$;
COMMENT ON FUNCTION fn_recommendations IS 'Reference implementation of the matching score (Matching Algorithm Design). Returns the ranked top N open listings for a student with the four component scores.';
