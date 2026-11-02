"""Uji kesamaan logika JS aplikasi (components/detektor) dengan versi Python (deteksi_kantuk.py).

1. Indikator: EAR, MAR, sudut kepala, koordinat piksel, dan teks di layar dari landmark acak
   (termasuk titik di luar frame, nilai persis 0/1, dan frame sangat kecil).
2. Logika: penghitung waktu, alarm, email, pencatatan kejadian, dan anotasi pada skenario acak,
   dibandingkan dengan VideoFrameHandler.process() asli (waktu dan wajah disimulasikan).
3. Email: teks email per jenis kejadian, email ringkasan, dan pembatasan 2 menit.
4. CLAHE: clahe.js dibandingkan piksel per piksel dengan enhance_low_light() (cv2).

Butuh Node.js dan paket Python versi lama (opencv, mediapipe). Jalankan dari folder repo:
    python pengujian/uji_kesamaan.py [--seed 2026]
Ringkasan hasil juga ditulis ke pengujian/hasil_uji_kesamaan.txt.
"""
import argparse
import glob
import json
import os
import random
import subprocess
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT]
os.chdir(ROOT)
# Kode yang diuji membaca konfigurasi saat diimpor; tidak ada koneksi database atau email.
os.environ.setdefault("GOOGLE_API_KEY", "uji")
os.environ.setdefault("DATABASE_URL", "postgresql://uji")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import deteksi_kantuk as dk  # noqa: E402
import email_darurat  # noqa: E402
from detektor import format_kejadian, waktu_wib  # noqa: E402

# Sama persis dengan VideoFrameHandler.__init__ di deteksi_kantuk.py
MATA_KIRI = [362, 385, 387, 263, 373, 380]
MATA_KANAN = [33, 160, 158, 133, 153, 144]
WARNA = {(0, 0, 255): "RED", (0, 255, 0): "GREEN", (0, 165, 255): "ORANGE", (0, 255, 255): "YELLOW"}
UKURAN = [(640, 360), (360, 640), (480, 640), (640, 480), (1280, 720), (275, 183), (320, 180)]
LAPORAN = []


def lapor(teks=""):
    print(teks, flush=True)
    LAPORAN.append(teks)


def jalankan_node(uji, masukan, keluaran):
    subprocess.run(["node", os.path.join(HERE, "jalankan_js.js"), uji, masukan, keluaran], check=True)


# ─── 1. Indikator ─────────────────────────────────────────────────────────────

class LM:
    __slots__ = ("x", "y")

    def __init__(self, x, y):
        self.x, self.y = x, y


NILAI_BATAS = [0.0, -0.0, 1.0, 1e-12, -1e-12, 1 - 1e-12, 1 + 1e-12, 1 + 5e-10, 1 + 2e-9, -1e-300, 0.5]


def acak_landmark(rng, mode):
    pts = []
    for _ in range(478):
        if mode == "batas" and rng.random() < 0.3:
            pts.append([rng.choice(NILAI_BATAS), rng.choice(NILAI_BATAS)])
        elif mode == "tepi":
            pts.append([rng.uniform(-0.05, 1.05), rng.uniform(-0.05, 1.05)])
        else:
            pts.append([rng.uniform(0.0, 1.0), rng.uniform(0.0, 1.0)])
    return pts


