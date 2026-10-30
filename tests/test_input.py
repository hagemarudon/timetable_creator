"""Excelの雛形と、Googleログイン（OAuth）まわりのテスト。通信はしない。"""
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from timetable import google_sheets as gs
from timetable.loader import REQUIRED_SHEETS, load_settings, parse, read_xlsx
from timetable.template import template_xlsx

ROOT = Path(__file__).parent.parent
CFG = gs.OAuthConfig("id.apps.googleusercontent.com", "secret", "http://localhost:8501")


def test_template_has_required_sheets_and_slot_columns():
    settings = load_settings(ROOT / "config.toml")
    dfs = read_xlsx(template_xlsx(settings))
    assert set(REQUIRED_SHEETS) <= set(dfs)
    slots = [s.label for s in settings.slots]
    assert list(dfs["生徒_空き時間"].columns) == ["生徒ID", "氏名", *slots]
    assert list(dfs["講師_空き時間"].columns) == ["講師ID", "氏名", *slots]
    # 空の雛形はそのまま読み込んでもエラーにならない（列が揃っている）
    problem, notes = parse(dfs, settings)
    assert problem is not None and not problem.requests


def test_template_follows_edited_komas():
    settings = load_settings(ROOT / "config.toml")
    settings.days = ["月", "水"]
    settings.komas = settings.komas[:2]
    cols = list(read_xlsx(template_xlsx(settings))["生徒_空き時間"].columns)
    assert cols == ["生徒ID", "氏名", "月1", "月2", "水1", "水2"]


def test_state_is_checked():
    state = gs.make_state(CFG, now=1000)
    assert gs.check_state(CFG, state, now=1000 + 60)
    assert not gs.check_state(CFG, state, now=1000 + gs.STATE_MAX_AGE + 1)  # 期限切れ
    assert not gs.check_state(CFG, state[:-1] + ("0" if state[-1] != "0" else "1"), now=1001)  # 改ざん
    other = gs.OAuthConfig(CFG.client_id, "other-secret", CFG.redirect_uri)
    assert not gs.check_state(other, state, now=1001)
    assert not gs.check_state(CFG, "", now=1001)


def test_login_url():
    q = parse_qs(urlparse(gs.login_url(CFG, "abc")).query)
    assert q["client_id"] == [CFG.client_id]
    assert q["redirect_uri"] == [CFG.redirect_uri]
    assert q["state"] == ["abc"]
    assert q["scope"] == [" ".join(gs.SCOPES)]


def test_config_from_mapping():
    assert gs.OAuthConfig.from_mapping({"client_id": "a", "client_secret": "b", "redirect_uri": "c"}) == \
        gs.OAuthConfig("a", "b", "c")
    assert gs.OAuthConfig.from_mapping({"client_id": "a"}) is None
    assert gs.OAuthConfig.from_mapping(None) is None


def test_values_to_frame_pads_short_rows():
    df = gs.values_to_frame([["生徒ID", "氏名", "月1"], ["S001", "佐藤"], ["S002", "鈴木", "○", "余り"]])
    assert list(df.columns) == ["生徒ID", "氏名", "月1", ""]
    assert df.iloc[0].tolist() == ["S001", "佐藤", "", ""]
    assert gs.values_to_frame([]).empty


def test_google_values_parse_like_excel():
    """Googleから読んだ表（文字列の2次元配列）を、Excelと同じように読める。"""
    settings = load_settings(ROOT / "config.toml")
    xl = read_xlsx(ROOT / "sample" / "サンプル入力.xlsx")
    as_values = {name: gs.values_to_frame([list(df.columns)] + df.fillna("").values.tolist())
                 for name, df in xl.items()}
    p1, _ = parse(xl, load_settings(ROOT / "config.toml"))
    p2, _ = parse(as_values, settings)
    assert p1.requests == p2.requests and set(p1.teachers) == set(p2.teachers)
