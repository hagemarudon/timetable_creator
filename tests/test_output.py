"""書き出し用の表示のテスト。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from timetable.model import Problem, Student  # noqa: E402
from timetable.output import student_names  # noqa: E402


def test_same_name_students_get_id():
    students = {
        "S001": Student("S001", "木村悠真", "高1"),
        "S002": Student("S002", "木村悠真", "高1"),
        "S003": Student("S003", "佐藤蓮", "高2"),
    }
    problem = Problem(settings=None, students=students, teachers={}, requests=[])
    assert student_names(problem, ["S001", "S002"]) == "木村悠真（S001）、木村悠真（S002）"
    assert student_names(problem, ["S003"]) == "佐藤蓮"
