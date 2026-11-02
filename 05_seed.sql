-- =====================================================================
-- InternLink Uganda - File 05: seed / demo data
-- DEMO ONLY. Every demo account uses the password  Demo@12345
-- Never load this file into a production database.
-- Ids are fixed so the team can refer to them (see README).
-- =====================================================================
SET client_min_messages = warning;
BEGIN;

-- Administrator (created by seeding, never through a public form)
SET LOCAL app.allow_role_change = 'on';
INSERT INTO users (user_id, email, password_hash, full_name, role, status, company_id, university_id, department_id, email_verified_at)
OVERRIDING SYSTEM VALUE VALUES
  (1,'admin@internlink.ug','$2b$12$TqC8uBYj3Pg/KFd0Y93lduRX7sui47VjcuKRaH81Gkg4K1MnKcGtC','System Administrator','admin','active',NULL,NULL,NULL,now());
SET LOCAL app.allow_role_change = 'off';
SET LOCAL app.user_id = '1';

-- Universities (3 = pending, to demonstrate the admin queue)
INSERT INTO universities (university_id, name, location, email_domain, status) OVERRIDING SYSTEM VALUE VALUES
  (1, 'Mbarara University of Science and Technology', 'Mbarara', 'must.ac.ug', 'verified'),
  (2, 'Makerere University', 'Kampala', 'mak.ac.ug', 'verified'),
  (3, 'Kampala International University', 'Kampala', 'kiu.ac.ug', 'pending');

INSERT INTO departments (department_id, university_id, name) OVERRIDING SYSTEM VALUE VALUES
  (1, 1, 'Software Engineering'), (2, 1, 'Computer Science'), (3, 1, 'Information Technology'),
  (4, 1, 'Accounting and Finance'), (5, 2, 'Computer Science');

INSERT INTO programmes (programme_id, department_id, name, programme_group) OVERRIDING SYSTEM VALUE VALUES
  (1, 1, 'BSc Software Engineering', 'computing'),
  (2, 2, 'BSc Computer Science', 'computing'),
  (3, 3, 'BSc Information Technology', 'computing'),
  (4, 4, 'Bachelor of Accounting and Finance', 'business'),
  (5, 5, 'BSc Computer Science', 'computing');

INSERT INTO skills (skill_id, name) OVERRIDING SYSTEM VALUE VALUES
  (1,'Python'),(2,'SQL'),(3,'Flask'),(4,'React'),(5,'JavaScript'),(6,'Java'),(7,'HTML/CSS'),(8,'Excel'),
  (9,'Statistics'),(10,'Data Analysis'),(11,'Networking'),(12,'Linux'),(13,'Communication'),(14,'Teamwork'),
  (15,'Accounting'),(16,'Tally'),(17,'Git'),(18,'Machine Learning'),(19,'Cybersecurity'),(20,'Project Management'),
  (21,'Power BI'),(22,'Research');
INSERT INTO skill_synonyms (synonym, skill_id) VALUES
  ('python3',1),('python 3',1),('py',1),('postgres',2),('postgresql',2),('structured query language',2),('mysql',2),
  ('reactjs',4),('react.js',4),('js',5),('ecmascript',5),('html',7),('css',7),('ms excel',8),('microsoft excel',8),
  ('stats',9),('data analytics',10),('computer networks',11),('ubuntu',12),('github',17),('ml',18),('infosec',19);
INSERT INTO interests (interest_id, name) OVERRIDING SYSTEM VALUE VALUES
  (1,'Software'),(2,'Data'),(3,'Networking'),(4,'Cybersecurity'),(5,'Finance'),(6,'Agriculture'),
  (7,'Healthcare'),(8,'Education'),(9,'Design'),(10,'Research'),(11,'Telecommunications'),(12,'Management');

-- Companies (5 = pending)
INSERT INTO companies (company_id, name, sector, location, description, contact_email, website, verification_status) OVERRIDING SYSTEM VALUE VALUES
  (1,'TechCo Ltd','Software','Kampala','Software house building web and mobile products.','hr@techco.example','https://techco.example','verified'),
  (2,'NGO Data Hub','Data','Mbarara','Non-profit data and research centre.','recruit@datahub.example','https://datahub.example','verified'),
  (3,'Telecom Uganda','Telecommunications','Kampala','National telecom operator.','interns@telecom.example','https://telecom.example','verified'),
  (4,'Finance One Ltd','Finance','Kampala','Accounting and advisory firm.','hr@financeone.example',NULL,'verified'),
  (5,'GreenFarm Agro','Agriculture','Mbale','Agribusiness company (awaiting verification).','hr@greenfarm.example',NULL,'pending');