def uji_indikator(rng, tmp, n=3000):
    kasus = []
    for i in range(n):
        mode = ("wajar", "tepi", "batas")[i % 3]
        if rng.random() < 0.1:
            w, h = rng.choice([(1, 1), (2, 2), (3, 2), (8, 5)])
        elif rng.random() < 0.5:
            w, h = rng.choice(UKURAN)
        else:
            w, h = rng.randint(1, 2000), rng.randint(1, 2000)
        kasus.append({"w": w, "h": h, "lm": acak_landmark(rng, mode)})

    masuk, keluar = os.path.join(tmp, "indikator_in.json"), os.path.join(tmp, "indikator_out.json")
    with open(masuk, "w") as f:
        json.dump(kasus, f)
    jalankan_node("indikator", masuk, keluar)
    with open(keluar) as f:
        js = json.load(f)

    lst = lambda c: None if c is None else [list(p) for p in c]
    beda, maks_selisih, nol, sudut_ulp, akar_ulp = 0, 0.0, 0, 0, 0
    for k, j in zip(kasus, js):
        lm = [LM(x, y) for x, y in k["lm"]]
        w, h = k["w"], k["h"]
        ear_l, cl = dk.get_ear(lm, MATA_KIRI, w, h)
        ear_r, cr = dk.get_ear(lm, MATA_KANAN, w, h)
        ear, _ = dk.calculate_avg_ear(lm, MATA_KIRI, MATA_KANAN, w, h)
        mar, mc = dk.get_mar(lm, dk.MOUTH_IDXS, w, h)
        ang, lpt, rpt = dk.get_head_tilt_angle(lm, w, h)
        py = {
            "ear_kiri": ear_l, "ear_kanan": ear_r, "ear": ear, "kiri": lst(cl), "kanan": lst(cr),
            "mar": mar, "mulut": lst(mc), "sudut": float(ang),
            "lpt": list(lpt) if lpt else None, "rpt": list(rpt) if rpt else None,
            "teks_ear": f"EAR: {round(ear, 2)}", "teks_sudut": f"TILT: {ang:.1f}deg",
        }
        if ear == 0.0 or mar == 0.0:
            nol += 1
        for kunci in ("ear_kiri", "ear_kanan", "ear", "mar", "sudut"):
            maks_selisih = max(maks_selisih, abs(py[kunci] - j[kunci]))
        # atan2 dan pow(x, 0.5) pustaka C bisa berbeda di bit terakhir dari JavaScript (pow di
        # Windows tidak selalu sama dengan sqrt). Selisih sekecil itu dihitung terpisah; koordinat,
        # teks, dan nilai lainnya harus identik.
        for kunci in ("ear_kiri", "ear_kanan", "ear", "mar", "sudut"):
            if py[kunci] != j[kunci] and abs(py[kunci] - j[kunci]) <= 1e-12 * max(1.0, abs(py[kunci])):
                if kunci == "sudut":
                    sudut_ulp += 1
                else:
                    akar_ulp += 1
                j = dict(j, **{kunci: py[kunci]})
        if py != j:
            beda += 1
            if beda <= 3:
                lapor(f"  BEDA {k['w']}x{k['h']}: python={ {a: py[a] for a in py if py[a] != j[a]} } js={ {a: j[a] for a in py if py[a] != j[a]} }")
    lapor(f"1. Indikator: {n} set landmark acak ({nol} kasus EAR/MAR = 0 karena titik di luar frame "
          f"atau pembagi nol) -> {n - beda} identik, {beda} berbeda. Koordinat piksel dan teks di layar "
          f"identik; nilai desimal berbeda hanya di digit terakhir (selisih maks {maks_selisih:.2g}): "
          f"sudut {sudut_ulp} kasus (atan2), EAR/MAR {akar_ulp} nilai (pow(x, 0.5) Python Windows != sqrt)")
    return beda == 0


# ─── 2. Logika per frame ──────────────────────────────────────────────────────

def acak_ambang(rng):
    return {
        "EAR_THRESH": round(rng.randint(10, 35) * 0.01, 2),
        "MAR_THRESH": round(rng.randint(30, 100) * 0.01, 2),
        "TILT_THRESH": float(rng.randint(5, 45)),
        "WAIT_TIME": rng.randint(0, 20) * 0.25,
    }


def acak_titik(rng, n, w, h):
    if rng.random() < 0.1:
        return None
    return [[rng.randint(0, w - 1), rng.randint(0, h - 1)] for _ in range(n)]


