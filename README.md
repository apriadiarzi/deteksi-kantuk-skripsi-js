# Sistem Pendeteksi Kantuk

Aplikasi Streamlit pendeteksi kantuk pengemudi (mata tertutup, menguap, kepala miring) dengan dua mode
deteksi yang bisa dipakai bergantian:

| | Mode **server** (versi lama) | Mode **browser** (baru) |
|---|---|---|
| Video kamera | dikirim ke server lewat streamlit-webrtc + relay TURN Metered | **tidak dikirim**, diproses di ponsel |
| Deteksi wajah | MediaPipe Face Mesh (Python) di server | MediaPipe FaceLandmarker (JavaScript, `@mediapipe/tasks-vision` 0.10.35) di browser |
| EAR, MAR, sudut, timer, alarm | `deteksi_kantuk.py` | `components/detektor/logika.js` (salinan langsung, diuji identik) |
| CLAHE kanal Y | OpenCV | `components/detektor/clahe.js` (meniru OpenCV, diuji identik piksel per piksel) |
| Alarm | disisipkan ke aliran audio WebRTC | diputar langsung di browser (`wake_up.wav`) |
| Data ke server | video + audio terus-menerus | hanya pesan kecil saat ada kejadian |

Login/daftar/OTP, mode tamu, penyimpanan ke Neon PostgreSQL, email darurat + lokasi, dan halaman Histori
tetap ditangani Python dan sama untuk kedua mode. Skema database tidak berubah.

## Memilih mode

- **Bawaan** diatur lewat `MODE_DETEKSI` di `.env` (lokal) atau Secrets (Streamlit Cloud):
  `MODE_DETEKSI = "browser"` atau `MODE_DETEKSI = "server"`. Kalau tidak diisi, bawaannya `browser`.
- **Saat aplikasi berjalan**, mode bisa diganti di sidebar ("Mode deteksi"). Pilihan ini dikunci selama
  sesi berjalan, jadi kedua mode bisa diuji bergantian pada deployment yang sama tanpa redeploy.

Mode browser tidak mengimpor streamlit-webrtc, aiortc, av, OpenCV, maupun MediaPipe Python, dan tidak
memanggil API Metered. Paket-paket itu tetap ada di `requirements.txt` karena mode server masih dipakai,
tetapi versi yang dikunci hanya punya wheel sampai Python 3.11. Di Python 3.12 ke atas paket itu dilewati
(penanda `python_version` di `requirements.txt`) dan sidebar hanya menawarkan mode browser.

## Cara kerja mode browser

```
Ponsel (browser)                                       Server (Streamlit/Python)
───────────────────────────────────────────            ─────────────────────────────────
kamera → [CLAHE] → FaceLandmarker → EAR/MAR/sudut
       → timer & alarm → anotasi di canvas
                         │ hanya saat ada kejadian:
                         ├─ mulai     (START)       ──►  start_session() di Neon
                         ├─ kejadian  (selesai)     ──►  save_session_progress()
                         ├─ email     (ambang lewat)──►  email darurat + tautan lokasi
                         ├─ flush     (jeda 2 mnt)  ──►  email ringkasan yang tertahan
                         └─ selesai   (STOP / kamera mati ≥ 3 dtk) ──► perbarui waktu selesai
```

- Setiap pesan memicu satu rerun Streamlit. Tidak ada pesan per frame dan tidak ada autorefresh.
- Pesan dikirim sebagai antrean bernomor. Python membalas nomor terakhir yang sudah diproses, jadi
  pesan tidak hilang atau tercatat dua kali, dan dikirim ulang otomatis kalau database sedang gagal.
- Mode tamu tidak mengirim email. Historinya ditulis komponen langsung ke `localStorage` dengan
  kunci dan format yang sama seperti sebelumnya (maksimal 10 sesi).
- Layar dijaga tetap menyala dengan Screen Wake Lock API selama sesi berjalan, kalau browser mendukung.
- Model (`face_landmarker.task`) dan wasm diunduh dari CDN resmi sekali saja, lalu disimpan di Cache
  Storage browser. Asalnya (CDN atau cache) terlihat di panel "Pengujian & diagnostik".

### Berkas

