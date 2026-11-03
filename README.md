# Sistem Pendeteksi Kantuk

Aplikasi web pendeteksi kantuk pengemudi roda empat. Kamera depan ponsel memantau wajah pengemudi dan
mendeteksi tiga kondisi: **mata tertutup**, **menguap**, dan **kepala miring**. Alarm berbunyi saat
kondisi itu berlangsung melewati batas waktu, kejadiannya tercatat di histori, dan kontak terdekat
mendapat email darurat berisi tautan lokasi kalau kantuk berlangsung lama.

Seluruh pemrosesan video berjalan di browser dengan MediaPipe FaceLandmarker (JavaScript). Video tidak
pernah dikirim ke server, sehingga pemakaian data kecil dan tidak butuh server relay TURN.

## Fitur

- Deteksi wajah dengan `@mediapipe/tasks-vision` 0.10.35 (FaceLandmarker, mode VIDEO, satu wajah).
- **EAR** (Eye Aspect Ratio) untuk mata tertutup, **MAR** (Mouth Aspect Ratio) untuk menguap, dan
  **sudut garis antar-telinga** untuk kepala miring. Ambang bisa diatur dengan slider (bawaan EAR 0,23,
  MAR 0,60, sudut 20°, waktu alarm 1 detik).
- CLAHE pada kanal Y supaya wajah tetap terdeteksi saat pencahayaan redup.
- Alarm `wake_up.wav` diputar langsung di browser, disertai getar (Android). Selama sesi mikrofon ikut
  dinyalakan (tidak direkam dan tidak dikirim), sehingga Chrome Android memakai jalur suara panggilan:
  alarm mengikuti volume panggilan, yang tidak bisa 0, bukan volume media. Kalau izin mikrofon ditolak,
  alarm mengikuti volume media. Layar dijaga tetap menyala selama sesi (Screen Wake Lock).
- Email darurat ke kontak terdekat setelah mata tertutup 5 detik, menguap 3 detik, atau kepala miring
  5 detik, paling banyak satu email per 2 menit (kejadian di dalam jeda dikirim sebagai ringkasan).
- Akun dengan verifikasi OTP email, atau **mode tamu** tanpa akun (histori disimpan di browser, tanpa email).
- Halaman **Histori**: ringkasan per sesi dan daftar kejadian, dengan filter tanggal dan jenis kejadian.
- Panel **Pengujian & diagnostik** (disembunyikan, bisa diaktifkan): waktu proses per frame, FPS, dan
  unduhan CSV data mentah.

## Cara kerja

```
Ponsel (browser)                                       Server (Streamlit/Python)
───────────────────────────────────────────            ─────────────────────────────────
kamera → [CLAHE] → FaceLandmarker → EAR/MAR/sudut
       → timer & alarm → anotasi di canvas
                         │ hanya saat ada kejadian:
                         ├─ mulai     (START)       ──►  buat sesi di database
                         ├─ kejadian  (selesai)     ──►  simpan kejadian
                         ├─ email     (ambang lewat)──►  email darurat + tautan lokasi
                         ├─ flush     (jeda 2 mnt)  ──►  email ringkasan yang tertahan
                         └─ selesai   (STOP / kamera mati ≥ 3 dtk) ──► perbarui waktu selesai
```

- Tidak ada data per frame yang dikirim ke server. Setiap pesan di atas memicu satu rerun Streamlit.
- Pesan dikirim sebagai antrean bernomor. Server membalas nomor terakhir yang sudah diproses, jadi
  pesan tidak hilang atau tercatat dua kali, dan dikirim ulang otomatis kalau database sedang gagal.
- Model (`face_landmarker.task`) dan wasm diunduh dari CDN resmi sekali saja (±6,9 MB), lalu disimpan
  di Cache Storage browser untuk sesi-sesi berikutnya.
- Sesi tamu ditulis komponen langsung ke `localStorage` (maksimal 10 sesi terbaru).
- Kalau sinyal hilang (mis. di terowongan), kamera, deteksi, dan alarm tetap berjalan tanpa perlu menekan
  START lagi; di bawah video muncul "tanpa sinyal, deteksi tetap berjalan". Pesan menunggu di antrean
  (juga disimpan di `localStorage`, jadi tidak hilang walau halaman dimuat ulang atau ditinggal ke Histori)
  dan dikirim begitu tersambung lagi.
- Pemrosesan pesan aman diulang: baris sesi dicari dari akun + waktu START di perangkat, kejadian yang
  sama tidak disimpan dua kali, dan permintaan email yang sama tidak dikirim dua kali.

## Struktur repositori

