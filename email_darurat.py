"""Email darurat ke kontak terdekat saat kantuk berlangsung lama.

Teks, penerima, tautan lokasi, dan pembatasan satu email per 2 menit sama dengan versi Python
(pengujian/deteksi_kantuk.py); kesamaannya diuji oleh pengujian/uji_kesamaan.py.
"""
import smtplib
import threading
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from decouple import config

# Paling banyak satu email per jeda ini; kejadian di dalam jeda dikirim sebagai ringkasan.
EMAIL_COOLDOWN_SECONDS = 2 * 60

EVENT_LABELS = {
    "eye_close": "mata tertutup",
    "yawn":      "menguap",
    "head_tilt": "kepala miring",
}

# Subjek dan isi email per jenis kejadian, sama dengan VideoFrameHandler.process().
PESAN_EMAIL = {
    "eye_close": (
        "⚠️ Pengemudi Terdeteksi Mengantuk!",
        "Kami mendeteksi bahwa mata pengemudi tertutup selama "
        "lebih dari 5 detik saat berkendara. Kondisi ini merupakan tanda "
        "bahwa pengemudi sedang tertidur atau sangat mengantuk, dan "
        "sangat berbahaya jika dibiarkan.\n\n"
        "Mohon segera hubungi pengemudi dan sarankan untuk segera menepi "
        "dan beristirahat di rest area terdekat.\n\n"
        "Pesan ini dikirim otomatis oleh Sistem Pendeteksi Kantuk."
    ),
    "yawn": (
        "⚠️ Pengemudi Terdeteksi Mengantuk!",
        "Kami mendeteksi bahwa pengemudi telah menguap selama "
        "lebih dari 3 detik saat berkendara. Menguap berlebihan merupakan "
        "tanda awal rasa kantuk yang dapat membahayakan keselamatan "
        "berkendara.\n\n"
        "Mohon segera hubungi pengemudi dan sarankan untuk beristirahat "
        "di rest area terdekat.\n\n"
        "Pesan ini dikirim otomatis oleh Sistem Pendeteksi Kantuk."
    ),
    "head_tilt": (
        "⚠️ Pengemudi Terdeteksi Mengantuk!",
        "Kami mendeteksi bahwa kepala pengemudi miring ke samping "
        "selama lebih dari 5 detik saat berkendara. Kondisi ini biasanya "
        "terjadi ketika pengemudi tertidur atau hampir tertidur, dan sangat "
        "berbahaya jika dibiarkan.\n\n"
        "Mohon segera hubungi pengemudi dan sarankan untuk segera menepi "
        "dan beristirahat di rest area terdekat.\n\n"
        "Pesan ini dikirim otomatis oleh Sistem Pendeteksi Kantuk."
    ),
}


class EmailDarurat:
    def __init__(self):
        self.email_sender   = "deteksikantuk@gmail.com"
        self.email_password = config('EMAIL_PASSWORD', default='')
        self.email_recipients = []  # diisi dari Streamlit sesuai email akun yang login; kosong = tidak kirim (mis. tamu)
        # Link Google Maps posisi terakhir pengemudi (per sesi browser).
        self.location_link = "Lokasi tidak tersedia"

        # Status pembatasan email.
        self._last_email_at  = None  # time.monotonic() saat email terakhir dikirim
        self._held_events    = {}    # jenis kejadian -> jumlah yang ditahan

    def _send_email_worker(self, subject: str, message: str):
        """Background thread — tidak membekukan halaman."""
        try:
            full_message  = f"{message}\n\nLokasi pengguna saat ini: {self.location_link}"

            msg = MIMEMultipart()
            msg["From"]    = self.email_sender
            msg["Subject"] = subject
            msg.attach(MIMEText(full_message, "plain"))

            with smtplib.SMTP("smtp.gmail.com", 587) as server:
                server.starttls()
                server.login(self.email_sender, self.email_password)
                for recipient in self.email_recipients:
                    # Hapus header To lama supaya tiap penerima hanya melihat alamatnya sendiri.
                    del msg["To"]
                    msg["To"] = recipient
                    server.sendmail(self.email_sender, recipient, msg.as_string())
        except Exception as e:
            print(f"Gagal mengirim email: {e}")

    def send_email_alert(self, subject: str, message: str):
        t = threading.Thread(target=self._send_email_worker, args=(subject, message), daemon=True)
        t.start()

    def _email_window_open(self) -> bool:
        return (self._last_email_at is None
                or time.monotonic() - self._last_email_at >= EMAIL_COOLDOWN_SECONDS)

    def request_email_alert(self, kind: str):
        """Kirim email darurat, atau tahan dan hitung kejadiannya kalau masih dalam jeda."""
        if not self.email_recipients:
            return  # tamu / akun tanpa email: tidak ada yang perlu dikirimi
        subject, message = PESAN_EMAIL[kind]
        if self._email_window_open():
            self._last_email_at = time.monotonic()
            self.send_email_alert(subject, message)
        else:
            self._held_events[kind] = self._held_events.get(kind, 0) + 1

    def flush_held_emails(self):
        """Kirim satu email ringkasan untuk kejadian yang ditahan setelah jeda habis."""
        if not self._held_events or not self._email_window_open():
            return
        rincian = ", ".join(
            f"{jumlah}× {EVENT_LABELS.get(jenis, jenis)}"
            for jenis, jumlah in self._held_events.items()
        )
        menit = EMAIL_COOLDOWN_SECONDS // 60
        self._held_events.clear()
        self._last_email_at = time.monotonic()
        self.send_email_alert(
            "⚠️ Pengemudi Masih Terdeteksi Mengantuk",
            f"Dalam {menit} menit terakhir sejak email sebelumnya, sistem kembali "
            f"mendeteksi tanda kantuk pada pengemudi: {rincian}.\n\n"
            "Kejadian yang berulang menandakan pengemudi masih mengantuk. Mohon "
            "segera hubungi pengemudi dan sarankan untuk menepi dan beristirahat "
            "di rest area terdekat.\n\n"
            f"Untuk mencegah spam, email dari sistem ini dikirim paling banyak "
            f"satu kali setiap {menit} menit.\n\n"
            "Pesan ini dikirim otomatis oleh Sistem Pendeteksi Kantuk."
        )

    def sisa_jeda_ms(self):
        """Milidetik sampai ringkasan email yang ditahan boleh dikirim; None jika tidak ada."""
        if not self._held_events:
            return None
        sisa = EMAIL_COOLDOWN_SECONDS - (time.monotonic() - self._last_email_at)
        return max(0, int(sisa * 1000))
