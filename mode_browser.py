"""Mode browser: deteksi kantuk berjalan di komponen JS (components/detektor), video tidak
dikirim ke server.

Komponen hanya mengirim pesan kecil saat ada kejadian, dan setiap pesan memicu satu rerun:
  mulai     — START ditekan (baris sesi dibuat di database, seperti start_session versi lama)
  kejadian  — satu kejadian kantuk selesai dan lolos durasi minimum
  email     — ambang email terlewati (5 dtk mata, 3 dtk menguap, 5 dtk kepala)
  flush     — jeda email 2 menit habis dan ada kejadian yang ditahan
  selesai   — STOP ditekan atau kamera tidak aktif >= 3 detik
Pesan dikirim sebagai antrean bernomor urut. Nomor terakhir yang sudah diproses dikembalikan
lewat argumen `ack`, jadi pesan tidak hilang atau terproses dua kali walaupun rerun terpotong.
"""
from datetime import datetime, timedelta

import streamlit as st

from database import start_session, save_session_progress, GUEST_STORAGE_KEY
from detektor_component import detektor_component
from email_darurat import EmailDarurat, PESAN_EMAIL

KEY = "detektor"


def waktu_wib(epoch_ms):
    """Datetime WIB (UTC+7, tanpa tzinfo) dari milidetik epoch, padanan now_wib()."""
    return datetime(1970, 1, 1) + timedelta(milliseconds=epoch_ms, hours=7)


def format_kejadian(p):
    """Baris kejadian untuk database, dengan format yang sama seperti pending_events versi lama."""
    return {
        'event_type': p['event_type'],
        'event_time': waktu_wib(p['mulai_ms']).strftime('%Y-%m-%d %H:%M:%S'),
        'duration':   round(float(p['durasi']), 2),
    }


def _state():
    ss = st.session_state
    if "browser_ack" not in ss:
        ss["browser_ack"] = {"id": None, "seq": 0}
    if "browser_sesi" not in ss:
        ss["browser_sesi"] = {}          # id sesi dari komponen -> {"db_id", "kejadian"}
    if "browser_sesi_aktif" not in ss:
        ss["browser_sesi_aktif"] = None  # id sesi yang sedang berjalan
    if "email_darurat" not in ss:
        ss["email_darurat"] = EmailDarurat()
    if "browser_info" not in ss:
        ss["browser_info"] = []          # pemberitahuan yang ditampilkan di bawah komponen
    return ss


def sesi_aktif():
    return bool(st.session_state.get("browser_sesi_aktif"))


def tutup_sesi_aktif(is_guest):
    """Dipanggil saat Keluar: perbarui waktu selesai sesi yang masih berjalan."""
    ss = _state()
    uid = ss["browser_sesi_aktif"]
    if not uid:
        return
    rec = ss["browser_sesi"].get(uid)
    if not is_guest and rec and rec["db_id"] is not None:
        try:
            save_session_progress(rec["db_id"], [])
        except Exception as e:
            print(f"Gagal menyimpan sesi saat keluar: {e}")
    ss["browser_sesi_aktif"] = None


def _catat_diagnostik(p):
    """Ringkasan waktu proses dari browser dicetak ke log, seperti FrameTimer versi lama."""
    r = p.get("ringkasan") or {}
    s = r.get("proses")
    if s:
        print(f"[DIAGNOSTIK] mode browser ({r.get('delegate')}, CLAHE {'on' if r.get('clahe') else 'off'}): "
              f"waktu proses frame n={s['n']} rata-rata={s['rata_rata']:.1f} ms median={s['median']:.1f} ms "
              f"p95={s['p95']:.1f} ms maks={s['maks']:.1f} ms fps={r.get('fps')}", flush=True)


def _proses_satu(p, user, is_guest, notifier, info):
    ss = st.session_state
    jenis = p.get("jenis")
    uid = p.get("sesi")
    if not uid:
        return
    rec = ss["browser_sesi"].setdefault(uid, {"db_id": None, "kejadian": 0})

    def sesi_db():
        if not is_guest and rec["db_id"] is None:
            rec["db_id"] = start_session(user)
        return rec["db_id"]

    if jenis == "mulai":
        sesi_db()
        ss["browser_sesi_aktif"] = uid
        # Versi lama memanggil flush_held_emails() di setiap frame, termasuk frame pertama sesi baru.
        notifier.flush_held_emails()

    elif jenis == "kejadian":
        if is_guest:
            # Kejadian tamu disimpan komponen langsung ke localStorage.
            ss["guest_history_dirty"] = True
        else:
            sid = sesi_db()
            if sid is not None:
                save_session_progress(sid, [format_kejadian(p)])
        rec["kejadian"] += 1

    elif jenis == "email":
        if p.get("lokasi"):
            notifier.location_link = p["lokasi"]
        if p.get("kind") in PESAN_EMAIL:
            notifier.request_email_alert(p["kind"])

    elif jenis == "flush":
        if p.get("lokasi"):
            notifier.location_link = p["lokasi"]
        notifier.flush_held_emails()

    elif jenis == "selesai":
        if is_guest:
            ss["guest_history_dirty"] = True
        elif rec["db_id"] is not None:
            save_session_progress(rec["db_id"], [])
        if ss["browser_sesi_aktif"] == uid:
            ss["browser_sesi_aktif"] = None
        _catat_diagnostik(p)
        info.append(("success", f"Sesi tersimpan! {rec['kejadian']} kejadian kantuk tercatat."))


def _proses_nilai(nilai, user, is_guest, notifier, info):
    """Proses pesan yang belum pernah diproses, berurutan; berhenti di pesan pertama yang gagal."""
    if not isinstance(nilai, dict):
        return
    ss = st.session_state
    ack = ss["browser_ack"]
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

    Nilai dari pesan terakhir komponen sudah tersedia di awal rerun, jadi status sesi (mis. kunci
    pilihan mode di sidebar) langsung mutakhir dan ack ikut terkirim di render ini juga, tanpa
    rerun tambahan.
    """
    ss = _state()
    notifier = ss["email_darurat"]
    notifier.email_recipients = recipient_emails
    _proses_nilai(ss.get(KEY), user, is_guest, notifier, ss["browser_info"])


def render(user, is_guest, recipient_emails, thresholds):
    ss = _state()
    notifier = ss["email_darurat"]
    notifier.email_recipients = recipient_emails
    info = ss["browser_info"]

    nilai = detektor_component(
        key=KEY,
        default=None,
        ambang=thresholds,
        email_aktif=bool(recipient_emails) and not is_guest,
        tamu=is_guest,
        kunci_tamu=GUEST_STORAGE_KEY,
        ack=dict(ss["browser_ack"]),
        flush_dalam_ms=notifier.sisa_jeda_ms(),
    )
    # Biasanya nilai yang sama dengan yang sudah diproses proses_pesan(), jadi semua dilewati.
    _proses_nilai(nilai, user, is_guest, notifier, info)

    # Pemberitahuan dirender setelah komponen agar posisi komponen tidak bergeser antar-rerun
    # (komponen yang bergeser dipasang ulang dan kameranya mati).
    for jenis, teks in info:
        getattr(st, jenis)(teks)
    info.clear()
