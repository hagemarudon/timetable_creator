"""設定ファイルとスプレッドシート（Googleスプレッドシート / Excel）の読み込み。"""
from __future__ import annotations

import io
import re
import tomllib
import urllib.request
from pathlib import Path

import pandas as pd

from .model import FORMS, SUBJECTS, Koma, Problem, Request, Settings, Slot, Student, Teacher

SHEET_KOMA = "コマ設定"
SHEET_STUDENT_REQ = "生徒_受講希望"
SHEET_STUDENT_AVAIL = "生徒_空き時間"
SHEET_TEACHER = "講師_担当可能科目"
SHEET_TEACHER_AVAIL = "講師_空き時間"
REQUIRED_SHEETS = [SHEET_STUDENT_REQ, SHEET_STUDENT_AVAIL, SHEET_TEACHER, SHEET_TEACHER_AVAIL]

MARKS = {"○", "◯", "〇", "o", "O", "1", "true", "TRUE", "True", "✓", "✔"}


def load_settings(path: str | Path) -> Settings:
    with open(path, "rb") as f:
        c = tomllib.load(f)
    return Settings(
        days=list(c["days"]),
        komas=[Koma(int(k["no"]), str(k["start"]), str(k["end"])) for k in c["komas"]],
        individual_booths=int(c["rooms"]["individual_booths"]),
        group_rooms=int(c["rooms"]["group_rooms"]),
        max_students_per_teacher=int(c["individual"]["max_students_per_teacher"]),
        allow_mixed_subjects=bool(c["individual"]["allow_mixed_subjects"]),
        group_capacity=int(c["group"]["capacity"]),
        time_limit_seconds=float(c["solver"]["time_limit_seconds"]),
        weights={k: int(v) for k, v in c["weights"].items()},
    )


def read_xlsx(source) -> dict[str, pd.DataFrame]:
    """Excelファイル（パスまたはバイト列）から全シートを読む。"""
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    return pd.read_excel(source, sheet_name=None, dtype=str)


def read_google_sheet(url: str) -> dict[str, pd.DataFrame]:
    """「リンクを知っている全員が閲覧可」のGoogleスプレッドシートを読む。"""
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url)
    if not m:
        raise ValueError("GoogleスプレッドシートのURLではないようです。")
    export = f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=xlsx"
    with urllib.request.urlopen(export, timeout=30) as r:
        data = r.read()
    if not data.startswith(b"PK"):
        raise ValueError("スプレッドシートを読めませんでした。共有設定を「リンクを知っている全員が閲覧可」にしてください。")
    return read_xlsx(data)


