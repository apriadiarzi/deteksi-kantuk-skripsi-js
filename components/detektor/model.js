/*
 * Memuat FaceLandmarker (MediaPipe Tasks Vision) dari CDN resmi.
 *
 * Bundle JS, file wasm, dan model disimpan di Cache Storage browser saat pertama diunduh, lalu
 * dipakai dari sana di sesi berikutnya. Cache HTTP saja tidak cukup: server model hanya memberi
 * max-age 1 jam. Kalau Cache Storage tidak tersedia, berkas dimuat langsung dari URL-nya.
 */
(function (root) {
  "use strict";

  const VERSI = "0.10.35";
  const CDN = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@" + VERSI;
  const URL_MODEL =
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task";
  const NAMA_CACHE = "deteksi-kantuk-mediapipe";

  // url -> { asal: "cache" | "jaringan", byte, transfer }; ditampilkan di panel pengujian.
  const sumber = {};
  const status = { cacheStorage: "belum dicek" };

  async function ambil(url, tipe) {
    let cache = null;
    try {
      cache = await caches.open(NAMA_CACHE);
      status.cacheStorage = "tersedia";
      const hit = await cache.match(url);
      if (hit) {
        const buf = await hit.arrayBuffer();
        sumber[url] = { asal: "cache", byte: buf.byteLength, transfer: 0 };
        return buf;
      }
    } catch (e) {
      // Mis. mode penyamaran atau penyimpanan situs diblokir: tetap jalan, hanya cache HTTP.
      status.cacheStorage = "tidak tersedia (" + e.name + ")";
      console.warn("Cache Storage tidak tersedia:", e);
      cache = null;
    }
    const resp = await fetch(url, { mode: "cors", credentials: "omit" });
    if (!resp.ok) throw new Error("Gagal mengunduh " + url + " (HTTP " + resp.status + ")");
    const buf = await resp.arrayBuffer();
    if (cache) {
      try {
        await cache.put(url, new Response(buf.slice(0), { headers: { "Content-Type": tipe } }));
      } catch (e) {
        console.warn("Gagal menyimpan ke Cache Storage:", e);
      }
    }
    const entri = performance.getEntriesByName(url).pop();
    sumber[url] = { asal: "jaringan", byte: buf.byteLength, transfer: entri ? entri.transferSize : 0 };
    return buf;
  }

  function blobUrl(buf, tipe) {
    return URL.createObjectURL(new Blob([buf], { type: tipe }));
  }

  let visionPromise = null, filesetPromise = null, modelPromise = null;

  function muatVision() {
    if (!visionPromise) {
      const url = CDN + "/vision_bundle.mjs";
      visionPromise = ambil(url, "text/javascript")
        .then((buf) => import(blobUrl(buf, "text/javascript")))
        .catch(() => import(url));
      visionPromise.catch(() => { visionPromise = null; });
    }
    return visionPromise;
  }

  function muatFileset(vision) {
    if (!filesetPromise) {
      filesetPromise = vision.FilesetResolver.forVisionTasks(CDN + "/wasm").then(async (asli) => {
        try {
          const [loader, wasm] = await Promise.all([
            ambil(asli.wasmLoaderPath, "text/javascript"),
            ambil(asli.wasmBinaryPath, "application/wasm"),
          ]);
          return {
            wasmLoaderPath: blobUrl(loader, "text/javascript"),
            wasmBinaryPath: blobUrl(wasm, "application/wasm"),
          };
        } catch (e) {
          console.warn("Wasm dimuat tanpa Cache Storage:", e);
          return asli;
        }
      });
      filesetPromise.catch(() => { filesetPromise = null; });
    }
    return filesetPromise;
  }

  function muatModel() {
    if (!modelPromise) {
      modelPromise = ambil(URL_MODEL, "application/octet-stream");
      modelPromise.catch(() => { modelPromise = null; });
    }
    return modelPromise;
  }

  /**
   * Buat FaceLandmarker dengan pengaturan yang sama seperti Face Mesh versi Python: satu wajah,
   * ambang deteksi dan pelacakan 0,5, tanpa blendshape. GPU yang gagal diganti CPU.
   * opsi: { mode: "VIDEO" | "IMAGE", delegate: "CPU" | "GPU" }
   */
  async function buatLandmarker(opsi) {
    const vision = await muatVision();
    const [fileset, model] = await Promise.all([muatFileset(vision), muatModel()]);
    const buat = (delegate) =>
      vision.FaceLandmarker.createFromOptions(fileset, {
        baseOptions: { modelAssetBuffer: new Uint8Array(model.slice(0)), delegate },
        runningMode: opsi.mode,
        numFaces: 1,
        minFaceDetectionConfidence: 0.5,
        minFacePresenceConfidence: 0.5,
        minTrackingConfidence: 0.5,
        outputFaceBlendshapes: false,
        outputFacialTransformationMatrixes: false,
      });
    try {
      return { landmarker: await buat(opsi.delegate), delegate: opsi.delegate };
    } catch (e) {
      if (opsi.delegate !== "GPU") throw e;
      console.warn("Delegate GPU gagal, memakai CPU:", e);
      return { landmarker: await buat("CPU"), delegate: "CPU" };
    }
  }

  root.ModelWajah = { VERSI, CDN, URL_MODEL, sumber, status, buatLandmarker };
})(self);
