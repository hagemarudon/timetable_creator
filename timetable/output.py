"""時間割を表にして、Excel / Googleスプレッドシートに書き出す。"""
from __future__ import annotations

import io
from dataclasses import dataclass

import pandas as pd
from openpyxl.utils import get_column_letter

from .model import Problem, Result

SHEET_ALL = "時間割_全体"
SHEET_STUDENT = "時間割_生徒別"
SHEET_TEACHER = "時間割_講師別"
SHEET_TEACHER_COLUMNS = "時間割_講師列"
SPARE = "予備"
SHEET_UNASSIGNED = "未配置"


# 科目の色（薄い色。文字は黒で読める）。足りなければ色相をずらして作る
PALETTE = ["#dbeafe", "#fee2e2", "#dcfce7", "#fef9c3", "#f3e8ff", "#ffedd5", "#ccfbf1", "#fce7f3",
           "#e0e7ff", "#ecfccb", "#cffafe", "#fae8ff", "#e7e5e4"]


def subject_colors(subjects: list[str]) -> dict[str, str]:
    """科目ごとに色を割り当てる。並び順で決まるので、同じシートなら毎回同じ色になる。"""
    colors = {}
    for i, subj in enumerate(subjects):
        if i < len(PALETTE):
            colors[subj] = PALETTE[i]
        else:
            hue = (i * 137.5) % 360  # 黄金角で色相をずらし、隣の色と似ないようにする
            colors[subj] = f"hsl({hue:.0f}, 80%, 90%)"
    return colors


@dataclass(frozen=True)
class View:
    """表示の切り替え。画面と書き出しの両方で使う。"""
    show_room: bool = True
    show_detail: bool = True  # 生徒の学年と、生徒・講師のIDを出す


def student_name(problem: Problem, sid: str, view: View = View()) -> str:
    st = problem.students[sid]
    return st.label if view.show_detail else st.name


def _students(problem: Problem, sids, view: View) -> str:
    return "、".join(student_name(problem, x, view) for x in sids)


def _room(room: str, view: View) -> str:
    return f" / {room}" if view.show_room else ""


def _koma_label(problem: Problem, no: int) -> str:
    k = next(k for k in problem.settings.komas if k.no == no)
    return f"{no}限 {k.start}-{k.end}"


def lessons_table(problem: Problem, result: Result, view: View = View()) -> pd.DataFrame:
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
            "生徒": _students(problem, ls.student_ids, view),
            "人数": len(ls.student_ids),
        })
    columns = ["曜日", "コマ", "教室", "形式", "科目", "クラス", "講師", "生徒", "人数"]
    if not view.show_room:
        columns.remove("教室")
    return pd.DataFrame(rows, columns=columns)


def overview_grid(problem: Problem, result: Result, view: View = View()) -> pd.DataFrame:
    """行 = コマ、列 = 曜日 の全体表。セルにはその時間の授業を並べる。"""
    s = problem.settings
    grid = pd.DataFrame("", index=[_koma_label(problem, k.no) for k in s.komas], columns=s.days)
    for ls in result.lessons:
        t = problem.teachers[ls.teacher_id].name
        room = f"[{ls.room}] " if view.show_room else ""
        text = (f"{room}{ls.class_name}（{t}）{len(ls.student_ids)}名" if ls.form == "集団"
                else f"{room}個別 {ls.subject}（{t}）{_students(problem, ls.student_ids, view)}")
        cell = grid.at[_koma_label(problem, ls.slot.koma), ls.slot.day]
        grid.at[_koma_label(problem, ls.slot.koma), ls.slot.day] = (cell + "\n" if cell else "") + text
    return grid


def person_grid(problem: Problem, result: Result, kind: str, pid: str, view: View = View()) -> pd.DataFrame:
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
                text = f"{subj}（{ls.form}）{problem.teachers[ls.teacher_id].name}{_room(ls.room, view)}"
            else:
                who = ls.class_name if ls.form == "集団" else _students(problem, ls.student_ids, view)
                text = f"{ls.subject}（{ls.form}）{who}{_room(ls.room, view)}"
            grid.at[_koma_label(problem, ls.slot.koma), ls.slot.day] = text
    return grid


