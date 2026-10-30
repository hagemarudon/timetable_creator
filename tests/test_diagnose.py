"""必須条件を1つずつ外して、入らない理由を見つけられることを確かめる。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from timetable.loader import load_settings  # noqa: E402
from timetable.model import Problem, Request, Slot, Student, Teacher  # noqa: E402
from timetable.solver import diagnose, solve  # noqa: E402


def _problem(n_students: int, booths: int) -> Problem:
    """講師2人・生徒 n 人が、全員 月1 しか空いていない個別授業の問題。"""
    s = load_settings(ROOT / "config.toml")
    s.days, s.individual_booths, s.max_students_per_teacher = ["月"], booths, 1
    s.time_limit_seconds = 5
    sl = Slot("月", 1)
    teachers = {f"T{i}": Teacher(f"T{i}", f"先生{i}", {"数学"}, False, True, None, {sl}) for i in range(2)}
    students = {f"S{i}": Student(f"S{i}", f"生徒{i}", "高1", {sl}) for i in range(n_students)}
    requests = [Request(i, sid, "数学", "個別", 1, None) for i, sid in enumerate(students)]
    return Problem(s, students, teachers, requests, ["数学"])


def test_booth_shortage_is_found():
    problem = _problem(2, booths=1)
    base = solve(problem)
    assert sum(u.missing for u in base.unassigned) == 1
    found = diagnose(problem, base, time_limit=5)
    assert found[0].key == "booths" and found[0].gained == 1
    assert len(found[0].newly_placed) == 1
    assert all(d.gained == 0 for d in found[1:])


def test_conflicting_fixed_lessons_are_found():
    problem = _problem(3, booths=2)
    for r in problem.requests:
        r.fixed = [Slot("月", 1)]  # 講師2人に3人を固定するので解けない
    base = solve(problem)
    assert base.status == "解けませんでした" and not base.lessons
    assert "必須条件" in base.unassigned[0].reason
    found = diagnose(problem, base, time_limit=5)
    assert found[0].key == "fixed" and found[0].gained == 2
