"""講習期（冬期・夏期・春期講習など、日付ごとの時間割）のテスト。"""
import io
import json
import shutil
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from timetable import google_sheets as gs  # noqa: E402
from timetable.loader import _read_availability, load_settings, parse, parse_slot, read_xlsx  # noqa: E402
from timetable.model import MODE_SEASON, MODE_WEEKLY, Koma, Season, Slot, date_label  # noqa: E402
from timetable.output import SHEET_SCHEDULE, schedule_pages, to_xlsx  # noqa: E402
from timetable.settings_io import check_season, save_settings  # noqa: E402
from timetable.solver import solve  # noqa: E402
from timetable.template import make_template  # noqa: E402


def season_settings(**kw):
    s = load_settings(ROOT / "config.toml")
    s.mode = MODE_SEASON
    s.season = Season(**{"name": "冬期講習", "start": date(2026, 12, 24), "end": date(2027, 1, 7),
                         "komas": [Koma(1, "13:00", "14:30"), Koma(2, "14:30", "16:00"), Koma(3, "16:00", "17:30")],
                         "closed_weekdays": ["日"], "closed_dates": [date(2026, 12, 31), date(2027, 1, 1)], **kw})
    s.time_limit_seconds = 10
    return s


def test_season_days():
    s = season_settings()
    assert date_label(date(2026, 12, 24)) == "12/24(木)"
    # 日曜（12/27, 1/3）と休みの日（12/31, 1/1）を除く
    assert s.days == ["12/24(木)", "12/25(金)", "12/26(土)", "12/28(月)", "12/29(火)", "12/30(水)",
                      "1/2(土)", "1/4(月)", "1/5(火)", "1/6(水)", "1/7(木)"]
    assert s.slots[0].label == "12/24(木)1"
    assert s.count_column == "回数" and s.limit_column == "上限コマ"
    # 通常期の曜日とコマ割は別に持っていて、切り替えると戻る
    s.mode = MODE_WEEKLY
    assert s.days == ["月", "火", "水", "木", "金", "土"] and s.komas[0] == Koma(1, "16:00", "17:30")
    assert s.count_column == "週の回数"


def test_check_season():
    assert check_season(season_settings().season) == []
    assert check_season(season_settings(end=date(2026, 12, 1)).season)
    assert check_season(season_settings(closed_weekdays=["月", "火", "水", "木", "金", "土", "日"]).season)
    assert check_season(season_settings(end=date(2027, 3, 31)).season)  # 長すぎる


def test_save_and_load_keeps_both_modes(tmp_path):
    s = season_settings()
    s.weekdays = ["月", "水"]
    path = tmp_path / "config.local.toml"
    save_settings(s, path)
    loaded = load_settings(ROOT / "config.toml", overlay=path)
    assert loaded == s
    assert loaded.mode == MODE_SEASON and loaded.weekdays == ["月", "水"]


def test_default_config_has_season():
    s = load_settings(ROOT / "config.toml")
    assert s.mode == MODE_WEEKLY
    assert s.season.start < s.season.end and s.season.komas


def test_parse_slot():
    s = season_settings()
    for text in ("12/24(木)1", "12/24 1", "12/24-1", "12/24（木）1限", "12/24_1"):
        assert parse_slot(text, s) == Slot("12/24(木)", 1), text
    assert parse_slot("12/27(日)1", s) is None  # 休み
    assert parse_slot("12/24(木)9", s) is None  # コマが無い
    assert parse_slot("月1", s) is None


def test_availability_by_date():
    s = season_settings()
    cols = ["生徒ID", "12/24(木)1", "12/24(木)2", "12/25(金)13:00", "12/25(金)13:30", "12/25(金)14:00",
            "12/27(日)1", "12/24(木)9"]
    df = pd.DataFrame([["S1", "○", "", "○", "○", "○", "○", "○"]], columns=cols)
    errors: list[str] = []
    avail = _read_availability(df, "生徒ID", s, "生徒_空き時間", errors)
    assert avail["S1"] == {Slot("12/24(木)", 1), Slot("12/25(金)", 1)}
    assert any("12/27(日)" in e and "無視" in e for e in errors)
    assert any("12/24(木)9" in e for e in errors)


