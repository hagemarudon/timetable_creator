"""Googleログイン（OAuth）とスプレッドシート読み込みまわりのテスト。通信はしない。"""
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd

from timetable import google_sheets as gs
from timetable.loader import load_settings, parse, read_xlsx

ROOT = Path(__file__).parent.parent
CFG = gs.OAuthConfig("id.apps.googleusercontent.com", "secret", "http://localhost:8501")


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


def test_availability_in_30min_cells():
    """空き時間を30分の枠（「月16:00」）で書くと、コマ（90分）の枠がすべて○のときだけ空きになる。"""
    from timetable.loader import _read_availability, load_settings
    from timetable.model import Slot

    settings = load_settings(Path(__file__).parent.parent / "config.toml")
    cols = ["生徒ID"] + [f"月{h}:{m}" for h in range(16, 22) for m in ("00", "30")]
    marks = {"月16:00", "月16:30", "月17:00", "月17:30", "月18:00", "月19:00", "月19:30", "月20:00"}
    df = pd.DataFrame([["S001"] + ["○" if c in marks else "" for c in cols[1:]]], columns=cols)
    errors: list[str] = []
    avail = _read_availability(df, "生徒ID", settings, "生徒_空き時間", errors)
    # 1限（16:00-17:30）と3限（19:00-20:30）は3枠そろう。2限は18:30が空いていない
    assert avail["S001"] == {Slot("月", 1), Slot("月", 3)}
    # 月以外の曜日は列が無いので注意は出さない
    assert errors == []