-- Other users (coordinators, employer representatives, students)
INSERT INTO users (user_id, email, password_hash, full_name, role, status, company_id, university_id, department_id, email_verified_at)
OVERRIDING SYSTEM VALUE VALUES
  (2,'coord.se@must.ac.ug','$2b$12$9OJ6rpfJeerTmOAkWqOmC.2/44SgJoIBUy3Nm04uqjFAAzJ6vbGeW','Dr. Tumusiime Alice','coordinator','active',NULL,1,1,now()),
  (3,'internships@must.ac.ug','$2b$12$Tq28Ri27RRixjUXlus6epeUyaZudmALhsmXZtzB4oX1i2LWiDHEFW','Kyomuhendo Peter','coordinator','active',NULL,1,NULL,now()),
  (4,'coord.cs@mak.ac.ug','$2b$12$A1O3x7azWrbQqTH9hMqKWuwjhSOnOhLdwHF3HbDXWLEv2.AFmGH4i','Dr. Nansubuga Rose','coordinator','active',NULL,2,5,now()),
  (5,'hr@techco.example','$2b$12$.6GJ.WekA.MbBi5n.cR7s.7sA/BbiL.0LVqB1PIkWwHcatl.V1XqO','Ssemakula John','employer','active',1,NULL,NULL,now()),
  (6,'recruit@datahub.example','$2b$12$pAwa.JrDxfkXQscDDapacuzbCe6YR4WqQ97N2SM/S9GItFYLKWb9a','Akello Janet','employer','active',2,NULL,NULL,now()),
  (7,'interns@telecom.example','$2b$12$CLnDfiiW0myxA1QQqpRjhODJdozEIUegfM/fXoWNP5Ooi6j1jRY2S','Mwesigwa Robert','employer','active',3,NULL,NULL,now()),
  (8,'hr@financeone.example','$2b$12$K.yo/fE2g2XOLPHyGQbOvuBdU5RZJVo/VhytylBmbEGWbDGYoN8FK','Namara Patricia','employer','active',4,NULL,NULL,now()),
  (9,'hr@greenfarm.example','$2b$12$/2NbzelHLMmJYRs7ZT3URelN8VCTzG308492zFZ0GSjgrAEy5o1Uq','Opio Samuel','employer','active',5,NULL,NULL,now()),
  (10,'nakato.aisha@std.must.ac.ug','$2b$12$Xhzu4JXac2lZ9YgJqnNKIOPcSWnTcG0zRKsL5Ppyu3ymYqc02vn9G','Nakato Aisha','student','active',NULL,NULL,NULL,now()),
  (11,'okello.james@std.must.ac.ug','$2b$12$RjDnEl7wgSY5IpbBTqEod.H7vReZYLke095V3XIlxWyaG2bwchoI6','Okello James','student','active',NULL,NULL,NULL,now()),
  (12,'mugisha.brian@std.must.ac.ug','$2b$12$0sX45gJ3nEWcH2sST8dykegm67V5kU4rXC4.OZkh3e4Q5NQGFIWta','Mugisha Brian','student','active',NULL,NULL,NULL,now()),
  (13,'atim.sarah@std.must.ac.ug','$2b$12$..Ao3gdQLA5wNQG9iyKpN.pXk1lgg/lx1NWn2D8dQwD1pz4ArZzvu','Atim Sarah','student','active',NULL,NULL,NULL,now()),
  (14,'byaruhanga.peter@std.must.ac.ug','$2b$12$YDXUivVqDelg1/xIwvdAc.Bx0HXadD7g.kizDQXDzNjyziCW6jC3a','Byaruhanga Peter','student','active',NULL,NULL,NULL,now()),
  (15,'namutebi.grace@students.mak.ac.ug','$2b$12$0zksXoHYWbRNRh94CJF8JevDQtpdwx6byki0DiKgtfvoqsavfwEOS','Namutebi Grace','student','active',NULL,NULL,NULL,now()),
  (16,'kato.david@std.must.ac.ug','$2b$12$8hjYsRsiiH3AnfFgWJLDKOAtj7Gx3ofTrJ1ByLpEdQjxUHvPM49Ta','Kato David','student','pending',NULL,NULL,NULL,NULL),
  (17,'achieng.mercy@std.must.ac.ug','$2b$12$hZkWjYHotBB15w/m2G2WOOEXpuu9if/mylxRGq2br9jN7ItCuwYKK','Achieng Mercy','student','active',NULL,NULL,NULL,now());

