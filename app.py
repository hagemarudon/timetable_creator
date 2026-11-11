"""塾の時間割作成（試作版）の画面。

起動: streamlit run app.py
"""
import html
import time
from pathlib import Path

import pandas as pd
import streamlit as st

from timetable import google_sheets as gs
from timetable.loader import SEASON_PREFIX, LOCAL_CONFIG_NAME, komas_from_sheet, load_settings, parse, read_xlsx
from timetable.model import MODE_SEASON, MODE_WEEKLY, MODES, WEEKDAYS, Koma, date_label
from timetable.output import (View, all_sheets, lessons_table, person_grid, student_name, subject_colors,
                              teacher_columns_grid, to_xlsx, unassigned_table)
from timetable.settings_io import ALL_DAYS, check_komas, check_season, describe_komas, make_komas, save_settings
from timetable.previous import kept, read_previous
from timetable.solver import diagnose, solve
from timetable.template import make_template

ROOT = Path(__file__).parent
WEIGHT_LABELS = {
    "assigned_lesson": "授業を1回入れる",
    "preferred_teacher": "希望講師に当てる",
    "same_teacher": "個別は毎回同じ講師にする",
    "same_day_repeat": "同じ科目を同じ日に固めない",
    "teacher_work_day": "講師の出勤日を少なくする",
    "student_gap": "生徒の空きコマを作らない",
    "keep_previous": "前回の時間割と同じコマにする",
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


def diagnosis_section(problem, result, view: View) -> None:
    """必須条件を1つずつ外して解き直し、どの条件のせいで入らないかを表にする。"""
    st.markdown("#### 入らない理由を調べる")
    per_run = min(10, int(problem.settings.time_limit_seconds))
    st.caption(f"必須条件を1つずつ外して作り直し、何コマ増えるかを比べます（1つにつき最大{per_run}秒）。")
    if st.button("調べる"):
        bar = st.progress(0.0)
        found = diagnose(problem, result, per_run,
                         lambda i, n, label: bar.progress(i / n, text=f"「{label}」を外して計算中…"))
        bar.empty()
        st.session_state["diagnosis"] = found
    found = st.session_state.get("diagnosis")
    if found is None:
        return
    rows = [{
        "外した条件": d.label,
        "増えるコマ": d.gained,
        "入るようになる授業": "、".join(f"{student_name(problem, r.student_id, view)} {r.subject}（{r.form}）"
                                  for r in d.newly_placed),
    } for d in found]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    best = found[0] if found and found[0].gained else None
    if best:
        st.info(f"「{best.label}」が一番の原因です。外すと {best.gained} コマ増えます。")
    else:
        st.info("どれか1つの条件を外しても増えません。生徒・講師の空き時間が足りないか、複数の条件が重なっています。")
    st.caption("計算時間を区切っているため、増えるコマは目安です。")


st.set_page_config(page_title="塾の時間割作成", layout="wide")

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


# Googleのログインから戻るとセッションが新しくなるので、ホームで選んだ種類を state に入れて持ち帰る
MODE_CODES = {MODE_WEEKLY: "w", MODE_SEASON: "s"}


def google_login_link(cfg: gs.OAuthConfig) -> None:
    # 新しいタブで開くとログインが別の画面に付くので、同じタブで Google のログイン画面へ移る
    state = gs.make_state(cfg, extra=MODE_CODES.get(st.session_state.get("mode"), ""))
    url = html.escape(gs.login_url(cfg, state))
    st.markdown(f'<a href="{url}" target="_self" style="display:inline-block;padding:6px 14px;border-radius:6px;'
                f'border:1px solid #aaa;text-decoration:none">Googleでログイン</a>', unsafe_allow_html=True)


def google_credentials(cfg: gs.OAuthConfig):
    token = st.session_state.get("google_token")
    return gs.credentials(cfg, token) if token else None


oauth = google_oauth_config()
# Googleのログイン画面から戻ってきたとき（URLに code と state が付く）
if oauth and "code" in st.query_params:
    if gs.check_state(oauth, st.query_params.get("state", "")):
        code = gs.state_extra(st.query_params.get("state", ""))
        st.session_state["mode"] = next((m for m, c in MODE_CODES.items() if c == code), None)
        try:
            st.session_state["google_token"] = gs.exchange_code(oauth, st.query_params["code"])
            st.session_state["source"] = SRC_GOOGLE
        except Exception as e:  # noqa: BLE001
            st.error(f"Googleにログインできませんでした：{e}")
    else:
        st.error("ログインの有効期限が切れました。もう一度「Googleでログイン」を押してください。")
    st.query_params.clear()

def go_home() -> None:
    for k in ("mode", "result", "diagnosis", "previous_used"):
        st.session_state.pop(k, None)


def home() -> None:
    """アプリを開いたときの画面。通常授業（毎週の時間割）か講習（日付ごとの時間割）かを選ぶ。"""
    st.title("塾の時間割作成")
    st.subheader("どちらの時間割を作りますか？")
    choices = [
        (MODE_WEEKLY, "毎週同じ曜日・時間の時間割",
         "読み込むもの：名前に「講習」が入っていないフォームの回答・シート"),
        (MODE_SEASON, f"{settings.season.name}など、日付ごとに違う時間割",
         "読み込むもの：名前に「講習」が入ったフォームの回答・シート（講習_生徒_受講希望 など）"),
    ]
    for col, (mode, what, reads) in zip(st.columns(2), choices):
        with col.container(border=True):
            st.markdown(f"### {mode}")
            st.write(what)
            st.caption(reads)
            if st.button(f"{mode}の時間割を作る", key=f"home_{mode}", type="primary", width="stretch"):
                st.session_state["mode"] = mode
                st.rerun()


if st.session_state.get("mode") not in MODES:
    home()
    st.stop()
settings.mode = st.session_state["mode"]

c1, c2 = st.columns([5, 1], vertical_alignment="center")
c1.title(f"{settings.season.name}の時間割" if settings.is_season else "通常授業の時間割")
c2.button("ホームに戻る", on_click=go_home, width="stretch")

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
        # サンプルは時間割の種類に合わせる（講習は日付ごとの空き時間）
        sample = ROOT / "sample" / ("サンプル入力_講習期.xlsx" if settings.is_season else "サンプル入力.xlsx")
        dfs = read_xlsx(sample)
        st.download_button("サンプル入力をダウンロード", sample.read_bytes(), sample.name)
except Exception as e:  # noqa: BLE001
    st.error(f"読み込めませんでした：{e}")
    if source == SRC_GOOGLE:
        st.caption("ログインから時間がたつと読めなくなります。ログアウトしてもう一度ログインしてください。")
# 雛形は左の条件（曜日・コマ割）が決まってから作るので、場所だけ先に取っておく
template_area = st.container()

with st.sidebar:
    st.header("条件")
    season_errors: list[str] = []
    if settings.is_season:
        st.subheader("講習の期間")
        season = settings.season
        season.name = st.text_input("講習の名前", season.name)
        season.start = st.date_input("初日", season.start, format="YYYY/MM/DD")
        season.end = st.date_input("最終日", season.end, format="YYYY/MM/DD")
        season.closed_weekdays = st.multiselect("休みの曜日", WEEKDAYS,
                                                default=[d for d in WEEKDAYS if d in season.closed_weekdays])
        open_by_weekday = [d for d in season.all_dates() if WEEKDAYS[d.weekday()] not in season.closed_weekdays]
        season.closed_dates = st.multiselect("休みの日（年末年始・お盆など）", open_by_weekday,
                                             default=[d for d in season.closed_dates if d in open_by_weekday],
                                             format_func=date_label)
        season_errors = check_season(season)
        for err in season_errors:
            st.error(err)
        if not season_errors:
            st.caption(f"授業をする日：{len(season.dates())}日（{'・'.join(season.days)}）")
    else:
        st.subheader("曜日")
        settings.days = st.multiselect("開講曜日", ALL_DAYS, default=[d for d in ALL_DAYS if d in settings.days]) or settings.days

# 入力に「コマ設定」シートがあれば、そのコマ割を入力欄の初期値にする
sheet_komas = komas_from_sheet(dfs, settings.is_season) if dfs is not None else None
base_komas = sheet_komas or settings.komas
k_count, k_start, k_len, k_break = describe_komas(base_komas)

with st.sidebar:
    st.subheader("コマ割" + (f"（{settings.season.name}）" if settings.is_season else ""))
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
        hide_index=True, disabled=["コマ"], width="stretch",
        key=f"komas_{settings.mode}_{count}_{start}_{length}_{brk}",
    )
    settings.komas = [Koma(int(r["コマ"]), str(r["開始"]), str(r["終了"])) for _, r in edited.iterrows()]
    first_day = settings.days[0] if settings.days else "月"
    st.caption(f"時刻はコマごとに表で直せます。生徒・講師の空き時間シートの列（{first_day}1, {first_day}2 …）は"
               "このコマ割に合わせてください。")
    koma_errors = check_komas(settings.komas) + season_errors
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
            w[key] = st.number_input(label, 0, 1000, w.get(key, 0), key=f"w_{key}")
    settings.time_limit_seconds = st.number_input("計算時間の上限（秒）", 5, 600, int(settings.time_limit_seconds))

    if st.button("この条件を既定にする", disabled=bool(koma_errors),
                 help="通常授業と講習の条件を両方とも保存します。"):
        save_settings(settings, LOCAL_CONFIG)
        st.success("保存しました。次回からこの条件が最初から入ります。")

