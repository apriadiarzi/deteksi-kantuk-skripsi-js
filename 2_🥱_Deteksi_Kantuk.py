import re
import random
import string
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import streamlit as st
from streamlit_autorefresh import st_autorefresh

import detektor
import sesi_login
from database import (
    create_db, add_user, check_username_exists, check_login,
    save_otp, verify_otp, get_user_email,
    resolve_guest_user, GUEST_COOKIE_VALUE,
)
from hashlib import sha256
from decouple import config
import time

create_db()

# ── Konstanta email pengirim ──────────────────────────────────────────────────
EMAIL_SENDER   = "deteksikantuk@gmail.com"
EMAIL_PASSWORD = config('EMAIL_PASSWORD')

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def is_valid_email(value: str) -> bool:
    return bool(EMAIL_RE.match(value))

# ── Kirim OTP ─────────────────────────────────────────────────────────────────
def generate_otp(length=6):
    return ''.join(random.choices(string.digits, k=length))

def send_otp_email(to_email: str, otp_code: str, username: str):
    try:
        msg = MIMEMultipart()
        msg['From']    = EMAIL_SENDER
        msg['To']      = to_email
        msg['Subject'] = "🔐 Kode Verifikasi Sistem Pendeteksi Kantuk"
        body = (
            f"Seseorang dengan username '{username}' mendaftarkan email ini sebagai "
            f"kontak darurat pada Sistem Pendeteksi Kantuk.\n\n"
            f"Kode verifikasi kamu:\n\n"
            f"{otp_code}\n\n"
            f"Kode ini berlaku selama 10 menit.\n"
            f"Jika kamu tidak merasa mendaftar, abaikan email ini.\n\n"
            f"— Sistem Pendeteksi Kantuk"
        )
        msg.attach(MIMEText(body, 'plain'))
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"Gagal kirim OTP: {e}")
        return False

# ── CSS ────────────────────────────────────────────────────────────────────────
# Tema gelap dengan satu warna aksen amber.
BG_COLOR = "#123A63"

MOBILE_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&display=swap');

:root {
    --bg:         __BG_COLOR__;
    --surface:    #17477A;
    --border:     rgba(255,255,255,0.10);
    --fg:         #f5f4f0;
    --muted:      #9FB3C8;
    --accent:     #ff8a1e;
    --accent-fg:  #16110a;
    --radius-sm:  6px;
    --radius-md:  10px;
}

html, body, [class*="css"] { font-family: 'Inter', sans-serif; color: var(--fg); }
h1, h2, h3 { font-family: 'Space Grotesk', sans-serif; }

/* Buang chrome bawaan Streamlit */
#MainMenu, footer, [data-testid="stToolbar"] { visibility: hidden; }
[data-testid="stHeader"] { background: transparent; }
[data-testid="stDecoration"] { display: none; }

/* Background: warna dasar + dot-grid halus dan sorotan di tengah atas. */
[data-testid="stAppViewContainer"] {
    background-color: var(--bg);
    background-image:
        radial-gradient(ellipse at 50% 0%, rgba(255,255,255,0.055), transparent 62%),
        radial-gradient(rgba(255,255,255,0.05) 1px, transparent 1px);
    background-size: 100% 100%, 22px 22px;
    background-attachment: fixed;
}
[data-testid="stAppViewContainer"] > .main > div {
    padding: 1.5rem 2rem 3rem 2rem !important;
    max-width: 860px;
    margin: 0 auto;
}
[data-testid="stSidebar"] { background: var(--surface); border-right: 1px solid var(--border); }

/* Identitas sidebar dalam satu blok. */
.side-user {
    font-weight: 600;
    font-size: 0.95rem;
    padding-bottom: 0.7rem;
    margin-bottom: 0.7rem;
    border-bottom: 1px solid var(--border);
}

/* ── Header ───────────────────────────────────────────────── */
.app-header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 12px;
    padding-bottom: 1rem;
    margin-bottom: 1.75rem;
    border-bottom: 1px solid var(--border);
}
.app-header h1 {
    margin: 0;
    font-size: 1.3rem;
    font-weight: 700;
    letter-spacing: -0.01em;
}
.app-header p { margin: 2px 0 0 0; font-size: 0.85rem; color: var(--muted); }

