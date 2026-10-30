"""塾の時間割作成（試作版）の画面。

起動: streamlit run app.py
"""
import html
import time
from pathlib import Path

import pandas as pd
import streamlit as st

from timetable import google_sheets as gs
from timetable.loader import LOCAL_CONFIG_NAME, komas_from_sheet, load_settings, parse, read_xlsx
from timetable.model import Koma
from timetable.output import (View, all_sheets, lessons_table, person_grid, student_name, subject_colors,
                              teacher_columns_grid, to_xlsx, unassigned_table)
from timetable.settings_io import ALL_DAYS, check_komas, describe_komas, make_komas, save_settings
from timetable.solver import solve
from timetable.template import make_template

ROOT = Path(__file__).parent
WEIGHT_LABELS = {
    "assigned_lesson": "授業を1回入れる",
    "preferred_teacher": "希望講師に当てる",
    "same_teacher": "個別は毎回同じ講師にする",
    "same_day_repeat": "同じ科目を同じ日に固めない",
    "teacher_work_day": "講師の出勤日を少なくする",
    "student_gap": "生徒の空きコマを作らない",
}
SRC_EXCEL, SRC_GOOGLE, SRC_SAMPLE = "Excelファイル", "Googleスプレッドシート", "サンプルデータ"


def overview_html(problem, result, view: View) -> str:
    """曜日×コマの全体表。1つの授業を科目色のカードで並べる。"""
    s = problem.settings
    colors = subject_colors(problem.subjects)
    cells = {}
    for ls in result.lessons:
        t = problem.teachers[ls.teacher_id].name
        if ls.form == "集団":
            body = f"<b>{ls.class_name}</b> 集団<br>{t}・{len(ls.student_ids)}名"
        else:
            names = "、".join(student_name(problem, x, view) for x in ls.student_ids)
            body = f"<b>{ls.subject}</b> 個別<br>{t}／{names}"
        color = colors.get(ls.subject.split("・")[0], "#eee")
        room = f'<span style="opacity:.6">{ls.room}</span> ' if view.show_room else ""
        cells.setdefault(ls.slot, []).append(
            f'<div style="background:{color};color:#111;border-radius:6px;padding:4px 6px;margin:3px 0;font-size:12px">'
            f'{room}{body}</div>')
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
# 画面で保存した条件は Git で管理しない別ファイルに置く（自動pullとぶつからないように）
LOCAL_CONFIG = ROOT / LOCAL_CONFIG_NAME
settings = load_settings(CONFIG, overlay=LOCAL_CONFIG)


def google_oauth_config() -> gs.OAuthConfig | None:
    """.streamlit/secrets.toml の [google_oauth]。無ければ Google からの読み込みは出さない。"""
    try:
        return gs.OAuthConfig.from_mapping(st.secrets.get("google_oauth"))
    except Exception:  # noqa: BLE001  secrets.toml が無いとき
        return None


def google_login_link(cfg: gs.OAuthConfig) -> None:
    # 新しいタブで開くとログインが別の画面に付くので、同じタブで Google のログイン画面へ移る
    url = html.escape(gs.login_url(cfg, gs.make_state(cfg)))
    st.markdown(f'<a href="{url}" target="_self" style="display:inline-block;padding:6px 14px;border-radius:6px;'
                f'border:1px solid #aaa;text-decoration:none">Googleでログイン</a>', unsafe_allow_html=True)


def google_credentials(cfg: gs.OAuthConfig):
    token = st.session_state.get("google_token")
    return gs.credentials(cfg, token) if token else None


oauth = google_oauth_config()
# Googleのログイン画面から戻ってきたとき（URLに code と state が付く）
if oauth and "code" in st.query_params:
    if gs.check_state(oauth, st.query_params.get("state", "")):
        try:
            st.session_state["google_token"] = gs.exchange_code(oauth, st.query_params["code"])
            st.session_state["source"] = SRC_GOOGLE
        except Exception as e:  # noqa: BLE001
            st.error(f"Googleにログインできませんでした：{e}")
    else:
        st.error("ログインの有効期限が切れました。もう一度「Googleでログイン」を押してください。")
    st.query_params.clear()