def buat_skenario(rng, n_frame):
    ambang = acak_ambang(rng)
    w, h = rng.choice(UKURAN)
    t = rng.uniform(100.0, 5000.0)
    wall = 1_760_000_000_000 + rng.randint(0, 10 ** 9)
    langkah, frame = [], 0
    while frame < n_frame:
        if rng.random() < 0.03:
            # STOP lalu START lagi: jeda panjang, penghitung harus mulai dari nol.
            jeda = rng.uniform(5.0, 90.0)
            t += jeda
            wall += int(jeda * 1000)
            langkah.append({"op": "sesi_baru"})
        if rng.random() < 0.05:
            ambang = acak_ambang(rng)  # slider digeser
        wajah = rng.random() > 0.12
        tutup, uap, miring = rng.random() < 0.45, rng.random() < 0.3, rng.random() < 0.3
        for _ in range(rng.randint(1, 140)):
            dt = (1 / 15) * rng.uniform(0.5, 1.8) if rng.random() > 0.02 else rng.uniform(0.3, 3.0)
            t += dt
            wall += int(round(dt * 1000)) + rng.randint(0, 2)
            ind = None
            if wajah:
                e, m, a = ambang["EAR_THRESH"], ambang["MAR_THRESH"], ambang["TILT_THRESH"]
                r = rng.random()
                ear = e if r < 0.02 else (e - rng.uniform(1e-9, 0.1) if tutup else e + rng.uniform(1e-9, 0.15))
                mar = m if r < 0.04 else (m + rng.uniform(1e-9, 0.4) if uap else m - rng.uniform(1e-9, 0.25))
                sudut = a if r < 0.06 else (a + rng.uniform(1e-9, 30) if miring else rng.uniform(0, a - 1e-9))
                if rng.random() < 0.5:
                    sudut = -sudut
                if rng.random() < 0.02:
                    ear = 0.0  # titik mata di luar frame
                ind = {
                    "ear": ear, "mar": max(mar, 0.0), "angle": sudut,
                    "eyeCoords": [acak_titik(rng, 6, w, h), acak_titik(rng, 6, w, h)],
                    "mouthCoords": acak_titik(rng, 8, w, h),
                    "leftPt": [rng.randint(-5, w), rng.randint(-5, h)],
                    "rightPt": [rng.randint(-5, w), rng.randint(-5, h)],
                }
            langkah.append({"op": "frame", "t": t, "wall": wall, "w": w, "h": h, "ambang": dict(ambang), "ind": ind})
            frame += 1
    return langkah


class FrameTiruan:
    def __init__(self, w, h):
        self.shape = (h, w, 3)


class GambarRGB:
    class flags:
        writeable = True


def jalankan_python(skenario, teks_email):
    """Jalankan VideoFrameHandler.process() asli dengan waktu, wajah, dan indikator tiruan."""
    cur = {"t": 0.0}
    rec = {"gambar": [], "email": []}

    class Mesh:
        def process(self, rgb):
            return types.SimpleNamespace(
                multi_face_landmarks=[types.SimpleNamespace(landmark=None)] if cur["ind"] else None)

    asli = {k: getattr(dk, k) for k in (
        "time", "now_wib", "get_mediapipe_app", "enhance_low_light", "cv2", "calculate_avg_ear",
        "get_mar", "get_head_tilt_angle", "plot_eye_landmarks", "plot_mouth_landmarks",
        "plot_head_tilt", "plot_text")}
    try:
        dk.time = types.SimpleNamespace(perf_counter=lambda: cur["t"])
        dk.now_wib = lambda: waktu_wib(cur["wall"])
        dk.get_mediapipe_app = lambda *a, **k: Mesh()
        dk.enhance_low_light = lambda frame: frame
        dk.cv2 = types.SimpleNamespace(cvtColor=lambda f, kode: GambarRGB(), COLOR_BGR2RGB=None)
        dk.calculate_avg_ear = lambda lm, l, r, w, h: (cur["ind"]["ear"], cur["ind"]["eyeCoords"])
        dk.get_mar = lambda lm, idx, w, h: (cur["ind"]["mar"], cur["ind"]["mouthCoords"])
        dk.get_head_tilt_angle = lambda lm, w, h: (cur["ind"]["angle"], cur["ind"]["leftPt"], cur["ind"]["rightPt"])

        def eye(frame, l, r, color):
            rec["gambar"].append({"op": "mata", "kiri": l, "kanan": r, "warna": WARNA[color]})
            return frame

        def mouth(frame, c, color):
            rec["gambar"].append({"op": "mulut", "koordinat": c, "warna": WARNA[color]})
            return frame

        def tilt(frame, l, r, angle, color):
            rec["gambar"].append({"op": "kepala", "kiri": l, "kanan": r, "sudut": angle, "warna": WARNA[color]})
            return frame

        def text(image, s, origin, color, *a, **k):
            rec["gambar"].append({"op": "teks", "teks": s, "x": origin[0], "y": origin[1], "warna": WARNA[color]})
            return image

        dk.plot_eye_landmarks, dk.plot_mouth_landmarks, dk.plot_head_tilt, dk.plot_text = eye, mouth, tilt, text

        hasil = []
        for langkah in skenario:
            handler = dk.VideoFrameHandler()

            def minta_email(kind, subject, message):
                rec["email"].append(kind)
                teks_email[kind] = (subject, message)

            handler.request_email_alert = minta_email
            handler.flush_held_emails = lambda: None
            out = []
            for l in langkah:
                if l["op"] == "sesi_baru":
                    handler.mulai_sesi_baru()
                    continue
                cur.update(l)
                rec["gambar"], rec["email"] = [], []
                sebelum = len(handler.pending_events)
                _, alarm = handler.process(FrameTiruan(l["w"], l["h"]), l["ambang"])
                out.append({"gambar": rec["gambar"], "email": rec["email"], "alarm": alarm,
                            "kejadian": handler.pending_events[sebelum:]})
            hasil.append(out)
        return hasil
    finally:
        for k, v in asli.items():
            setattr(dk, k, v)


