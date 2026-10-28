"""サンプル入力で時間割を組み、必須条件が守られているかを確かめる。"""
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from timetable.loader import load_settings, parse, read_xlsx  # noqa: E402
from timetable.solver import solve  # noqa: E402


@pytest.fixture(scope="module")
def solved(tmp_path_factory):
    xlsx = tmp_path_factory.mktemp("in") / "sample.xlsx"
    subprocess.run([sys.executable, "make_sample.py", str(xlsx)], cwd=ROOT, check=True)
    settings = load_settings(ROOT / "config.toml")
    settings.time_limit_seconds = 20
    problem, _ = parse(read_xlsx(xlsx), settings)
    return problem, solve(problem)


def test_solved(solved):
    _, result = solved
    assert result.status in ("最適解", "時間内の最良解")
    assert result.lessons


def test_people_only_in_available_slots(solved):
    problem, result = solved
    for ls in result.lessons:
        assert ls.slot in problem.teachers[ls.teacher_id].available
        for sid in ls.student_ids:
            assert ls.slot in problem.students[sid].available


def test_no_double_booking(solved):
    problem, result = solved
    t = Counter((ls.teacher_id, ls.slot) for ls in result.lessons)
    assert max(t.values()) == 1
    s = Counter((sid, ls.slot) for ls in result.lessons for sid in ls.student_ids)
    assert max(s.values()) == 1


def test_teacher_can_teach(solved):
    problem, result = solved
    for ls in result.lessons:
        t = problem.teachers[ls.teacher_id]
        assert set(ls.subject.split("・")) <= t.subjects
        assert t.can_group if ls.form == "集団" else t.can_individual


def test_capacity_and_rooms(solved):
    problem, result = solved
    s = problem.settings
    for ls in result.lessons:
        limit = s.group_capacity if ls.form == "集団" else s.max_students_per_teacher
        assert len(ls.student_ids) <= limit
    per_slot = Counter((ls.slot, ls.form) for ls in result.lessons)
    for (sl, form), n in per_slot.items():
        assert n <= (s.group_rooms if form == "集団" else s.individual_booths)


def test_times_and_teacher_limit(solved):
    problem, result = solved
    got = Counter()
    for ls in result.lessons:
        for sid in ls.student_ids:
            r = next(r for r in problem.requests
                     if r.student_id == sid and r.form == ls.form and r.subject == ls.student_subjects[sid])
            got[r.index] += 1
    for r in problem.requests:
        missing = next((u.missing for u in result.unassigned if u.request.index == r.index), 0)
        assert got[r.index] == r.times - missing
    load = Counter(ls.teacher_id for ls in result.lessons)
    for tid, n in load.items():
        mx = problem.teachers[tid].max_komas
        assert mx is None or n <= mx