/* ── Section — pengganti "card" berat, cukup garis & label ─── */
.section-label {
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--muted);
    margin: 0 0 0.75rem 0;
}
/* ── Tombol — default: outline (aksi sekunder) ──────────────── */
.stButton > button {
    width: 100%;
    height: 2.6rem;
    font-family: 'Inter', sans-serif;
    font-size: 0.9rem;
    font-weight: 600;
    white-space: nowrap;
    border-radius: var(--radius-sm);
    cursor: pointer;
    background: transparent;
    border: 1px solid var(--border);
    transition: border-color 0.15s ease, background 0.15s ease;
}
.stButton > button, .stButton > button p { color: var(--fg) !important; }
.stButton > button:hover { border-color: var(--fg); background: rgba(255,255,255,0.04); }
.stButton > button:disabled { opacity: 0.45; cursor: not-allowed; }

/* Tombol utama — ditandai marker tak-terlihat sebelum tombolnya */
.element-container:has(.btn-primary-marker) + .element-container .stButton > button {
    background: var(--accent);
    border-color: var(--accent);
}
.element-container:has(.btn-primary-marker) + .element-container .stButton > button,
.element-container:has(.btn-primary-marker) + .element-container .stButton > button p {
    color: var(--accent-fg) !important;
}
.element-container:has(.btn-primary-marker) + .element-container .stButton > button:hover {
    background: #ffa347;
    border-color: #ffa347;
}

/* Tombol bergaya teks bergaris bawah (mis. "Ganti email", "Kirim ulang") */
.element-container:has(.btn-link-marker) + .element-container .stButton,
.element-container:has(.btn-link-marker-right) + .element-container .stButton {
    width: auto;
    display: inline-block;
}
.element-container:has(.btn-link-marker) + .element-container .stButton > button,
.element-container:has(.btn-link-marker-right) + .element-container .stButton > button {
    width: auto;
    height: auto;
    padding: 0;
    background: transparent !important;
    border: none;
    color: var(--muted) !important;
    text-decoration: underline;
    text-underline-offset: 2px;
    font-weight: 500;
    font-size: 0.85rem;
    white-space: nowrap;
}
.element-container:has(.btn-link-marker) + .element-container .stButton > button p,
.element-container:has(.btn-link-marker-right) + .element-container .stButton > button p {
    color: var(--muted) !important;
}
.element-container:has(.btn-link-marker) + .element-container .stButton > button:hover,
.element-container:has(.btn-link-marker-right) + .element-container .stButton > button:hover {
    text-decoration: none;
    background: transparent !important;
    border: none;
    color: var(--fg) !important;
}
.element-container:has(.btn-link-marker) + .element-container .stButton > button:hover p,
.element-container:has(.btn-link-marker-right) + .element-container .stButton > button:hover p {
    color: var(--fg) !important;
}
.element-container:has(.btn-link-marker-right) + .element-container { text-align: right; }

/* Rapatkan gap sebelum tombol link (mis. "Ganti email" nempel ke teks di atasnya) */
.element-container:has(.btn-link-marker) {
    margin-top: -10px;
    margin-bottom: -14px;
}

/* ── Input field ─────────────────────────────────────────── */
input[type="text"], input[type="password"], input[type="number"],
[data-testid="stTextInput"] input {
    background: transparent !important;
    color: var(--fg) !important;
    border: 1px solid var(--border) !important;
    font-size: 1rem !important;
    height: 2.6rem !important;
    border-radius: var(--radius-sm) !important;
}
[data-testid="stTextInput"] input:focus { border-color: var(--accent) !important; }
[data-testid="stTextInput"] input::placeholder { color: var(--muted) !important; }

/* Validasi field inline: border merah dan teks error di bawah field. */
.element-container:has(.field-error-marker) + .element-container [data-testid="stTextInput"] input {
    border-color: #ff5c5c !important;
}
.field-error-text {
    margin: -12px 0 10px 0;
    font-size: 0.8rem;
    color: #ff5c5c;
}

/* Ikon show/hide password — center-kan vertikal di dalam kotak input */
[data-testid="stTextInput"] div[data-baseweb="base-input"] {
    display: flex;
    align-items: center;
}
div[data-baseweb="input"].st-ck, div[data-baseweb="input"].st-cm {
    padding-right: 0px !important;
}
[data-testid="stTextInput"] button {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
}

