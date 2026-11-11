"""画面から入力した条件を扱う（コマ割の生成と設定ファイルへの保存）。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from .model import WEEKDAYS, Koma, Season, Settings

ALL_DAYS = WEEKDAYS
# 講習の期間の長さの目安（これより長いと計算に時間がかかる）
SEASON_MAX_DAYS = 45


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


def check_season(season: Season) -> list[str]:
    """講習の期間と休みを確かめる。"""
    if season.end < season.start:
        return ["講習の最終日が初日より前になっています。"]
    if not season.dates():
        return ["講習の期間に授業をする日がありません（休みの曜日・休みの日を見直してください）。"]
    if len(season.all_dates()) > SEASON_MAX_DAYS:
        return [f"講習の期間が{len(season.all_dates())}日あります。{SEASON_MAX_DAYS}日までにしてください"
                "（長い期間は計算が終わらなくなります。前半・後半に分けて作ってください）。"]
    return []


def _quoted(values) -> str:
    return ", ".join(f'"{v}"' for v in values)


def _koma_lines(table: str, komas: list[Koma]) -> list[str]:
    lines = []
    for k in komas:
        lines += [f"[[{table}]]", f"no = {k.no}", f'start = "{k.start}"', f'end = "{k.end}"', ""]
    return lines


def save_settings(settings: Settings, path: str | Path) -> None:
    """条件を config.toml と同じ形で保存する（config.local.toml に保存し、次回からの初期値になる）。

    通常授業と講習の条件は両方とも保存し、今の時間割の種類（mode）も次回の初期値にする。
    """
    season = settings.season
    lines = [
        "# 塾の時間割作成の設定（画面の「この条件を既定にする」で保存）",
        "",
        "# 時間割の種類（\"通常授業\" = 毎週同じ曜日の時間割、\"講習\" = 講習の日付ごとの時間割）",
        f'mode = "{settings.mode}"',
        "",
        "# 開講曜日（通常授業）",
        f"days = [{_quoted(settings.weekdays)}]",
        "",
        "# コマ割（通常授業。番号, 開始, 終了）",
        *_koma_lines("komas", settings.weekly_komas),
        "# 講習の期間とコマ割",
        "[season]",
        f"name = {json.dumps(season.name, ensure_ascii=False)}",
        f"start = {season.start.isoformat()}",
        f"end = {season.end.isoformat()}",
        f"closed_weekdays = [{_quoted(season.closed_weekdays)}]",
        f"closed_dates = [{', '.join(d.isoformat() for d in season.closed_dates)}]",
        "",
        *_koma_lines("season.komas", season.komas),
    ]
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
        f"keep_previous = {w.get('keep_previous', 0)}         # 前回の時間割と同じコマに入ったら加点（同じ講師ならさらに半分）",
        "",
    ]
    Path(path).write_text("\n".join(lines), encoding="utf-8")
