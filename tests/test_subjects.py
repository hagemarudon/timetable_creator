"""科目を「講師_担当可能科目」シートの列見出しから読むことを確かめる。"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from timetable.loader import load_settings, parse  # noqa: E402
from timetable.output import subject_colors  # noqa: E402
from timetable.solver import solve  # noqa: E402


def _sheets(teacher_rows, req_rows):
    return {
        "生徒_受講希望": pd.DataFrame(req_rows, dtype=str),
        "生徒_空き時間": pd.DataFrame([{"生徒ID": "S1", "氏名": "生徒A", "月1": "○", "月2": "○"},
                                   {"生徒ID": "S2", "氏名": "生徒B", "月1": "○", "月2": "○"}], dtype=str),
        "講師_担当可能科目": pd.DataFrame(teacher_rows, dtype=str),
        "講師_空き時間": pd.DataFrame([{"講師ID": "T1", "氏名": "先生A", "月1": "○", "月2": "○"}], dtype=str),
    }


def _settings():
    s = load_settings(ROOT / "config.toml")
    s.time_limit_seconds = 5
    return s


def test_custom_subjects_from_header():
    teachers = [{"講師ID": "T1", "氏名": "先生A", "社会": "○", "英検対策": "○", "理科": "",
                 "集団可": "", "個別可": "○", "備考": "火曜は遅め"}]
    reqs = [{"生徒ID": "S1", "氏名": "生徒A", "学年": "中2", "科目": "社会", "形式": "個別", "週の回数": "1"},
            {"生徒ID": "S2", "氏名": "生徒B", "学年": "中3", "科目": "英検対策", "形式": "個別", "週の回数": "1"}]
    problem, errors = parse(_sheets(teachers, reqs), _settings(), use_koma_sheet=False)
    assert errors == []
    assert problem.subjects == ["社会", "英検対策", "理科"]
    assert problem.teachers["T1"].subjects == {"社会", "英検対策"}
    result = solve(problem)
    assert sorted(ls.student_subjects[sid] for ls in result.lessons for sid in ls.student_ids) == ["社会", "英検対策"]


def test_unknown_subject_is_reported():
    teachers = [{"講師ID": "T1", "氏名": "先生A", "数学": "○", "集団可": "", "個別可": "○"}]
    reqs = [{"生徒ID": "S1", "氏名": "生徒A", "学年": "中2", "科目": "英語", "形式": "個別", "週の回数": "1"}]
    _, errors = parse(_sheets(teachers, reqs), _settings(), use_koma_sheet=False)
    assert any("科目「英語」" in e and "数学" in e for e in errors)


def test_no_subject_column():
    teachers = [{"講師ID": "T1", "氏名": "先生A", "集団可": "", "個別可": "○"}]
    reqs = [{"生徒ID": "S1", "氏名": "生徒A", "学年": "中2", "科目": "英語", "形式": "個別", "週の回数": "1"}]
    problem, errors = parse(_sheets(teachers, reqs), _settings(), use_koma_sheet=False)
    assert problem is None
    assert any("科目の列がありません" in e for e in errors)


def test_subject_colors_are_distinct_and_stable():
    subjects = [f"科目{i}" for i in range(20)]
    colors = subject_colors(subjects)
    assert len(set(colors.values())) == 20
    assert colors == subject_colors(subjects)
