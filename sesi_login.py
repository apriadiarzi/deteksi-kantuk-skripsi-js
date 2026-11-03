"""Login yang bertahan walau sesi Streamlit berganti.

Streamlit 1.17 membuat sesi baru setiap kali websocket tersambung ulang (halaman dimuat ulang, layar
ponsel mati, pindah aplikasi, sinyal putus), dan st.session_state ikut hilang. Karena itu token login
disimpan di localStorage browser lewat komponen kecil (components/penyimpanan_login), lalu divalidasi
ulang ke database di awal setiap sesi baru. Token tidak pernah lewat URL.
"""
import os
import secrets

import streamlit as st
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh

from database import (
    AUTH_STORAGE_KEY, GUEST_COOKIE_VALUE, GUEST_STORAGE_KEY,
    get_username_by_token, set_session_token,
)

_komponen = components.declare_component(
    "penyimpanan_login",
    path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "components", "penyimpanan_login"),
)

# Komponen tidak punya tampilan; elemennya dikeluarkan dari tata letak supaya tidak menambah jarak.
# Disisipkan ke CSS tiap halaman.
CSS = """
.element-container:has(iframe[src*="penyimpanan_login"]) {
    position: absolute; width: 0; height: 0; overflow: hidden;
}
"""


def akun():
    """Login sesi ini: nama akun, GUEST_COOKIE_VALUE (tamu), atau None."""
    return st.session_state.get("auth_user") or None


def perlu_dipulihkan():
    """True kalau sesi ini baru dan login belum dipulihkan dari browser."""
    return "auth_user" not in st.session_state


def _tunda_tulis(nilai):
    # Ditulis komponen di render berikutnya dan diulang sampai komponen melaporkan sudah ditulis.
    st.session_state["token_tertunda"] = {"id": secrets.token_hex(4), "nilai": nilai}


def atur_login(username):
    """Catat login di sesi ini dan di browser: nama akun, GUEST_COOKIE_VALUE, atau "" untuk keluar.

    Keluar hanya menghapus token di browser ini, jadi perangkat lain dengan akun yang sama tetap masuk.
    """
    st.session_state["auth_user"] = username
    if username == GUEST_COOKIE_VALUE:
        _tunda_tulis(GUEST_COOKIE_VALUE)
    elif username:
        _tunda_tulis(set_session_token(username))
    else:
        _tunda_tulis(None)


def pulihkan_login(baca_tamu=False):
    """Render komponen penyimpanan dan pulihkan login di awal sesi baru.

    Dipanggil di setiap halaman setelah set_page_config. Skrip dihentikan selama isi localStorage
    belum terbaca atau database belum bisa dihubungi. Mengembalikan laporan komponen
    ({"sesi", "token", "ditulis"}, plus "tamu" = daftar sesi tamu kalau baca_tamu=True) atau None.
    """
    ss = st.session_state
    if not ss.get("url_dibersihkan"):
        # Versi sebelumnya menitipkan token di URL (?authtok=…); dibuang supaya tidak ikut tersalin.
        ss["url_dibersihkan"] = True
        if st.experimental_get_query_params():
            st.experimental_set_query_params()

    if "penyimpanan_sesi" not in ss:
        # Penanda sesi: komponen yang tidak dipasang ulang saat websocket tersambung ulang tetap
        # mengirim laporan baru ke sesi yang baru.
        ss["penyimpanan_sesi"] = secrets.token_hex(4)
    tertunda = ss.get("token_tertunda")
    isi = _komponen(
        key="penyimpanan_login",
        sesi=ss["penyimpanan_sesi"],
        kunci=AUTH_STORAGE_KEY,
        tulis=tertunda,
        kunci_tamu=GUEST_STORAGE_KEY if baca_tamu else None,
        default=None,
    )
    if isi and tertunda and isi.get("ditulis") == tertunda["id"]:
        ss.pop("token_tertunda", None)

    if not perlu_dipulihkan():
        return isi
    if isi is None:
        st.caption("Memuat sesi...")
        st.stop()

    token = isi.get("token")
    if token == GUEST_COOKIE_VALUE:
        ss["auth_user"] = GUEST_COOKIE_VALUE
    elif token:
        try:
            nama = get_username_by_token(token)
        except Exception as e:
            # Database belum bisa dihubungi (mis. Neon baru bangun): coba lagi, jangan dikeluarkan.
            print(f"Gagal memulihkan login: {e}")
            st.caption("Tidak bisa menghubungi server. Mencoba lagi...")
            st_autorefresh(interval=3000, key="pulihkan_login_ulang")
            st.stop()
        ss["auth_user"] = nama or ""
        if not nama:
            _tunda_tulis(None)  # token sudah tidak berlaku
    else:
        ss["auth_user"] = ""
    # Jalankan ulang supaya set_page_config (mis. sidebar) mengikuti status login yang baru.
    st.experimental_rerun()
