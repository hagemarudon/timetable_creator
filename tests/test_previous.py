"""前回の時間割を読み込み、作り直しでなるべく同じコマに入ることを確かめる。"""
import io
import subprocess
import sys
from pathlib import Path

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from timetable.loader import load_settings, parse, read_xlsx  # noqa: E402
from timetable.output import View, to_xlsx  # noqa: E402
from timetable.previous import SHEET_PREVIOUS, kept, read_previous  # noqa: E402
from timetable.solver import solve  # noqa: E402


@pytest.fixture(scope="module")
def first(tmp_path_factory):
    xlsx = tmp_path_factory.mktemp("in") / "sample.xlsx"
    subprocess.run([sys.executable, "make_sample.py", str(xlsx)], cwd=ROOT, check=True)
    dfs = read_xlsx(xlsx)
    settings = load_settings(ROOT / "config.toml")
    settings.time_limit_seconds = 15
    problem, _ = parse(dfs, settings)
    return dfs, problem, solve(problem)


def test_output_has_hidden_previous_sheet(first):
    _, problem, result = first
    data = to_xlsx(problem, result, View(show_detail=False))  # IDを隠した表示でも記録はIDで残る
    wb = openpyxl.load_workbook(io.BytesIO(data))
    assert wb[SHEET_PREVIOUS].sheet_state == "hidden"
    prev = read_previous(data)
    assert len(prev) == sum(len(ls.student_ids) for ls in result.lessons)
    assert kept(prev, problem, result) == (len(prev), len(prev))


def test_rebuild_keeps_lessons_after_small_change(first):
    dfs, problem, result = first
    prev = read_previous(to_xlsx(problem, result))
    # 講師を1人、ある曜日に出られなくする（その分は動かざるを得ない）
    t_av = dfs["講師_空き時間"].copy()
    tid = result.lessons[0].teacher_id
    day = result.lessons[0].slot.day
    cols = [c for c in t_av.columns if c.startswith(day)]
    t_av.loc[t_av["講師ID"] == tid, cols] = ""
    changed = {**dfs, "講師_空き時間": t_av}

    settings = load_settings(ROOT / "config.toml")
    settings.time_limit_seconds = 15
    p2, _ = parse(changed, settings)
    with_prev = solve(p2, previous=prev)
    p2.settings.weights["keep_previous"] = 0
    without = solve(p2)
    same_with, still = kept(prev, p2, with_prev)
    same_without, _ = kept(prev, p2, without)
    assert same_with >= same_without
    assert same_with >= 0.8 * still
    # 前回どおりを優先しても、入る授業の数は減らさない
    missing = lambda r: sum(u.missing for u in r.unassigned)  # noqa: E731
    assert missing(with_prev) == missing(without)


def test_wrong_file_is_rejected(tmp_path):
    path = tmp_path / "x.xlsx"
    openpyxl.Workbook().save(path)
    with pytest.raises(ValueError, match=SHEET_PREVIOUS):
        read_previous(path.read_bytes())
