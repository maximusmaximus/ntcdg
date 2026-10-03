/* "Scan another card": reads a card-back QR code with the camera.
   Uses the native BarcodeDetector when available, otherwise loads jsQR from jsDelivr
   with Subresource Integrity. Only NTCDG card URLs on this site's configured public
   host(s) open directly; anything else shows a warning first. */
(function () {
  "use strict";
  var btn = document.querySelector("[data-scan]");
  var dialog = document.querySelector("[data-scanner]");
  if (!btn || !dialog) return;
  if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia) || !window.isSecureContext) return;
  btn.hidden = false;

  var video = dialog.querySelector("[data-scanner-video]");
  var statusEl = dialog.querySelector("[data-scanner-status]");
  var warn = dialog.querySelector("[data-scanner-warn]");
  var warnUrl = dialog.querySelector("[data-scanner-url]");
  var openAnyway = dialog.querySelector("[data-scanner-open]");
  var hosts = (btn.getAttribute("data-hosts") || "").split(",").map(function (h) { return h.trim().toLowerCase(); })
    .filter(Boolean);
  var suffix = (btn.getAttribute("data-suffix") || "").toLowerCase();
  var stream = null, timer = null, detector = null, canvas = null, ctx = null, jsqrPromise = null;

  function setStatus(text) { if (statusEl) statusEl.textContent = text; }

  function trusted(url) {
    if (url.protocol !== "https:" && url.protocol !== "http:") return false;
    var host = url.hostname.toLowerCase();
    if (url.host === window.location.host) return true;
    if (hosts.indexOf(host) >= 0) return true;
    return !!(suffix && host.length > suffix.length && host.slice(-suffix.length) === suffix);
  }

  function loadJsQR() {
    if (window.jsQR) return Promise.resolve(window.jsQR);
    if (jsqrPromise) return jsqrPromise;
    jsqrPromise = new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = btn.getAttribute("data-jsqr-url");
      s.integrity = btn.getAttribute("data-jsqr-sri");
      s.crossOrigin = "anonymous";
      s.referrerPolicy = "no-referrer";
      s.onload = function () { window.jsQR ? resolve(window.jsQR) : reject(new Error("jsQR missing")); };
      s.onerror = function () { jsqrPromise = null; reject(new Error("Could not load the QR reader")); };
      document.head.appendChild(s);
    });
    return jsqrPromise;
  }

  function getDetector() {
    if (!("BarcodeDetector" in window)) return Promise.resolve(null);
    var get = window.BarcodeDetector.getSupportedFormats
      ? window.BarcodeDetector.getSupportedFormats() : Promise.resolve(["qr_code"]);
    return get.then(function (formats) {
      return formats.indexOf("qr_code") >= 0 ? new window.BarcodeDetector({ formats: ["qr_code"] }) : null;
    }).catch(function () { return null; });
  }

  function stop() {
    if (timer) { clearTimeout(timer); timer = null; }
    if (stream) { stream.getTracks().forEach(function (t) { t.stop(); }); stream = null; }
    if (video) video.srcObject = null;
  }

  function close() {
    stop();
    if (dialog.open) { if (dialog.close) dialog.close(); else dialog.removeAttribute("open"); }
  }

  function handle(text) {
    var url;
    try { url = new URL(String(text).trim(), window.location.href); } catch (e) { url = null; }
    if (url && trusted(url)) {
      setStatus("Opening card…");
      stop();
      window.location.assign(url.href);
      return true;
    }
    stop();
    warn.hidden = false;
    warnUrl.textContent = String(text).slice(0, 300);
    if (url && (url.protocol === "https:" || url.protocol === "http:")) {
      openAnyway.href = url.href;
      openAnyway.hidden = false;
    } else {
      openAnyway.removeAttribute("href");
      openAnyway.hidden = true;
    }
    setStatus("That code isn't a card from this deck's site.");
    return true;
  }

  function scanFrame(jsQR) {
    if (!stream) return;
    if (video.readyState < 2) { timer = setTimeout(function () { scanFrame(jsQR); }, 150); return; }
    var next = function () { if (stream) timer = setTimeout(function () { scanFrame(jsQR); }, 180); };
    if (detector) {
      detector.detect(video).then(function (codes) {
        if (codes && codes.length && codes[0].rawValue) { handle(codes[0].rawValue); return; }
        next();
      }).catch(next);
      return;
    }
    var w = video.videoWidth, h = video.videoHeight;
    if (!w || !h) { next(); return; }
    var scale = Math.min(1, 640 / Math.max(w, h));
    canvas.width = Math.round(w * scale);
    canvas.height = Math.round(h * scale);
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    var img = ctx.getImageData(0, 0, canvas.width, canvas.height);
    var code = jsQR(img.data, img.width, img.height, { inversionAttempts: "dontInvert" });
    if (code && code.data) { handle(code.data); return; }
    next();
  }

  function start() {
    warn.hidden = true;
    setStatus("Starting camera…");
    if (dialog.showModal) dialog.showModal(); else dialog.setAttribute("open", "");
    getDetector().then(function (d) {
      detector = d;
      if (detector) return null;
      canvas = canvas || document.createElement("canvas");
      ctx = ctx || canvas.getContext("2d", { willReadFrequently: true });
      return loadJsQR();
    }).then(function (jsQR) {
      return navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false })
        .then(function (s) {
          stream = s;
          video.srcObject = s;
          return video.play().catch(function () { /* autoplay quirks */ });
        }).then(function () {
          setStatus("Point your camera at the QR code on the back of a card.");
          scanFrame(jsQR);
        });
    }).catch(function (e) {
      stop();
      setStatus((e && e.name === "NotAllowedError")
        ? "Camera permission was denied. You can still open a card by scanning with your phone's camera app."
        : "Could not start the scanner: " + (e && e.message ? e.message : e));
    });
  }

  btn.addEventListener("click", start);
  dialog.querySelector("[data-scanner-close]").addEventListener("click", close);
  dialog.addEventListener("close", stop);
  dialog.addEventListener("cancel", stop);
})();