source = st.radio("入力", [SRC_EXCEL, SRC_GOOGLE, SRC_SAMPLE], horizontal=True, key="source")
dfs = None
sheet_url = ""
try:
    if source == SRC_EXCEL:
        up = st.file_uploader("Excelファイル", type=["xlsx"])
        if up:
            dfs = read_xlsx(up.getvalue())
        st.caption("Googleスプレッドシートで作った場合は「ファイル → ダウンロード → Microsoft Excel」で保存してアップロードできます。")
    elif source == SRC_GOOGLE:
        if oauth is None:
            st.info("Googleログインの設定がまだです。設定方法は README の「Googleスプレッドシートから読む」を見てください。"
                    "それまではExcelファイルで読み込めます。")
        elif google_credentials(oauth) is None:
            google_login_link(oauth)
        else:
            c1, c2 = st.columns([4, 1])
            sheet_url = c1.text_input("スプレッドシートのURL")
            if c2.button("ログアウト"):
                for k in ("google_token", "google_dfs"):
                    st.session_state.pop(k, None)
                st.rerun()
            cached = st.session_state.get("google_dfs")
            if sheet_url and st.button("読み込む"):
                cached = st.session_state["google_dfs"] = (sheet_url, gs.read_sheet(google_credentials(oauth), sheet_url))
            if cached and cached[0] == sheet_url:
                dfs = cached[1]
    else:
        sample = ROOT / "sample" / "サンプル入力.xlsx"
        dfs = read_xlsx(sample)
        st.download_button("サンプル入力をダウンロード", sample.read_bytes(), sample.name)
except Exception as e:  # noqa: BLE001
    st.error(f"読み込めませんでした：{e}")
    if source == SRC_GOOGLE:
        st.caption("ログインから時間がたつと読めなくなります。ログアウトしてもう一度ログインしてください。")
# 雛形は左の条件（曜日・コマ割）が決まってから作るので、場所だけ先に取っておく
template_area = st.container()

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
        save_settings(settings, LOCAL_CONFIG)
        st.success("保存しました。次回からこの条件が最初から入ります。")

problem, notes = parse(dfs, settings, use_koma_sheet=False) if dfs is not None and not koma_errors else (None, [])
if not koma_errors:
    with template_area.expander("入力用の雛形をダウンロード"):
        st.caption("左の曜日・コマ割に合わせた空き時間表など、入力の5シートです。○は選択肢から選べます。")
        keep_people = problem is not None and st.checkbox("読み込んだ生徒・講師のIDと氏名を入れておく", True)
        st.download_button("雛形をダウンロード", make_template(settings, problem if keep_people else None),
                           "入力の雛形.xlsx")

if dfs is None or koma_errors:
    st.stop()

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

# 表示の切り替えは画面の表と書き出し（Excel・スプレッドシート）の両方に効く
c1, c2, _ = st.columns([1, 1, 2])
view = View(show_room=c1.toggle("教室を表示", True),
            show_detail=c2.toggle("学年とIDを表示", True))

tabs = st.tabs(["全体", "講師列", "生徒別", "講師別", f"未配置（{missing}）", "授業一覧"])
with tabs[0]:
    st.markdown(overview_html(problem, result, view), unsafe_allow_html=True)
with tabs[1]:
    st.dataframe(teacher_columns_grid(problem, result, view), width="stretch")
    st.caption("授業のない講師はその曜日に出しません。「予備」は手書き用の空き列です")
with tabs[2]:
    sid = st.selectbox("生徒", list(problem.students), format_func=lambda k: f"{k} {problem.students[k].name}（{problem.students[k].grade}）" if view.show_detail
                       else problem.students[k].name)
    st.dataframe(person_grid(problem, result, "student", sid, view), width="stretch")
    st.caption("－ は空き時間でないコマ")
with tabs[3]:
    tid = st.selectbox("講師", list(problem.teachers), format_func=lambda k: f"{k} {problem.teachers[k].name}" if view.show_detail
                       else problem.teachers[k].name)
    st.dataframe(person_grid(problem, result, "teacher", tid, view), width="stretch")
with tabs[4]:
    df = unassigned_table(problem, result, view)
    if df.empty:
        st.info("すべての希望が入りました。")
    else:
        st.dataframe(df, width="stretch", hide_index=True)
with tabs[5]:
    st.dataframe(lessons_table(problem, result, view), width="stretch", hide_index=True)

st.subheader("書き出し")
st.download_button("Excelでダウンロード", to_xlsx(problem, result, view), "時間割.xlsx", type="primary")
if source == SRC_GOOGLE and sheet_url and oauth and google_credentials(oauth):
    if st.button("元のGoogleスプレッドシートに書き込む"):
        try:
            gs.write_sheets(google_credentials(oauth), sheet_url, all_sheets(problem, result, view))
            st.success("「時間割_全体」などのシートを書き込みました。")
        except Exception as e:  # noqa: BLE001
            st.error(f"書き込めませんでした：{e}")
