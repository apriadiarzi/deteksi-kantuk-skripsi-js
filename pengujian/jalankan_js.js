// Menjalankan logika JS mode browser di Node untuk uji_kesamaan.py.
// Pemakaian: node jalankan_js.js <indikator|logika|clahe> <masukan> <keluaran>
"use strict";
const fs = require("fs");
const path = require("path");

const DIR = path.join(__dirname, "..", "components", "detektor");
const Logika = require(path.join(DIR, "logika.js"));
const { Clahe } = require(path.join(DIR, "clahe.js"));

const [uji, masukan, keluaran] = process.argv.slice(2);

function landmarkDari(arr) {
  return arr.map(([x, y]) => ({ x, y }));
}

if (uji === "indikator") {
  const kasus = JSON.parse(fs.readFileSync(masukan, "utf8"));
  const hasil = kasus.map((k) => {
    const lm = landmarkDari(k.lm);
    const [earKiri, kiri] = Logika.getEar(lm, Logika.EYE_IDXS.left, k.w, k.h);
    const [earKanan, kanan] = Logika.getEar(lm, Logika.EYE_IDXS.right, k.w, k.h);
    const ind = Logika.hitungIndikator(lm, k.w, k.h);
    return {
      ear_kiri: earKiri, ear_kanan: earKanan, ear: ind.ear, kiri, kanan,
      mar: ind.mar, mulut: ind.mouthCoords, sudut: ind.angle, lpt: ind.leftPt, rpt: ind.rightPt,
      teks_ear: `EAR: ${Logika.pyStr(Logika.pyRound(ind.ear, 2))}`,
      teks_sudut: `TILT: ${Logika.pyFixed(ind.angle, 1)}deg`,
    };
  });
  fs.writeFileSync(keluaran, JSON.stringify(hasil));
} else if (uji === "logika") {
  const skenario = JSON.parse(fs.readFileSync(masukan, "utf8"));
  const hasil = skenario.map((langkah) => {
    const det = new Logika.DetektorKantuk();
    const out = [];
    for (const l of langkah) {
      if (l.op === "sesi_baru") { det.mulaiSesi(); continue; }
      out.push(det.prosesFrame(l.ind, l.t, l.wall, l.ambang, l.w, l.h));
    }
    return out;
  });
  fs.writeFileSync(keluaran, JSON.stringify(hasil));
} else if (uji === "clahe") {
  // masukan: JSON daftar {berkas, w, h} berisi piksel BGR mentah; keluaran: folder hasil BGR.
  const daftar = JSON.parse(fs.readFileSync(masukan, "utf8"));
  const clahe = new Clahe(3.0, 8, 8);
  for (const d of daftar) {
    const bgr = fs.readFileSync(d.berkas);
    const n = d.w * d.h;
    const rgba = new Uint8ClampedArray(n * 4);
    for (let i = 0; i < n; i++) {
      rgba[4 * i] = bgr[3 * i + 2];
      rgba[4 * i + 1] = bgr[3 * i + 1];
      rgba[4 * i + 2] = bgr[3 * i];
      rgba[4 * i + 3] = 255;
    }
    const t0 = process.hrtime.bigint();
    clahe.terapkanRGBA(rgba, d.w, d.h);
    d.ms = Number(process.hrtime.bigint() - t0) / 1e6;
    const out = Buffer.alloc(n * 3);
    for (let i = 0; i < n; i++) {
      out[3 * i] = rgba[4 * i + 2];
      out[3 * i + 1] = rgba[4 * i + 1];
      out[3 * i + 2] = rgba[4 * i];
    }
    fs.writeFileSync(path.join(keluaran, path.basename(d.berkas) + ".js.bin"), out);
  }
  fs.writeFileSync(path.join(keluaran, "waktu.json"), JSON.stringify(daftar.map((d) => d.ms)));
} else {
  console.error("uji tidak dikenal:", uji);
  process.exit(2);
}
