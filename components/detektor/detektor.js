/*
 * Komponen Streamlit "detektor": kamera, deteksi wajah, logika kantuk, alarm, dan pengukuran
 * waktu proses, semuanya di browser. Ke Python hanya dikirim pesan kecil saat ada kejadian
 * (lihat detektor.py); setiap pesan memicu satu rerun Streamlit.
 */
(function () {
  "use strict";

  const L = window.Logika, M = window.ModelWajah, A = window.Anotasi;

  const PEMANASAN = 10;           // frame awal tiap sesi yang tidak dihitung (pemanasan)
  const BATAS_KAMERA_MATI = 3000; // ms kamera tidak aktif sebelum sesi disimpan
  const JEDA_KIRIM_ULANG = 8000;  // ms sebelum pesan yang belum dikonfirmasi dikirim ulang
  const KUNCI_PENGATURAN = "deteksi_kantuk_pengaturan_uji";
  const KUNCI_ANTREAN = "deteksi_kantuk_antrean";

  const el = (id) => document.getElementById(id);
  const layar = el("layar"), layarPesan = el("layar-pesan");
  const kanvas = el("kanvas"), ctx = kanvas.getContext("2d");
  const kanvasKerja = document.createElement("canvas");
  const ctxKerja = kanvasKerja.getContext("2d", { willReadFrequently: true });
  const video = el("video");
  const tombolMulai = el("tombol-mulai"), tombolBerhenti = el("tombol-berhenti");
  const statusEl = el("status");

  const alarmAudio = new Audio("wake_up.wav");
  alarmAudio.preload = "auto";

  // ─── Protokol komponen Streamlit ────────────────────────────────────────────

  function kirimStreamlit(type, data) {
    window.parent.postMessage(Object.assign({ isStreamlitMessage: true, type }, data), "*");
  }

  let tinggiTerakhir = 0;
  function aturTinggi() {
    const t = Math.ceil(document.body.getBoundingClientRect().height);
    if (t !== tinggiTerakhir) {
      tinggiTerakhir = t;
      kirimStreamlit("streamlit:setFrameHeight", { height: t });
    }
  }
  new ResizeObserver(aturTinggi).observe(document.body);

  let args = {
    ambang: { EAR_THRESH: 0.23, MAR_THRESH: 0.6, TILT_THRESH: 20.0, WAIT_TIME: 1.0 },
    email_aktif: false,
    tamu: false,
    kunci_tamu: "drowsiness_guest_sessions",
    ack: null,
    flush_dalam_ms: null,
    panel_pengujian: false,
    akun: null,
  };

  window.addEventListener("message", (ev) => {
    const d = ev.data;
    if (!d || d.type !== "streamlit:render") return;
    Object.assign(args, d.args || {});
    terapkanPanel();
    terimaAck();
    aturFlush();
    mulaiGps();
    perbaruiPanel();
  });

  // ─── Pengaturan pengujian (per browser) ────────────────────────────────────
  // Pengaturan tersimpan hanya dipakai kalau panel pengujian ditampilkan; tanpa panel selalu bawaan.

  const BAWAAN = { clahe: true, delegate: "CPU" };
  const pengaturan = { ...BAWAAN };
  let panelTampil = false;

  function simpanPengaturan() {
    try { localStorage.setItem(KUNCI_PENGATURAN, JSON.stringify(pengaturan)); } catch (e) { /* abaikan */ }
  }

  function isiOpsi() {
    el("opsi-clahe").checked = pengaturan.clahe;
    el("opsi-delegate").value = pengaturan.delegate;
  }

  function terapkanPanel() {
    const tampil = !!args.panel_pengujian;
    if (tampil === panelTampil) return;
    panelTampil = tampil;
    el("panel").hidden = !tampil;
    const delegateLama = pengaturan.delegate;
    Object.assign(pengaturan, BAWAAN);
    if (tampil) {
      try {
        Object.assign(pengaturan, JSON.parse(localStorage.getItem(KUNCI_PENGATURAN) || "{}"));
      } catch (e) { /* localStorage tidak tersedia: pakai bawaan */ }
    }
    isiOpsi();
    if (pengaturan.delegate !== delegateLama) muatUlangModel();
  }

  isiOpsi();
  el("opsi-clahe").addEventListener("change", (e) => {
    pengaturan.clahe = e.target.checked;
    simpanPengaturan();
  });
  el("opsi-delegate").addEventListener("change", (e) => {
    pengaturan.delegate = e.target.value;
    simpanPengaturan();
    muatUlangModel();
  });

  // ─── Model ─────────────────────────────────────────────────────────────────

  let landmarker = null, delegateAktif = null, pemuatan = null;
  const clahe = new window.Clahe.Clahe(3.0, 8, 8);

  function muatModel() {
    if (landmarker) return Promise.resolve();
    if (!pemuatan) {
      perbaruiTombol();
      pemuatan = M.buatLandmarker({ mode: "VIDEO", delegate: pengaturan.delegate })
        .then((h) => {
          landmarker = h.landmarker;
          delegateAktif = h.delegate;
        })
        .catch((e) => {
          console.error(e);
          aturStatus("Gagal memuat model deteksi wajah. Periksa koneksi internet lalu muat ulang halaman. (" + e.message + ")", "galat");
        })
        .finally(() => {
          pemuatan = null;
          perbaruiTombol();
          perbaruiPanel();
        });
    }
    return pemuatan;
  }

  function muatUlangModel() {
    if (berjalan) return;
    // Model yang sedang dimuat ditunggu dulu, lalu dimuat ulang dengan delegate terbaru.
    if (pemuatan) { pemuatan.then(muatUlangModel); return; }
    if (landmarker && delegateAktif === pengaturan.delegate) return;
    if (landmarker) {
      landmarker.close();
      landmarker = null;
    }
    muatModel();
  }

  // ─── Sesi ──────────────────────────────────────────────────────────────────

  let berjalan = false, sedangMulai = false;
  let stream = null, track = null, streamMik = null, statusMik = "belum diminta";
  let sesi = null, sesiTerakhir = null; // { uid, mulaiMs, jumlah, kejadianTamu }
  const detektor = new L.DetektorKantuk();
  let ukur = null; // pengukuran waktu proses sesi berjalan/terakhir
  let frameTerakhir = 0, tsTerakhir = 0, galatFrame = null;

  function pesanGalatKamera(e) {
    if (!navigator.mediaDevices) return "Kamera hanya bisa dibuka lewat HTTPS atau localhost.";
    switch (e && e.name) {
      case "NotAllowedError": return "Izin kamera ditolak. Izinkan akses kamera untuk situs ini lalu tekan START lagi.";
      case "NotFoundError": return "Kamera tidak ditemukan.";
      case "NotReadableError": return "Kamera sedang dipakai aplikasi lain.";
      default: return "Kamera tidak bisa dibuka: " + (e && e.message ? e.message : e);
    }
  }

  async function mulai() {
    if (berjalan || sedangMulai) return;
    sedangMulai = true;
    perbaruiTombol();
    bukaKunciAudio();
    try {
      aturStatus("Membuka kamera…");
      try {
        // Kamera depan, tinggi 360 px, 15 fps.
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: "user" }, height: { ideal: 360 }, frameRate: { ideal: 15, max: 20 } },
          audio: false,
        });
      } catch (e) {
        throw new Error(pesanGalatKamera(e));
      }
      track = stream.getVideoTracks()[0];
      track.addEventListener("ended", cekKamera);
      video.srcObject = stream;
      await video.play();

      // Mikrofon ikut dinyalakan (tidak direkam dan tidak dikirim ke mana pun) supaya Chrome Android
      // memakai jalur suara panggilan: alarm mengikuti volume panggilan, yang tidak bisa 0, bukan
      // volume media. Kalau ditolak, sesi tetap berjalan dan alarm mengikuti volume media.
      try {
        streamMik = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
        statusMik = "aktif";
      } catch (e) {
        streamMik = null;
        statusMik = "tidak diizinkan, alarm mengikuti volume media";
      }
      bukaKunciAudio();

      if (!landmarker) {
        aturStatus("Memuat model deteksi wajah…");
        await muatModel();
        if (!landmarker) throw new Error("Model deteksi wajah belum siap.");
      }

      const sekarang = Date.now();
      sesi = { uid: (args.tamu ? "g_" : "s_") + sekarang, mulaiMs: sekarang, jumlah: 0, kejadianTamu: [] };
      detektor.mulaiSesi();
      ukur = { baris: [], n: 0, mulai: performance.now(), clahe: pengaturan.clahe, delegate: delegateAktif, ringkasan: null };
      galatFrame = null;
      if (args.tamu) simpanTamu();
      kirimPesan({ jenis: "mulai", mulai_ms: sesi.mulaiMs });

      berjalan = true;
      frameTerakhir = performance.now();
      mintaWakeLock();
      jadwalkanFrame();
      aturStatus("");
    } catch (e) {
      console.error(e);
      hentikanKamera();
      aturStatus(e && e.message ? e.message : String(e), "galat");
    } finally {
      sedangMulai = false;
      perbaruiTombol();
      perbaruiPanel();
    }
  }

  function hentikan(alasan) {
    if (!berjalan) return;
    berjalan = false;
    aturAlarm(false);
    alarmAudio.pause();
    alarmAudio.loop = false;
    hentikanKamera();
    lepasWakeLock();
    clearTimeout(timerFlush);

    ukur.ringkasan = ringkasanWaktu();
    if (args.tamu) simpanTamu();
    kirimPesan({ jenis: "selesai", alasan, jumlah_kejadian: sesi.jumlah, ringkasan: ukur.ringkasan });
    sesiTerakhir = sesi;
    sesi = null;
    layarPesan.textContent = alasan === "kamera"
      ? "Kamera tidak aktif selama 3 detik, sesi disimpan. Tekan START untuk sesi baru."
      : "Sesi dihentikan. Tekan START untuk sesi baru.";
    layarPesan.hidden = false;
    aturStatus("");
    perbaruiTombol();
    perbaruiPanel();
  }

  function hentikanKamera() {
    if (stream) stream.getTracks().forEach((t) => t.stop());
    if (streamMik) streamMik.getTracks().forEach((t) => t.stop());
    stream = null;
    streamMik = null;
    track = null;
    video.srcObject = null;
  }

  // Kamera dianggap tidak aktif kalau track berakhir/dibisukan atau tidak ada frame baru,
  // selama halaman terlihat (saat halaman disembunyikan browser memang berhenti mengirim frame).
  let tandaMati = null;
  function cekKamera() {
    if (!berjalan) return;
    const now = performance.now();
    const terlihat = document.visibilityState === "visible";
    let sejak = null;
    if (!track || track.readyState === "ended" || (terlihat && track.muted)) {
      if (tandaMati === null) tandaMati = now;
      sejak = tandaMati;
    } else {
      tandaMati = null;
    }
    if (terlihat && now - frameTerakhir >= BATAS_KAMERA_MATI) {
      sejak = sejak === null ? frameTerakhir : Math.min(sejak, frameTerakhir);
    }
    if (sejak !== null && now - sejak >= BATAS_KAMERA_MATI) hentikan("kamera");
  }
  setInterval(cekKamera, 500);

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && berjalan) {
      frameTerakhir = performance.now();
      mintaWakeLock();
    }
  });

  // Komponen dilepas (logout, pindah halaman, tab ditutup): simpan histori tamu terakhir.
  window.addEventListener("pagehide", () => {
    if (berjalan && args.tamu && sesi) simpanTamu();
    hentikanKamera();
  });

  // ─── Per frame ─────────────────────────────────────────────────────────────

  let waktuVideoTerakhir = -1;
  function jadwalkanFrame() {
    if (!berjalan) return;
    if (video.requestVideoFrameCallback) {
      video.requestVideoFrameCallback(() => {
        olahFrame();
        jadwalkanFrame();
      });
    } else {
      requestAnimationFrame(() => {
        if (video.currentTime !== waktuVideoTerakhir) {
          waktuVideoTerakhir = video.currentTime;
          olahFrame();
        }
        jadwalkanFrame();
      });
    }
  }

  const waktuFrame = []; // performance.now() frame-frame terakhir, untuk FPS
  function fpsSekarang(now) {
    waktuFrame.push(now);
    while (waktuFrame.length && now - waktuFrame[0] > 1000) waktuFrame.shift();
    return waktuFrame.length;
  }

  function olahFrame() {
    if (!berjalan || !landmarker) return;
    const w = video.videoWidth, h = video.videoHeight;
    if (!w || !h) return;
    frameTerakhir = performance.now();
    if (kanvas.width !== w || kanvas.height !== h) {
      kanvas.width = kanvasKerja.width = w;
      kanvas.height = kanvasKerja.height = h;
    }
    if (layar.classList.contains("kosong")) layar.classList.remove("kosong");
    layarPesan.hidden = true;

    try {
      // Pengukuran: praproses (CLAHE) | deteksi | indikator + logika. Menggambar tidak diukur.
      const t0 = performance.now();
      let masukan = video, img = null;
      if (ukur.clahe) {
        ctxKerja.drawImage(video, 0, 0, w, h);
        img = ctxKerja.getImageData(0, 0, w, h);
        clahe.terapkanRGBA(img.data, w, h);
        masukan = img;
      }
      const t1 = performance.now();
      tsTerakhir = Math.max(t1, tsTerakhir + 1);
      const hasil = landmarker.detectForVideo(masukan, tsTerakhir);
      const t2 = performance.now();
      const lm = hasil.faceLandmarks && hasil.faceLandmarks[0];
      const ind = lm ? L.hitungIndikator(lm, w, h) : null;
      const keluaran = detektor.prosesFrame(ind, t2 / 1000, Date.now(), args.ambang, w, h);
      const t3 = performance.now();

      // Frame yang ditampilkan adalah frame hasil CLAHE.
      if (img) ctx.putImageData(img, 0, 0);
      else ctx.drawImage(video, 0, 0, w, h);
      A.gambar(ctx, keluaran.gambar, w);

      aturAlarm(keluaran.alarm);
      for (const k of keluaran.kejadian) catatKejadian(k);
      if (args.email_aktif) {
        for (const kind of keluaran.email) kirimPesan({ jenis: "email", kind, lokasi });
      }

      ukur.n += 1;
      ukur.baris.push([
        ukur.n, (t0 - ukur.mulai) / 1000, ukur.n <= PEMANASAN ? 1 : 0, ind ? 1 : 0, w, h,
        t1 - t0, t2 - t1, t3 - t2, t3 - t1, t3 - t0, fpsSekarang(t3),
        ind ? ind.ear : null, ind ? ind.mar : null, ind ? ind.angle : null,
      ]);
    } catch (e) {
      if (!galatFrame) {
        galatFrame = e;
        console.error("Error saat memproses frame:", e);
        aturStatus("Ada gangguan saat memproses frame kamera: " + e.message, "galat");
      }
    }
  }

  // ─── Alarm ─────────────────────────────────────────────────────────────────
  // Seperti AudioFrameHandler: berulang selama alarm menyala; saat padam, putaran yang
  // sedang berjalan diselesaikan dulu baru berhenti.

  // Getar (Android) ikut menandai alarm selama alarm menyala.
  let timerGetar = null;
  function aturAlarm(nyala) {
    if (nyala) {
      if (!timerGetar && navigator.vibrate) {
        const getar = () => navigator.vibrate(600);
        getar();
        timerGetar = setInterval(getar, 900);
      }
      alarmAudio.loop = true;
      if (alarmAudio.paused) {
        alarmAudio.currentTime = 0;
        alarmAudio.play().catch((e) => console.warn("Alarm tidak bisa diputar:", e));
      }
    } else {
      if (timerGetar) {
        clearInterval(timerGetar);
        timerGetar = null;
        navigator.vibrate(0);
      }
      if (!alarmAudio.paused) alarmAudio.loop = false;
    }
  }

  // Browser hanya mengizinkan audio setelah interaksi pengguna; START dipakai untuk membukanya.
  function bukaKunciAudio() {
    if (!alarmAudio.paused) return;
    alarmAudio.muted = true;
    const p = alarmAudio.play();
    if (!p) { alarmAudio.muted = false; return; }
    p.then(() => {
      if (alarmAudio.muted) {
        alarmAudio.pause();
        alarmAudio.currentTime = 0;
      }
    }).catch(() => {}).finally(() => { alarmAudio.muted = false; });
  }

  // ─── Kejadian & histori tamu ───────────────────────────────────────────────

  function catatKejadian(k) {
    sesi.jumlah += 1;
    if (args.tamu) {
      sesi.kejadianTamu.push({ event_type: k.event_type, event_time: L.formatWib(k.mulai_ms), duration: L.pyRound(k.durasi, 2) });
      simpanTamu();
    }
    kirimPesan({ jenis: "kejadian", event_type: k.event_type, mulai_ms: k.mulai_ms, durasi: k.durasi });
    perbaruiStatus();
  }

  // Format yang dibaca halaman Histori untuk tamu (maksimal 10 sesi terbaru).
  function simpanTamu() {
    const akhir = Date.now();
    const total = { eye_close: 0, yawn: 0, head_tilt: 0 };
    for (const e of sesi.kejadianTamu) if (e.event_type in total) total[e.event_type] += 1;
    const data = {
      id: sesi.uid,
      start_time: L.formatWib(sesi.mulaiMs),
      end_time: L.formatWib(akhir),
      duration: Math.floor(akhir / 1000) - Math.floor(sesi.mulaiMs / 1000),
      total_eye_close: total.eye_close,
      total_yawn: total.yawn,
      total_head_tilt: total.head_tilt,
      events: sesi.kejadianTamu,
    };
    try {
      let arr = JSON.parse(localStorage.getItem(args.kunci_tamu) || "[]");
      arr = arr.filter((x) => x.id !== data.id);
      arr.unshift(data);
      if (arr.length > 10) arr = arr.slice(0, 10);
      localStorage.setItem(args.kunci_tamu, JSON.stringify(arr));
    } catch (e) {
      console.error("Gagal simpan histori tamu:", e);
    }
  }

  // ─── Pesan ke Python ───────────────────────────────────────────────────────
  // Semua pesan yang belum dikonfirmasi dikirim bersama; Python membalas nomor terakhir yang
  // sudah diproses lewat args.ack. Tanpa konfirmasi, antrean dikirim ulang dengan jeda bertambah.

  const idKomponen = Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
  let seq = 0, kirimKe = 0, antrean = [], timerUlang = null, jedaUlang = JEDA_KIRIM_ULANG;
  let ackIdTerakhir; // undefined: render pertama selalu dianggap sesi Python baru

  // Antrean juga disimpan di localStorage, jadi pesan yang belum dikonfirmasi tidak hilang saat
  // halaman dimuat ulang, ditutup, atau ditinggal ke halaman Histori. Pesan tertinggal dari komponen
  // sebelumnya diberi nomor urut baru dan dikirim lagi; Python aman memproses pesan yang sama ulang.
  try {
    antrean = JSON.parse(localStorage.getItem(KUNCI_ANTREAN) || "[]").map((p) => Object.assign(p, { seq: ++seq }));
  } catch (e) { antrean = []; }

  function simpanAntrean() {
    try {
      if (antrean.length) localStorage.setItem(KUNCI_ANTREAN, JSON.stringify(antrean));
      else localStorage.removeItem(KUNCI_ANTREAN);
    } catch (e) { /* localStorage penuh atau diblokir: antrean tetap di memori */ }
  }

  // Pesan hanya dikirim saat akun yang membuatnya sedang masuk (tamu = null).
  function milikAkunIni(p) {
    return (p.akun || null) === (args.akun || null);
  }

  function kirimPesan(p, s = sesi) {
    p.seq = ++seq;
    p.mid = idKomponen + "-" + p.seq;  // id tetap walau dikirim ulang oleh komponen lain
    p.sesi = s.uid;
    p.sesi_mulai_ms = s.mulaiMs;      // Python mencari baris sesi dari akun + waktu START ini
    p.akun = args.akun || null;
    p.waktu_ms = Date.now();
    antrean.push(p);
    simpanAntrean();
    jedaUlang = JEDA_KIRIM_ULANG;
    kirimAntrean();
  }

  function kirimAntrean() {
    clearTimeout(timerUlang);
    const pesan = antrean.filter(milikAkunIni);
    if (!pesan.length) return;
    kirimKe += 1;
    kirimStreamlit("streamlit:setComponentValue", {
      value: { id: idKomponen, kirim: kirimKe, pesan },
      dataType: "json",
    });
    timerUlang = setTimeout(() => {
      jedaUlang = Math.min(jedaUlang * 2, 60000);
      kirimAntrean();
    }, jedaUlang);
  }

  function terimaAck() {
    const a = args.ack;
    if (!a) return;
    const idBaru = a.id !== ackIdTerakhir;
    ackIdTerakhir = a.id;
    if (a.id !== idKomponen) {
      // Komponen baru dibuka atau sesi Python baru (koneksi tersambung lagi): kirim antrean sekarang.
      if (idBaru) {
        jedaUlang = JEDA_KIRIM_ULANG;
        kirimAntrean();
      }
      return;
    }
    const sebelum = antrean.length;
    antrean = antrean.filter((p) => !milikAkunIni(p) || p.seq > a.seq);
    if (antrean.length !== sebelum) simpanAntrean();
    if (!antrean.some(milikAkunIni)) clearTimeout(timerUlang);
    perbaruiStatus();
  }

  // Ringkasan email yang tertahan jeda 2 menit dikirim Python saat jeda habis; komponen hanya
  // mengingatkan Python tepat waktu karena tanpa pesan Python tidak berjalan.
  let timerFlush = null;
  function aturFlush() {
    clearTimeout(timerFlush);
    const ms = args.flush_dalam_ms;
    if (typeof ms !== "number" || !berjalan) return;
    timerFlush = setTimeout(() => {
      if (berjalan) kirimPesan({ jenis: "flush", lokasi });
    }, ms + 500);
  }

  // ─── Lokasi untuk email darurat ────────────────────────────────────────────

  let lokasi = null, gpsMulai = false;
  function mulaiGps() {
    if (gpsMulai || !args.email_aktif || !navigator.geolocation) return;
    gpsMulai = true;
    navigator.geolocation.watchPosition(
      (pos) => { lokasi = "https://www.google.com/maps?q=" + pos.coords.latitude + "," + pos.coords.longitude; },
      (err) => console.warn("Gagal ambil lokasi:", err),
      { enableHighAccuracy: true, maximumAge: 10000 }
    );
  }

  // ─── Layar tetap menyala ───────────────────────────────────────────────────
  // Izin iframe Streamlit 1.17 memakai nama lama "wake-lock", jadi permintaan dari dalam iframe
  // bisa ditolak; dicoba juga dari halaman induk (same-origin).

  let wakeLock = null, statusWakeLock = "belum diminta";
  async function mintaWakeLock() {
    if (wakeLock && !wakeLock.released) return;
    const jendela = [window];
    try { if (window.parent !== window && window.parent.navigator) jendela.push(window.parent); } catch (e) { /* lintas origin */ }
    try { if (window.top !== window.parent && window.top.navigator) jendela.push(window.top); } catch (e) { /* lintas origin */ }
    let galat = null;
    for (const w of jendela) {
      try {
        if (!w.navigator.wakeLock) continue;
        wakeLock = await w.navigator.wakeLock.request("screen");
        statusWakeLock = "aktif" + (w === window ? "" : " (lewat halaman induk)");
        wakeLock.addEventListener("release", () => {
          statusWakeLock = berjalan ? "dilepas sistem, diminta lagi saat halaman terlihat" : "nonaktif";
          perbaruiPanel();
        });
        perbaruiPanel();
        return;
      } catch (e) {
        galat = e;
      }
    }
    statusWakeLock = galat ? "ditolak (" + galat.name + ")" : "tidak didukung browser ini";
    perbaruiPanel();
  }

  function lepasWakeLock() {
    if (wakeLock && !wakeLock.released) wakeLock.release().catch(() => {});
    wakeLock = null;
  }

  // ─── Pengukuran waktu proses ───────────────────────────────────────────────

  function ringkasanWaktu() {
    if (!ukur) return null;
    const terukur = ukur.baris.filter((b) => !b[2]);
    const durasi = ukur.baris.length > 1 ? ukur.baris[ukur.baris.length - 1][1] - ukur.baris[0][1] : 0;
    return {
      delegate: ukur.delegate,
      clahe: ukur.clahe,
      pemanasan: Math.min(ukur.n, PEMANASAN),
      proses: L.ringkasStatistik(terukur.map((b) => b[9])),
      deteksi: L.ringkasStatistik(terukur.map((b) => b[7])),
      praproses: ukur.clahe ? L.ringkasStatistik(terukur.map((b) => b[6])) : null,
      total: ukur.clahe ? L.ringkasStatistik(terukur.map((b) => b[10])) : null,
      fps: durasi > 0 ? Math.round(((ukur.baris.length - 1) / durasi) * 10) / 10 : null,
    };
  }

  function unduhCsv() {
    if (!ukur || !ukur.baris.length) return;
    const kepala = ["frame", "waktu_s", "pemanasan", "wajah", "lebar", "tinggi", "praproses_ms", "deteksi_ms",
      "indikator_ms", "proses_ms", "total_ms", "fps", "ear", "mar", "sudut", "delegate", "clahe"];
    const desimal = [0, 3, 0, 0, 0, 0, 3, 3, 3, 3, 3, 0, 6, 6, 3];
    const angka = (v, n) => (v === null ? "" : v.toFixed(n).replace(".", ","));
    const baris = ukur.baris.map((b) =>
      b.map((v, i) => angka(v, desimal[i])).concat([ukur.delegate, ukur.clahe ? 1 : 0]).join(";"));
    const blob = new Blob(["﻿" + kepala.join(";") + "\n" + baris.join("\n") + "\n"], { type: "text/csv;charset=utf-8" });
    const d = new Date(Date.now() + 7 * 3600 * 1000).toISOString().slice(0, 19).replace(/[-:]/g, "").replace("T", "_");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `waktu_proses_browser_${d}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 10000);
  }

  // ─── Tampilan ──────────────────────────────────────────────────────────────

  let statusKhusus = null; // pesan proses/galat; kalau kosong, status sesi yang ditampilkan
  function aturStatus(teks, jenis) {
    statusKhusus = teks ? { teks, jenis: jenis || "" } : null;
    perbaruiStatus();
  }

  // Tanpa sinyal: browser melaporkan offline, atau ada pesan yang 10 detik belum dikonfirmasi Python.
  function tanpaSinyal() {
    const pesan = antrean.filter(milikAkunIni);
    return !navigator.onLine || (pesan.length > 0 && Date.now() - pesan[0].waktu_ms > 10000);
  }

  function perbaruiStatus() {
    statusEl.className = "status";
    if (statusKhusus) {
      statusEl.textContent = statusKhusus.teks;
      if (statusKhusus.jenis) statusEl.classList.add(statusKhusus.jenis);
    } else if (berjalan) {
      statusEl.textContent = `Sesi aktif — ${sesi.jumlah} kejadian tercatat` +
        (tanpaSinyal() ? " · tanpa sinyal, deteksi tetap berjalan" : "");
      statusEl.classList.add("aktif");
    } else if (sesiTerakhir) {
      const tersimpan = !antrean.some((p) => p.sesi === sesiTerakhir.uid);
      statusEl.textContent = tersimpan
        ? `Sesi selesai — ${sesiTerakhir.jumlah} kejadian kantuk tercatat.`
        : "Menyimpan sesi…";
    } else {
      statusEl.textContent = "Tekan START untuk memulai sesi monitoring.";
    }
  }

  function perbaruiTombol() {
    tombolBerhenti.hidden = !berjalan;
    tombolMulai.hidden = berjalan;
    tombolMulai.disabled = sedangMulai || (!landmarker && !!pemuatan);
    tombolMulai.textContent = sedangMulai ? "Membuka…" : (!landmarker && pemuatan ? "Memuat…" : "START");
    el("opsi-clahe").disabled = berjalan;
    el("opsi-delegate").disabled = berjalan || !!pemuatan;
    el("tombol-csv").disabled = !ukur || !ukur.baris.length;
  }

  const fmt = (v) => (v === null || v === undefined ? "–" : v.toFixed(1).replace(".", ","));
  const mb = (b) => (b / 1048576).toFixed(2).replace(".", ",") + " MB";

  function barisTabel(nama, s) {
    if (!s) return "";
    return `<tr><td>${nama}</td><td class="angka">${s.n}</td><td class="angka">${fmt(s.rata_rata)} ms</td>` +
      `<td class="angka">${fmt(s.median)} ms</td><td class="angka">${fmt(s.p95)} ms</td>` +
      `<td class="angka">${fmt(s.min)} ms</td><td class="angka">${fmt(s.maks)} ms</td></tr>`;
  }

  function perbaruiPanel() {
    perbaruiTombol();
    const r = ukur ? (berjalan ? ringkasanWaktu() : ukur.ringkasan || ringkasanWaktu()) : null;
    el("info-pemanasan").textContent = `${PEMANASAN} frame pertama tiap sesi diabaikan sebagai pemanasan.`;
    el("tabel-waktu").innerHTML = r && r.proses
      ? barisTabel("Deteksi + indikator", r.proses) + barisTabel("Deteksi saja", r.deteksi) +
        barisTabel("CLAHE", r.praproses) + barisTabel("Total termasuk CLAHE", r.total)
      : `<tr><td colspan="7" class="kecil">Belum ada data. ${PEMANASAN} frame pertama setelah START diabaikan.</td></tr>`;

    const terakhir = ukur && ukur.baris.length ? ukur.baris[ukur.baris.length - 1] : null;
    const berkas = Object.entries(M.sumber);
    const dariJaringan = berkas.filter(([, s]) => s.asal === "jaringan");
    const asalModel = !berkas.length ? (pemuatan ? "sedang dimuat…" : "belum dimuat")
      : dariJaringan.length
        ? `diunduh dari CDN di sesi ini (${dariJaringan.length} berkas, ${mb(dariJaringan.reduce((t, [, s]) => t + s.byte, 0))} setelah dekompresi)`
        : "dari cache browser (tidak diunduh ulang)";
    const info = [
      ["FPS", berjalan && terakhir ? `${terakhir[11]} (rata-rata sesi ${r && r.fps !== null ? fmt(r.fps) : "–"})` : (r && r.fps !== null ? `rata-rata sesi ${fmt(r.fps)}` : "–")],
      ["Resolusi frame", terakhir ? `${terakhir[4]} × ${terakhir[5]} px` : "–"],
      ["Delegate", delegateAktif || pengaturan.delegate],
      ["CLAHE", (ukur ? ukur.clahe : pengaturan.clahe) ? "aktif" : "nonaktif"],
      ["Model & wasm", `tasks-vision ${M.VERSI}, ${asalModel}`],
      ["Cache Storage", M.status.cacheStorage],
      ["Layar tetap menyala", statusWakeLock],
      ["Mikrofon (jalur suara panggilan)", statusMik],
      ["Email darurat", args.email_aktif ? (lokasi ? "aktif, lokasi GPS tersedia" : "aktif, lokasi belum tersedia") : "nonaktif"],
      ["Pesan belum dikonfirmasi", String(antrean.length)],
    ];
    el("info").innerHTML = info.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
  }
  setInterval(() => { if (berjalan) { perbaruiPanel(); perbaruiStatus(); } }, 500);

  tombolMulai.addEventListener("click", mulai);
  tombolBerhenti.addEventListener("click", () => hentikan("stop"));
  el("tombol-csv").addEventListener("click", unduhCsv);
  el("panel").addEventListener("toggle", aturTinggi);

  perbaruiStatus();
  perbaruiPanel();
  kirimStreamlit("streamlit:componentReady", { apiVersion: 1 });
  muatModel();
})();