def teacher_columns_grid(problem: Problem, result: Result, view: View = View()) -> pd.DataFrame:
    """行 = コマ、列 = 曜日 → その日に授業がある講師 の表。

    授業のない講師の列はその曜日に出さず、各曜日の最後に空の「予備」列を1列入れる。
    """
    s = problem.settings
    index = [_koma_label(problem, k.no) for k in s.komas]
    cells: dict[tuple[str, str], dict[str, str]] = {}
    for ls in result.lessons:
        who = ls.class_name if ls.form == "集団" else _students(problem, ls.student_ids, view)
        cells.setdefault((ls.slot.day, ls.teacher_id), {})[_koma_label(problem, ls.slot.koma)] = \
            f"{ls.subject}（{ls.form}）{who}{_room(ls.room, view)}"
    columns, data = [], []
    for d in s.days:
        for tid, t in problem.teachers.items():
            if (d, tid) in cells:
                columns.append((d, t.name))
                data.append([cells[d, tid].get(i, "") for i in index])
        columns.append((d, SPARE))
        data.append([""] * len(index))
    grid = pd.DataFrame(dict(zip(range(len(columns)), data)), index=index)
    grid.columns = pd.MultiIndex.from_tuples(columns, names=["曜日", "講師"])
    grid.index.name = "コマ"
    return grid


def unassigned_table(problem: Problem, result: Result, view: View = View()) -> pd.DataFrame:
    rows = [{
        "生徒ID": u.request.student_id,
        "氏名": problem.students[u.request.student_id].name,
        "科目": u.request.subject,
        "形式": u.request.form,
        "希望回数": u.request.times,
        "入らなかった回数": u.missing,
        "理由": u.reason,
    } for u in result.unassigned]
    columns = ["生徒ID", "氏名", "科目", "形式", "希望回数", "入らなかった回数", "理由"]
    if not view.show_detail:
        columns.remove("生徒ID")
    return pd.DataFrame(rows, columns=columns)


def _stacked(problem: Problem, result: Result, kind: str, view: View) -> pd.DataFrame:
    people = problem.students if kind == "student" else problem.teachers
    frames = []
    for pid, p in people.items():
        g = person_grid(problem, result, kind, pid, view).reset_index(names="コマ")
        g.insert(0, "氏名", p.name)
        if view.show_detail:
            g.insert(0, "ID", pid)
        frames.append(g)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def all_sheets(problem: Problem, result: Result, view: View = View()) -> dict[str, pd.DataFrame]:
    return {
        SHEET_ALL: overview_grid(problem, result, view).reset_index(names="コマ"),
        SHEET_STUDENT: _stacked(problem, result, "student", view),
        SHEET_TEACHER: _stacked(problem, result, "teacher", view),
        SHEET_TEACHER_COLUMNS: teacher_columns_grid(problem, result, view),
        SHEET_UNASSIGNED: unassigned_table(problem, result, view),
        "授業一覧": lessons_table(problem, result, view),
    }


def to_xlsx(problem: Problem, result: Result, view: View = View()) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, df in all_sheets(problem, result, view).items():
            # 曜日と講師の2段の見出しは、コマを行の見出しにして書く（Excel で曜日がまとまる）
            df.to_excel(xw, sheet_name=name, index=isinstance(df.columns, pd.MultiIndex))
            ws = xw.sheets[name]
            for col in ws.iter_cols():
                width = max((len(str(c.value or "")) for c in col), default=4)
                ws.column_dimensions[get_column_letter(col[0].column)].width = min(60, max(8, width * 1.6))
    return buf.getvalue()


def write_google_sheet(problem: Problem, result: Result, url: str, credentials_json: dict,
                       view: View = View()) -> None:
    """サービスアカウントで、元のスプレッドシートに時間割のシートを書き込む。

    スプレッドシートをサービスアカウントのメールアドレスに「編集者」で共有しておく必要がある。
    """
    import gspread

    gc = gspread.service_account_from_dict(credentials_json)
    sh = gc.open_by_url(url)
    existing = {ws.title: ws for ws in sh.worksheets()}
    for name, df in all_sheets(problem, result, view).items():
        ws = existing.get(name) or sh.add_worksheet(name, rows=max(len(df) + 5, 20), cols=max(len(df.columns) + 2, 10))
        ws.clear()
        if isinstance(df.columns, pd.MultiIndex):
            # 2段の見出しは、曜日の行と講師の行に分けて書く
            header = [[df.index.name or ""] + [c[0] for c in df.columns],
                      [""] + [c[1] for c in df.columns]]
            body = [[i] + row for i, row in zip(df.index, df.astype(str).values.tolist())]
            ws.update(header + body)
        else:
            ws.update([df.columns.tolist()] + df.astype(str).values.tolist())
