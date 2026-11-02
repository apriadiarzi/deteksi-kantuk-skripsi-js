/*
 * Menggambar anotasi hasil Logika.prosesFrame() ke canvas dengan posisi, ukuran, dan warna yang
 * mengikuti plot_* di deteksi_kantuk.py (cv2.circle, cv2.line, cv2.putText).
 */
(function (root) {
  "use strict";

  const WARNA = {
    RED: "rgb(255, 0, 0)",
    GREEN: "rgb(0, 255, 0)",
    ORANGE: "rgb(255, 165, 0)",
    YELLOW: "rgb(255, 255, 0)",
  };
  // Tinggi huruf kapital FONT_HERSHEY_SIMPLEX skala 1 ±22 px ≈ font sans-serif 30 px.
  const PX_PER_SKALA = 30;

  // Koordinat OpenCV menunjuk pusat piksel; di canvas pusat piksel ada di +0,5.
  function titik(ctx, koordinat, warna) {
    if (!koordinat) return;
    ctx.fillStyle = WARNA[warna];
    for (const c of koordinat) {
      if (!c) continue;
      ctx.beginPath();
      ctx.arc(c[0] + 0.5, c[1] + 0.5, 2, 0, 2 * Math.PI);
      ctx.fill();
    }
  }

  function teks(ctx, s, x, y, warna, skala, tebal) {
    ctx.font = `${tebal >= 2 ? 700 : 400} ${Math.round(skala * PX_PER_SKALA)}px "Helvetica Neue", Arial, sans-serif`;
    ctx.textBaseline = "alphabetic";
    ctx.fillStyle = WARNA[warna];
    ctx.fillText(s, x, y);
  }

  function kepala(ctx, p, w) {
    if (!p.kiri || !p.kanan) return;
    ctx.strokeStyle = WARNA[p.warna];
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(p.kiri[0] + 0.5, p.kiri[1] + 0.5);
    ctx.lineTo(p.kanan[0] + 0.5, p.kanan[1] + 0.5);
    ctx.stroke();
    const midX = Math.floor((p.kiri[0] + p.kanan[0]) / 2);
    const midY = Math.floor((p.kiri[1] + p.kanan[1]) / 2);
    const s = Math.max(0.3, Math.min(0.6, (w / 640) * 0.5));
    teks(ctx, `${root.Logika.pyFixed(p.sudut, 1)}deg`, Math.trunc(midX - 30 * s * 2), midY - 10, p.warna, s, 1);
  }

  /** Gambar daftar perintah dari prosesFrame() untuk frame selebar w piksel. */
  function gambar(ctx, perintah, w) {
    // Ukuran huruf mengikuti lebar frame (0.8 untuk frame 640 px), seperti plot_text().
    const skala = Math.max(0.35, Math.min(1.0, (w / 640) * 0.8));
    const tebal = Math.max(1, Math.round(skala * 2.5));
    for (const p of perintah) {
      if (p.op === "mata") {
        titik(ctx, p.kiri, p.warna);
        titik(ctx, p.kanan, p.warna);
      } else if (p.op === "mulut") {
        titik(ctx, p.koordinat, p.warna);
      } else if (p.op === "kepala") {
        kepala(ctx, p, w);
      } else if (p.op === "teks") {
        teks(ctx, p.teks, p.x, p.y, p.warna, skala, tebal);
      }
    }
  }

  root.Anotasi = { gambar, WARNA };
})(self);