| Berkas | Isi |
|---|---|
| `components/detektor/index.html`, `detektor.js` | komponen Streamlit: kamera, loop deteksi, alarm, wake lock, GPS, antrean pesan, panel pengujian |
| `components/detektor/logika.js` | indikator + penghitung waktu + aturan pencatatan (salinan `deteksi_kantuk.py`) |
| `components/detektor/clahe.js` | CLAHE kanal Y tanpa OpenCV.js |
| `components/detektor/model.js` | pemuatan FaceLandmarker + Cache Storage |
| `components/detektor/anotasi.js` | gambar titik, garis, dan teks seperti `plot_*` versi lama |
| `components/detektor/uji_statis.html` | uji statis versi browser (padanan `uji_statis.py`) |
| `components/detektor/wake_up.wav` | salinan `audio/wake_up.wav` (komponen hanya bisa menyajikan berkas dari foldernya) |
| `detektor_component.py` | `declare_component` untuk komponen di atas |
| `mode_browser.py` | sisi Python mode browser: proses pesan, simpan ke Neon, email |
| `email_darurat.py` | logika email darurat (teks & jeda 2 menit sama dengan versi lama) tanpa OpenCV/MediaPipe |
| `uji_mode_browser/` | uji kesamaan JS vs Python dan hasilnya |

## Menjalankan di lokal

1. Python 3.10 + Node.js (Node hanya untuk uji kesamaan), lalu:
   ```bash
   pip install -r requirements.txt
   ```
2. Buat `.env` berisi `DATABASE_URL`, `EMAIL_PASSWORD`, `GOOGLE_API_KEY`, `METERED_APP_NAME`,
   `METERED_API_KEY` (dua terakhir hanya dipakai mode server), dan opsional `MODE_DETEKSI`, `DIAGNOSTIK=1`.
3. Jalankan:
   ```bash
   streamlit run "2_🥱_Deteksi_Kantuk.py"
   ```
4. Buka `http://localhost:8501`. Browser hanya mengizinkan kamera di HTTPS atau `localhost`. Streamlit
   1.17 belum punya opsi HTTPS, jadi untuk mencoba dari ponsel di jaringan yang sama pakai salah satu:
   - tunnel HTTPS, mis. `cloudflared tunnel --url http://localhost:8501`, lalu buka URL `https://…` di ponsel;
   - Chrome Android: `chrome://flags/#unsafely-treat-insecure-origin-as-secure`, isi
     `http://<IP-laptop>:8501`, lalu muat ulang Chrome;
   - atau langsung deploy ke Streamlit Community Cloud (sudah HTTPS).

## Deploy ke Streamlit Community Cloud

