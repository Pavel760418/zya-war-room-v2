"""Ролевая видимость: обычный пользователь vs владелец (admin)."""
from __future__ import annotations

import os

import streamlit as st

from app.streamlit_ui.maintenance import _owner_key, owner_unlocked


def is_admin() -> bool:
    """Admin = owner bypass / session flag / URL ?admin=1 + ключ."""
    if st.session_state.get("wr_admin") is True:
        return True
    if owner_unlocked() and st.session_state.get("owner_bypass") is True:
        # Owner unlock during maintenance also grants admin for this session
        st.session_state["wr_admin"] = True
        return True
    return False


def activate_admin_from_query() -> None:
    """Спецпараметр URL: ?wr_admin=1 — показать поле пароля; успешный ввод → admin."""
    try:
        params = st.query_params
    except Exception:  # noqa: BLE001
        return
    flag = str(params.get("wr_admin", "") or params.get("admin", "") or "").strip().lower()
    if flag in {"1", "true", "yes"} and not is_admin():
        st.session_state["wr_admin_prompt"] = True


def render_admin_unlock_sidebar() -> None:
    """Компактный вход admin (только если запрошен или уже admin)."""
    key = _owner_key()
    if is_admin():
        st.caption("Роль: администратор")
        if st.button("Выйти из режима администратора", key="btn_admin_logout"):
            st.session_state["wr_admin"] = False
            st.session_state["owner_bypass"] = False
            st.rerun()
        return
    if not st.session_state.get("wr_admin_prompt") and not (
        (os.environ.get("WARROOM_SHOW_ADMIN_LOGIN") or "").strip().lower() in {"1", "true", "yes"}
    ):
        return
    with st.expander("Вход администратора", expanded=False):
        pwd = st.text_input("Ключ", type="password", key="wr_admin_key")
        if st.button("Войти", key="btn_admin_login"):
            if key and pwd.strip() == key:
                st.session_state["wr_admin"] = True
                st.session_state["owner_bypass"] = True
                st.rerun()
            else:
                st.error("Неверный ключ")


def show_risks_block() -> bool:
    """Блок «Проблемы и риски» — только admin."""
    return is_admin()


def show_tech_sidebar() -> bool:
    """Техническая панель / диагностика в sidebar — только admin."""
    return is_admin()