| Berkas / folder | Isi |
|---|---|
| `2_🥱_Deteksi_Kantuk.py` | halaman utama: masuk, daftar + OTP, mode tamu, slider ambang, detektor |
| `pages/3_🕓_Histori.py` | histori sesi (akun dari database, tamu dari `localStorage`) |
| `detektor.py` | sisi Python komponen detektor: terima pesan, simpan ke database, email darurat |
| `sesi_login.py`, `components/penyimpanan_login/` | login yang bertahan saat halaman dimuat ulang atau koneksi tersambung ulang: token di `localStorage` browser, divalidasi ke database |
| `email_darurat.py` | teks email darurat, tautan lokasi, dan jeda 2 menit |
| `database.py` | Neon PostgreSQL: akun, OTP, sesi berkendara, kejadian kantuk |
| `components/detektor/` | komponen browser (lihat tabel di bawah) |
| `pengujian/` | uji kesamaan, uji statis, ukur database, versi Python acuan, citra uji, dan hasilnya |
| `lampiran_skripsi/` | dokumentasi pengujian, tampilan aplikasi, dan gambar untuk naskah |

| `components/detektor/` | Isi |
|---|---|
| `index.html`, `detektor.js` | kamera, loop deteksi, alarm, wake lock, GPS, antrean pesan, panel pengujian |
| `logika.js` | EAR, MAR, sudut kepala, penghitung waktu, alarm, dan aturan pencatatan kejadian |
| `clahe.js` | CLAHE kanal Y tanpa OpenCV.js |
| `model.js` | pemuatan FaceLandmarker + Cache Storage |
| `anotasi.js` | titik landmark, garis, dan teks di atas video |
| `uji_statis.html`, `uji_statis.js` | uji statis pada citra uji |
| `wake_up.wav` | suara alarm |

## Menjalankan di lokal

1. Python 3.10 ke atas, lalu:
   ```bash
   pip install -r requirements.txt
   ```
2. Buat `.env` berisi `DATABASE_URL` (Neon PostgreSQL) dan `EMAIL_PASSWORD` (app password Gmail
   pengirim `deteksikantuk@gmail.com`). Opsional: `PANEL_PENGUJIAN=1` untuk menampilkan panel pengujian.
3. Jalankan:
   ```bash
   streamlit run "2_🥱_Deteksi_Kantuk.py"
   ```
4. Buka `http://localhost:8501`. Browser hanya mengizinkan kamera di HTTPS atau `localhost`, dan
   Streamlit 1.17 belum punya opsi HTTPS. Untuk mencoba dari ponsel di jaringan yang sama:
   - tunnel HTTPS, mis. `cloudflared tunnel --url http://localhost:8501`, lalu buka URL `https://…` di ponsel;
   - atau Chrome Android: `chrome://flags/#unsafely-treat-insecure-origin-as-secure`, isi
     `http://<IP-laptop>:8501`, lalu muat ulang Chrome.

## Deploy ke Streamlit Community Cloud