/* ── Slider ───────────────────────────────────────────────── */
[data-baseweb="slider"] [role="slider"] { background: var(--accent) !important; }

/* ── Auth (Masuk / Daftar / OTP) ─────────────────────────── */
.auth-title {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.5rem;
    font-weight: 700;
    margin-bottom: 0.2rem;
    text-align: center;
    color: var(--fg);
}
.auth-subtitle {
    font-size: 0.85rem;
    color: var(--muted);
    text-align: center;
    margin-bottom: 1.75rem;
}

/* ── Alert box ───────────────────────────────────────────── */
[data-testid="stAlert"] { border-radius: var(--radius-sm); }

/* ── Mobile ──────────────────────────────────────────────── */
@media (max-width: 768px) {
    [data-testid="stAppViewContainer"] > .main > div {
        padding: 1rem 1rem 2rem 1rem !important;
    }
    [data-testid="column"] {
        width: 100% !important;
        flex: 1 1 100% !important;
        min-width: 100% !important;
    }
    .stButton > button { height: 3rem; font-size: 1rem; }
    input[type="text"], input[type="password"] {
        height: 3rem !important;
        font-size: 1rem !important;
    }
    .auth-title { font-size: 1.3rem; }
    .app-header h1 { font-size: 1.1rem; }
}
__CSS_PENYIMPANAN_LOGIN__
</style>
""".replace("__BG_COLOR__", BG_COLOR).replace("__CSS_PENYIMPANAN_LOGIN__", sesi_login.CSS)

# ─── App ─────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Sistem Pendeteksi Kantuk",
    page_icon="https://cdn-icons-png.flaticon.com/512/1464/1464723.png",
    layout="wide",
    # auto: terbuka di desktop, tertutup di ponsel supaya tidak menutupi kamera.
    initial_sidebar_state="auto" if sesi_login.akun() else "collapsed",
)
st.markdown(MOBILE_CSS, unsafe_allow_html=True)

# Login dipulihkan dari token di browser setiap kali sesi Streamlit baru dimulai (lihat sesi_login.py).
sesi_login.pulihkan_login()

user, is_guest = resolve_guest_user(sesi_login.akun())
logged_in = bool(user or is_guest)

# ══════════════════════════════════════════════════════════════════════════════
# SUDAH LOGIN / TAMU
# ══════════════════════════════════════════════════════════════════════════════
if logged_in:
    display_name = user or "Tamu"

    # Email tujuan alarm (tamu tidak punya).
    if is_guest:
        recipient_emails = []
    else:
        # Email tujuan di-cache per user.
        if st.session_state.get("email_recipient_for") != user:
            try:
                recipient_email = get_user_email(user)
            except Exception as e:
                # Gagal ambil email: lanjut tanpa notifikasi email.
                print(f"Gagal ambil email penerima: {e}")
                recipient_email = None
            else:
                # Tandai cache hanya setelah query berhasil.
                st.session_state["email_recipient_for"] = user
            st.session_state["email_recipient_cached"] = [recipient_email] if recipient_email else []
        recipient_emails = st.session_state.get("email_recipient_cached", [])

    # Pesan dari komponen detektor diproses sebelum apa pun dirender (lihat detektor.py).
    detektor.proses_pesan(user, is_guest, recipient_emails)

    with st.sidebar:
        st.markdown(f'<div class="side-user">{display_name}</div>', unsafe_allow_html=True)

        if st.button("Keluar"):
            # Sesi yang masih berjalan disimpan dulu sebelum logout.
            detektor.tutup_sesi_aktif(is_guest)
            sesi_login.atur_login("")
            st.experimental_rerun()

    st.markdown("""
    <div class="app-header">
        <div>
            <h1>Pendeteksi Kantuk</h1>
            <p>Pada pengendara roda empat</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Ambang batas sensor — 1 kolom di mobile, 2 kolom di desktop
    st.markdown('<p class="section-label">Sensitivitas Deteksi</p>', unsafe_allow_html=True)
    s1, s2 = st.columns(2)
    with s1:
        WAIT_TIME = st.slider("Waktu alarm menyala (detik):", 0.0, 5.0, 1.0, 0.25,
            help="Berapa lama kondisi kantuk berlangsung sebelum alarm berbunyi. "
                 "Berlaku untuk semua jenis deteksi. "
                 "Referensi: Albadawi et al. (2023) menganggap mata tertutup ≥ 0,4–0,5 detik "
                 "sebagai kedipan mengantuk; Florez et al. (2024) membunyikan alarm setelah "
                 "mata tertutup > 0,3 detik.")
        MAR_THRESH = st.slider("Ambang batas mulut (menguap):", 0.3, 1.0, 0.6, 0.01,
            help="Nilai MAR di atas threshold = mulut terbuka lebar = menguap. "
                 "Referensi: Albadawi et al. (2023) memakai 0,5; Baul et al. (2025) memakai "
                 "0,65 pada MediaPipe Face Mesh. Default 0,6 berada di antara keduanya.")
    with s2:
        EAR_THRESH = st.slider("Ambang batas mata (tertutup):", 0.0, 0.4, 0.23, 0.01,
            help="Nilai EAR di bawah threshold = mata tertutup = mengantuk. "
                 "Referensi: Dewi et al. (2022) mendapati 0,18 sebagai ambang optimal; "
                 "Albadawi et al. (2023) memakai 0,2; Baul et al. (2025) memakai 0,22 "
                 "pada MediaPipe Face Mesh.")
        TILT_THRESH = st.slider("Ambang batas kemiringan kepala (°):", 5.0, 45.0, 20.0, 1.0,
            help="Sudut kemiringan kepala dari posisi tegak. "
                 "Referensi: Baul et al. (2025) memakai ±20° pada MediaPipe Face Mesh.")

    thresholds = {
        "EAR_THRESH": EAR_THRESH, "WAIT_TIME": WAIT_TIME,
        "MAR_THRESH": MAR_THRESH, "TILT_THRESH": TILT_THRESH,
    }

    # Kamera, deteksi, alarm, dan anotasi berjalan di browser; lihat components/detektor.
    detektor.render(user, is_guest, recipient_emails, thresholds)

