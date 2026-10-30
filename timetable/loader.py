"""設定ファイルと入力（Excel）の読み込み。Googleスプレッドシートは google_sheets.read_sheet で読む。"""
from __future__ import annotations

import io
import re
import tomllib
from pathlib import Path

import pandas as pd

from .model import FORMS, Koma, Problem, Request, Settings, Slot, Student, Teacher

SHEET_KOMA = "コマ設定"
SHEET_STUDENT_REQ = "生徒_受講希望"
SHEET_STUDENT_AVAIL = "生徒_空き時間"
SHEET_TEACHER = "講師_担当可能科目"
SHEET_TEACHER_AVAIL = "講師_空き時間"
REQUIRED_SHEETS = [SHEET_STUDENT_REQ, SHEET_STUDENT_AVAIL, SHEET_TEACHER, SHEET_TEACHER_AVAIL]

MARKS = {"○", "◯", "〇", "o", "O", "1", "true", "TRUE", "True", "✓", "✔"}


# 「講師_担当可能科目」シートで科目ではない列。これ以外の列見出しはすべて科目として扱う
TEACHER_INFO_COLS = {"講師ID", "氏名", "集団可", "個別可", "週の上限コマ", "備考", "メモ"}

LOCAL_CONFIG_NAME = "config.local.toml"


def _merge(base: dict, over: dict) -> dict:
    """over の値で base を上書きする（表は中まで、配列は丸ごと置き換え）。"""
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_settings(path: str | Path, overlay: str | Path | None = None) -> Settings:
    """設定ファイルを読む。overlay のファイルがあれば、その値で上書きする。

    overlay には画面で保存した条件（config.local.toml、Git管理外）を渡す。
    config.toml に新しい項目が増えても、overlay に無い項目は config.toml の値が使われる。
    """
    with open(path, "rb") as f:
        c = tomllib.load(f)
    if overlay is not None and Path(overlay).exists():
        with open(overlay, "rb") as f:
            c = _merge(c, tomllib.load(f))
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


def subjects_from_sheet(df: pd.DataFrame) -> list[str]:
    """「講師_担当可能科目」シートの列見出しから科目を読む（シートの列順）。"""
    return [c for c in df.columns
            if c and c not in TEACHER_INFO_COLS and not c.startswith("Unnamed")]


# 空き時間を30分ごとに書いた列（例：「月16:00」）。Googleフォームの空き時間はこの形でまとめる
CELL_MINUTES = 30
CELL_COL = re.compile(r"([月火水木金土日])(\d{1,2}):(\d{2})")


def _minutes(hhmm: str) -> int:
    h, m = hhmm.strip().split(":")
    return int(h) * 60 + int(m)


