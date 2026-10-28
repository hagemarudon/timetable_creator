"""塾の時間割作成（試作版）の画面。

起動: streamlit run app.py
"""
import json
import time
from pathlib import Path

import pandas as pd
import streamlit as st

from timetable.loader import komas_from_sheet, load_settings, parse, read_google_sheet, read_xlsx
from timetable.model import Koma
from timetable.output import lessons_table, person_grid, student_names, to_xlsx, unassigned_table, write_google_sheet
from timetable.settings_io import ALL_DAYS, check_komas, describe_komas, make_komas, save_settings
from timetable.solver import solve

ROOT = Path(__file__).parent
WEIGHT_LABELS = {
    "assigned_lesson": "授業を1回入れる",
    "preferred_teacher": "希望講師に当てる",
    "same_teacher": "個別は毎回同じ講師にする",
    "same_day_repeat": "同じ科目を同じ日に固めない",
    "teacher_work_day": "講師の出勤日を少なくする",
    "student_gap": "生徒の空きコマを作らない",
}
COLORS = {"英語": "#dbeafe", "数学": "#fee2e2", "物理": "#dcfce7", "化学": "#fef9c3", "国語": "#f3e8ff"}


def overview_html(problem, result) -> str:
    """曜日×コマの全体表。1つの授業を科目色のカードで並べる。"""
    s = problem.settings
    cells = {}
    for ls in result.lessons:
        t = problem.teachers[ls.teacher_id].name
        if ls.form == "集団":
            body = f"<b>{ls.class_name}</b> 集団<br>{t}・{len(ls.student_ids)}名"
        else:
            names = student_names(problem, ls.student_ids)
            body = f"<b>{ls.subject}</b> 個別<br>{t}／{names}"
        color = COLORS.get(ls.subject.split("・")[0], "#eee")
        cells.setdefault(ls.slot, []).append(
            f'<div style="background:{color};color:#111;border-radius:6px;padding:4px 6px;margin:3px 0;font-size:12px">'
            f'<span style="opacity:.6">{ls.room}</span> {body}</div>')
    head = "".join(f"<th style='min-width:170px'>{d}</th>" for d in s.days)
    rows = []
    for k in s.komas:
        tds = "".join(f"<td style='vertical-align:top'>{''.join(cells.get(sl, []))}</td>"
                      for sl in s.slots if sl.koma == k.no)
        rows.append(f"<tr><th style='white-space:nowrap'>{k.no}限<br><small>{k.start}-{k.end}</small></th>{tds}</tr>")
    return (f"<div style='overflow-x:auto'><table style='border-collapse:collapse;width:100%'>"
            f"<tr><th></th>{head}</tr>{''.join(rows)}</table></div>")


st.set_page_config(page_title="塾の時間割作成", layout="wide")
st.title("塾の時間割作成")

CONFIG = ROOT / "config.toml"
settings = load_settings(CONFIG)

source = st.radio("入力", ["Googleスプレッドシート", "Excelファイル", "サンプルデータ"], horizontal=True)
dfs = None
sheet_url = ""
try:
    if source == "Googleスプレッドシート":
        sheet_url = st.text_input("スプレッドシートのURL（共有設定：リンクを知っている全員が閲覧可）")
        if sheet_url:
            dfs = read_google_sheet(sheet_url)
    elif source == "Excelファイル":
        up = st.file_uploader("Excelファイル", type=["xlsx"])
        if up:
            dfs = read_xlsx(up.getvalue())
    else:
        sample = ROOT / "sample" / "サンプル入力.xlsx"
        dfs = read_xlsx(sample)
        st.download_button("サンプル入力をダウンロード", sample.read_bytes(), sample.name)
except Exception as e:  # noqa: BLE001
    st.error(f"読み込めませんでした：{e}")

# 入力に「コマ設定」シートがあれば、そのコマ割を入力欄の初期値にする
sheet_komas = komas_from_sheet(dfs) if dfs is not None else None
base_komas = sheet_komas or settings.komas
k_count, k_start, k_len, k_break = describe_komas(base_komas)

