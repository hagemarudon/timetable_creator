"""前回の時間割を読み込み、作り直しでなるべく同じコマに入れるための情報にする。

このアプリで書き出した Excel には、隠しシート「再作成用」に1生徒×1授業ずつの記録を入れておく。
次の作り直しではこのシートを読み、同じ生徒・科目を同じコマ（できれば同じ講師）に入れると加点する。
"""
from __future__ import annotations

import io
from dataclasses import dataclass

import pandas as pd

from .model import Problem, Result, Slot

SHEET_PREVIOUS = "再作成用"
COLUMNS = ["生徒ID", "科目", "形式", "曜日", "コマ", "講師ID"]


@dataclass(frozen=True)
class PrevLesson:
    student_id: str
    subject: str
    form: str
    slot: Slot
    teacher_id: str


def previous_sheet(result: Result) -> pd.DataFrame:
    rows = [{"生徒ID": sid, "科目": ls.student_subjects.get(sid, ls.subject), "形式": ls.form,
             "曜日": ls.slot.day, "コマ": ls.slot.koma, "講師ID": ls.teacher_id}
            for ls in result.lessons for sid in ls.student_ids]
    return pd.DataFrame(rows, columns=COLUMNS)


def read_previous(source) -> list[PrevLesson]:
    """書き出した時間割の Excel（パスまたはバイト列）から前回の授業を読む。"""
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    try:
        df = pd.read_excel(source, sheet_name=SHEET_PREVIOUS, dtype=str)
    except ValueError as e:
        raise ValueError(f"シート「{SHEET_PREVIOUS}」がありません。このアプリで書き出した時間割のExcelを選んでください。") from e
    lack = [c for c in COLUMNS if c not in df.columns]
    if lack:
        raise ValueError(f"シート「{SHEET_PREVIOUS}」に列 {', '.join(lack)} がありません。")
    df = df.fillna("")
    return [PrevLesson(r["生徒ID"], r["科目"], r["形式"], Slot(r["曜日"], int(r["コマ"])), r["講師ID"])
            for _, r in df.iterrows() if r["生徒ID"] and str(r["コマ"]).isdigit()]


def kept(previous: list[PrevLesson], problem: Problem, result: Result) -> tuple[int, int]:
    """（前回と同じコマに入った授業の数, 今回も希望がある前回の授業の数）。"""
    wanted = {(r.student_id, r.subject, r.form) for r in problem.requests}
    still = [p for p in previous if (p.student_id, p.subject, p.form) in wanted]
    now = {(sid, ls.student_subjects.get(sid, ls.subject), ls.form, ls.slot)
           for ls in result.lessons for sid in ls.student_ids}
    same = sum((p.student_id, p.subject, p.form, p.slot) in now for p in still)
    return same, len(still)