def uji_logika(rng, tmp, n_skenario=60, n_frame=2500):
    skenario = [buat_skenario(rng, n_frame) for _ in range(n_skenario)]
    masuk, keluar = os.path.join(tmp, "logika_in.json"), os.path.join(tmp, "logika_out.json")
    with open(masuk, "w") as f:
        json.dump(skenario, f)
    jalankan_node("logika", masuk, keluar)
    with open(keluar) as f:
        js = json.load(f)
    # Skenario dibaca ulang dari JSON supaya Python dan JS memakai angka yang persis sama.
    with open(masuk) as f:
        skenario = json.load(f)

    teks_email = {}
    py = jalankan_python(skenario, teks_email)

    total = beda = n_kejadian = n_email = n_alarm = n_sesi_baru = 0
    for s, (fp, fj) in enumerate(zip(py, js)):
        n_sesi_baru += sum(1 for l in skenario[s] if l["op"] == "sesi_baru")
        for i, (a, b) in enumerate(zip(fp, fj)):
            total += 1
            b_kejadian = [format_kejadian(k) for k in b["kejadian"]]
            n_kejadian += len(a["kejadian"])
            n_email += len(a["email"])
            n_alarm += bool(a["alarm"])
            sama = (a["gambar"] == b["gambar"] and a["email"] == b["email"]
                    and bool(a["alarm"]) == b["alarm"] and a["kejadian"] == b_kejadian)
            if not sama:
                beda += 1
                if beda <= 3:
                    lapor(f"  BEDA skenario {s} frame {i}:\n    python={a}\n    js={b} (kejadian={b_kejadian})")
        if len(fp) != len(fj):
            beda += 1
            lapor(f"  BEDA jumlah frame skenario {s}: {len(fp)} vs {len(fj)}")
    lapor(f"2. Logika: {n_skenario} skenario, {total} frame, {n_sesi_baru} kali STOP/START, "
          f"{n_kejadian} kejadian tercatat, {n_email} permintaan email, {n_alarm} frame alarm "
          f"-> {total - beda} frame identik, {beda} berbeda")
    return beda == 0, teks_email


# ─── 3. Email ─────────────────────────────────────────────────────────────────

def uji_email(rng, teks_email):
    ok = True
    for kind in ("eye_close", "yawn", "head_tilt"):
        if kind not in teks_email:
            lapor(f"  email {kind} tidak muncul di skenario; teks tidak teruji")
            ok = False
        elif teks_email[kind] != email_darurat.PESAN_EMAIL[kind]:
            lapor(f"  BEDA teks email {kind}")
            ok = False

    # Pembatasan 2 menit + email ringkasan, dengan jam tiruan.
    jam = {"t": 1000.0}
    jam_tiruan = types.SimpleNamespace(perf_counter=lambda: jam["t"], monotonic=lambda: jam["t"])
    asli_dk, asli_em, asli_mesh = dk.time, email_darurat.time, dk.get_mediapipe_app
    try:
        dk.time, email_darurat.time = jam_tiruan, jam_tiruan
        dk.get_mediapipe_app = lambda *a, **k: None
        lama, baru = dk.VideoFrameHandler(), email_darurat.EmailDarurat()
        kirim_lama, kirim_baru = [], []
        lama.send_email_alert = lambda s, m: kirim_lama.append((jam["t"], s, m))
        baru.send_email_alert = lambda s, m: kirim_baru.append((jam["t"], s, m))
        lama.email_recipients = baru.email_recipients = ["kontak@contoh.id"]
        for _ in range(3000):
            jam["t"] += rng.choice([0.5, 3.0, 20.0, 60.0, 119.9, 120.0, 150.0])
            if rng.random() < 0.6:
                kind = rng.choice(["eye_close", "yawn", "head_tilt"])
                lama.request_email_alert(kind, *email_darurat.PESAN_EMAIL[kind])
                baru.request_email_alert(kind)
            else:
                lama.flush_held_emails()
                baru.flush_held_emails()
        n_ringkasan = sum(1 for k in kirim_lama if "Masih" in k[1])
        if kirim_lama != kirim_baru:
            lapor("  BEDA urutan/teks email dengan pembatasan 2 menit")
            ok = False
    finally:
        dk.time, email_darurat.time, dk.get_mediapipe_app = asli_dk, asli_em, asli_mesh
    lapor(f"3. Email: teks 3 jenis kejadian + simulasi 3000 langkah ({len(kirim_lama)} email terkirim, "
          f"{n_ringkasan} di antaranya email ringkasan) -> {'identik' if ok else 'BERBEDA'}")
    return ok