def test_mode_mismatch_is_reported():
    """通常期の入力を講習期で読んだら（その逆も）、時間割の種類を切り替えるよう伝えて止める。"""
    sample = read_xlsx(ROOT / "sample" / "サンプル入力.xlsx")
    problem, errors = parse(sample, season_settings())
    assert problem is None and any("時間割の種類" in e and "通常期" in e for e in errors)
    season_sample = read_xlsx(ROOT / "sample" / "サンプル入力_講習期.xlsx")
    problem, errors = parse(season_sample, load_settings(ROOT / "config.toml"))
    assert problem is None and any("時間割の種類" in e and "講習期" in e for e in errors)


def _season_problem():
    s = season_settings()
    days = s.days
    reqs = [
        {"生徒ID": "S1", "氏名": "山田", "学年": "中3", "科目": "数学", "形式": "個別", "回数": "4", "固定（任意）": "1/4(月)2"},
        {"生徒ID": "S1", "氏名": "山田", "学年": "中3", "科目": "英語", "形式": "集団", "回数": "3"},
        {"生徒ID": "S2", "氏名": "佐藤", "学年": "中3", "科目": "英語", "形式": "集団", "回数": "3"},
        {"生徒ID": "S2", "氏名": "佐藤", "学年": "中3", "科目": "数学", "形式": "個別", "回数": "6"},
    ]
    every = {f"{d}{k.no}": "○" for d in days for k in s.komas}
    st_av = [{"生徒ID": "S1", "氏名": "山田", **every},
             {"生徒ID": "S2", "氏名": "佐藤", **{c: v for c, v in every.items() if not c.startswith("12/")}}]
    teachers = [{"講師ID": "T1", "氏名": "鈴木", "英語": "○", "数学": "", "集団可": "○", "個別可": "", "上限コマ": "5"},
                {"講師ID": "T2", "氏名": "高橋", "英語": "", "数学": "○", "集団可": "", "個別可": "○", "上限コマ": ""}]
    t_av = [{"講師ID": "T1", "氏名": "鈴木", **every}, {"講師ID": "T2", "氏名": "高橋", **every}]
    dfs = {"生徒_受講希望": pd.DataFrame(reqs), "生徒_空き時間": pd.DataFrame(st_av),
           "講師_担当可能科目": pd.DataFrame(teachers), "講師_空き時間": pd.DataFrame(t_av)}
    dfs = {k: v.fillna("").astype(str) for k, v in dfs.items()}
    return parse(dfs, s)


@pytest.fixture(scope="module")
def solved():
    problem, errors = _season_problem()
    assert problem is not None, errors
    return problem, solve(problem)


def test_season_solve(solved):
    problem, result = solved
    assert result.status in ("最適解", "時間内の最良解")
    assert not result.unassigned
    # 回数は講習期間全体の回数
    got = Counter((sid, ls.student_subjects[sid]) for ls in result.lessons for sid in ls.student_ids)
    assert got == {("S1", "数学"): 4, ("S1", "英語"): 3, ("S2", "英語"): 3, ("S2", "数学"): 6}
    # 空き時間（S2 は1月だけ）と固定（S1 の数学は 1/4(月)2）
    for ls in result.lessons:
        for sid in ls.student_ids:
            assert ls.slot in problem.students[sid].available
    assert all(ls.slot.day.startswith("1/") for ls in result.lessons if "S2" in ls.student_ids)
    assert any(ls.slot == Slot("1/4(月)", 2) and ls.student_subjects.get("S1") == "数学" for ls in result.lessons)
    # 講師の上限は講習期間全体のコマ数
    assert problem.teachers["T1"].max_komas == 5
    assert sum(ls.teacher_id == "T1" for ls in result.lessons) <= 5


def test_season_schedule_sheets_per_week(solved):
    problem, result = solved
    pages = schedule_pages(problem)
    assert [name for name, _ in pages] == [f"{SHEET_SCHEDULE} 12月24日〜", f"{SHEET_SCHEDULE} 12月28日〜",
                                           f"{SHEET_SCHEDULE} 1月4日〜"]
    assert sum(len(d) for _, d in pages) == len(problem.settings.days)
    wb = openpyxl.load_workbook(io.BytesIO(to_xlsx(problem, result)))
    assert wb.sheetnames[:3] == [name for name, _ in pages]
    ws = wb[pages[2][0]]
    assert [c.value for c in ws[1] if c.value] == ["1/4(月)", "1/5(火)", "1/6(水)", "1/7(木)"]
    lessons = sum(1 for ls in result.lessons if ls.slot.day in pages[2][1])
    merged = [m for m in ws.merged_cells.ranges if m.min_row >= 3 and m.min_col == m.max_col]
    assert len(merged) == lessons