def _cell(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    return "" if s.lower() == "nan" else s


def _marked(v) -> bool:
    return _cell(v) in MARKS


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [_cell(c) for c in df.columns]
    df = df.map(_cell)
    return df[(df != "").any(axis=1)]


def _read_availability(df: pd.DataFrame, id_col: str, settings: Settings, sheet: str,
                       errors: list[str]) -> dict[str, set[Slot]]:
    valid = {s.label: s for s in settings.slots}
    slot_cols = [c for c in df.columns if c in valid]
    if not slot_cols:
        errors.append(f"「{sheet}」に「月1」のようなコマの列がありません。")
    unknown = [c for c in df.columns if re.fullmatch(r"[月火水木金土日]\d+", c) and c not in valid]
    if unknown:
        errors.append(f"「{sheet}」の列 {', '.join(unknown)} は設定のコマ割にありません（無視します）。")
    out: dict[str, set[Slot]] = {}
    for _, row in df.iterrows():
        pid = row.get(id_col, "")
        if not pid:
            continue
        out[pid] = {valid[c] for c in slot_cols if _marked(row[c])}
    return out


def apply_koma_sheet(dfs: dict[str, pd.DataFrame], settings: Settings) -> None:
    """「コマ設定」シートがあれば設定ファイルのコマ割を上書きする。"""
    if SHEET_KOMA not in dfs:
        return
    df = _clean(dfs[SHEET_KOMA])
    if not {"コマ", "開始", "終了"} <= set(df.columns):
        return
    komas = [Koma(int(r["コマ"]), r["開始"], r["終了"]) for _, r in df.iterrows() if r["コマ"].isdigit()]
    if komas:
        settings.komas = komas


def parse(dfs: dict[str, pd.DataFrame], settings: Settings) -> tuple[Problem | None, list[str]]:
    """読み込んだシートを検証して Problem にする。2つ目の戻り値はエラー・注意の一覧。"""
    errors: list[str] = []
    missing = [s for s in REQUIRED_SHEETS if s not in dfs]
    if missing:
        return None, [f"シート「{s}」がありません。" for s in missing]
    apply_koma_sheet(dfs, settings)

    req_df = _clean(dfs[SHEET_STUDENT_REQ])
    st_av_df = _clean(dfs[SHEET_STUDENT_AVAIL])
    t_df = _clean(dfs[SHEET_TEACHER])
    t_av_df = _clean(dfs[SHEET_TEACHER_AVAIL])

    for sheet, df, cols in [
        (SHEET_STUDENT_REQ, req_df, ["生徒ID", "氏名", "学年", "科目", "形式", "週の回数"]),
        (SHEET_STUDENT_AVAIL, st_av_df, ["生徒ID"]),
        (SHEET_TEACHER, t_df, ["講師ID", "氏名", *SUBJECTS, "集団可", "個別可"]),
        (SHEET_TEACHER_AVAIL, t_av_df, ["講師ID"]),
    ]:
        lack = [c for c in cols if c not in df.columns]
        if lack:
            errors.append(f"「{sheet}」に列 {', '.join(lack)} がありません。")
    if errors:
        return None, errors

    st_avail = _read_availability(st_av_df, "生徒ID", settings, SHEET_STUDENT_AVAIL, errors)
    t_avail = _read_availability(t_av_df, "講師ID", settings, SHEET_TEACHER_AVAIL, errors)

    teachers: dict[str, Teacher] = {}
    for _, r in t_df.iterrows():
        tid = r["講師ID"]
        if not tid:
            continue
        if tid in teachers:
            errors.append(f"講師ID {tid} が「{SHEET_TEACHER}」で重複しています。")
            continue
        limit = r.get("週の上限コマ", "")
        teachers[tid] = Teacher(
            id=tid, name=r["氏名"],
            subjects={s for s in SUBJECTS if _marked(r[s])},
            can_group=_marked(r["集団可"]), can_individual=_marked(r["個別可"]),
            max_komas=int(limit) if limit.isdigit() else None,
            available=t_avail.get(tid, set()),
        )
        if tid not in t_avail:
            errors.append(f"講師 {tid}（{r['氏名']}）の空き時間が「{SHEET_TEACHER_AVAIL}」にありません。")

    students: dict[str, Student] = {}
    requests: list[Request] = []
    seen: set[tuple[str, str]] = set()
    for i, r in req_df.iterrows():
        sid = r["生徒ID"]
        if not sid:
            continue
        row_no = int(i) + 2
        if sid not in students:
            students[sid] = Student(sid, r["氏名"], r["学年"], st_avail.get(sid, set()))
            if sid not in st_avail:
                errors.append(f"生徒 {sid}（{r['氏名']}）の空き時間が「{SHEET_STUDENT_AVAIL}」にありません。")
        if r["科目"] not in SUBJECTS:
            errors.append(f"「{SHEET_STUDENT_REQ}」{row_no}行目：科目「{r['科目']}」は対象外です（{'・'.join(SUBJECTS)}）。")
            continue
        if r["形式"] not in FORMS:
            errors.append(f"「{SHEET_STUDENT_REQ}」{row_no}行目：形式は「集団」か「個別」にしてください。")
            continue
        if not r["週の回数"].isdigit() or int(r["週の回数"]) < 1:
            errors.append(f"「{SHEET_STUDENT_REQ}」{row_no}行目：週の回数は1以上の数字にしてください。")
            continue
        key = (sid, r["科目"])
        if key in seen:
            errors.append(f"「{SHEET_STUDENT_REQ}」{row_no}行目：生徒 {sid} の{r['科目']}が重複しています。")
            continue
        seen.add(key)
        pref = r.get("希望講師（任意）", "") or r.get("希望講師", "")
        if pref and pref not in teachers:
            errors.append(f"「{SHEET_STUDENT_REQ}」{row_no}行目：希望講師 {pref} が講師一覧にありません（無視します）。")
            pref = ""
        requests.append(Request(len(requests), sid, r["科目"], r["形式"], int(r["週の回数"]), pref or None))

    for subj in SUBJECTS:
        for form in FORMS:
            if any(q.subject == subj and q.form == form for q in requests) and not any(
                subj in t.subjects and (t.can_group if form == "集団" else t.can_individual)
                for t in teachers.values()
            ):
                errors.append(f"{subj}（{form}）を担当できる講師がいません。")

    return Problem(settings, students, teachers, requests), errors
