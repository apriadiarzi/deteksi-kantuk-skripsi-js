/*
 * Logika deteksi kantuk: EAR, MAR, sudut kepala, penghitung waktu, alarm, dan pencatatan kejadian.
 *
 * Diterjemahkan dari versi Python (pengujian/deteksi_kantuk.py: fungsi indikator +
 * VideoFrameHandler.process), sehingga rumus, indeks landmark, urutan cek, penghitung waktu,
 * durasi minimum, dan teks di layar sama persis. Kesamaannya diuji otomatis oleh
 * pengujian/uji_kesamaan.py.
 *
 * Berkas ini dipakai di browser (window.Logika) dan di Node (require) untuk pengujian.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.Logika = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const EYE_IDXS = {
    left: [362, 385, 387, 263, 373, 380],
    right: [33, 160, 158, 133, 153, 144],
  };
  const MOUTH_IDXS = [61, 39, 0, 269, 291, 405, 17, 181]; // P1 … P8
  const EAR_LEFT_TRAGUS = 234;
  const EAR_RIGHT_TRAGUS = 454;

  // Durasi minimal kejadian (detik) agar dicatat, untuk menyaring noise.
  const MIN_DURATION_EYE = 1.0;
  const MIN_DURATION_YAWN = 1.0;
  const MIN_DURATION_TILT = 1.5;

  // Nama warna; anotasi.js menerjemahkannya ke warna canvas (versi Python memakai BGR OpenCV).
  const RED = "RED", GREEN = "GREEN", ORANGE = "ORANGE", YELLOW = "YELLOW";

  // ─── Pembulatan & format ala Python ──────────────────────────────────────────
  // Teks di layar versi Python memakai round() dan format ".1f" Python, yang membulatkan
  // nilai desimal persis dengan aturan half-even. toFixed() JavaScript membulatkan ke atas
  // saat seri, jadi dibuat versi yang sama dengan Python.

  // Digit desimal persis dari |x| (toFixed menghasilkan ekspansi desimal yang tepat).
  function bulatkanDigit(x, n) {
    const s = Math.abs(x).toFixed(100);
    const titik = s.indexOf(".");
    let digit = s.slice(0, titik) + s.slice(titik + 1, titik + 1 + n);
    const sisa = s.slice(titik + 1 + n);
    let naik = false;
    if (sisa[0] > "5") naik = true;
    else if (sisa[0] === "5") {
      naik = /[1-9]/.test(sisa.slice(1)) || Number(digit[digit.length - 1]) % 2 === 1;
    }
    if (naik) {
      const arr = digit.split("");
      let i = arr.length - 1;
      while (i >= 0 && arr[i] === "9") { arr[i] = "0"; i--; }
      if (i < 0) arr.unshift("1"); else arr[i] = String(Number(arr[i]) + 1);
      digit = arr.join("");
    }
    const bulat = digit.slice(0, digit.length - n) || "0";
    const pecahan = n > 0 ? digit.slice(digit.length - n) : "";
    return { negatif: x < 0 || Object.is(x, -0), bulat: bulat.replace(/^0+(?=\d)/, ""), pecahan };
  }

  /** Sama dengan round(x, n) Python. */
  function pyRound(x, n) {
    if (!Number.isFinite(x) || Math.abs(x) >= 1e21) return x;
    const d = bulatkanDigit(x, n);
    const v = Number(d.bulat + (n > 0 ? "." + d.pecahan : ""));
    return d.negatif ? -v : v;
  }

  /** Sama dengan f"{x:.nf}" Python. */
  function pyFixed(x, n) {
    if (!Number.isFinite(x)) return String(x);
    const d = bulatkanDigit(x, n);
    return (d.negatif ? "-" : "") + d.bulat + (n > 0 ? "." + d.pecahan : "");
  }

  /** Sama dengan str(float) Python untuk nilai yang sudah dibulatkan (mis. 0.3, 1.0, -0.0). */
  function pyStr(x) {
    if (Object.is(x, -0)) return "-0.0";
    if (Number.isInteger(x)) return x.toFixed(1);
    return String(x);
  }

  // ─── Indikator ───────────────────────────────────────────────────────────────

  function isClose(a, b) {
    // math.isclose(a, b) dengan toleransi bawaan (rel_tol=1e-9, abs_tol=0)
    return Math.abs(a - b) <= 1e-9 * Math.max(Math.abs(a), Math.abs(b));
  }

  /** _normalized_to_pixel_coordinates dari MediaPipe Python: null jika di luar [0, 1]. */
  function denormalize(x, y, w, h) {
    const valid = (v) => (v > 0 || isClose(0, v)) && (v < 1 || isClose(1, v));
    if (!(valid(x) && valid(y))) return null;
    return [Math.min(Math.floor(x * w), w - 1), Math.min(Math.floor(y * h), h - 1)];
  }

  function distance(p1, p2) {
    const dx = p1[0] - p2[0], dy = p1[1] - p2[1];
    return (dx * dx + dy * dy) ** 0.5;
  }

  // Versi lama membungkus perhitungan dengan try/except: satu titik di luar frame
  // (koordinat None) atau pembagi nol membuat nilai = 0.0 dan koordinat = None.
  function ambilKoordinat(landmarks, idxs, w, h) {
    const coords = [];
    for (const i of idxs) {
      const lm = landmarks[i];
      if (!lm) return null;
      const c = denormalize(lm.x, lm.y, w, h);
      if (c === null) return null;
      coords.push(c);
    }
    return coords;
  }

  function getEar(landmarks, idxs, w, h) {
    const c = ambilKoordinat(landmarks, idxs, w, h);
    if (c === null) return [0.0, null];
    const P2_P6 = distance(c[1], c[5]);
    const P3_P5 = distance(c[2], c[4]);
    const P1_P4 = distance(c[0], c[3]);
    if (P1_P4 === 0) return [0.0, null];
    return [(P2_P6 + P3_P5) / (2.0 * P1_P4), c];
  }

  function getMar(landmarks, idxs, w, h) {
    const c = ambilKoordinat(landmarks, idxs, w, h);
    if (c === null) return [0.0, null];
    const P2_P8 = distance(c[1], c[7]);
    const P3_P7 = distance(c[2], c[6]);
    const P4_P6 = distance(c[3], c[5]);
    const P1_P5 = distance(c[0], c[4]);
    if (P1_P5 === 0) return [0.0, null];
    return [(P2_P8 + P3_P7 + P4_P6) / (3.0 * P1_P5), c];
  }

  /** Sudut garis 234–454 terhadap horizontal, dalam derajat, tanpa pembulatan piksel. */
  function getHeadTiltAngle(landmarks, w, h) {
    const left = landmarks[EAR_LEFT_TRAGUS], right = landmarks[EAR_RIGHT_TRAGUS];
    if (!left || !right) return [0.0, null, null];
    const lx = left.x * w, ly = left.y * h;
    const rx = right.x * w, ry = right.y * h;
    const angle = Math.atan2(ry - ly, rx - lx) * (180.0 / Math.PI);
    return [angle, [Math.trunc(lx), Math.trunc(ly)], [Math.trunc(rx), Math.trunc(ry)]];
  }

  /** Semua indikator dari satu set landmark wajah (koordinat ternormalisasi). */
  function hitungIndikator(landmarks, w, h) {
    const [earKiri, kiri] = getEar(landmarks, EYE_IDXS.left, w, h);
    const [earKanan, kanan] = getEar(landmarks, EYE_IDXS.right, w, h);
    const [mar, mulut] = getMar(landmarks, MOUTH_IDXS, w, h);
    const [angle, leftPt, rightPt] = getHeadTiltAngle(landmarks, w, h);
    return {
      ear: (earKiri + earKanan) / 2.0, earKiri, earKanan,
      eyeCoords: [kiri, kanan],
      mar, mouthCoords: mulut,
      angle, leftPt, rightPt,
    };
  }

  // ─── Penghitung waktu & peringatan ───────────────────────────────────────────

  function stateAwal(t) {
    return {
      // EAR
      start_time: t, DROWSY_TIME: 0.0, COLOR: GREEN, play_alarm: false, message_sent: false,
      // MAR
      YAWN_start_time: t, YAWN_TIME: 0.0, is_yawning: false, yawn_alarm: false, yawn_message_sent: false,
      // Head tilt
      TILT_start_time: t, TILT_TIME: 0.0, is_tilting: false, tilt_alarm: false, tilt_message_sent: false,
    };
  }

  /**
   * Padanan VideoFrameHandler untuk satu sesi kamera. prosesFrame() dipanggil sekali per
   * frame dengan waktu monoton (detik, seperti time.perf_counter) dan waktu dinding (ms epoch,
   * dipakai sebagai waktu mulai kejadian seperti now_wib()).
   */
  function DetektorKantuk() {
    this.state = stateAwal(0);
    this.eyeStart = null;
    this.yawnStart = null;
    this.tiltStart = null;
    this.resetTertunda = true;
  }

  /** Penghitung waktu di-reset pada frame pertama sesi (sama dengan mulai_sesi_baru()). */
  DetektorKantuk.prototype.mulaiSesi = function () {
    this.resetTertunda = true;
  };

  DetektorKantuk.prototype.prosesFrame = function (ind, t, epochMs, ambang, frameW, frameH) {
    if (this.resetTertunda) {
      this.resetTertunda = false;
      this.state = stateAwal(t);
      this.eyeStart = this.yawnStart = this.tiltStart = null;
    }
    const st = this.state;
    const gambar = [], kejadian = [], email = [];
    const teks = (s, pos, warna) => gambar.push({ op: "teks", teks: s, x: pos[0], y: pos[1], warna });

    // Jarak antar baris teks mengikuti lebar frame.
    const ui = Math.max(0.45, Math.min(1.25, frameW / 640));
    const pad = Math.trunc(10 * ui), line = Math.trunc(30 * ui);
    const EAR_txt_pos = [pad, line];
    const MAR_txt_pos = [pad, line * 2];
    const TILT_txt_pos = [pad, line * 3];
    const DROWSY_TIME_txt_pos = [pad, Math.trunc(frameH - line * 3)];
    const YAWN_TIME_txt_pos = [pad, Math.trunc(frameH - line * 2)];
    const TILT_TIME_txt_pos = [pad, Math.trunc(frameH - line)];
    const WARN_DROWSY_pos = [pad, Math.trunc(frameH / 2 - line * 0.7)];
    const WARN_YAWN_pos = [pad, Math.trunc(frameH / 2 + line * 0.7)];
    const WARN_TILT_pos = [pad, Math.trunc(frameH / 2 + line * 2)];
    const ALM_txt_pos = [pad, Math.trunc(frameH / 2 - line * 2)];

    if (ind) {
      // ── EAR ── (titik mata memakai warna dari frame sebelumnya, seperti versi Python)
      const EAR = ind.ear;
      gambar.push({ op: "mata", kiri: ind.eyeCoords[0], kanan: ind.eyeCoords[1], warna: st.COLOR });

      // ── MAR ──
      const MAR = ind.mar;
      gambar.push({ op: "mulut", koordinat: ind.mouthCoords, warna: ORANGE });

      // ── Head Tilt ──
      const tiltAngle = ind.angle;
      const absAngle = Math.abs(tiltAngle);
      const tiltColor = absAngle > ambang.TILT_THRESH ? YELLOW : GREEN;
      gambar.push({ op: "kepala", kiri: ind.leftPt, kanan: ind.rightPt, sudut: tiltAngle, warna: tiltColor });

      // ── Logika EAR ──
      if (EAR < ambang.EAR_THRESH) {
        if (this.eyeStart === null) this.eyeStart = epochMs;
        st.DROWSY_TIME += t - st.start_time;
        st.start_time = t;
        st.COLOR = RED;

        if (st.DROWSY_TIME >= ambang.WAIT_TIME) {
          st.play_alarm = true;
          teks("WAKE UP! WAKE UP", ALM_txt_pos, RED);
          teks("MATA TERTUTUP!", WARN_DROWSY_pos, RED);

          if (!st.message_sent && st.DROWSY_TIME >= 5) {
            email.push("eye_close");
            st.message_sent = true;
          }
        }
      } else {
        if (this.eyeStart !== null) {
          const durasi = st.DROWSY_TIME;
          if (durasi >= MIN_DURATION_EYE) {
            kejadian.push({ event_type: "eye_close", mulai_ms: this.eyeStart, durasi });
          }
          this.eyeStart = null;
        }
        st.start_time = t;
        st.DROWSY_TIME = 0.0;
        st.COLOR = GREEN;
        st.play_alarm = false;
        st.message_sent = false;
      }

      // ── Logika MAR ──
      if (MAR > ambang.MAR_THRESH) {
        if (this.yawnStart === null) this.yawnStart = epochMs;
        st.YAWN_TIME += t - st.YAWN_start_time;
        st.YAWN_start_time = t;
        st.is_yawning = true;
        // Alarm menguap menyala setelah mulut terbuka selama WAIT_TIME.
        if (st.YAWN_TIME >= ambang.WAIT_TIME) {
          st.yawn_alarm = true;
          teks("MENGUAP TERDETEKSI!", WARN_YAWN_pos, ORANGE);
        }

        if (!st.yawn_message_sent && st.YAWN_TIME >= 3) {
          email.push("yawn");
          st.yawn_message_sent = true;
        }
      } else {
        if (this.yawnStart !== null) {
          const durasi = st.YAWN_TIME;
          if (durasi >= MIN_DURATION_YAWN) {
            kejadian.push({ event_type: "yawn", mulai_ms: this.yawnStart, durasi });
          }
          this.yawnStart = null;
        }
        st.YAWN_start_time = t;
        st.YAWN_TIME = 0.0;
        st.is_yawning = false;
        st.yawn_alarm = false;
        st.yawn_message_sent = false;
      }

      // ── Logika Head Tilt ──
      if (absAngle > ambang.TILT_THRESH) {
        if (this.tiltStart === null) this.tiltStart = epochMs;
        st.TILT_TIME += t - st.TILT_start_time;
        st.TILT_start_time = t;
        st.is_tilting = true;
        // Alarm kepala miring menyala setelah kepala miring selama WAIT_TIME.
        if (st.TILT_TIME >= ambang.WAIT_TIME) {
          st.tilt_alarm = true;
          teks("KEPALA MIRING!", WARN_TILT_pos, YELLOW);
        }

        if (!st.tilt_message_sent && st.TILT_TIME >= 5) {
          email.push("head_tilt");
          st.tilt_message_sent = true;
        }
      } else {
        if (this.tiltStart !== null) {
          const durasi = st.TILT_TIME;
          if (durasi >= MIN_DURATION_TILT) {
            kejadian.push({ event_type: "head_tilt", mulai_ms: this.tiltStart, durasi });
          }
          this.tiltStart = null;
        }
        st.TILT_start_time = t;
        st.TILT_TIME = 0.0;
        st.is_tilting = false;
        st.tilt_alarm = false;
        st.tilt_message_sent = false;
      }

      // ── Teks overlay ──
      teks(`EAR: ${pyStr(pyRound(EAR, 2))}`, EAR_txt_pos, st.COLOR);
      teks(`MAR: ${pyStr(pyRound(MAR, 2))}`, MAR_txt_pos, st.is_yawning ? ORANGE : GREEN);
      teks(`TILT: ${pyFixed(tiltAngle, 1)}deg`, TILT_txt_pos, tiltColor);
      teks(`DROWSY: ${pyStr(pyRound(st.DROWSY_TIME, 3))} Secs`, DROWSY_TIME_txt_pos, st.COLOR);
      teks(`YAWN  : ${pyStr(pyRound(st.YAWN_TIME, 3))} Secs`, YAWN_TIME_txt_pos, st.is_yawning ? ORANGE : GREEN);
      teks(`TILT  : ${pyStr(pyRound(st.TILT_TIME, 3))} Secs`, TILT_TIME_txt_pos, tiltColor);
    } else {
      // Wajah hilang: penghitung waktu dan alarm kembali ke nol. Penanda awal kejadian dan
      // status email TIDAK di-reset (sama seperti versi Python).
      st.start_time = t; st.DROWSY_TIME = 0.0; st.COLOR = GREEN; st.play_alarm = false;
      st.YAWN_start_time = t; st.YAWN_TIME = 0.0; st.is_yawning = false; st.yawn_alarm = false;
      st.TILT_start_time = t; st.TILT_TIME = 0.0; st.is_tilting = false; st.tilt_alarm = false;
    }

    const alarm = st.play_alarm || st.yawn_alarm || st.tilt_alarm;
    return { gambar, kejadian, email, alarm };
  };

  // ─── Statistik waktu proses (persentil nearest-rank) ────────────────────────

  function ringkasStatistik(nilai) {
    if (!nilai.length) return null;
    const data = Array.from(nilai).sort((a, b) => a - b);
    const n = data.length;
    // metode nearest-rank: nilai yang benar-benar terukur, tanpa interpolasi
    const persentil = (p) => data[Math.max(0, Math.ceil((p / 100) * n) - 1)];
    let total = 0;
    for (const v of data) total += v;
    return { n, rata_rata: total / n, median: persentil(50), p95: persentil(95), min: data[0], maks: data[n - 1] };
  }

  // ─── Waktu WIB ───────────────────────────────────────────────────────────────

  /** 'YYYY-MM-DD HH:MM:SS' dalam WIB (UTC+7), seperti now_wib().strftime(...). */
  function formatWib(epochMs) {
    const d = new Date(epochMs + 7 * 3600 * 1000);
    const p = (v) => String(v).padStart(2, "0");
    return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ` +
      `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}`;
  }

  return {
    EYE_IDXS, MOUTH_IDXS, EAR_LEFT_TRAGUS, EAR_RIGHT_TRAGUS,
    MIN_DURATION_EYE, MIN_DURATION_YAWN, MIN_DURATION_TILT,
    pyRound, pyFixed, pyStr,
    denormalize, getEar, getMar, getHeadTiltAngle, hitungIndikator,
    DetektorKantuk, ringkasStatistik, formatWib,
  };
});