1. Push branch ini ke GitHub: `git push -u origin deteksi-browser`.
2. Di [share.streamlit.io](https://share.streamlit.io), pilih salah satu:
   - **app baru** (disarankan, supaya versi lama di `main` tetap jalan): *Create app* → repo
     `apriadiarzi/deteksi-kantuk-skripsi`, branch `deteksi-browser`, main file `2_🥱_Deteksi_Kantuk.py`;
   - atau ubah branch app yang sudah ada di *Settings*.
3. *Advanced settings* → **Python 3.11** (atau 3.10 kalau masih ada) → Secrets: salin isi `.env` dalam
   format TOML, mis.
   ```toml
   DATABASE_URL = "postgresql://…"
   EMAIL_PASSWORD = "…"
   GOOGLE_API_KEY = "…"
   METERED_APP_NAME = "…"
   METERED_API_KEY = "…"
   MODE_DETEKSI = "browser"
   ```
4. Versi Python hanya bisa dipilih saat app dibuat. Reboot atau push tidak mengubahnya; untuk menggantinya,
   catat Secrets, hapus app, lalu deploy ulang. Cek baris `Using Python 3.x.y` di awal log. Kalau Streamlit
   Cloud memakai Python 3.12 ke atas (bawaannya sekarang versi terbaru), app tetap terpasang dan mode browser
   berjalan, tetapi mode server tidak tersedia, jadi pembandingan dengan mode server butuh Python 3.11.

## Pengujian

### Uji kesamaan logika (JS vs Python)

```bash
python uji_mode_browser/uji_kesamaan.py
```

Membandingkan kode JS mode browser dengan kode Python versi lama secara langsung: indikator dari 3.000 set
landmark acak, logika per frame dari ±150 ribu frame skenario acak (termasuk wajah hilang, STOP/START, dan
slider yang digeser), teks email dan jeda 2 menit, serta CLAHE pada citra uji dan foto lampiran. Hasil
terakhir ada di [`uji_mode_browser/hasil_uji_kesamaan.txt`](uji_mode_browser/hasil_uji_kesamaan.txt).

### Uji statis (Tabel hasil citra uji)

Buka `http://localhost:8501/component/detektor_component.detektor/uji_statis.html` saat aplikasi berjalan.
Bisa juga lewat `python -m http.server` dari folder repo, lalu buka
`http://localhost:8000/components/detektor/uji_statis.html`. Pilih keenam berkas `test-*.jp*g` dan,
opsional, `hasil_uji_statis/hasil_uji_statis.csv` untuk perbandingan dengan versi lama. Hasilnya bisa
diunduh sebagai CSV dengan format yang sama seperti `hasil_uji_statis.csv`.

### Uji langsung (Tabel 3.12 dan 3.13)

Nilai EAR, MAR, sudut, dan lama tiap kondisi tampil di layar dengan posisi, warna, dan teks yang sama
seperti versi lama. Panel **Pengujian & diagnostik** di bawah video menampilkan:

- waktu proses per frame, yaitu deteksi FaceLandmarker + perhitungan EAR/MAR/sudut. Statistiknya rata-rata,
  median, P95, minimum, dan maksimum (metode nearest-rank seperti `diagnostik.py`), dan 10 frame pertama
  tiap sesi diabaikan;
- baris terpisah untuk deteksi saja, CLAHE, dan total termasuk CLAHE;
- FPS (sekarang dan rata-rata sesi), resolusi frame, delegate (CPU/GPU), status CLAHE, asal model;
- tombol **Unduh CSV** berisi data mentah per frame (pemisah `;`, desimal koma). Frame pemanasan
  ditandai di kolom `pemanasan`;
- pilihan CLAHE on/off dan delegate CPU/GPU untuk pengujian. Bawaannya CLAHE aktif dan CPU, yang paling
  mirip versi lama.

Catatan pengukuran waktu: `performance.now()` dibulatkan browser (Chrome ±0,1 ms, Safari/Firefox ±1 ms).
Versi lama (mode server, `DIAGNOSTIK=1`) mengukur seluruh callback, termasuk konversi frame, CLAHE, dan
menggambar anotasi. Bandingkan dengan baris "Total termasuk CLAHE", jangan dengan "Deteksi + indikator".

## Mengukur pemakaian data secara adil

Tujuannya membandingkan MB per menit kedua mode dalam kondisi yang sama.

**Persiapan (sama untuk kedua mode)**
1. Ponsel, browser, posisi ponsel, pencahayaan, dan lokasi yang sama. Tutup tab dan aplikasi lain.
   Matikan pembaruan otomatis, sinkronisasi foto/cloud, dan hotspot.
2. **Matikan Wi-Fi**, pakai data seluler saja.
3. Login dengan akun yang sama (atau sama-sama mode tamu).

**Pisahkan unduhan sekali di awal**

Pada sesi pertama mode browser, browser mengunduh pustaka dan model sekali saja. Ukuran yang diukur dari
CDN (terkompresi):

| Berkas | Ukuran transfer |
|---|---|
| `vision_wasm_internal.wasm` | ±2,99 MB |
| `face_landmarker.task` (model) | ±3,76 MB |
| `vision_wasm_internal.js` + `vision_bundle.mjs` | ±0,11 MB |
| **Total sekali unduh** | **±6,9 MB** |

Mode server juga punya unduhan sekali, yaitu kode komponen streamlit-webrtc. Kedua mode sama-sama
memuat halaman Streamlit itu sendiri. Supaya yang diukur hanya pemakaian per menit:

1. Lakukan **sesi pemanasan** dulu untuk tiap mode: buka aplikasi, tekan START, tunggu deteksi berjalan,
   lalu STOP. Di mode browser, panel diagnostik harus menunjukkan "Model & wasm … dari cache browser"
   saat dimuat ulang.
2. Kalau ingin mencatat unduhan sekali secara terpisah: hapus data situs dulu (Chrome › Setelan ›
   Setelan situs › Data situs › hapus untuk domain aplikasi), lalu ukur sesi pertama itu sendiri.

**Pengukuran per sesi**
1. Tentukan durasi tetap, mis. 10 menit, dengan skenario yang sama, mis. tiap menit tutup mata 3 detik
   dan menguap sekali.
2. Sebelum mulai, catat:
   - pemakaian data browser di ponsel. Android: Setelan › Jaringan › Penggunaan data › aplikasi browser
     (lebih teliti daripada sisa kuota total). iOS: Setelan › Seluler, catat angka Safari/Chrome;
   - sisa kuota operator, kalau ingin;
   - dashboard Metered (Usage).
3. Jalankan sesi, lalu STOP tepat di akhir durasi.
4. Catat lagi angka yang sama. Dashboard Metered bisa terlambat beberapa menit, jadi tunggu sebelum
   mencatatnya.
5. Ulangi minimal 3 kali per mode secara bergantian (server, browser, server, browser, …) supaya
   perubahan kondisi jaringan tidak hanya mengenai satu mode.
6. Hitung `MB/menit = (sesudah − sebelum) / durasi`. Kalau sesi itu juga memuat unduhan sekali,
   kurangi dengan angka di tabel di atas.

**Hal yang perlu dicatat di skripsi**
- Mode server mengirim video **dan audio mikrofon** ke server, lalu menerima video beranotasi dan audio
  balik. Resolusinya bisa diturunkan otomatis oleh WebRTC saat sinyal jelek.
- Kuota Metered hanya terpakai kalau koneksi WebRTC lewat relay TURN. Kalau jalur langsung (STUN)
  berhasil, Metered bisa tetap 0 walau data seluler terpakai. Jenis jalurnya terlihat di
  `chrome://webrtc-internals` (candidate pair `relay` vs `srflx`/`host`). Halaman yang sama juga
  menampilkan `bytesSent`/`bytesReceived` WebRTC secara tepat.
- Mode browser tidak memakai Metered sama sekali. Sisa lalu lintasnya: websocket Streamlit (rerun saat
  ada pesan, ±14 KB per pesan pada uji lokal), ping websocket, dan unduhan sekali di atas. Pada uji lokal,
  sesi 20 detik dengan 5 pesan memakai ±75 KB websocket.
- Rerun mode server terjadi tiap 2 detik (autorefresh), dan setiap rerun juga mengirim ulang elemen
  halaman. Lalu lintas ini ikut terhitung di mode server.

## Perbedaan perilaku dengan versi lama

Rumus, indeks landmark, ambang, penghitung waktu, aturan pencatatan, teks di layar, dan teks email
identik (lihat uji kesamaan). Perbedaan yang tersisa:

1. **Model landmark.** Versi lama memakai Face Mesh legacy (`refine_landmarks=False`, 468 titik). Mode
   browser memakai FaceLandmarker (478 titik). Indeks 0–467 sama, tapi bobot modelnya berbeda. Pada citra
   uji, EAR mata terbuka mirip (0,28–0,39), sedangkan EAR mata tertutup jauh lebih rendah (±0,05–0,08
   vs ±0,16–0,20). Pada `test-head-tilt.jpeg` (mata terpejam) mode browser ikut menyimpulkan "mata
   tertutup", yang tidak terdeteksi versi lama. Ambang 0,23 tetap memisahkan kedua kondisi.
2. **Frame masukan.** Versi lama memproses frame hasil kompresi WebRTC. Mode browser memproses frame
   kamera asli dengan constraint yang sama (kamera depan, tinggi 360, 15 fps). Mikrofon tidak diminta.
3. **STOP langsung menyimpan.** Versi lama menutup sesi setelah kamera mati ≥ 3 detik (dicek tiap
   2 detik), jadi waktu selesai di database ±3–5 detik lebih lambat. Kamera yang mati sendiri ≥ 3 detik
   tetap menutup sesi di kedua mode.
4. **Tanpa checkpoint berkala.** Versi lama memperbarui waktu selesai sesi tiap 15 detik. Mode browser
   hanya mengirim pesan saat ada kejadian, jadi kalau tab ditutup paksa tanpa STOP, waktu selesai sesi
   = waktu pesan terakhir.
5. **Lokasi GPS** dikirim bersama pesan email, tidak lagi lewat komponen geolocation terpisah, jadi
   tidak ada rerun tiap kali posisi berubah.
6. **Perbaikan di kedua mode:** penghitung waktu kini di-reset pada frame pertama tiap sesi kamera.
   Sebelumnya jeda sejak frame terakhir sesi sebelumnya (atau sejak halaman dibuka) bisa langsung terhitung
   sebagai lama mata tertutup/kepala miring kalau frame pertama sesi sudah dalam kondisi itu.
7. **Pembulatan numerik.** `atan2` dan `pow(x, 0.5)` di pustaka C bisa berbeda di digit terakhir
   (±1e-14) dari JavaScript. Ini tidak mengubah teks di layar maupun keputusan.

<!-- # Driver Drowsines Detection using Mediapipe in Python

**This repository contains code for the blog post [Driver Drowsines Detection using Mediapipe in Python](https://learnopencv.com/driver-drowsiness-detection-using-mediapipe-in-python/)**.

In this post, we will:

* Learn how to detect eye landmarks using the Mediapipe Face Mesh solution pipeline in python.
* Introduce and demonstrate the Eye Aspect Ratio (EAR) technique.
* Create a Drowsiness Detection web application using streamlit.
* Use streamlit-webrtc to help transmit real-time video/audio streams over the network.
* Deploy it on a cloud service.

[<img src="https://learnopencv.com/wp-content/uploads/2022/07/download-button-e1657285155454.png" alt="download" width="200">](https://www.dropbox.com/scl/fo/5uqodfo3b668xbtqzqqt0/h?dl=1&rlkey=cb2gkzoeobpvyv74299rbdg8c)

<img src = 'app_image/page_SS.jpg'>

# AI Courses by OpenCV

Want to become an expert in AI? [AI Courses by OpenCV](https://opencv.org/courses/) is a great place to start.

<a href="https://opencv.org/courses/">
<p align="center">
<img src="https://learnopencv.com/wp-content/uploads/2023/01/AI-Courses-By-OpenCV-Github.png">
</p>
</a> -->
#   d e t e k s i - k a n t u k - s k r i p s i - j s  
 #   d e t e k s i - k a n t u k - s k r i p s i - j s  
 