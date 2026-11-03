"""Sisi Python komponen detektor kantuk (components/detektor).

Kamera, deteksi wajah (MediaPipe FaceLandmarker), EAR/MAR/sudut kepala, penghitung waktu, alarm,
dan anotasi berjalan di browser, jadi video tidak pernah dikirim ke server. Komponen hanya
mengirim pesan kecil saat ada kejadian, dan setiap pesan memicu satu rerun:
  mulai     — START ditekan (baris sesi dibuat di database)
  kejadian  — satu kejadian kantuk selesai dan lolos durasi minimum
  email     — ambang email terlewati (5 dtk mata, 3 dtk menguap, 5 dtk kepala)
  flush     — jeda email 2 menit habis dan ada kejadian yang ditahan
  selesai   — STOP ditekan atau kamera tidak aktif >= 3 detik
Pesan dikirim sebagai antrean bernomor urut. Nomor terakhir yang sudah diproses dikembalikan
lewat argumen `ack`, dan antrean disimpan di localStorage browser sampai dikonfirmasi, jadi pesan
tidak hilang walaupun sinyal putus, halaman dimuat ulang, atau pengguna pindah ke halaman Histori.

Pesan yang sama bisa sampai lebih dari sekali (mis. konfirmasinya tidak sempat diterima sebelum sinyal
putus, lalu Streamlit membuat sesi baru saat tersambung ulang). Karena itu pemrosesannya dibuat aman
diulang: baris sesi dicari dari akun + waktu START di perangkat, kejadian yang sama tidak disimpan dua
kali, dan permintaan email yang sama tidak dikirim dua kali.
"""
import mimetypes
import os
import threading
from datetime import datetime, timedelta

import streamlit as st
import streamlit.components.v1 as components
from decouple import config

from database import start_session, save_session_progress, GUEST_STORAGE_KEY
from email_darurat import EmailDarurat, PESAN_EMAIL

# Panel "Pengujian & diagnostik" di bawah video; disembunyikan kecuali PANEL_PENGUJIAN=1.
PANEL_PENGUJIAN = config("PANEL_PENGUJIAN", default=False, cast=bool)

# Registry Windows kadang memetakan .js ke text/plain; tanpa ini skrip komponen tidak dijalankan
# browser saat aplikasi dijalankan lokal di Windows.
mimetypes.add_type("application/javascript", ".js")

_komponen = components.declare_component(
    "detektor",
    path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "components", "detektor"),
)

KEY = "detektor"

# Satu pengirim email darurat per akun di proses server ini. Sesi Streamlit berganti setiap kali
# koneksi tersambung ulang, tetapi jeda 2 menit dan email ringkasan yang tertahan harus berlanjut.
_notifier_akun = {}
_email_diproses = {}  # akun -> id permintaan email yang sudah diproses (pesan ulang dilewati)
_kunci_notifier = threading.Lock()


def waktu_wib(epoch_ms):
    """Datetime WIB (UTC+7, tanpa tzinfo) dari milidetik epoch, padanan now_wib()."""
    return datetime(1970, 1, 1) + timedelta(milliseconds=epoch_ms, hours=7)


def _teks_wib(epoch_ms):
    """'YYYY-MM-DD HH:MM:SS' WIB dari milidetik epoch, atau None kalau tidak ada."""
    if not isinstance(epoch_ms, (int, float)):
        return None
    return waktu_wib(epoch_ms).strftime('%Y-%m-%d %H:%M:%S')


def format_kejadian(p):
    """Baris kejadian untuk tabel drowsiness_events."""
    return {
        'event_type': p['event_type'],
        'event_time': waktu_wib(p['mulai_ms']).strftime('%Y-%m-%d %H:%M:%S'),
        'duration':   round(float(p['durasi']), 2),
    }


def _state():
    ss = st.session_state
    if "detektor_ack" not in ss:
        ss["detektor_ack"] = {"id": None, "seq": 0}
    if "detektor_sesi" not in ss:
        ss["detektor_sesi"] = {}          # id sesi dari komponen -> {"db_id", "kejadian"}
    if "detektor_sesi_aktif" not in ss:
        ss["detektor_sesi_aktif"] = None  # id sesi yang sedang berjalan
    if "detektor_info" not in ss:
        ss["detektor_info"] = []          # pemberitahuan yang ditampilkan di bawah komponen
    return ss


def _notifier(user):
    if not user:
        # Tamu tidak mengirim email; cukup satu per sesi.
        ss = st.session_state
        if "email_darurat" not in ss:
            ss["email_darurat"] = EmailDarurat()
        return ss["email_darurat"]
    with _kunci_notifier:
        return _notifier_akun.setdefault(user, EmailDarurat())


def _email_pertama(user, mid):
    """True kalau permintaan email ini belum pernah diproses untuk akun ini."""
    if not mid:
        return True
    with _kunci_notifier:
        sudah = _email_diproses.setdefault(user, set())
        if mid in sudah:
            return False
        sudah.add(mid)
        return True


def tutup_sesi_aktif(is_guest):
    """Dipanggil saat Keluar: perbarui waktu selesai sesi yang masih berjalan."""
    ss = _state()
    uid = ss["detektor_sesi_aktif"]
    if not uid:
        return
    rec = ss["detektor_sesi"].get(uid)
    if not is_guest and rec and rec["db_id"] is not None:
        try:
            save_session_progress(rec["db_id"], [])
        except Exception as e:
            print(f"Gagal menyimpan sesi saat keluar: {e}")
    ss["detektor_sesi_aktif"] = None


