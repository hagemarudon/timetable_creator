"""画面から入力した条件を扱う（コマ割の生成と設定ファイルへの保存）。"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from .model import Koma, Settings

ALL_DAYS = ["月", "火", "水", "木", "金", "土", "日"]


def _to_min(hhmm: str) -> int:
    t = datetime.strptime(hhmm.strip(), "%H:%M")
    return t.hour * 60 + t.minute


def _to_hhmm(minutes: int) -> str:
    return (datetime(2000, 1, 1) + timedelta(minutes=minutes)).strftime("%H:%M")


def make_komas(count: int, start: str, lesson_minutes: int, break_minutes: int) -> list[Koma]:
    """開始時刻・授業の長さ・休憩から、等間隔のコマ割を作る。"""
    t = _to_min(start)
    komas = []
    for no in range(1, count + 1):
        komas.append(Koma(no, _to_hhmm(t), _to_hhmm(t + lesson_minutes)))
        t += lesson_minutes + break_minutes
    return komas


def describe_komas(komas: list[Koma]) -> tuple[int, str, int, int]:
    """コマ割から（コマ数, 開始時刻, 授業の長さ, 休憩）を読み取る。入力欄の初期値に使う。"""
    first = komas[0]
    lesson = _to_min(first.end) - _to_min(first.start)
    brk = _to_min(komas[1].start) - _to_min(first.end) if len(komas) > 1 else 10
    return len(komas), first.start, lesson, max(brk, 0)


def check_komas(komas: list[Koma]) -> list[str]:
    """時刻の書式と、コマ同士の重なりを確かめる。"""
    errors = []
    prev_end = None
    for k in komas:
        try:
            s, e = _to_min(k.start), _to_min(k.end)
        except ValueError:
            errors.append(f"{k.no}限の時刻は「16:00」の形で入力してください。")
            continue
        if e <= s:
            errors.append(f"{k.no}限の終了が開始より前になっています。")
        if prev_end is not None and s < prev_end:
            errors.append(f"{k.no}限が前のコマと重なっています。")
        prev_end = e
    return errors


def save_settings(settings: Settings, path: str | Path) -> None:
    """条件を config.toml の形で保存する（次回からの初期値になる）。"""
    days = ", ".join(f'"{d}"' for d in settings.days)
    lines = [
        "# 塾の時間割作成の設定（画面の「この条件を既定にする」で保存）",
        "",
        "# 開講曜日",
        f"days = [{days}]",
        "",
        "# コマ割（番号, 開始, 終了）",
    ]
    for k in settings.komas:
        lines += ["[[komas]]", f"no = {k.no}", f'start = "{k.start}"', f'end = "{k.end}"', ""]
    w = settings.weights
    lines += [
        "[rooms]",
        "# 個別授業のブース数（同じコマで同時に個別授業ができる講師の数）",
        f"individual_booths = {settings.individual_booths}",
        "# 集団授業の教室数",
        f"group_rooms = {settings.group_rooms}",
        "",
        "[individual]",
        "# 講師1人が同じコマで同時に見られる生徒の最大数（1 = 1対1, 2 = 1対2）",
        f"max_students_per_teacher = {settings.max_students_per_teacher}",
        "# 同じコマで講師が見る生徒同士の科目が違ってもよいか",
        f"allow_mixed_subjects = {'true' if settings.allow_mixed_subjects else 'false'}",
        "",
        "[group]",
        "# 集団授業1クラスの定員",
        f"capacity = {settings.group_capacity}",
        "",
        "[solver]",
        "# 計算時間の上限（秒）",
        f"time_limit_seconds = {int(settings.time_limit_seconds)}",
        "",
        "# 優先条件の重み（大きいほど重視）",
        "[weights]",
        f"assigned_lesson = {w['assigned_lesson']}      # 授業を1回入れられたら加点",
        f"preferred_teacher = {w['preferred_teacher']}      # 希望講師に当たったら加点",
        f"same_teacher = {w['same_teacher']}          # 個別で講師が2人目以上になったら減点（毎回同じ講師にしたい）",
        f"same_day_repeat = {w['same_day_repeat']}        # 同じ科目が同じ日に2回入ったら減点",
        f"teacher_work_day = {w['teacher_work_day']}       # 講師の出勤日1日ごとに減点（出勤日をまとめたい）",
        f"student_gap = {w['student_gap']}            # 生徒の1日の授業の間に空きコマができたら減点",
        "",
    ]
    Path(path).write_text("\n".join(lines), encoding="utf-8")