problem, notes = parse(dfs, settings, use_koma_sheet=False) if dfs is not None and not koma_errors else (None, [])
if not koma_errors:
    with template_area.expander("入力用の雛形をダウンロード"):
        st.caption(("左の講習の期間（日付）" if settings.is_season else "左の曜日")
                   + "・コマ割に合わせた空き時間表など、入力の5シートです。○は選択肢から選べます。")
        keep_people = problem is not None and st.checkbox("読み込んだ生徒・講師のIDと氏名を入れておく", True)
        st.download_button("雛形をダウンロード", make_template(settings, problem if keep_people else None),
                           f"{settings.season.name}_入力の雛形.xlsx" if settings.is_season else "入力の雛形.xlsx")

if dfs is None or koma_errors:
    st.stop()

if notes:
    mode_mismatch = any("ホームで" in n for n in notes)
    with st.expander(f"入力の確認（{len(notes)}件）", expanded=problem is None or mode_mismatch):
        for n in notes:
            st.warning(n)
if problem is None:
    st.stop()

c1, c2, c3 = st.columns(3)
c1.metric("生徒", f"{len(problem.students)}人")
c2.metric("講師", f"{len(problem.teachers)}人")
c3.metric(f"希望コマ数（{problem.settings.period}）", sum(r.times for r in problem.requests))