def _catat_waktu_proses(p):
    """Ringkasan waktu proses per frame dari browser dicetak ke log aplikasi."""
    r = p.get("ringkasan") or {}
    s = r.get("proses")
    if s:
        print(f"[WAKTU PROSES] ({r.get('delegate')}, CLAHE {'on' if r.get('clahe') else 'off'}): "
              f"n={s['n']} rata-rata={s['rata_rata']:.1f} ms median={s['median']:.1f} ms "
              f"p95={s['p95']:.1f} ms maks={s['maks']:.1f} ms fps={r.get('fps')}", flush=True)


def _proses_satu(p, user, is_guest, notifier, info):
    ss = st.session_state
    jenis = p.get("jenis")
    uid = p.get("sesi")
    if not uid:
        return
    if p.get("akun", user) != user:
        # Pesan milik akun lain yang tertinggal di browser ini: jangan disimpan ke akun yang sekarang.
        return
    rec = ss["detektor_sesi"].setdefault(uid, {"db_id": None, "kejadian": 0})
    waktu = _teks_wib(p.get("waktu_ms"))  # waktu pesan dibuat di perangkat

    def sesi_db():
        if rec["db_id"] is None:
            rec["db_id"] = start_session(user, _teks_wib(p.get("sesi_mulai_ms")))
            if rec["db_id"] is None:
                raise RuntimeError(f"baris sesi untuk akun {user!r} tidak bisa dibuat")
        return rec["db_id"]

    if jenis == "mulai":
        if not is_guest:
            sesi_db()
        ss["detektor_sesi_aktif"] = uid
        # Email ringkasan yang masih tertahan dari sesi sebelumnya dikirim saat sesi baru dimulai.
        notifier.flush_held_emails()

    elif jenis == "kejadian":
        # Kejadian tamu disimpan komponen langsung ke localStorage.
        if not is_guest:
            save_session_progress(sesi_db(), [format_kejadian(p)], waktu)
        rec["kejadian"] += 1

    elif jenis == "email":
        if p.get("lokasi"):
            notifier.location_link = p["lokasi"]
        if p.get("kind") in PESAN_EMAIL and _email_pertama(user, p.get("mid")):
            notifier.request_email_alert(p["kind"])

    elif jenis == "flush":
        if p.get("lokasi"):
            notifier.location_link = p["lokasi"]
        notifier.flush_held_emails()

    elif jenis == "selesai":
        if not is_guest:
            save_session_progress(sesi_db(), [], waktu)
        if ss["detektor_sesi_aktif"] == uid:
            ss["detektor_sesi_aktif"] = None
        _catat_waktu_proses(p)
        # Jumlah dari komponen mencakup kejadian yang diproses di sesi Streamlit sebelumnya.
        jumlah = p.get("jumlah_kejadian")
        if not isinstance(jumlah, int):
            jumlah = rec["kejadian"]
        info.append(("success", f"Sesi tersimpan! {jumlah} kejadian kantuk tercatat."))


def _proses_nilai(nilai, user, is_guest, notifier, info):
    """Proses pesan yang belum pernah diproses, berurutan; berhenti di pesan pertama yang gagal."""
    if not isinstance(nilai, dict):
        return
    ss = st.session_state
    ack = ss["detektor_ack"]
    if nilai.get("id") != ack["id"]:
        # Komponen baru dipasang (mis. halaman dimuat ulang): nomor urutnya mulai dari awal.
        ack["id"], ack["seq"] = nilai.get("id"), 0
    for p in sorted(nilai.get("pesan") or [], key=lambda p: p.get("seq", 0)):
        seq = p.get("seq", 0)
        if seq <= ack["seq"]:
            continue
        try:
            _proses_satu(p, user, is_guest, notifier, info)
        except Exception as e:
            # Tidak di-ack: komponen mengirim ulang pesan ini otomatis.
            print(f"Gagal memproses pesan {p.get('jenis')} dari komponen: {e}")
            info.append(("warning", "Gagal menyimpan data sesi ke database. Akan dicoba lagi otomatis."))
            return
        ack["seq"] = seq


def proses_pesan(user, is_guest, recipient_emails):
    """Proses pesan baru dari komponen sebelum apa pun dirender.

    Nilai dari pesan terakhir komponen sudah tersedia di awal rerun, jadi status sesi langsung
    mutakhir dan ack ikut terkirim di render ini juga, tanpa rerun tambahan.
    """
    ss = _state()
    notifier = _notifier(user)
    notifier.email_recipients = recipient_emails
    _proses_nilai(ss.get(KEY), user, is_guest, notifier, ss["detektor_info"])


def render(user, is_guest, recipient_emails, thresholds):
    ss = _state()
    notifier = _notifier(user)
    notifier.email_recipients = recipient_emails
    info = ss["detektor_info"]

    nilai = _komponen(
        key=KEY,
        default=None,
        ambang=thresholds,
        email_aktif=bool(recipient_emails) and not is_guest,
        tamu=is_guest,
        kunci_tamu=GUEST_STORAGE_KEY,
        ack=dict(ss["detektor_ack"]),
        flush_dalam_ms=notifier.sisa_jeda_ms(),
        panel_pengujian=PANEL_PENGUJIAN,
        akun=user,
    )
    # Biasanya nilai yang sama dengan yang sudah diproses proses_pesan(), jadi semua dilewati.
    _proses_nilai(nilai, user, is_guest, notifier, info)

    # Pemberitahuan dirender setelah komponen agar posisi komponen tidak bergeser antar-rerun
    # (komponen yang bergeser dipasang ulang dan kameranya mati).
    for jenis, teks in info:
        getattr(st, jenis)(teks)
    info.clear()
