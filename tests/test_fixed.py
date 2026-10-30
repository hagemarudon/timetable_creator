"""「固定」列で指定した授業が、そのコマに入ることを確かめる。"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from timetable.loader import SHEET_STUDENT_REQ, load_settings, parse, read_xlsx  # noqa: E402
from timetable.solver import solve  # noqa: E402


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    xlsx = tmp_path_factory.mktemp("in") / "sample.xlsx"
    subprocess.run([sys.executable, "make_sample.py", str(xlsx)], cwd=ROOT, check=True)
    return read_xlsx(xlsx)


def _settings():
    s = load_settings(ROOT / "config.toml")
    s.time_limit_seconds = 15
    return s


def _common_slot(problem, r, teacher_id=None):
    """生徒と担当できる講師がどちらも空いているコマを1つ探す。"""
    st = problem.students[r.student_id]
    for t in problem.teachers.values():
        ok = t.can_individual if r.form == "個別" else t.can_group
        if ok and r.subject in t.subjects and (teacher_id is None or t.id == teacher_id):
            common = sorted(st.available & t.available, key=problem.settings.slots.index)
            if common:
                return common[-1], t.id
    return None, None


def _fix(dfs, row: int, text: str):
    dfs = {k: v.copy() for k, v in dfs.items()}
    df = dfs[SHEET_STUDENT_REQ]
    df["固定"] = ""
    df.loc[df.index[row], "固定"] = text
    return dfs


def test_fixed_individual_lesson_is_placed(sample):
    problem, _ = parse(sample, _settings())
    r = next(r for r in problem.requests if r.form == "個別" and _common_slot(problem, r)[0])
    sl, tid = _common_slot(problem, r)
    problem, notes = parse(_fix(sample, r.index, sl.label), _settings())
    req = problem.requests[r.index]
    assert req.fixed == [sl], notes
    result = solve(problem)
    assert any(ls.slot == sl and r.student_id in ls.student_ids and ls.student_subjects[r.student_id] == r.subject
               for ls in result.lessons)


def test_fixed_group_lesson_is_placed(sample):
    problem, _ = parse(sample, _settings())
    r = next(r for r in problem.requests if r.form == "集団" and _common_slot(problem, r)[0])
    sl, _ = _common_slot(problem, r)
    problem, notes = parse(_fix(sample, r.index, sl.label), _settings())
    assert problem.requests[r.index].fixed == [sl], notes
    result = solve(problem)
    assert any(ls.slot == sl and ls.form == "集団" and r.student_id in ls.student_ids for ls in result.lessons)


def test_bad_fixed_slots_are_ignored_with_note(sample):
    problem, _ = parse(sample, _settings())
    r = problem.requests[0]
    off = next(sl for sl in problem.settings.slots if sl not in problem.students[r.student_id].available)
    problem, notes = parse(_fix(sample, 0, f"月9、{off.label}"), _settings())
    assert problem.requests[0].fixed == []
    assert any("月9" in n for n in notes)
    assert any(off.label in n and "空き時間" in n for n in notes)