-- Student profiles
INSERT INTO student_profiles (student_id, user_id, university_id, department_id, programme_id, student_number, year_of_study,
                              preferred_location, willing_to_relocate, cv_path, cv_size_bytes, verified, verified_by)
OVERRIDING SYSTEM VALUE VALUES
  (1,10,1,1,1,'2024/BSE/201/PS',3,'Kampala',false,'cv/2024-BSE-201.pdf',182000,true,3),
  (2,11,1,2,2,'2024/BCS/110/PS',3,'Mbarara',true,'cv/2024-BCS-110.pdf',150000,true,3),
  (3,12,1,3,3,'2024/BIT/075/PS',2,'Kampala',true,'cv/2024-BIT-075.pdf',140000,true,3),
  (4,13,1,4,4,'2024/BAF/032/PS',3,'Kampala',false,'cv/2024-BAF-032.pdf',160000,true,3),
  (5,14,1,1,1,'2024/BSE/245/PS',3,'Kampala',true,'cv/2024-BSE-245.pdf',175000,true,3),
  (6,15,2,5,5,'U1234/2024',3,'Kampala',false,'cv/U1234-2024.pdf',190000,true,4),
  (7,16,1,1,1,'2024/BSE/260/PS',3,NULL,false,NULL,NULL,false,NULL),
  (8,17,1,2,2,'2024/BCS/118/PS',3,NULL,false,NULL,NULL,true,3);

INSERT INTO student_skills (student_id, skill_id)
SELECT v.sid, s.skill_id FROM (VALUES
  (1,'Python'),(1,'SQL'),(1,'Flask'),
  (2,'Python'),(2,'Data Analysis'),(2,'Statistics'),(2,'SQL'),
  (3,'Networking'),(3,'Linux'),(3,'Communication'),
  (4,'Accounting'),(4,'Excel'),(4,'Tally'),
  (5,'JavaScript'),(5,'React'),(5,'HTML/CSS'),(5,'Git'),(5,'Python'),
  (6,'Java'),(6,'SQL'),(6,'Python'),
  (7,'Python'),(8,'Python')) AS v(sid, sk) JOIN skills s ON s.name = v.sk;
INSERT INTO student_interests (student_id, interest_id)
SELECT v.sid, i.interest_id FROM (VALUES
  (1,'Software'),(1,'Data'),(2,'Data'),(2,'Research'),(3,'Networking'),(3,'Telecommunications'),
  (4,'Finance'),(5,'Software'),(5,'Design'),(6,'Software'),(8,'Data')) AS v(sid, it) JOIN interests i ON i.name = v.it;