# ══════════════════════════════════════════════════════════════════════════════
# BELUM LOGIN
# ══════════════════════════════════════════════════════════════════════════════
else:
    # Sembunyikan Histori dari sidebar
    st.markdown("""
    <style>
    [data-testid="stSidebarNav"] ul li:nth-child(2) { display: none; }
    </style>
    """, unsafe_allow_html=True)

    if 'page' not in st.session_state:
        st.session_state['page'] = 'daftar'

    # ── MASUK ─────────────────────────────────────────────────────────────────
    if st.session_state['page'] == 'masuk':
        _, auth_col, _ = st.columns([1, 1.4, 1])
        with auth_col:
            st.markdown('<div class="auth-title">Masuk</div><div class="auth-subtitle">Sistem Pendeteksi Kantuk</div>', unsafe_allow_html=True)

            username = st.text_input("Username", placeholder="Masukkan username kamu")
            password = st.text_input("Password", type="password", placeholder="Masukkan password kamu")

            logging_in = st.session_state.get('logging_in', False)

            st.markdown('<div class="btn-primary-marker"></div>', unsafe_allow_html=True)
            if logging_in:
                st.button("Memproses...", disabled=True, key="login_btn_busy")
            elif st.button("Masuk", key="login_btn"):
                # Query login dijalankan di render berikutnya agar tombol terkunci dulu.
                if not username or not password:
                    st.error("Tolong lengkapi semua field.")
                else:
                    st.session_state['logging_in']    = True
                    st.session_state['login_attempt'] = (username, password)
                    st.experimental_rerun()

            if logging_in:
                login_user, login_pw = st.session_state.get('login_attempt', ('', ''))
                try:
                    if not check_username_exists(login_user):
                        st.session_state['login_error'] = "Username belum terdaftar. Silakan daftar terlebih dahulu."
                    elif check_login(login_user, sha256(login_pw.encode()).hexdigest()):
                        sesi_login.atur_login(login_user)
                    else:
                        st.session_state['login_error'] = "Password salah. Silakan coba lagi."
                except Exception as e:
                    # Error ditangkap agar tombol tidak terkunci selamanya.
                    print(f"Login gagal: {e}")
                    st.session_state['login_error'] = "Gagal menghubungi server. Periksa koneksi internet kamu lalu coba lagi."
                st.session_state['logging_in'] = False
                st.session_state.pop('login_attempt', None)
                st.experimental_rerun()

            if st.session_state.get('login_error'):
                st.error(st.session_state.pop('login_error'))

            st.markdown("---")
            st.markdown("Belum punya akun?")
            if st.button("Daftar di sini"):
                st.session_state['page'] = 'daftar'
                st.experimental_rerun()

            st.markdown('<div class="btn-link-marker"></div>', unsafe_allow_html=True)
            if st.button("Coba tanpa akun", key="guest_btn_masuk"):
                sesi_login.atur_login(GUEST_COOKIE_VALUE)
                st.experimental_rerun()

    # ── DAFTAR ────────────────────────────────────────────────────────────────
    elif st.session_state['page'] == 'daftar':
        _, auth_col, _ = st.columns([1, 1.4, 1])
        with auth_col:
            st.markdown('<div class="auth-title">Daftar Akun</div><div class="auth-subtitle">Buat akun baru kamu</div>', unsafe_allow_html=True)

            # ── Form daftar — disembunyikan begitu kode OTP sudah terkirim ──
            if not st.session_state.get('otp_step'):
                username = st.text_input("Username", placeholder="Buat username kamu")
                password = st.text_input("Password", type="password", placeholder="Buat password kamu")

                # Validasi email dibaca dari session_state sebelum field dirender.
                email_now = st.session_state.get('reg_email_input', '').strip()
                email_invalid = bool(email_now) and not is_valid_email(email_now)

                if email_invalid:
                    st.markdown('<div class="field-error-marker"></div>', unsafe_allow_html=True)
                email = st.text_input(
                    "Email orang terdekat (opsional)",
                    placeholder="contoh: keluarga@gmail.com",
                    key="reg_email_input",
                    help="Jika diisi, email ini akan menerima notifikasi darurat saat kantuk "
                         "terdeteksi. Boleh dikosongkan jika tidak diperlukan."
                )
                if email_invalid:
                    st.markdown('<p class="field-error-text">Masukkan alamat email yang valid.</p>', unsafe_allow_html=True)

                registering = st.session_state.get('sending_otp', False)

                st.markdown('<div class="btn-primary-marker"></div>', unsafe_allow_html=True)
                if registering:
                    st.button("Memproses...", disabled=True, key="send_otp_btn_sending")
                elif st.button("Daftar", key="send_otp_btn"):
                    # Semua jalur daftar diproses di render berikutnya agar tombol terkunci dulu.
                    if not username or not password:
                        st.error("Tolong lengkapi username dan password.")
                    elif email_invalid:
                        pass  # sudah kelihatan di teks merah bawah field-nya
                    else:
                        st.session_state['sending_otp']       = True
                        st.session_state['pending_username']  = username
                        st.session_state['pending_email']     = email.strip()
                        st.session_state['pending_password']  = password
                        st.experimental_rerun()

                if registering:
                    reg_user  = st.session_state['pending_username']
                    reg_email = st.session_state['pending_email']
                    pw_hash   = sha256(st.session_state['pending_password'].encode()).hexdigest()
                    try:
                        if check_username_exists(reg_user):
                            st.session_state['register_error'] = "Username sudah digunakan. Coba username lain."
                        elif not reg_email:
                            # Tanpa email — daftar langsung, tanpa verifikasi OTP
                            add_user(reg_user, "", pw_hash)
                            sesi_login.atur_login(reg_user)
                        else:
                            otp = generate_otp()
                            save_otp(reg_email, otp, reg_user, pw_hash)
                            if send_otp_email(reg_email, otp, reg_user):
                                st.session_state['reg_username']      = reg_user
                                st.session_state['reg_email']         = reg_email
                                st.session_state['reg_password_hash'] = pw_hash
                                st.session_state['otp_step']          = True
                                st.session_state['otp_last_sent']     = time.time()
                            else:
                                st.session_state['register_error'] = "Gagal mengirim email. Periksa kembali alamat email dan coba lagi."
                    except Exception as e:
                        # Error ditangkap agar tombol tidak terkunci selamanya.
                        print(f"Pendaftaran gagal: {e}")
                        st.session_state['register_error'] = "Gagal menghubungi server. Periksa koneksi internet kamu lalu coba lagi."
                    st.session_state['sending_otp'] = False
                    st.session_state.pop('pending_password', None)
                    st.experimental_rerun()

                if st.session_state.get('register_error'):
                    st.error(st.session_state.pop('register_error'))

            # ── Verifikasi OTP — muncul menggantikan form, tanpa pindah halaman ──
            else:
                st.markdown('<p class="section-label">Verifikasi</p>', unsafe_allow_html=True)
                st.markdown(f"Kode dikirim ke **{st.session_state['reg_email']}**")

                st.markdown('<div class="btn-link-marker"></div>', unsafe_allow_html=True)
                if st.button("Ganti email", key="change_email_btn"):
                    st.session_state['otp_step'] = False
                    st.experimental_rerun()

                otp_input = st.text_input("Masukkan Kode OTP", placeholder="6 digit kode dari email",
                                          max_chars=6, key="otp_input")

                verifying = st.session_state.get('verifying_otp', False)

                st.markdown('<div class="btn-primary-marker"></div>', unsafe_allow_html=True)
                if verifying:
                    st.button("Memverifikasi...", disabled=True, key="verify_otp_btn_busy")
                elif st.button("Verifikasi & Buat Akun", key="verify_otp_btn"):
                    # Verifikasi dijalankan di render berikutnya agar tombol terkunci dulu.
                    if not otp_input.strip():
                        st.session_state['otp_error'] = "Masukkan kode OTP terlebih dahulu."
                    else:
                        st.session_state['verifying_otp'] = True
                    st.experimental_rerun()

                if verifying:
                    with st.spinner("Memverifikasi kode..."):
                        try:
                            valid, msg = verify_otp(
                                st.session_state['reg_username'],
                                st.session_state.get('otp_input', '').strip(),
                            )
                        except Exception as e:
                            print(f"Verifikasi OTP gagal: {e}")
                            valid, msg = False, "Gagal menghubungi server. Periksa koneksi internet kamu lalu coba lagi."
                    st.session_state['verifying_otp'] = False
                    if valid:
                        sesi_login.atur_login(st.session_state['reg_username'])
                    else:
                        st.session_state['otp_error'] = msg
                    st.experimental_rerun()

                if st.session_state.get('otp_error'):
                    st.error(st.session_state.pop('otp_error'))

                # Tombol kirim ulang, kanan bawah, kena cooldown 30 detik
                remaining = int(30 - (time.time() - st.session_state.get('otp_last_sent', 0)))
                # Hitung mundur kirim ulang di-refresh tiap 3 detik, berhenti saat mengetik atau verifikasi.
                if remaining > 0 and not otp_input and not verifying:
                    st_autorefresh(interval=3000, limit=12, key=f"resend_countdown_{st.session_state['otp_last_sent']}")
                resending = st.session_state.get('resending_otp', False)
                if remaining > 0:
                    st.markdown(f'<p style="text-align:right; font-size:0.8rem; color:var(--muted);">Kirim ulang ({remaining}s)</p>', unsafe_allow_html=True)
                elif resending:
                    st.markdown('<div class="btn-link-marker-right"></div>', unsafe_allow_html=True)
                    st.button("Mengirim...", disabled=True, key="resend_otp_btn_busy")
                else:
                    st.markdown('<div class="btn-link-marker-right"></div>', unsafe_allow_html=True)
                    if st.button("Kirim ulang", key="resend_otp_btn"):
                        # Tombol dikunci dulu sebelum OTP dikirim ulang.
                        st.session_state['resending_otp'] = True
                        st.experimental_rerun()

                if resending:
                    try:
                        otp = generate_otp()
                        save_otp(st.session_state['reg_email'], otp, st.session_state['reg_username'], st.session_state['reg_password_hash'])
                        send_otp_email(st.session_state['reg_email'], otp, st.session_state['reg_username'])
                    except Exception as e:
                        print(f"Kirim ulang OTP gagal: {e}")
                        st.session_state['otp_error'] = "Gagal mengirim ulang kode. Coba lagi sebentar lagi."
                    st.session_state['otp_last_sent'] = time.time()
                    st.session_state['resending_otp'] = False
                    st.experimental_rerun()

            st.markdown("---")
            st.markdown("Sudah punya akun?")
            if st.button("Masuk di sini"):
                st.session_state['page']     = 'masuk'
                st.session_state['otp_step'] = False
                st.experimental_rerun()

            st.markdown('<div class="btn-link-marker"></div>', unsafe_allow_html=True)
            if st.button("Coba tanpa akun", key="guest_btn_daftar"):
                sesi_login.atur_login(GUEST_COOKIE_VALUE)
                st.experimental_rerun()
