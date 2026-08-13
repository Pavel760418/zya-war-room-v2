"""Режим техобслуживания: заставка для всех, кроме владельца."""
from __future__ import annotations

import ipaddress
import os
from pathlib import Path
from typing import Iterable

import streamlit as st

ASSETS = Path(__file__).resolve().parent / "assets"
SPLASH_IMAGE = ASSETS / "maintenance_fun.png"


def maintenance_enabled() -> bool:
    return (os.environ.get("WARROOM_MAINTENANCE") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _owner_key() -> str:
    return (os.environ.get("WARROOM_OWNER_KEY") or "").strip()


def _owner_ips() -> set[str]:
    raw = (os.environ.get("WARROOM_OWNER_IPS") or "127.0.0.1,::1").strip()
    return {p.strip() for p in raw.split(",") if p.strip()}


def _client_ip() -> str:
    """Best-effort client IP (Streamlit + nginx X-Forwarded-For / X-Real-IP)."""
    try:
        headers = st.context.headers  # Streamlit >= 1.37
    except Exception:  # noqa: BLE001
        headers = {}

    def _get(name: str) -> str:
        if not headers:
            return ""
        for k, v in headers.items():
            if str(k).lower() == name.lower():
                return str(v)
        return ""

    xff = _get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    xr = _get("X-Real-IP")
    if xr:
        return xr.strip()
    try:
        return str(getattr(st.context, "ip_address", "") or "")
    except Exception:  # noqa: BLE001
        return ""


def _ip_allowed(ip: str, allow: Iterable[str]) -> bool:
    if not ip:
        return False
    allow_list = list(allow)
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip in allow_list
    for item in allow_list:
        try:
            if "/" in item:
                if addr in ipaddress.ip_network(item, strict=False):
                    return True
            elif addr == ipaddress.ip_address(item):
                return True
        except ValueError:
            if ip == item:
                return True
    return False


def owner_unlocked() -> bool:
    """True if current visitor may bypass maintenance."""
    if st.session_state.get("owner_bypass") is True:
        return True
    ip = _client_ip()
    if _ip_allowed(ip, _owner_ips()):
        st.session_state["owner_bypass"] = True
        return True
    return False


def render_maintenance_splash() -> None:
    """Полноэкранная заставка «ведутся технические работы»."""
    st.markdown(
        """
<style>
  [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] { display: none !important; }
  .block-container { padding-top: 2rem; max-width: 920px; }
  .maint-title { font-size: 2rem; font-weight: 700; text-align: center; margin: 0.4rem 0 0.2rem; }
  .maint-sub { text-align: center; opacity: 0.85; font-size: 1.15rem; margin-bottom: 1rem; }
</style>
""",
        unsafe_allow_html=True,
    )
    st.markdown('<p class="maint-title">🍏 МегаМетрики на техобслуживании</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="maint-sub">Ведутся технические работы. Скоро вернёмся с ещё более точными цифрами!</p>',
        unsafe_allow_html=True,
    )
    if SPLASH_IMAGE.is_file():
        st.image(str(SPLASH_IMAGE), use_container_width=True)
    else:
        st.info("Ведутся технические работы. Зайдите позже.")

    key = _owner_key()
    if key:
        with st.expander("Вход для администратора", expanded=False):
            pwd = st.text_input("Ключ доступа", type="password", key="owner_key_input")
            if st.button("Открыть приложение", type="primary"):
                if pwd.strip() == key:
                    st.session_state["owner_bypass"] = True
                    st.rerun()
                else:
                    st.error("Неверный ключ")


def gate_or_continue() -> bool:
    """Return True if the main app may render; False if splash was shown (caller should stop)."""
    if not maintenance_enabled():
        return True
    if owner_unlocked():
        return True
    render_maintenance_splash()
    return False
