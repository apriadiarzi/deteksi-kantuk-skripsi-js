/*
 * CLAHE pada kanal Y (YUV) tanpa OpenCV.js — padanan enhance_low_light() di deteksi_kantuk.py:
 *   yuv = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV)
 *   yuv[:, :, 0] = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(yuv[:, :, 0])
 *   frame = cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR)
 *
 * Mengikuti implementasi OpenCV (color_yuv.simd.hpp dan clahe.cpp): koefisien YUV fixed-point
 * 14 bit, skala clipLimit, redistribusi kelebihan histogram, padding BORDER_REFLECT_101, dan
 * interpolasi bilinear dengan aritmetika float32. Hasilnya dibandingkan piksel per piksel
 * dengan cv2 oleh uji_mode_browser/uji_kesamaan.py.
 *
 * Dipakai di browser (window.Clahe) dan di Node (require) untuk pengujian.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.Clahe = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const SHIFT = 14;
  const HALF = 1 << (SHIFT - 1);
  const DELTA = 128 << SHIFT;
  // BGR → YUV
  const R2Y = 4899, G2Y = 9617, B2Y = 1868, R2VI = 14369, B2UI = 8061;
  // YUV → BGR
  const V2RI = 18678, V2GI = -9519, U2GI = -6472, U2BI = 33292;

  const fr = Math.fround;

  function sat8(v) {
    return v < 0 ? 0 : v > 255 ? 255 : v;
  }

  // cvRound: pembulatan ke bilangan bulat terdekat, seri ke genap.
  function cvRound(v) {
    const f = Math.floor(v);
    const d = v - f;
    if (d < 0.5) return f;
    if (d > 0.5) return f + 1;
    return f % 2 === 0 ? f : f + 1;
  }

  // borderInterpolate(..., BORDER_REFLECT_101)
  function reflect101(p, len) {
    if (len === 1) return 0;
    while (p < 0 || p >= len) {
      if (p < 0) p = -p;
      else p = 2 * len - 2 - p;
    }
    return p;
  }

  function Clahe(clipLimit, tilesX, tilesY) {
    this.clipLimit = clipLimit === undefined ? 3.0 : clipLimit;
    this.tilesX = tilesX || 8;
    this.tilesY = tilesY || 8;
    this.w = 0;
    this.h = 0;
  }

  Clahe.prototype._siapkan = function (w, h) {
    if (w === this.w && h === this.h) return;
    this.w = w;
    this.h = h;
    const tx = this.tilesX, ty = this.tilesY;
    this.Y = new Uint8Array(w * h);
    this.U = new Uint8Array(w * h);
    this.V = new Uint8Array(w * h);
    this.Y2 = new Uint8Array(w * h);

    // Ukuran yang tidak habis dibagi jumlah tile diperluas dulu, persis seperti OpenCV
    // (kedua sisi ditambah tiles - (ukuran % tiles), walau salah satunya sudah habis dibagi).
    this.perluas = !(w % tx === 0 && h % ty === 0);
    this.lw = this.perluas ? w + tx - (w % tx) : w;
    this.lh = this.perluas ? h + ty - (h % ty) : h;
    this.ext = this.perluas ? new Uint8Array(this.lw * this.lh) : null;
    this.tileW = this.lw / tx;
    this.tileH = this.lh / ty;
    this.lut = new Uint8Array(tx * ty * 256);
    this.hist = new Int32Array(256);

    // Bobot interpolasi per kolom (sama untuk setiap baris).
    const invTw = fr(1 / this.tileW);
    this.ind1 = new Int32Array(w);
    this.ind2 = new Int32Array(w);
    this.xa = new Float32Array(w);
    this.xa1 = new Float32Array(w);
    for (let x = 0; x < w; x++) {
      const txf = fr(fr(x * invTw) - 0.5);
      let tx1 = Math.floor(txf);
      let tx2 = tx1 + 1;
      this.xa[x] = fr(txf - tx1);
      this.xa1[x] = fr(1 - this.xa[x]);
      tx1 = Math.max(tx1, 0);
      tx2 = Math.min(tx2, tx - 1);
      this.ind1[x] = tx1 * 256;
      this.ind2[x] = tx2 * 256;
    }
  };

  /** CLAHE untuk satu kanal 8 bit (w × h). Hasil di this.Y2. */
  Clahe.prototype._claheY = function (src) {
    const w = this.w, h = this.h, lw = this.lw, lh = this.lh;
    const tilesX = this.tilesX, tilesY = this.tilesY;
    const tileW = this.tileW, tileH = this.tileH;
    const lut = this.lut, hist = this.hist;

    let srcLut = src;
    if (this.perluas) {
      const ext = this.ext;
      for (let y = 0; y < lh; y++) {
        const sy = y < h ? y : reflect101(y, h);
        const baris = sy * w, tujuan = y * lw;
        for (let x = 0; x < lw; x++) ext[tujuan + x] = src[baris + (x < w ? x : reflect101(x, w))];
      }
      srcLut = ext;
    }

    const tileTotal = tileW * tileH;
    const lutScale = fr(255 / tileTotal);
    let clip = 0;
    if (this.clipLimit > 0) clip = Math.max(Math.trunc((this.clipLimit * tileTotal) / 256), 1);

    for (let k = 0; k < tilesX * tilesY; k++) {
      const ty = Math.floor(k / tilesX), tx = k % tilesX;
      hist.fill(0);
      for (let y = ty * tileH, yEnd = y + tileH; y < yEnd; y++) {
        let i = y * lw + tx * tileW;
        const iEnd = i + tileW;
        for (; i < iEnd; i++) hist[srcLut[i]]++;
      }

      if (clip > 0) {
        let clipped = 0;
        for (let i = 0; i < 256; i++) {
          if (hist[i] > clip) {
            clipped += hist[i] - clip;
            hist[i] = clip;
          }
        }
        const redistBatch = Math.trunc(clipped / 256);
        let residual = clipped - redistBatch * 256;
        for (let i = 0; i < 256; i++) hist[i] += redistBatch;
        if (residual !== 0) {
          const residualStep = Math.max(Math.trunc(256 / residual), 1);
          for (let i = 0; i < 256 && residual > 0; i += residualStep, residual--) hist[i]++;
        }
      }

      let sum = 0;
      const base = k * 256;
      for (let i = 0; i < 256; i++) {
        sum += hist[i];
        lut[base + i] = sat8(cvRound(fr(sum * lutScale)));
      }
    }

    const out = this.Y2, ind1 = this.ind1, ind2 = this.ind2, xa = this.xa, xa1 = this.xa1;
    const invTh = fr(1 / tileH);
    for (let y = 0; y < h; y++) {
      const tyf = fr(fr(y * invTh) - 0.5);
      let ty1 = Math.floor(tyf);
      let ty2 = ty1 + 1;
      const ya = fr(tyf - ty1), ya1 = fr(1 - ya);
      ty1 = Math.max(ty1, 0);
      ty2 = Math.min(ty2, tilesY - 1);
      const plane1 = ty1 * tilesX * 256, plane2 = ty2 * tilesX * 256;
      const baris = y * w;
      for (let x = 0; x < w; x++) {
        const v = src[baris + x];
        const i1 = ind1[x] + v, i2 = ind2[x] + v;
        const a = fr(fr(lut[plane1 + i1] * xa1[x]) + fr(lut[plane1 + i2] * xa[x]));
        const b = fr(fr(lut[plane2 + i1] * xa1[x]) + fr(lut[plane2 + i2] * xa[x]));
        out[baris + x] = sat8(cvRound(fr(fr(a * ya1) + fr(b * ya))));
      }
    }
  };

  /**
   * Terapkan BGR→YUV, CLAHE kanal Y, YUV→BGR langsung pada data RGBA (ImageData.data).
   * Alpha tidak diubah.
   */
  Clahe.prototype.terapkanRGBA = function (data, w, h) {
    this._siapkan(w, h);
    const Y = this.Y, U = this.U, V = this.V, n = w * h;
    for (let i = 0, j = 0; i < n; i++, j += 4) {
      const r = data[j], g = data[j + 1], b = data[j + 2];
      const y = (b * B2Y + g * G2Y + r * R2Y + HALF) >> SHIFT;
      Y[i] = sat8(y);
      V[i] = sat8(((r - y) * R2VI + DELTA + HALF) >> SHIFT);
      U[i] = sat8(((b - y) * B2UI + DELTA + HALF) >> SHIFT);
    }
    this._claheY(Y);
    const Y2 = this.Y2;
    for (let i = 0, j = 0; i < n; i++, j += 4) {
      const y = Y2[i], u = U[i] - 128, v = V[i] - 128;
      data[j] = sat8(y + ((v * V2RI + HALF) >> SHIFT));
      data[j + 1] = sat8(y + ((u * U2GI + v * V2GI + HALF) >> SHIFT));
      data[j + 2] = sat8(y + ((u * U2BI + HALF) >> SHIFT));
    }
  };

  return { Clahe, cvRound, reflect101 };
});