previous = None
with st.expander("今の時間割をなるべく変えずに作り直す"):
    st.caption("このアプリで前回書き出した時間割のExcelを選ぶと、前回と同じコマ（できれば同じ講師）に入れることを優先します。"
               "どれだけ優先するかは左の「優先条件の重み」で変えられます。")
    prev_file = st.file_uploader("前回の時間割（Excel）", type=["xlsx"], key="previous")
    if prev_file:
        try:
            previous = read_previous(prev_file.getvalue())
            st.success(f"前回の授業 {len(previous)} 件を読み込みました。")
        except Exception as e:  # noqa: BLE001
            st.error(f"読み込めませんでした：{e}")

if st.button("時間割を作る", type="primary"):
    with st.spinner("時間割を計算中…"):
        t0 = time.time()
        st.session_state["result"] = (problem, solve(problem, previous=previous), time.time() - t0)
        st.session_state["previous_used"] = previous
        st.session_state.pop("diagnosis", None)

# 時間割の種類を切り替えたら、前の種類で作った結果は出さない
if "result" in st.session_state and st.session_state["result"][0].settings.mode != settings.mode:
    for k in ("result", "diagnosis", "previous_used"):
        st.session_state.pop(k, None)
if "result" not in st.session_state:
    st.stop()

problem, result, elapsed = st.session_state["result"]
total = sum(r.times for r in problem.requests)
missing = sum(u.missing for u in result.unassigned)
if result.lessons or not result.unassigned:
    st.success(f"{result.status}（{elapsed:.1f}秒）：希望 {total} コマ中 {total - missing} コマを配置しました。")
else:
    st.error(f"{result.status}（{elapsed:.1f}秒）：{result.unassigned[0].reason}。"
             "「未配置」の「入らない理由を調べる」で、どの条件が原因かを確かめられます。")
if prev := st.session_state.get("previous_used"):
    same, still = kept(prev, problem, result)
    st.info(f"前回の授業 {still} 件のうち {same} 件が前回と同じコマです。")

# 表示の切り替えは画面の表と書き出し（Excel・スプレッドシート）の両方に効く
c1, c2, _ = st.columns([1, 1, 2])
view = View(show_room=c1.toggle("教室を表示", True),
            show_detail=c2.toggle("学年とIDを表示", True))

tabs = st.tabs(["全体", "講師列", "生徒別", "講師別", f"未配置（{missing}）", "授業一覧"])
with tabs[0]:
    st.markdown(overview_html(problem, result, view), unsafe_allow_html=True)
with tabs[1]:
    st.dataframe(teacher_columns_grid(problem, result, view), width="stretch")
    st.caption(f"授業のない講師はその{'日' if problem.settings.is_season else '曜日'}に出しません。「予備」は手書き用の空き列です")
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
        diagnosis_section(problem, result, view)
with tabs[5]:
    st.dataframe(lessons_table(problem, result, view), width="stretch", hide_index=True)

st.subheader("書き出し")
st.download_button("Excelでダウンロード", to_xlsx(problem, result, view),
                   f"{problem.settings.season.name}_時間割.xlsx" if problem.settings.is_season else "時間割.xlsx",
                   type="primary")
if source == SRC_GOOGLE and sheet_url and oauth and google_credentials(oauth):
    if st.button("元のGoogleスプレッドシートに書き込む"):
        try:
            # 講習の結果は「講習_時間割_全体」などにして、通常授業の結果を上書きしない
            prefix = SEASON_PREFIX if problem.settings.is_season else ""
            gs.write_sheets(google_credentials(oauth), sheet_url,
                            {prefix + k: v for k, v in all_sheets(problem, result, view).items()})
            st.success(f"「{prefix}時間割_全体」などのシートを書き込みました。")
        except Exception as e:  # noqa: BLE001
            st.error(f"書き込めませんでした：{e}")
