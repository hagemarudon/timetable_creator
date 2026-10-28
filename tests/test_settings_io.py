"""画面から入力する条件（コマ割の生成・確認・保存）のテスト。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from timetable.loader import load_settings  # noqa: E402
from timetable.model import Koma  # noqa: E402
from timetable.settings_io import check_komas, describe_komas, make_komas, save_settings  # noqa: E402


def test_make_komas():
    komas = make_komas(3, "16:00", 80, 10)
    assert komas == [Koma(1, "16:00", "17:20"), Koma(2, "17:30", "18:50"), Koma(3, "19:00", "20:20")]


def test_describe_round_trip():
    komas = make_komas(5, "15:30", 60, 15)
    assert describe_komas(komas) == (5, "15:30", 60, 15)
    assert make_komas(*describe_komas(komas)) == komas


def test_check_komas():
    assert check_komas(make_komas(4, "16:00", 80, 10)) == []
    assert check_komas([Koma(1, "16:00", "15:00")])
    assert check_komas([Koma(1, "16:00", "17:00"), Koma(2, "16:30", "17:30")])
    assert check_komas([Koma(1, "4時", "17:00")])


def test_save_and_load(tmp_path):
    settings = load_settings(ROOT / "config.toml")
    settings.days = ["月", "水", "金"]
    settings.komas = make_komas(2, "17:00", 90, 0)
    settings.individual_booths = 9
    settings.group_rooms = 1
    settings.max_students_per_teacher = 3
    settings.allow_mixed_subjects = False
    settings.group_capacity = 20
    settings.weights["student_gap"] = 7
    path = tmp_path / "config.toml"
    save_settings(settings, path)
    assert load_settings(path) == settings


def test_overlay_keeps_new_base_keys(tmp_path):
    """画面で保存した条件（overlay）に無い項目は config.toml の値が使われる。"""
    from timetable.loader import load_settings

    overlay = tmp_path / "config.local.toml"
    overlay.write_text('[rooms]\nindividual_booths = 3\n\n[group]\ncapacity = 4\n', encoding="utf-8")
    base = load_settings(ROOT / "config.toml")
    merged = load_settings(ROOT / "config.toml", overlay=overlay)
    assert merged.individual_booths == 3 and merged.group_capacity == 4
    assert merged.group_rooms == base.group_rooms and merged.komas == base.komas
    assert load_settings(ROOT / "config.toml", overlay=tmp_path / "none.toml") == base


def test_saved_settings_round_trip_as_overlay(tmp_path):
    from timetable.loader import load_settings

    s = load_settings(ROOT / "config.toml")
    s.group_capacity = 4
    s.komas = make_komas(3, "17:00", 60, 10)
    overlay = tmp_path / "config.local.toml"
    save_settings(s, overlay)
    assert load_settings(ROOT / "config.toml", overlay=overlay) == s
