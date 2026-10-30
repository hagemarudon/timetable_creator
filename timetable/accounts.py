"""塾と利用者（ログインできるメールアドレス）の登録。

登録は保存先の members.toml に置く：

    [[juku]]
    id = "sample"            # 英小文字・数字・ハイフン。保存先のフォルダ名になる
    name = "サンプル塾"
    members = ["owner@example.com", "staff@example.com"]

1つのメールアドレスは1つの塾にだけ登録できる。ログインした人は、自分の塾の保存先（jukus/<id>/）だけを読み書きする。
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field

MEMBERS_KEY = "members.toml"
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


@dataclass
class Juku:
    id: str
    name: str
    members: list[str] = field(default_factory=list)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def juku_key(juku_id: str, name: str) -> str:
    """塾ごとの保存先の場所。ほかの塾の場所は作れないよう、IDを確かめてから組み立てる。"""
    if not ID_PATTERN.match(juku_id):
        raise ValueError(f"塾IDが正しくありません：{juku_id}")
    return f"jukus/{juku_id}/{name}"


def parse_members(text: str | None) -> list[Juku]:
    if not text:
        return []
    data = tomllib.loads(text)
    return [Juku(str(j["id"]), str(j.get("name", j["id"])), [normalize_email(m) for m in j.get("members", [])])
            for j in data.get("juku", [])]


def check_members(jukus: list[Juku]) -> list[str]:
    """IDの書式・重複と、同じメールアドレスが複数の塾に入っていないかを確かめる。"""
    errors = []
    ids: set[str] = set()
    owner: dict[str, str] = {}
    for j in jukus:
        if not ID_PATTERN.match(j.id):
            errors.append(f"塾ID「{j.id}」は英小文字・数字・ハイフンで40文字までにしてください。")
        if j.id in ids:
            errors.append(f"塾ID「{j.id}」が重複しています。")
        ids.add(j.id)
        for m in j.members:
            if "@" not in m:
                errors.append(f"「{m}」はメールアドレスではないようです。")
            elif m in owner and owner[m] != j.id:
                errors.append(f"{m} が「{owner[m]}」と「{j.id}」の両方に登録されています。")
            owner.setdefault(m, j.id)
    return errors


def members_to_toml(jukus: list[Juku]) -> str:
    def q(s: str) -> str:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

    lines = ["# 塾と、ログインできるメールアドレス（画面の「塾と利用者の管理」で保存）", ""]
    for j in jukus:
        members = ", ".join(q(m) for m in j.members)
        lines += ["[[juku]]", f"id = {q(j.id)}", f"name = {q(j.name)}", f"members = [{members}]", ""]
    return "\n".join(lines)


def find_juku(jukus: list[Juku], email: str) -> Juku | None:
    email = normalize_email(email)
    return next((j for j in jukus if email in j.members), None)
