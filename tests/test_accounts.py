"""塾と利用者の登録、塾ごとの保存先の分離のテスト。"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from timetable.accounts import Juku, check_members, find_juku, juku_key, members_to_toml, parse_members  # noqa: E402
from timetable.storage import LocalStore, open_store  # noqa: E402


def test_members_round_trip_and_lookup():
    jukus = [Juku("a-juku", "A塾", ["Owner@Example.com "]), Juku("b", 'B"塾', ["b@example.com"])]
    parsed = parse_members(members_to_toml(jukus))
    assert [(j.id, j.name, j.members) for j in parsed] == [("a-juku", "A塾", ["owner@example.com"]),
                                                           ("b", 'B"塾', ["b@example.com"])]
    assert find_juku(parsed, "OWNER@example.com").id == "a-juku"
    assert find_juku(parsed, "stranger@example.com") is None


def test_check_members():
    assert check_members([Juku("a", "A", ["x@example.com"])]) == []
    assert check_members([Juku("A塾", "A")])
    assert check_members([Juku("a", "A"), Juku("a", "A2")])
    assert check_members([Juku("a", "A", ["x@example.com"]), Juku("b", "B", ["x@example.com"])])
    assert check_members([Juku("a", "A", ["not-mail"])])


def test_juku_key_rejects_other_paths():
    assert juku_key("a-juku", "config.toml") == "jukus/a-juku/config.toml"
    for bad in ["../b", "a/b", "", "A"]:
        with pytest.raises(ValueError):
            juku_key(bad, "config.toml")


def test_local_store_separates_jukus(tmp_path):
    store = open_store(str(tmp_path))
    assert isinstance(store, LocalStore)
    store.put(juku_key("a", "config.toml"), "days = ['月']")
    assert store.get(juku_key("a", "config.toml")) == "days = ['月']"
    assert store.get(juku_key("b", "config.toml")) is None
    with pytest.raises(ValueError):
        store.get("../outside.toml")