with st.sidebar:
    st.header("条件")

    st.subheader("曜日とコマ割")
    settings.days = st.multiselect("開講曜日", ALL_DAYS, default=[d for d in ALL_DAYS if d in settings.days]) or settings.days
    c1, c2 = st.columns(2)
    count = c1.number_input("1日のコマ数", 1, 12, k_count)
    start = c2.text_input("1限の開始", k_start)
    c1, c2 = st.columns(2)
    length = c1.number_input("授業の長さ（分）", 10, 240, k_len, step=5)
    brk = c2.number_input("休憩（分）", 0, 120, k_break, step=5)
    try:
        generated = make_komas(count, start, length, brk)
    except ValueError:
        st.error("1限の開始は「16:00」の形で入力してください。")
        st.stop()
    # 入力欄が元のコマ割と同じなら元の時刻をそのまま使う（コマごとに時刻が不揃いな場合のため）
    initial = base_komas if (count, start, length, brk) == (k_count, k_start, k_len, k_break) else generated
    edited = st.data_editor(
        pd.DataFrame([{"コマ": k.no, "開始": k.start, "終了": k.end} for k in initial]),
        hide_index=True, disabled=["コマ"], width="stretch", key=f"komas_{count}_{start}_{length}_{brk}",
    )
    settings.komas = [Koma(int(r["コマ"]), str(r["開始"]), str(r["終了"])) for _, r in edited.iterrows()]
    st.caption("時刻はコマごとに表で直せます。生徒・講師の空き時間シートの列（月1, 月2 …）はこのコマ割に合わせてください。")
    koma_errors = check_komas(settings.komas)
    for err in koma_errors:
        st.error(err)

    st.subheader("教室")
    settings.individual_booths = st.number_input("個別ブース数", 1, 50, settings.individual_booths)
    settings.group_rooms = st.number_input("集団教室数", 0, 20, settings.group_rooms)

    st.subheader("個別授業")
    settings.max_students_per_teacher = st.number_input("講師1人が同時に見る生徒数（1 = 1対1）", 1, 4, settings.max_students_per_teacher)
    settings.allow_mixed_subjects = st.checkbox("科目の違う生徒を同時に見てよい", settings.allow_mixed_subjects)

    st.subheader("集団授業")
    settings.group_capacity = st.number_input("1クラスの定員", 1, 60, settings.group_capacity)

    with st.expander("優先条件の重み（大きいほど重視）"):
        w = settings.weights
        for key, label in WEIGHT_LABELS.items():
            w[key] = st.number_input(label, 0, 1000, w[key], key=f"w_{key}")
    settings.time_limit_seconds = st.number_input("計算時間の上限（秒）", 5, 600, int(settings.time_limit_seconds))

    if st.button("この条件を既定にする", disabled=bool(koma_errors)):
        save_settings(settings, CONFIG)
        st.success("保存しました。次回からこの条件が最初から入ります。")

if dfs is None or koma_errors:
    st.stop()

problem, notes = parse(dfs, settings, use_koma_sheet=False)
if notes:
    with st.expander(f"入力の確認（{len(notes)}件）", expanded=problem is None):
        for n in notes:
            st.warning(n)
if problem is None:
    st.stop()

c1, c2, c3 = st.columns(3)
c1.metric("生徒", f"{len(problem.students)}人")
c2.metric("講師", f"{len(problem.teachers)}人")
c3.metric("希望コマ数（週）", sum(r.times for r in problem.requests))

if st.button("時間割を作る", type="primary"):
    with st.spinner("時間割を計算中…"):
        t0 = time.time()
        st.session_state["result"] = (problem, solve(problem), time.time() - t0)

if "result" not in st.session_state:
    st.stop()

problem, result, elapsed = st.session_state["result"]
total = sum(r.times for r in problem.requests)
missing = sum(u.missing for u in result.unassigned)
st.success(f"{result.status}（{elapsed:.1f}秒）：希望 {total} コマ中 {total - missing} コマを配置しました。")

tabs = st.tabs(["全体", "生徒別", "講師別", f"未配置（{missing}）", "授業一覧"])
with tabs[0]:
    st.markdown(overview_html(problem, result), unsafe_allow_html=True)
with tabs[1]:
    sid = st.selectbox("生徒", list(problem.students), format_func=lambda k: f"{k} {problem.students[k].name}（{problem.students[k].grade}）")
    st.dataframe(person_grid(problem, result, "student", sid), width="stretch")
    st.caption("－ は空き時間でないコマ")
with tabs[2]:
    tid = st.selectbox("講師", list(problem.teachers), format_func=lambda k: f"{k} {problem.teachers[k].name}")
    st.dataframe(person_grid(problem, result, "teacher", tid), width="stretch")
with tabs[3]:
    df = unassigned_table(problem, result)
    if df.empty:
        st.info("すべての希望が入りました。")
    else:
        st.dataframe(df, width="stretch", hide_index=True)
with tabs[4]:
    st.dataframe(lessons_table(problem, result), width="stretch", hide_index=True)

st.subheader("書き出し")
st.download_button("Excelでダウンロード", to_xlsx(problem, result), "時間割.xlsx", type="primary")
if source == "Googleスプレッドシート" and sheet_url:
    with st.expander("元のGoogleスプレッドシートに書き込む"):
        st.caption("Google Cloud のサービスアカウントの鍵（JSON）が必要です。スプレッドシートをそのメールアドレスに編集者として共有してください。")
        key = st.file_uploader("サービスアカウントの鍵（JSON）", type=["json"])
        if key and st.button("スプレッドシートに書き込む"):
            try:
                write_google_sheet(problem, result, sheet_url, json.loads(key.getvalue()))
                st.success("「時間割_全体」などのシートを書き込みました。")
            except Exception as e:  # noqa: BLE001
                st.error(f"書き込めませんでした：{e}")
