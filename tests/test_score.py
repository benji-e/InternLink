"""Section 5 as a whole: score(), the Section 6 worked example, and SR20 properties."""
from hypothesis import given, settings
from hypothesis import strategies as st

from matching_engine.models import Opportunity, StudentProfile
from matching_engine.scoring import score

FAMILIES = {"BSc SE": "computing", "BSc CS": "computing", "BSc IT": "computing"}

# ---- Section 6 worked example ------------------------------------------------

STUDENT = StudentProfile(
    program="BSc SE",
    skills=["python", "sql", "react", "git"],
    interests=["fintech", "data science"],
)
DATA_ANALYST = Opportunity(
    sector="fintech",
    target_programs=["BSc CS", "BSc SE", "BSc Statistics"],
    required_skills=["python", "sql", "excel"],
    tags=["data science", "banking"],
)
NETWORK_SUPPORT = Opportunity(
    sector="telecom",
    target_programs=["BSc IT"],
    required_skills=["networking", "linux", "git"],
    tags=["infrastructure"],
)
FRONTEND_DEV = Opportunity(
    sector="software",
    target_programs=["BSc SE", "BSc CS"],
    required_skills=["react", "javascript", "css"],
    tags=["web development"],
)


def test_worked_example_scores_81_36_50():
    assert score(STUDENT, DATA_ANALYST, families=FAMILIES).score == 81
    assert score(STUDENT, NETWORK_SUPPORT, families=FAMILIES).score == 36
    assert score(STUDENT, FRONTEND_DEV, families=FAMILIES).score == 50


def test_result_explains_matched_and_missing_skills():
    result = score(STUDENT, DATA_ANALYST, families=FAMILIES)
    assert result.matched_skills == ["python", "sql"]
    assert result.missing_skills == ["excel"]


def test_result_includes_rounded_breakdown():
    result = score(STUDENT, DATA_ANALYST, families=FAMILIES)
    assert result.breakdown == {"skills": 0.667, "program": 1.0, "interests": 0.8}


def test_free_text_values_are_cleaned_before_comparing():
    student = StudentProfile(program="BSc SE", skills=[" JS ", "CSS"], interests=[])
    result = score(student, FRONTEND_DEV, families=FAMILIES)
    assert result.matched_skills == ["css", "javascript"]


def test_rounds_half_up_not_to_even():
    # 0.45 x 0.5 = 0.225 -> 22.5 -> 23. Python's round() would give 22.
    student = StudentProfile(program="BSc Nursing", skills=["python"], interests=[])
    opp = Opportunity(sector="health", target_programs=["BSc IT"], required_skills=[], tags=[])
    assert score(student, opp, families=FAMILIES).score == 23


# ---- SR20 properties (Section 10) --------------------------------------------

VOCAB = ["python", "sql", "excel", "react", "git", "linux", "css", "fintech", "banking", "health"]
PROGRAMS = ["BSc SE", "BSc CS", "BSc IT", "BSc Nursing"]
words = st.lists(st.sampled_from(VOCAB), max_size=6)

students = st.builds(
    StudentProfile, program=st.sampled_from(PROGRAMS), skills=words, interests=words
)
opportunities = st.builds(
    Opportunity,
    sector=st.sampled_from(VOCAB),
    target_programs=st.lists(st.sampled_from(PROGRAMS), max_size=3),
    required_skills=words,
    tags=words,
)


@settings(deadline=None)  # speed is tested in 4.6.3, not here
@given(students, opportunities)
def test_score_is_a_whole_number_from_0_to_100(student, opp):
    result = score(student, opp, families=FAMILIES)
    assert isinstance(result.score, int)
    assert 0 <= result.score <= 100


@settings(deadline=None)  # speed is tested in 4.6.3, not here
@given(students, opportunities)
def test_same_input_always_gives_same_output(student, opp):
    first = score(student, opp, families=FAMILIES)
    for _ in range(20):
        assert score(student, opp, families=FAMILIES) == first


@settings(deadline=None)  # speed is tested in 4.6.3, not here
@given(students, opportunities, st.sampled_from(VOCAB))
def test_adding_a_skill_never_lowers_the_score(student, opp, extra):
    richer = StudentProfile(student.program, [*student.skills, extra], student.interests)
    assert score(richer, opp, families=FAMILIES).score >= score(student, opp, families=FAMILIES).score


@settings(deadline=None)  # speed is tested in 4.6.3, not here
@given(students, opportunities, st.sampled_from(VOCAB))
def test_adding_an_interest_never_lowers_the_score(student, opp, extra):
    richer = StudentProfile(student.program, student.skills, [*student.interests, extra])
    assert score(richer, opp, families=FAMILIES).score >= score(student, opp, families=FAMILIES).score