def test_season_template_round_trip():
    s = season_settings()
    wb = openpyxl.load_workbook(io.BytesIO(make_template(s)))
    header = [c.value for c in wb["生徒_空き時間"][1]]
    assert header[2:4] == ["12/24(木)1", "12/24(木)2"] and len(header) == 2 + len(s.slots)
    assert "回数" in [c.value for c in wb["生徒_受講希望"][1]]
    assert [c.value for c in wb["講師_担当可能科目"][1]][-1] == "上限コマ"
    wb["生徒_受講希望"].append(["S1", "山田", "高1", "数学", "個別", 5, "", "12/25(金)1"])
    wb["生徒_空き時間"].append(["S1", "山田", "○", "", "", "○"])
    wb["講師_担当可能科目"].append(["T1", "佐藤", "", "○", "", "", "", "", "○", 20])
    wb["講師_空き時間"].append(["T1", "佐藤", "○", "", "", "○"])
    buf = io.BytesIO()
    wb.save(buf)
    problem, notes = parse(read_xlsx(buf.getvalue()), s)
    assert problem is not None, notes
    assert problem.students["S1"].available == {Slot("12/24(木)", 1), Slot("12/25(金)", 1)}
    assert problem.requests[0].times == 5 and problem.requests[0].fixed == [Slot("12/25(金)", 1)]
    assert problem.teachers["T1"].max_komas == 20


def test_season_sample_is_readable():
    s = load_settings(ROOT / "config.toml")
    s.mode = MODE_SEASON
    problem, notes = parse(read_xlsx(ROOT / "sample" / "サンプル入力_講習期.xlsx"), s)
    assert problem is not None and not notes, notes
    assert all(p.available for p in problem.students.values())


@pytest.mark.skipif(shutil.which("node") is None, reason="node がない")
def test_google_forms_season():
    """Googleフォーム（講習期）の回答をまとめた表を、アプリの講習期で読める。"""
    script = r"""
const g = require(process.argv[1]);
const cfg = Object.assign({}, g.CONFIG, {kind: '講習期'});
const Q = g.q_(cfg), days = g.days_(cfg), rows = g.cellLabels_(cfg);
const s = {time: 1, answers: {[Q.name]: '佐藤蓮', [Q.grade]: '中3', [Q.lessons]: ['個別 6回', '集団 4回'],
           [Q.studentAvail]: rows.map(() => days)}};
const t = {time: 1, answers: {[Q.name]: '渡辺先生', [Q.teacherSubjects]: ['英語', '数学'], [Q.teacherForms]: ['集団', '個別'],
           [Q.teacherMax]: '30', [Q.teacherAvail]: rows.map(() => days)}};
console.log(JSON.stringify({days, choices: g.lessonChoices_(cfg), koma: g.komaSheet(cfg),
  s: g.buildStudentSheets([s], cfg, []), t: g.buildTeacherSheets([t], cfg, [])}));
"""
    res = subprocess.run(["node", "-e", script, str(ROOT / "google_forms" / "forms.gs")],
                         capture_output=True, text=True, check=True)
    out = json.loads(res.stdout)
    s = load_settings(ROOT / "config.toml")
    s.mode = MODE_SEASON
    assert out["days"] == s.days  # フォームの初期設定とアプリの初期設定が同じ期間
    assert "個別 10回" in out["choices"] and not any("週" in c for c in out["choices"])
    assert out["s"]["requests"][0][5] == "回数" and out["t"]["teachers"][0][-1] == "上限コマ"
    sheets = {"コマ設定": out["koma"], "生徒_受講希望": out["s"]["requests"], "生徒_空き時間": out["s"]["avail"],
              "講師_担当可能科目": out["t"]["teachers"], "講師_空き時間": out["t"]["avail"]}
    dfs = {k: gs.values_to_frame([[str(c) for c in r] for r in v]) for k, v in sheets.items()}
    problem, errors = parse(dfs, s)
    assert problem is not None, errors
    assert problem.students["S001"].available == set(s.slots)
    assert [(r.subject, r.form, r.times) for r in problem.requests] == [("英語", "個別", 6), ("数学", "集団", 4)]
    assert problem.teachers["T001"].max_komas == 30
