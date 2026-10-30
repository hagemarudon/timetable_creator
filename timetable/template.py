"""入力用の雛形（空き時間表など）を、今のコマ割に合わせて作る。"""
from __future__ import annotations

import io

import pandas as pd
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .loader import SHEET_KOMA, SHEET_STUDENT_AVAIL, SHEET_STUDENT_REQ, SHEET_TEACHER, SHEET_TEACHER_AVAIL
from .model import FORMS, Problem, Settings

BLANK_ROWS = 50  # 人を事前に入れないときに、○の選択肢を付けておく行数
# 入力がまだ無いときに、講師シートへ見本として並べる科目（列は自由に足し引きできる）
EXAMPLE_SUBJECTS = ["英語", "数学", "物理", "化学", "国語"]
REQUEST_COLUMNS = ["生徒ID", "氏名", "学年", "科目", "形式", "週の回数", "希望講師（任意）"]


def template_sheets(settings: Settings, problem: Problem | None = None) -> dict[str, pd.DataFrame]:
    """雛形のシート。problem を渡すと、その生徒・講師のIDと氏名・科目の列を入れておく。"""
    subjects = (problem.subjects if problem and problem.subjects else EXAMPLE_SUBJECTS)
    slots = [s.label for s in settings.slots]
    students = [(p.id, p.name) for p in problem.students.values()] if problem else []
    teachers = [(p.id, p.name) for p in problem.teachers.values()] if problem else []

    def avail(id_col: str, people: list[tuple[str, str]]) -> pd.DataFrame:
        return pd.DataFrame([{id_col: i, "氏名": n, **{c: "" for c in slots}} for i, n in people],
                            columns=[id_col, "氏名", *slots])

    return {
        SHEET_KOMA: pd.DataFrame([{"コマ": k.no, "開始": k.start, "終了": k.end} for k in settings.komas]),
        SHEET_STUDENT_REQ: pd.DataFrame(columns=REQUEST_COLUMNS),
        SHEET_STUDENT_AVAIL: avail("生徒ID", students),
        SHEET_TEACHER: pd.DataFrame(columns=["講師ID", "氏名", *subjects, "集団可", "個別可", "週の上限コマ"]),
        SHEET_TEACHER_AVAIL: avail("講師ID", teachers),
    }


def _choices(ws, values: list[str], first_col: int, last_col: int, last_row: int) -> None:
    dv = DataValidation(type="list", formula1='"' + ",".join(values) + '"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"{get_column_letter(first_col)}2:{get_column_letter(last_col)}{last_row}")


def make_template(settings: Settings, problem: Problem | None = None) -> bytes:
    """雛形を Excel にする。○を付ける欄と形式の欄は選択肢から選べるようにする。"""
    sheets = template_sheets(settings, problem)
    subjects = list(sheets[SHEET_TEACHER].columns[2:-3])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name, index=False)
            ws = xw.sheets[name]
            ws.freeze_panes = "C2" if name in (SHEET_STUDENT_AVAIL, SHEET_TEACHER_AVAIL) else "A2"
            for i, col in enumerate(df.columns, start=1):
                ws.column_dimensions[get_column_letter(i)].width = max(6, len(str(col)) * 2 + 2)
            last_row = max(len(df), BLANK_ROWS) + 1
            n = len(df.columns)
            if name in (SHEET_STUDENT_AVAIL, SHEET_TEACHER_AVAIL) and n > 2:
                _choices(ws, ["○"], 3, n, last_row)
            elif name == SHEET_TEACHER:
                _choices(ws, ["○"], 3, n - 1, last_row)
            elif name == SHEET_STUDENT_REQ:
                _choices(ws, FORMS, REQUEST_COLUMNS.index("形式") + 1, REQUEST_COLUMNS.index("形式") + 1, last_row)
                col = REQUEST_COLUMNS.index("科目") + 1
                _choices(ws, subjects, col, col, last_row)
    return buf.getvalue()