-- Listings (posted by the company's own representative)
INSERT INTO listings (listing_id, company_id, posted_by, title, description, sector, location, is_remote, duration_weeks, slots, application_deadline, status) OVERRIDING SYSTEM VALUE VALUES
  (1,1,5,'Software Developer Intern','Build and test features for our web platform using Python, SQL and React.','Software','Kampala',false,12,3,CURRENT_DATE+30,'open'),
  (2,2,6,'Data Analyst Intern','Clean, analyse and report on programme data for field projects.','Data','Mbarara',false,8,2,CURRENT_DATE+25,'open'),
  (3,4,8,'Accounting Intern','Support bookkeeping, reconciliations and month-end reporting.','Finance','Kampala',false,12,2,CURRENT_DATE+20,'open'),
  (4,3,7,'Network Support Intern','Assist the network operations team with monitoring and troubleshooting.','Telecommunications','Kampala',false,12,2,CURRENT_DATE+28,'open'),
  (5,1,5,'Frontend Developer Intern','Create responsive user interfaces with JavaScript and React.','Software','Kampala',false,10,2,CURRENT_DATE+35,'open'),
  (6,2,6,'Data Entry and Reporting Intern','Prepare survey data and weekly reports (draft).','Data','Mbarara',false,6,1,CURRENT_DATE+40,'draft'),
  (7,5,9,'Agronomy Data Intern','Record and analyse farm data (cannot open until the company is verified).','Agriculture','Mbale',false,8,1,CURRENT_DATE+40,'draft'),
  (8,1,5,'Software QA Intern','Write and run test cases for new releases.','Software','Kampala',false,10,1,CURRENT_DATE+10,'open'),
  (9,2,6,'Remote Research Assistant','Support literature reviews and statistical analysis remotely.','Data','Mbarara',true,8,2,CURRENT_DATE+30,'open');
INSERT INTO listing_programmes (listing_id, programme_id) VALUES
  (1,1),(2,2),(3,4),(4,3),(4,2),(5,1),(5,3),(6,2),(6,3),(7,2),(8,1),(8,3),(9,2),(9,5);
INSERT INTO listing_skills (listing_id, skill_id, is_required)
SELECT v.lid, s.skill_id, v.req FROM (VALUES
  (1,'Python',true),(1,'SQL',true),(1,'React',true),(1,'Git',false),
  (2,'SQL',true),(2,'Excel',true),(2,'Statistics',true),
  (3,'Excel',true),(3,'Tally',true),
  (4,'Networking',true),(4,'Linux',true),
  (5,'JavaScript',true),(5,'React',true),(5,'HTML/CSS',true),
  (6,'Excel',true),(6,'Communication',true),
  (7,'Data Analysis',true),(7,'Excel',true),
  (8,'Python',true),(8,'Git',true),
  (9,'Python',true),(9,'Data Analysis',true),(9,'Statistics',true)) AS v(lid, sk, req) JOIN skills s ON s.name = v.sk;
INSERT INTO listing_interests (listing_id, interest_id)
SELECT v.lid, i.interest_id FROM (VALUES (4,'Networking'),(4,'Telecommunications'),(5,'Design'),(9,'Research')) AS v(lid, it) JOIN interests i ON i.name = v.it;

-- Applications (match scores come from fn_recommendations so they are consistent with the algorithm)
INSERT INTO applications (student_id, listing_id, match_score, cover_note)
SELECT v.sid, v.lid, (SELECT r.score FROM fn_recommendations(v.sid, 1000, 0) r WHERE r.listing_id = v.lid), v.note
FROM (VALUES
  (1,1,'I enjoy building web systems and would like to learn from your team.'),
  (1,5,NULL),(2,2,NULL),(3,4,NULL),(4,3,NULL),(5,5,NULL),(6,1,NULL),(5,8,NULL)) AS v(sid, lid, note);

-- TechCo representative works the applicants
SET LOCAL app.user_id = '5';
UPDATE applications SET status = 'under_review' WHERE student_id = 1 AND listing_id = 1;
UPDATE applications SET status = 'shortlisted'  WHERE student_id = 1 AND listing_id = 1;
UPDATE applications SET status = 'accepted'     WHERE student_id = 1 AND listing_id = 1;   -- placement 1 (pending)
UPDATE applications SET status = 'rejected'     WHERE student_id = 1 AND listing_id = 5;
UPDATE applications SET status = 'under_review' WHERE student_id = 6 AND listing_id = 1;
UPDATE applications SET status = 'shortlisted'  WHERE student_id = 5 AND listing_id = 8;
UPDATE applications SET status = 'accepted'     WHERE student_id = 5 AND listing_id = 8;   -- placement 4
SET LOCAL app.user_id = '6';
UPDATE applications SET status = 'shortlisted' WHERE student_id = 2 AND listing_id = 2;
UPDATE applications SET status = 'accepted'    WHERE student_id = 2 AND listing_id = 2;    -- placement 2
SET LOCAL app.user_id = '7';
UPDATE applications SET status = 'under_review' WHERE student_id = 3 AND listing_id = 4;
SET LOCAL app.user_id = '8';
UPDATE applications SET status = 'shortlisted' WHERE student_id = 4 AND listing_id = 3;
UPDATE applications SET status = 'accepted'    WHERE student_id = 4 AND listing_id = 3;    -- placement 3

-- Messages between TechCo and Nakato (application 1 is accepted)
SET LOCAL app.user_id = '5';
INSERT INTO messages (application_id, sender_id, recipient_id, body)
SELECT application_id, 5, 10, 'Congratulations Aisha. Please confirm you can start on the agreed date.' FROM applications WHERE student_id = 1 AND listing_id = 1;
SET LOCAL app.user_id = '10';
INSERT INTO messages (application_id, sender_id, recipient_id, body, is_read)
SELECT application_id, 10, 5, 'Thank you. I can start on the agreed date.', false FROM applications WHERE student_id = 1 AND listing_id = 1;

-- University decisions (coordinator 3 = whole MUST internship office)
SET LOCAL app.user_id = '3';
UPDATE placements SET status = 'confirmed', start_date = CURRENT_DATE - 20, end_date = CURRENT_DATE + 50
 WHERE application_id = (SELECT application_id FROM applications WHERE student_id = 2 AND listing_id = 2);
UPDATE placements SET status = 'rejected', rejection_reason = 'Placement dates overlap with the student''s examination period.'
 WHERE application_id = (SELECT application_id FROM applications WHERE student_id = 4 AND listing_id = 3);
UPDATE placements SET status = 'confirmed', start_date = CURRENT_DATE - 150, end_date = CURRENT_DATE - 80
 WHERE application_id = (SELECT application_id FROM applications WHERE student_id = 5 AND listing_id = 8);
INSERT INTO check_ins (placement_id, coordinator_id, notes, checkin_date)
SELECT p.placement_id, 3, 'Supervisor confirms good attendance and steady progress.', CURRENT_DATE - 7
FROM placements p JOIN applications a USING (application_id) WHERE a.student_id = 2 AND a.listing_id = 2;
SET LOCAL app.user_id = '2';
INSERT INTO check_ins (placement_id, coordinator_id, notes, checkin_date)
SELECT p.placement_id, 2, 'Mid-term visit: student is contributing to the test suite.', CURRENT_DATE - 110
FROM placements p JOIN applications a USING (application_id) WHERE a.student_id = 5 AND a.listing_id = 8;

-- TechCo completes the finished placement, then the listing is closed and back-dated
SET LOCAL app.user_id = '5';
UPDATE placements SET status = 'completed', completion_note = 'Completed all assigned test cycles. Reliable and well organised.'
 WHERE application_id = (SELECT application_id FROM applications WHERE student_id = 5 AND listing_id = 8);
UPDATE listings SET status = 'closed', application_deadline = CURRENT_DATE - 90, posted_at = now() - interval '160 days' WHERE listing_id = 8;

-- Sample security events written by the API (SR19)
SET LOCAL app.user_id = '10';
DO $$ BEGIN
  PERFORM log_event('auth.login', 'users', '10', 'success', '{"method":"password"}', '196.43.10.21');
  PERFORM log_event('access.denied', 'endpoint', '/api/admin/registrations', 'denied', '{"role":"student"}', '196.43.10.21');
END $$;
SET LOCAL app.user_id = '1';
DO $$ BEGIN PERFORM log_event('auth.login', 'users', '1', 'success', '{"method":"password"}', '196.43.10.5'); END $$;

-- Keep identity sequences ahead of the fixed ids above
DO $$ BEGIN
  PERFORM setval(pg_get_serial_sequence('universities','university_id'), (SELECT max(university_id) FROM universities));
  PERFORM setval(pg_get_serial_sequence('departments','department_id'), (SELECT max(department_id) FROM departments));
  PERFORM setval(pg_get_serial_sequence('programmes','programme_id'), (SELECT max(programme_id) FROM programmes));
  PERFORM setval(pg_get_serial_sequence('skills','skill_id'), (SELECT max(skill_id) FROM skills));
  PERFORM setval(pg_get_serial_sequence('interests','interest_id'), (SELECT max(interest_id) FROM interests));
  PERFORM setval(pg_get_serial_sequence('companies','company_id'), (SELECT max(company_id) FROM companies));
  PERFORM setval(pg_get_serial_sequence('users','user_id'), (SELECT max(user_id) FROM users));
  PERFORM setval(pg_get_serial_sequence('student_profiles','student_id'), (SELECT max(student_id) FROM student_profiles));
  PERFORM setval(pg_get_serial_sequence('listings','listing_id'), (SELECT max(listing_id) FROM listings));
END $$;
COMMIT;
