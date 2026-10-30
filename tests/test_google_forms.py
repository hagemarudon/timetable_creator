"""google_forms/forms.gs の、フォームの回答を入力シートにまとめる処理のテスト（node で動かす）。"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from timetable import google_sheets as gs
from timetable.loader import load_settings, parse
from timetable.solver import solve

ROOT = Path(__file__).parent.parent
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node がない")

# 回答の形は Apps Script の ItemResponse.getResponse() と同じ（グリッドは行ごとの配列、未回答の行は null）
SCRIPT = r"""
const g = require(process.argv[1]);
const Q = g.Q, cfg = g.CONFIG;
const student = (time, name, grade, lessons, grid, note) => ({time, answers: {
  [Q.name]: name, [Q.grade]: grade, [Q.lessons]: lessons, [Q.studentAvail]: grid, [Q.note]: note}});
const teacher = (time, name, subjects, forms, max, grid) => ({time, answers: {
  [Q.name]: name, [Q.teacherSubjects]: subjects, [Q.teacherForms]: forms, [Q.teacherMax]: max, [Q.teacherAvail]: grid}});
const all = [cfg.days, cfg.days, cfg.days, cfg.days];
const students = [
  student(3, '鈴木 凛', '高3', ['受けない', null, null, null, '集団 週1回'], all, ''),
  student(1, '佐藤蓮', '高2', ['個別 週2回', '受けない', null, null, null], [['月', '火'], null, ['月'], null], '月曜は遅め'),
  student(5, '鈴木　凛', '高3', ['受けない', '個別 週1回', null, null, '集団 週1回'], all, ''),  // 答え直し
  student(6, '空欄', '中1', [null, null, null, null, null], null, ''),
];
const prevReq = [['生徒ID', '氏名', '学年', '科目', '形式', '週の回数', '希望講師（任意）', '固定（任意）'],
                 ['S007', '佐藤蓮', '高2', '英語', '個別', '2', 'T009', '月1']];
const teachers = [
  teacher(1, '渡辺先生', ['英語', '国語'], ['集団', '個別'], '10', all),
  teacher(2, '山本先生', ['数学'], ['個別'], '', all),
];
console.log(JSON.stringify({
  koma: g.komaSheet(cfg),
  s: g.buildStudentSheets(students, cfg, prevReq),
  t: g.buildTeacherSheets(teachers, cfg, []),
  choices: g.lessonChoices_(cfg),
}));
"""


@pytest.fixture(scope="module")
def out():
    res = subprocess.run(["node", "-e", SCRIPT, str(ROOT / "google_forms" / "forms.gs")],
                         capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def test_choices(out):
    assert out["choices"] == ["受けない", "集団 週1回", "集団 週2回", "集団 週3回", "個別 週1回", "個別 週2回", "個別 週3回"]


def test_student_rows(out):
    req = out["s"]["requests"]
    # 最初に回答した順。同じ氏名（空白違い）は最後の回答を使い、前回の生徒IDと手で足した列を引き継ぐ
    assert req[1] == ["S007", "佐藤蓮", "高2", "英語", "個別", "2", "T009", "月1", "月曜は遅め"]
    assert [r[:6] for r in req[2:]] == [["S008", "鈴木　凛", "高3", "数学", "個別", "1"],
                                        ["S008", "鈴木　凛", "高3", "国語", "集団", "1"]]
    avail = out["s"]["avail"]
    header = avail[0]
    sato = dict(zip(header, avail[1]))
    assert {k for k, v in sato.items() if v == "○"} == {"月1", "火1", "月3"}
    assert len(avail) == 4  # 科目なしの生徒も空き時間には入れる
    assert any("空欄" in w and "科目" in w for w in out["s"]["warnings"])


def test_parsed_by_app(out):
    """まとめた表をアプリの読み込み（Googleスプレッドシートと同じ経路）で読めて、時間割が組める。"""
    sheets = {"コマ設定": out["koma"], "生徒_受講希望": out["s"]["requests"], "生徒_空き時間": out["s"]["avail"],
              "講師_担当可能科目": out["t"]["teachers"], "講師_空き時間": out["t"]["avail"]}
    dfs = {k: gs.values_to_frame([[str(c) for c in r] for r in v]) for k, v in sheets.items()}
    problem, errors = parse(dfs, load_settings(ROOT / "config.toml"))
    assert problem is not None
    assert sorted(problem.subjects) == sorted(["英語", "数学", "物理", "化学", "国語"])
    assert problem.teachers["T001"].subjects == {"英語", "国語"}
    assert problem.teachers["T001"].max_komas == 10
    assert problem.teachers["T002"].can_group is False
    # 前回の希望講師 T009 はもういないので注意が出る
    assert any("T009" in e for e in errors)
    result = solve(problem, time_limit=10)
    assert not result.unassigned