# ─── 4. CLAHE ─────────────────────────────────────────────────────────────────

def uji_clahe(rng, tmp):
    gambar = []
    for path in sorted(glob.glob("pengujian/citra_uji/test*.jp*g") + glob.glob("lampiran_skripsi/*/*.jpg")):
        img = cv2.imread(path)
        if img is None:
            continue
        if max(img.shape[:2]) > 1280:  # foto lampiran diperkecil agar uji tidak lama
            s = 1280 / max(img.shape[:2])
            img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        gambar.append((os.path.basename(path), img))
        if len(gambar) % 3 == 0:  # versi gelap untuk kondisi minim cahaya
            gambar.append((os.path.basename(path) + " (gelap)", (img * 0.2).astype(np.uint8)))
    for w, h in [(640, 360), (360, 640), (275, 183), (17, 33), (9, 9), (1, 1), (643, 361)]:
        gambar.append((f"acak {w}x{h}", np.random.default_rng(rng.randint(0, 10 ** 9)).integers(0, 256, (h, w, 3), dtype=np.uint8)))

    daftar = []
    for i, (nama, img) in enumerate(gambar):
        berkas = os.path.join(tmp, f"clahe_{i}.bin")
        img = np.ascontiguousarray(img)
        img.tofile(berkas)
        daftar.append({"berkas": berkas, "w": img.shape[1], "h": img.shape[0]})
    masuk = os.path.join(tmp, "clahe_in.json")
    with open(masuk, "w") as f:
        json.dump(daftar, f)
    jalankan_node("clahe", masuk, tmp)

    total_px = beda_px = 0
    maks = 0
    for (nama, img), d in zip(gambar, daftar):
        harap = dk.enhance_low_light(img)
        hasil = np.fromfile(d["berkas"] + ".js.bin", dtype=np.uint8).reshape(img.shape)
        selisih = np.abs(harap.astype(int) - hasil.astype(int))
        total_px += img.shape[0] * img.shape[1]
        beda_px += int(np.count_nonzero(selisih.max(axis=2)))
        maks = max(maks, int(selisih.max()))
    with open(os.path.join(tmp, "waktu.json")) as f:
        waktu = json.load(f)
    ms640 = [ms for d, ms in zip(daftar, waktu) if (d["w"], d["h"]) in ((640, 360), (360, 640))]
    lapor(f"4. CLAHE: {len(gambar)} citra, {total_px} piksel (OpenCV {cv2.__version__}) -> "
          f"{total_px - beda_px} piksel identik, {beda_px} berbeda, selisih maks {maks} level")
    if ms640:
        lapor(f"   waktu clahe.js di Node (PC ini) untuk 640x360: ±{sum(ms640) / len(ms640):.1f} ms per frame")
    return beda_px == 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    sys.stdout.reconfigure(encoding="utf-8")

    import mediapipe
    lapor(f"Uji kesamaan JS vs Python (seed {args.seed}, Python {sys.version.split()[0]}, "
          f"mediapipe {mediapipe.__version__}, OpenCV {cv2.__version__}, "
          f"Node {subprocess.run(['node', '--version'], capture_output=True, text=True).stdout.strip()})")
    with tempfile.TemporaryDirectory() as tmp:
        ok1 = uji_indikator(rng, tmp)
        ok2, teks_email = uji_logika(rng, tmp)
        ok3 = uji_email(rng, teks_email)
        ok4 = uji_clahe(rng, tmp)
    semua = ok1 and ok2 and ok3 and ok4
    lapor("SEMUA IDENTIK" if semua else "ADA PERBEDAAN (lihat di atas)")
    with open(os.path.join(HERE, "hasil_uji_kesamaan.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(LAPORAN) + "\n")
    sys.exit(0 if semua else 1)


if __name__ == "__main__":
    main()
