"""ログインと、ログインした人の塾の保存先を決める（Streamlit の画面部品つき）。

secrets.toml に [auth] があればクラウド用：Googleアカウントでログインし、members.toml に登録された塾のデータだけを使う。
[auth] がなければ手元用：ログインなしで、これまでどおり config.local.toml を使う。
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import streamlit as st

from .accounts import MEMBERS_KEY, Juku, check_members, find_juku, juku_key, members_to_toml, normalize_email, parse_members
from .loader import LOCAL_CONFIG_NAME
from .storage import LocalStore, open_store

ROOT = Path(__file__).resolve().parents[1]
LEGAL = ROOT / "legal"
LEGAL_DOCS = {"利用規約": LEGAL / "terms.md", "プライバシーポリシー": LEGAL / "privacy.md"}


@dataclass
class Account:
    """ログイン中の人と、その人が使う塾の保存先。"""

    juku: Juku
    store: object
    settings_key: str
    email: str | None = None
    cloud: bool = False

    def load_settings_overlay(self) -> dict | None:
        text = self.store.get(self.settings_key)
        return tomllib.loads(text) if text else None

    def save_settings(self, text: str) -> None:
        self.store.put(self.settings_key, text)


def _secrets_section(name: str) -> dict:
    try:
        return dict(st.secrets[name]) if name in st.secrets else {}
    except Exception:  # noqa: BLE001  secrets.toml が無いときは手元用
        return {}


def cloud_mode() -> bool:
    return bool(_secrets_section("auth"))


def show_legal() -> None:
    for title, path in LEGAL_DOCS.items():
        with st.expander(title):
            st.markdown(path.read_text(encoding="utf-8"))


def _login_screen() -> None:
    st.write("Googleアカウントでログインしてください。")
    agreed = st.checkbox("利用規約とプライバシーポリシーに同意します")
    if st.button("Googleでログイン", type="primary", disabled=not agreed):
        st.login()
    show_legal()


def _admin_panel(store, jukus: list[Juku]) -> None:
    """運営者（secrets の [app] admins）が塾と利用者を登録する。"""
    with st.expander("塾と利用者の管理（運営者のみ）"):
        st.caption("1行に1人。同じ塾IDの行は同じ塾になります。塾IDは英小文字・数字・ハイフンで、あとから変えると保存した条件が見えなくなります。")
        rows = [{"塾ID": j.id, "塾名": j.name, "メールアドレス": m} for j in jukus for m in (j.members or [""])]
        edited = st.data_editor(pd.DataFrame(rows or [{"塾ID": "", "塾名": "", "メールアドレス": ""}]),
                                num_rows="dynamic", hide_index=True, width="stretch", key="members_editor")
        new: dict[str, Juku] = {}
        for _, r in edited.fillna("").iterrows():
            jid, name, mail = str(r["塾ID"]).strip(), str(r["塾名"]).strip(), normalize_email(str(r["メールアドレス"]))
            if not jid:
                continue
            j = new.setdefault(jid, Juku(jid, name or jid))
            if mail:
                j.members.append(mail)
        errors = check_members(list(new.values()))
        for e in errors:
            st.error(e)
        if st.button("登録を保存", disabled=bool(errors)):
            store.put(MEMBERS_KEY, members_to_toml(list(new.values())))
            st.success("保存しました。")
            st.rerun()


def require_account() -> Account:
    """ログインを求め、ログインした人の塾を返す。使えないときは画面を止める。"""
    if not cloud_mode():
        if os.environ.get("TIMETABLE_REQUIRE_LOGIN"):
            # クラウドでログインの設定が抜けたまま、誰でも使える状態で公開しないため
            st.error("ログインの設定（secrets.toml の [auth]）がないため、使えません。")
            st.stop()
        local = Juku("local", "この端末")
        return Account(local, LocalStore(ROOT), LOCAL_CONFIG_NAME)

    if not st.user.get("is_logged_in", False):
        _login_screen()
        st.stop()

    email = normalize_email(st.user.get("email") or "")
    if not email or not st.user.get("email_verified", True):
        st.error("メールアドレスが確認されたGoogleアカウントでログインしてください。")
        if st.button("ログアウト"):
            st.logout()
        st.stop()
    store = open_store()
    jukus = parse_members(store.get(MEMBERS_KEY))
    admins = {normalize_email(a) for a in _secrets_section("app").get("admins", [])}
    juku = find_juku(jukus, email)

    with st.sidebar:
        st.caption(f"{juku.name if juku else '塾の登録なし'}／{email}")
        if st.button("ログアウト"):
            st.logout()
    if email in admins:
        _admin_panel(store, jukus)
    if juku is None:
        st.warning(f"{email} はまだどの塾にも登録されていません。運営者に登録を依頼してください。")
        st.stop()
    return Account(juku, store, juku_key(juku.id, "config.toml"), email=email, cloud=True)