def _cells(start: str, end: str) -> list[int]:
    """コマの時間にかかる30分の枠（開始の分）。16:00-17:30 なら 16:00・16:30・17:00 の3枠。"""
    s, e = _minutes(start), _minutes(end)
    return list(range(s // CELL_MINUTES * CELL_MINUTES, e, CELL_MINUTES))


def _read_availability(df: pd.DataFrame, id_col: str, settings: Settings, sheet: str,
                       errors: list[str]) -> dict[str, set[Slot]]:
    """空き時間を読む。列は「月1」（コマ）か「月16:00」（30分の枠）のどちらでもよい。

    30分の枠で書いた場合は、そのコマの時間にかかる枠すべてに○があればコマが空いているとする。
    """
    valid = {s.label: s for s in settings.slots}
    slot_cols = [c for c in df.columns if c in valid]
    cell_cols: dict[tuple[str, int], str] = {}
    for c in df.columns:
        if m := CELL_COL.fullmatch(c):
            cell_cols[m[1], int(m[2]) * 60 + int(m[3])] = c
    if not slot_cols and not cell_cols:
        errors.append(f"「{sheet}」に「月1」や「月16:00」のような空き時間の列がありません。")
    unknown = [c for c in df.columns if re.fullmatch(r"[月火水木金土日]\d+", c) and c not in valid]
    if unknown:
        errors.append(f"「{sheet}」の列 {', '.join(unknown)} は設定のコマ割にありません（無視します）。")
    komas = {k.no: k for k in settings.komas}
    # 30分の枠で決めるコマ（コマの時間にかかる枠の列がすべてあるもの）
    by_cells = {sl: [cell_cols[sl.day, t] for t in _cells(komas[sl.koma].start, komas[sl.koma].end)]
                for sl in settings.slots
                if cell_cols and all((sl.day, t) in cell_cols
                                     for t in _cells(komas[sl.koma].start, komas[sl.koma].end))}
    if cell_cols:
        days = {d for d, _ in cell_cols}
        lack = [sl.label for sl in settings.slots if sl.day in days and sl not in by_cells and sl.label not in slot_cols]
        if lack:
            errors.append(f"「{sheet}」の30分の枠の列が、コマ {'・'.join(lack)} の時間をすべては含んでいません"
                          "（そのコマは空いていないものとします）。")
    out: dict[str, set[Slot]] = {}
    for _, row in df.iterrows():
        pid = row.get(id_col, "")
        if not pid:
            continue
        out[pid] = ({valid[c] for c in slot_cols if _marked(row[c])}
                    | {sl for sl, cols in by_cells.items() if all(_marked(row[c]) for c in cols)})
    return out


def _read_fixed(text: str, req: Request, student: Student, teachers: dict[str, Teacher],
                settings: Settings, where: str, errors: list[str]) -> list[Slot]:
    """「固定」列（例：「月1」「月1、木2」）を読む。入れられないコマは注意を出して外す。"""
    valid = {s.label: s for s in settings.slots}
    fixed: list[Slot] = []
    for label in re.split(r"[、,，・\s]+", text):
        if not label:
            continue
        sl = valid.get(label)
        if sl is None:
            errors.append(f"{where}：固定の「{label}」は設定のコマ割にありません（無視します）。")
            continue
        if sl in fixed:
            continue
        if sl not in student.available:
            errors.append(f"{where}：固定の{label}は生徒の空き時間ではありません（無視します）。")
            continue
        elig = [t for t in teachers.values()
                if (t.can_group if req.form == "集団" else t.can_individual)
                and req.subject in t.subjects and sl in t.available]
        if not elig:
            errors.append(f"{where}：固定の{label}に{req.subject}（{req.form}）を担当できる講師が空いていません（無視します）。")
            continue
        if req.preferred_teacher and req.form == "個別" and all(t.id != req.preferred_teacher for t in elig):
            errors.append(f"{where}：希望講師 {req.preferred_teacher} は{label}に入れないため、固定は他の講師で入れます。")
        fixed.append(sl)
    if len(fixed) > req.times:
        errors.append(f"{where}：固定のコマが週の回数（{req.times}）より多いです（先の{req.times}コマだけ使います）。")
        fixed = fixed[:req.times]
    return fixed


def komas_from_sheet(dfs: dict[str, pd.DataFrame]) -> list[Koma] | None:
    """「コマ設定」シートがあれば、そのコマ割を返す。"""
    if SHEET_KOMA not in dfs:
        return None
    df = _clean(dfs[SHEET_KOMA])
    if not {"コマ", "開始", "終了"} <= set(df.columns):
        return None
    komas = [Koma(int(r["コマ"]), r["開始"], r["終了"]) for _, r in df.iterrows() if r["コマ"].isdigit()]
    return komas or None


def parse(dfs: dict[str, pd.DataFrame], settings: Settings,
          use_koma_sheet: bool = True) -> tuple[Problem | None, list[str]]:
    """読み込んだシートを検証して Problem にする。2つ目の戻り値はエラー・注意の一覧。

    use_koma_sheet が True なら「コマ設定」シートのコマ割で settings を上書きする。
    """
    errors: list[str] = []
    missing = [s for s in REQUIRED_SHEETS if s not in dfs]
    if missing:
        return None, [f"シート「{s}」がありません。" for s in missing]
    if use_koma_sheet and (komas := komas_from_sheet(dfs)):
        settings.komas = komas

    req_df = _clean(dfs[SHEET_STUDENT_REQ])
    st_av_df = _clean(dfs[SHEET_STUDENT_AVAIL])
    t_df = _clean(dfs[SHEET_TEACHER])
    t_av_df = _clean(dfs[SHEET_TEACHER_AVAIL])

    for sheet, df, cols in [
        (SHEET_STUDENT_REQ, req_df, ["生徒ID", "氏名", "学年", "科目", "形式", "週の回数"]),
        (SHEET_STUDENT_AVAIL, st_av_df, ["生徒ID"]),
        (SHEET_TEACHER, t_df, ["講師ID", "氏名", "集団可", "個別可"]),
        (SHEET_TEACHER_AVAIL, t_av_df, ["講師ID"]),
    ]:
        lack = [c for c in cols if c not in df.columns]
        if lack:
            errors.append(f"「{sheet}」に列 {', '.join(lack)} がありません。")
    subjects = subjects_from_sheet(t_df)
    if not subjects:
        errors.append(f"「{SHEET_TEACHER}」に科目の列がありません。科目名（例：英語、数学）を列見出しにして、担当できる講師に○を付けてください。")
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
            subjects={s for s in subjects if _marked(r[s])},
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
        if r["科目"] not in subjects:
            errors.append(f"「{SHEET_STUDENT_REQ}」{row_no}行目：科目「{r['科目']}」が「{SHEET_TEACHER}」の列にありません"
                          f"（今ある科目：{'・'.join(subjects)}）。")
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
        req = Request(len(requests), sid, r["科目"], r["形式"], int(r["週の回数"]), pref or None)
        req.fixed = _read_fixed(r.get("固定（任意）", "") or r.get("固定", ""), req, students[sid], teachers,
                                settings, f"「{SHEET_STUDENT_REQ}」{row_no}行目", errors)
        requests.append(req)

    taken: dict[tuple[str, Slot], str] = {}
    for q in requests:
        for sl in list(q.fixed):
            other = taken.setdefault((q.student_id, sl), q.subject)
            if other != q.subject:
                errors.append(f"生徒 {q.student_id} の{other}と{q.subject}が同じ{sl.label}に固定されています"
                              f"（{q.subject}の固定は無視します）。")
                q.fixed.remove(sl)

    for subj in subjects:
        for form in FORMS:
            if any(q.subject == subj and q.form == form for q in requests) and not any(
                subj in t.subjects and (t.can_group if form == "集団" else t.can_individual)
                for t in teachers.values()
            ):
                errors.append(f"{subj}（{form}）を担当できる講師がいません。")

    return Problem(settings, students, teachers, requests, subjects), errors
