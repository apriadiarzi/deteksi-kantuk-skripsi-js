/* Uji statis: padanan pengujian/uji_statis.py dengan FaceLandmarker (mode IMAGE). */
(function () {
  "use strict";

  const L = window.Logika, M = window.ModelWajah, A = window.Anotasi;
  const el = (id) => document.getElementById(id);

  // Nilai bawaan slider dan keterangan citra, sama dengan uji_statis.py.
  const EAR_THRESH = 0.23, MAR_THRESH = 0.60, TILT_THRESH = 20.0;
  const KETERANGAN = {
    "test-open-eyes.jpg": "mata terbuka",
    "test-open-eyes2.jpg": "mata terbuka",
    "test-close-eyes.jpg": "mata tertutup",
    "test-close-eyes2.jpg": "mata tertutup",
    "test-yawning.jpg": "menguap",
    "test-head-tilt.jpeg": "kepala miring",
  };
  const KEPALA = ["Citra", "Ukuran (piksel)", "EAR kiri", "EAR kanan", "EAR rata-rata", "MAR", "Sudut", "Kesimpulan sistem"];
  const MIN_LEBAR_GAMBAR = 640; // citra kecil diperbesar HANYA untuk tampilan

  const koma = (x, n = 3) => L.pyFixed(x, n).replace(".", ",");
  let baris = [], csvLama = null, landmarker = null, delegateAktif = null, kunciModel = null;

  function aturStatus(teks) { el("status").textContent = teks; }

  async function siapkanModel() {
    const kunci = el("opsi-delegate").value;
    if (landmarker && kunciModel === kunci) return;
    if (landmarker) landmarker.close();
    aturStatus("Memuat model deteksi wajah…");
    const h = await M.buatLandmarker({ mode: "IMAGE", delegate: kunci });
    landmarker = h.landmarker;
    delegateAktif = h.delegate;
    kunciModel = kunci;
  }

  function kesimpulan(ear, mar, sudut) {
    const kondisi = [];
    if (mar > MAR_THRESH) kondisi.push("Menguap");
    if (ear < EAR_THRESH) kondisi.push("Mata tertutup");
    if (Math.abs(sudut) > TILT_THRESH) kondisi.push("Kepala miring");
    return kondisi.length ? kondisi[0] + kondisi.slice(1).map((k) => " dan " + k.toLowerCase()).join("") : "Normal";
  }

  function gambarHasil(img, ind, nama) {
    const s = Math.max(1, MIN_LEBAR_GAMBAR / img.width);
    const W = Math.round(img.width * s), H = Math.round(img.height * s);
    const asal = document.createElement("canvas");
    asal.width = img.width;
    asal.height = img.height;
    asal.getContext("2d").putImageData(img, 0, 0);
    const kanvas = document.createElement("canvas");
    kanvas.width = W;
    kanvas.height = H;
    const ctx = kanvas.getContext("2d");
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(asal, 0, 0, W, H);

    const sk = (pts) => (pts ? pts.map((p) => (p ? [Math.round(p[0] * s), Math.round(p[1] * s)] : p)) : pts);
    const perintah = [];
    const ui = Math.max(0.45, Math.min(1.25, W / 640));
    const pad = Math.trunc(10 * ui), line = Math.trunc(30 * ui);
    if (!ind) {
      perintah.push({ op: "teks", teks: "WAJAH TIDAK TERDETEKSI", x: 10, y: Math.floor(H / 2), warna: "RED" });
    } else {
      const warnaMata = ind.ear < EAR_THRESH ? "RED" : "GREEN";
      const menguap = ind.mar > MAR_THRESH;
      const warnaMiring = Math.abs(ind.angle) > TILT_THRESH ? "YELLOW" : "GREEN";
      perintah.push({ op: "mata", kiri: sk(ind.eyeCoords[0]), kanan: sk(ind.eyeCoords[1]), warna: warnaMata });
      perintah.push({ op: "mulut", koordinat: sk(ind.mouthCoords), warna: "ORANGE" });
      perintah.push({ op: "kepala", kiri: sk([ind.leftPt])[0], kanan: sk([ind.rightPt])[0], sudut: ind.angle, warna: warnaMiring });
      perintah.push({ op: "teks", teks: `EAR: ${L.pyStr(L.pyRound(ind.ear, 3))}`, x: pad, y: line, warna: warnaMata });
      perintah.push({ op: "teks", teks: `MAR: ${L.pyStr(L.pyRound(ind.mar, 3))}`, x: pad, y: line * 2, warna: menguap ? "ORANGE" : "GREEN" });
      perintah.push({ op: "teks", teks: `TILT: ${L.pyFixed(ind.angle, 1)}deg`, x: pad, y: line * 3, warna: warnaMiring });
      if (ind.ear < EAR_THRESH) perintah.push({ op: "teks", teks: "MATA TERTUTUP!", x: pad, y: Math.trunc(H / 2 - line * 0.7), warna: "RED" });
      if (menguap) perintah.push({ op: "teks", teks: "MENGUAP TERDETEKSI!", x: pad, y: Math.trunc(H / 2 + line * 0.7), warna: "ORANGE" });
      if (Math.abs(ind.angle) > TILT_THRESH) perintah.push({ op: "teks", teks: "KEPALA MIRING!", x: pad, y: Math.trunc(H / 2 + line * 2), warna: "YELLOW" });
    }
    A.gambar(ctx, perintah, W);

    const fig = document.createElement("figure");
    const cap = document.createElement("figcaption");
    cap.textContent = nama;
    fig.append(kanvas, cap);
    el("galeri").append(fig);
  }

  async function proses() {
    const berkas = Array.from(el("berkas").files).sort((a, b) => a.name.localeCompare(b.name));
    if (!berkas.length) return;
    el("tombol-proses").disabled = true;
    el("galeri").innerHTML = "";
    baris = [];
    try {
      await siapkanModel();
      const clahe = el("opsi-clahe").checked ? new window.Clahe.Clahe(3.0, 8, 8) : null;
      for (const f of berkas) {
        aturStatus("Memproses " + f.name + "…");
        // Tanpa konversi profil warna, supaya piksel sama dengan cv2.imread.
        const bmp = await createImageBitmap(f, { colorSpaceConversion: "none", premultiplyAlpha: "none" });
        const w = bmp.width, h = bmp.height;
        const c = document.createElement("canvas");
        c.width = w;
        c.height = h;
        const ctx = c.getContext("2d", { willReadFrequently: true, colorSpace: "srgb" });
        ctx.drawImage(bmp, 0, 0);
        const img = ctx.getImageData(0, 0, w, h);
        if (clahe) clahe.terapkanRGBA(img.data, w, h);
        const hasil = landmarker.detect(img);
        const lm = hasil.faceLandmarks && hasil.faceLandmarks[0];
        const ind = lm ? L.hitungIndikator(lm, w, h) : null;
        const nama = KETERANGAN[f.name] ? `${f.name} (${KETERANGAN[f.name]})` : f.name;
        baris.push(ind
          ? [nama, `${w} x ${h}`, koma(ind.earKiri), koma(ind.earKanan), koma(ind.ear), koma(ind.mar),
             koma(ind.angle, 1) + " derajat", kesimpulan(ind.ear, ind.mar, ind.angle)]
          : [nama, `${w} x ${h}`, "-", "-", "-", "-", "-", "Wajah tidak terdeteksi"]);
        gambarHasil(img, ind, nama);
      }
      tampilkanTabel();
      tampilkanBanding();
      el("judul-galeri").hidden = false;
      el("tombol-csv").disabled = false;
      aturStatus(`Selesai: ${berkas.length} citra, tasks-vision ${M.VERSI}, delegate ${delegateAktif}, CLAHE ${clahe ? "aktif" : "nonaktif"}.`);
    } catch (e) {
      console.error(e);
      aturStatus("Gagal: " + e.message);
    } finally {
      el("tombol-proses").disabled = false;
    }
  }

  const escape = (s) => String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);

  function tampilkanTabel() {
    el("tabel").innerHTML = `<thead><tr>${KEPALA.map((k) => `<th>${k}</th>`).join("")}</tr></thead><tbody>` +
      baris.map((b) => `<tr>${b.map((v) => `<td>${escape(v)}</td>`).join("")}</tr>`).join("") + "</tbody>";
  }

  const angka = (s) => (s && s !== "-" ? Number(String(s).replace(" derajat", "").replace(",", ".")) : null);

  function tampilkanBanding() {
    if (!csvLama || !baris.length) { el("bagian-banding").hidden = true; return; }
    const kolom = [["EAR rata-rata", 4, 3], ["MAR", 5, 3], ["Sudut", 6, 1]];
    let html = "<thead><tr><th>Citra</th>" +
      kolom.map(([k]) => `<th>${k} lama</th><th>${k} baru</th><th>Selisih</th>`).join("") +
      "<th>Kesimpulan lama → baru</th></tr></thead><tbody>";
    for (const b of baris) {
      const lama = csvLama.find((r) => r[0] === b[0]);
      if (!lama) continue;
      html += `<tr><td>${escape(b[0])}</td>`;
      for (const [, i, n] of kolom) {
        const a = angka(lama[i]), c = angka(b[i]);
        const sel = a === null || c === null ? "–" : (c - a >= 0 ? "+" : "") + koma(c - a, n);
        html += `<td>${escape(lama[i])}</td><td>${escape(b[i])}</td><td>${sel}</td>`;
      }
      const sama = lama[7] === b[7];
      html += `<td class="${sama ? "" : "beda"}">${escape(lama[7])}${sama ? "" : " → " + escape(b[7])}</td></tr>`;
    }
    el("tabel-banding").innerHTML = html + "</tbody>";
    el("bagian-banding").hidden = false;
  }

  function unduhCsv() {
    const isi = [KEPALA, ...baris].map((b) => b.join(";")).join("\n") + "\n";
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob(["﻿" + isi], { type: "text/csv;charset=utf-8" }));
    a.download = "hasil_uji_statis_browser.csv";
    document.body.append(a);
    a.click();
    a.remove();
  }

  el("berkas").addEventListener("change", () => { el("tombol-proses").disabled = !el("berkas").files.length; });
  el("csv-lama").addEventListener("change", async () => {
    const f = el("csv-lama").files[0];
    if (!f) { csvLama = null; return; }
    const teks = (await f.text()).replace(/^﻿/, "");
    csvLama = teks.split(/\r?\n/).filter(Boolean).slice(1).map((r) => r.split(";"));
    tampilkanBanding();
  });
  el("tombol-proses").addEventListener("click", proses);
  el("tombol-csv").addEventListener("click", unduhCsv);
})();
