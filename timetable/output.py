"""時間割を表にして、Excel / Googleスプレッドシートに書き出す。"""
from __future__ import annotations

import io

import pandas as pd

from .model import Problem, Result

SHEET_ALL = "時間割_全体"
SHEET_STUDENT = "時間割_生徒別"
SHEET_TEACHER = "時間割_講師別"
SHEET_UNASSIGNED = "未配置"


def _koma_label(problem: Problem, no: int) -> str:
    k = next(k for k in problem.settings.komas if k.no == no)
    return f"{no}限 {k.start}-{k.end}"


def lessons_table(problem: Problem, result: Result) -> pd.DataFrame:
    rows = []
    for ls in result.lessons:
        rows.append({
            "曜日": ls.slot.day,
            "コマ": _koma_label(problem, ls.slot.koma),
            "教室": ls.room,
            "形式": ls.form,
            "科目": ls.subject,
            "クラス": ls.class_name,
            "講師": problem.teachers[ls.teacher_id].name,
            "生徒": "、".join(problem.students[sid].label for sid in ls.student_ids),
            "人数": len(ls.student_ids),
        })
    return pd.DataFrame(rows, columns=["曜日", "コマ", "教室", "形式", "科目", "クラス", "講師", "生徒", "人数"])


def overview_grid(problem: Problem, result: Result) -> pd.DataFrame:
    """行 = コマ、列 = 曜日 の全体表。セルにはその時間の授業を並べる。"""
    s = problem.settings
    grid = pd.DataFrame("", index=[_koma_label(problem, k.no) for k in s.komas], columns=s.days)
    for ls in result.lessons:
        t = problem.teachers[ls.teacher_id].name
        text = (f"[{ls.room}] {ls.class_name}（{t}）{len(ls.student_ids)}名" if ls.form == "集団"
                else f"[{ls.room}] 個別 {ls.subject}（{t}）{'、'.join(problem.students[x].label for x in ls.student_ids)}")
        cell = grid.at[_koma_label(problem, ls.slot.koma), ls.slot.day]
        grid.at[_koma_label(problem, ls.slot.koma), ls.slot.day] = (cell + "\n" if cell else "") + text
    return grid


def person_grid(problem: Problem, result: Result, kind: str, pid: str) -> pd.DataFrame:
    """1人分の週間時間割。kind は "student" か "teacher"。"""
    s = problem.settings
    grid = pd.DataFrame("", index=[_koma_label(problem, k.no) for k in s.komas], columns=s.days)
    person = problem.students[pid] if kind == "student" else problem.teachers[pid]
    for sl in s.slots:
        if sl not in person.available:
            grid.at[_koma_label(problem, sl.koma), sl.day] = "－"
    for ls in result.lessons:
        if (kind == "student" and pid in ls.student_ids) or (kind == "teacher" and ls.teacher_id == pid):
            if kind == "student":
                subj = ls.student_subjects.get(pid, ls.subject)
                text = f"{subj}（{ls.form}）{problem.teachers[ls.teacher_id].name} / {ls.room}"
            else:
                who = ls.class_name if ls.form == "集団" else "、".join(problem.students[x].label for x in ls.student_ids)
                text = f"{ls.subject}（{ls.form}）{who} / {ls.room}"
            grid.at[_koma_label(problem, ls.slot.koma), ls.slot.day] = text
    return grid


def unassigned_table(problem: Problem, result: Result) -> pd.DataFrame:
    rows = [{
        "生徒ID": u.request.student_id,
        "氏名": problem.students[u.request.student_id].name,
        "科目": u.request.subject,
        "形式": u.request.form,
        "希望回数": u.request.times,
        "入らなかった回数": u.missing,
        "理由": u.reason,
    } for u in result.unassigned]
    return pd.DataFrame(rows, columns=["生徒ID", "氏名", "科目", "形式", "希望回数", "入らなかった回数", "理由"])


def _stacked(problem: Problem, result: Result, kind: str) -> pd.DataFrame:
    people = problem.students if kind == "student" else problem.teachers
    frames = []
    for pid, p in people.items():
        g = person_grid(problem, result, kind, pid).reset_index(names="コマ")
        g.insert(0, "氏名", p.name)
        g.insert(0, "ID", pid)
        frames.append(g)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def all_sheets(problem: Problem, result: Result) -> dict[str, pd.DataFrame]:
    return {
        SHEET_ALL: overview_grid(problem, result).reset_index(names="コマ"),
        SHEET_STUDENT: _stacked(problem, result, "student"),
        SHEET_TEACHER: _stacked(problem, result, "teacher"),
        SHEET_UNASSIGNED: unassigned_table(problem, result),
        "授業一覧": lessons_table(problem, result),
    }


def to_xlsx(problem: Problem, result: Result) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, df in all_sheets(problem, result).items():
            df.to_excel(xw, sheet_name=name, index=False)
            ws = xw.sheets[name]
            for col in ws.columns:
                width = max((len(str(c.value or "")) for c in col), default=4)
                ws.column_dimensions[col[0].column_letter].width = min(60, max(8, width * 1.6))
    return buf.getvalue()


def write_google_sheet(problem: Problem, result: Result, url: str, credentials_json: dict) -> None:
    """サービスアカウントで、元のスプレッドシートに時間割のシートを書き込む。

    スプレッドシートをサービスアカウントのメールアドレスに「編集者」で共有しておく必要がある。
    """
    import gspread

    gc = gspread.service_account_from_dict(credentials_json)
    sh = gc.open_by_url(url)
    existing = {ws.title: ws for ws in sh.worksheets()}
    for name, df in all_sheets(problem, result).items():
        ws = existing.get(name) or sh.add_worksheet(name, rows=max(len(df) + 5, 20), cols=max(len(df.columns) + 2, 10))
        ws.clear()
        ws.update([df.columns.tolist()] + df.astype(str).values.tolist())
