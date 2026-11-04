"""Jaga aplikasi Streamlit Community Cloud tetap aktif (dipakai .github/workflows/keep-awake.yml).

Membuka APP_URL dengan Chromium headless. Kalau aplikasi sedang tidur, tombol
"Yes, get this app back up!" diklik dan skrip menunggu sampai aplikasinya tampil.
Kalau aplikasi sudah aktif, skrip tetap di halaman sekitar 30 detik supaya terhitung
sebagai kunjungan. Screenshot akhir disimpan ke keep_awake.png.

Skrip tidak pernah masuk, mendaftar, atau mengisi formulir: satu-satunya yang diklik adalah tombol
bangunkan milik Streamlit Cloud, dan tombol di dalam tampilan aplikasi atau formulir tidak pernah diklik.

Exit code 1 kalau halaman gagal dibuka atau tombol masih ada setelah 3 menit, selain itu 0.
Jalankan: APP_URL=https://... python scripts/keep_awake.py
"""
import os
import re
import sys
import time

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

TEKS_TOMBOL = re.compile(r"get this app back up", re.IGNORECASE)
TUNGGU_TOMBOL_DETIK = 15     # halaman "tidur" dirender JavaScript, jadi tombolnya muncul belakangan
BATAS_BANGUN_DETIK = 3 * 60  # waktu maksimal aplikasi bangun setelah tombol diklik
DIAM_DETIK = 30              # lama tinggal di halaman supaya terhitung sebagai kunjungan
SCREENSHOT = "keep_awake.png"


def log(pesan):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {pesan}", flush=True)


def cari_tombol(page):
    """Tombol pembangun yang terlihat di halaman utama atau salah satu iframe-nya, atau None.

    Tombol di dalam tampilan aplikasi atau formulir dilewati, supaya skrip tidak pernah menekan
    tombol aplikasi (masuk, daftar, dan sebagainya).
    """
    for frame in page.frames:
        try:
            tombol = frame.locator("button, [role='button']").filter(has_text=TEKS_TOMBOL)
            for i in range(tombol.count()):
                calon = tombol.nth(i)
                di_aplikasi = calon.evaluate("el => !!el.closest(\"[data-testid='stAppViewContainer'], form\")")
                if calon.is_visible() and not di_aplikasi:
                    return calon
        except PlaywrightError:
            continue  # frame berpindah atau dilepas saat diperiksa
    return None


def aplikasi_tampil(page):
    """True kalau tampilan aplikasi Streamlit sudah ada di salah satu frame."""
    for frame in page.frames:
        try:
            if frame.locator("[data-testid='stAppViewContainer'], .stApp").count():
                return True
        except PlaywrightError:
            continue
    return False


def tunggu_tombol(page, detik):
    batas = time.monotonic() + detik
    while time.monotonic() < batas:
        tombol = cari_tombol(page)
        if tombol is not None:
            return tombol
        page.wait_for_timeout(1000)
    return None


def bangunkan_atau_kunjungi(page):
    tombol = tunggu_tombol(page, TUNGGU_TOMBOL_DETIK)
    if tombol is None:
        if aplikasi_tampil(page):
            log("Aplikasi sudah aktif (tidak ada tombol untuk membangunkan).")
        else:
            log("Tidak ada tombol untuk membangunkan; aplikasi dianggap aktif walau tampilannya belum terdeteksi.")
        log(f"Tetap di halaman {DIAM_DETIK} detik supaya terhitung sebagai kunjungan.")
        page.wait_for_timeout(DIAM_DETIK * 1000)
        return 0

    log("Aplikasi sedang tidur. Menekan tombol untuk membangunkannya.")
    try:
        tombol.click(timeout=30_000)
    except PlaywrightError as e:
        log(f"Gagal menekan tombol: {e}")
    batas = time.monotonic() + BATAS_BANGUN_DETIK
    while time.monotonic() < batas:
        page.wait_for_timeout(5000)
        if cari_tombol(page) is None and aplikasi_tampil(page):
            log("Aplikasi baru saja dibangunkan dan sudah tampil.")
            return 0
    if cari_tombol(page) is None:
        log(f"Tombol sudah hilang, tetapi tampilan aplikasi belum muncul setelah {BATAS_BANGUN_DETIK // 60} menit.")
    else:
        log(f"Tombol masih ada setelah {BATAS_BANGUN_DETIK // 60} menit; aplikasi gagal dibangunkan.")
    return 1


def simpan_screenshot(page):
    try:
        page.screenshot(path=SCREENSHOT, full_page=True)
        log(f"Screenshot disimpan ke {SCREENSHOT}.")
    except PlaywrightError as e:
        log(f"Screenshot gagal disimpan: {e}")


def main():
    url = os.environ.get("APP_URL", "").strip()
    if not url:
        log("Environment variable APP_URL belum diisi.")
        return 1

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        try:
            log(f"Membuka {url}")
            try:
                page.goto(url, wait_until="load", timeout=90_000)
            except PlaywrightError as e:
                log(f"Halaman gagal dibuka: {e}")
                return 1
            try:
                page.wait_for_load_state("networkidle", timeout=30_000)
            except PlaywrightTimeout:
                pass  # koneksi Streamlit yang terus terbuka bisa membuat jaringan tidak pernah diam
            return bangunkan_atau_kunjungi(page)
        finally:
            simpan_screenshot(page)
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