1. Push ke GitHub.
2. Di [share.streamlit.io](https://share.streamlit.io): *Create app* → repo
   `apriadiarzi/deteksi-kantuk-skripsi-js`, branch `main`, main file `2_🥱_Deteksi_Kantuk.py`.
   Versi Python bebas (3.10–3.14).
3. *Advanced settings* → Secrets:
   ```toml
   DATABASE_URL = "postgresql://…"
   EMAIL_PASSWORD = "…"
   # PANEL_PENGUJIAN = "1"   # opsional, tampilkan panel Pengujian & diagnostik
   ```

## Pengujian

### Uji langsung (panel Pengujian & diagnostik)

Nilai EAR, MAR, sudut kepala, dan lama tiap kondisi tampil di atas video. Panel **Pengujian &
diagnostik** disembunyikan secara bawaan; tampilkan dengan `PANEL_PENGUJIAN = "1"` di Secrets (atau
`PANEL_PENGUJIAN=1` di `.env`), lalu reboot aplikasi. Tanpa panel, CLAHE selalu aktif dan delegate CPU.
Panel ini muncul di bawah video dan menampilkan:

- waktu proses per frame, yaitu deteksi FaceLandmarker + perhitungan EAR/MAR/sudut: rata-rata, median,
  P95, minimum, dan maksimum (nearest-rank). 10 frame pertama tiap sesi diabaikan sebagai pemanasan;
- baris terpisah untuk deteksi saja, CLAHE, dan total termasuk CLAHE;
- FPS, resolusi frame, delegate (CPU/GPU), status CLAHE, dan asal model (CDN atau cache);
- tombol **Unduh CSV** berisi data mentah per frame (pemisah `;`, desimal koma, frame pemanasan ditandai);
- pilihan CLAHE on/off dan delegate CPU/GPU (bawaannya CLAHE aktif, CPU).

Waktu diukur dengan `performance.now()`, yang dibulatkan browser (Chrome ±0,1 ms, Safari/Firefox ±1 ms).

### Uji statis

Setelah halaman aplikasi dibuka sekali, buka `/component/detektor.detektor/uji_statis.html` di alamat
yang sama (mis. `http://localhost:8501/component/detektor.detektor/uji_statis.html`), pilih citra di
`pengujian/citra_uji/`, lalu **Proses**. Hasilnya bisa diunduh sebagai CSV. Opsional, pilih
`pengujian/hasil_uji_statis/hasil_uji_statis.csv` untuk membandingkan dengan versi Python.

### Uji kesamaan logika dengan versi Python

Logika di `components/detektor/` diterjemahkan dari versi Python sebelumnya
(`pengujian/deteksi_kantuk.py`, MediaPipe Face Mesh + OpenCV). Uji ini membandingkan keduanya langsung:
indikator dari 3.000 set landmark acak, logika per frame dari ±150 ribu frame skenario acak (termasuk
wajah hilang, STOP/START, dan slider yang digeser), teks email dan jeda 2 menit, serta CLAHE piksel per
piksel. Butuh Python ≤ 3.11 dan Node.js:

```bash
pip install -r pengujian/requirements.txt
python pengujian/uji_kesamaan.py
```

Hasil terakhir: **semua identik**, lihat [`pengujian/hasil_uji_kesamaan.txt`](pengujian/hasil_uji_kesamaan.txt).

### Lainnya

- `python pengujian/uji_statis.py`: uji statis versi Python, hasil di `pengujian/hasil_uji_statis/`.
- `python pengujian/ukur_db.py`: waktu handshake dan query ke database (baris uji di-rollback).
- `pengujian/test_deteksi_statis*.ipynb`: notebook eksplorasi titik landmark.

## Pemakaian data

Hasil pengukuran dengan data seluler, dibandingkan dengan versi sebelumnya yang mengirim video ke server
lewat streamlit-webrtc dan relay TURN Metered:

| | Versi browser (repo ini) | Versi Python (sebelumnya) |
|---|---|---|
| Durasi uji | ±2 menit | ±1,5 menit |
| Data seluler terpakai | **±10 MB** | ±35 MB |
| Relay TURN Metered | tidak dipakai sama sekali | dipakai |

Angka versi browser di atas sudah termasuk unduhan model dan wasm sekali di awal:

| Berkas (dari CDN, terkompresi) | Ukuran |
|---|---|
| `vision_wasm_internal.wasm` | ±2,99 MB |
| `face_landmarker.task` (model) | ±3,76 MB |
| `vision_wasm_internal.js` + `vision_bundle.mjs` | ±0,11 MB |
| **Total sekali unduh** | **±6,9 MB** |

Sesi berikutnya memakai model dari cache browser, sehingga pemakaiannya lebih kecil lagi. Sisa lalu
lintasnya hanya websocket Streamlit: ±14 KB per pesan kejadian pada uji lokal.

Untuk pengukuran ulang yang adil: matikan Wi-Fi, pakai ponsel dan posisi yang sama, catat pemakaian data
aplikasi browser (Android: Setelan › Jaringan › Penggunaan data) sebelum dan sesudah sesi dengan durasi
dan skenario yang sama, ulangi beberapa kali, dan pisahkan sesi pertama (yang mengunduh model) dari
sesi-sesi berikutnya.

## Catatan perbedaan dengan versi Python

Rumus, indeks landmark, ambang, penghitung waktu, aturan pencatatan, teks di layar, dan teks email
identik dengan versi Python (lihat uji kesamaan). Perbedaan yang tersisa:

1. **Model landmark.** Versi Python memakai Face Mesh legacy (468 titik), versi ini FaceLandmarker
   (478 titik). Indeks 0–467 sama, tetapi bobot modelnya berbeda. Pada citra uji, EAR mata terbuka mirip
   (0,28–0,39), sedangkan EAR mata tertutup jauh lebih rendah (±0,05–0,08 vs ±0,16–0,20). Pada
   `test-head-tilt.jpeg` (mata terpejam) versi ini ikut menyimpulkan "mata tertutup", yang tidak
   terdeteksi versi Python. Ambang 0,23 tetap memisahkan kedua kondisi.
2. **Frame masukan.** Versi Python memproses frame hasil kompresi WebRTC; versi ini memproses frame kamera
   asli (kamera depan, tinggi 360 px, 15 fps). Mikrofon hanya dinyalakan untuk jalur suara alarm, tidak
   direkam atau dikirim.
3. **STOP langsung menyimpan.** Versi Python menutup sesi setelah kamera mati ≥ 3 detik, jadi waktu
   selesai di database ±3–5 detik lebih lambat. Kamera yang mati sendiri ≥ 3 detik tetap menutup sesi.
4. **Tanpa simpan berkala.** Versi Python memperbarui waktu selesai sesi tiap 15 detik. Versi ini hanya
   mengirim pesan saat ada kejadian, jadi kalau tab ditutup paksa tanpa STOP, waktu selesai sesi = waktu
   pesan terakhir.
5. **Penghitung waktu di-reset di awal sesi.** Di versi Python, jeda sejak sesi sebelumnya bisa langsung
   terhitung sebagai lama mata tertutup/kepala miring pada frame pertama sesi baru. Ini diperbaiki.
6. **Pembulatan numerik.** `atan2` dan `pow(x, 0.5)` di pustaka C bisa berbeda di digit terakhir
   (±1e-14) dari JavaScript. Ini tidak mengubah teks di layar maupun keputusan.
