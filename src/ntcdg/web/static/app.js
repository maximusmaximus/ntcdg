/* NTCDG web app: tool forms, live job widget, uploads. No frameworks; CSP-safe (no inline code). */
(function () {
  "use strict";

  var CSRF = (document.querySelector('meta[name="csrf-token"]') || {}).content || "";

  // ---------- tiny DOM helpers ----------
  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (v === null || v === undefined || v === false) return;
        if (k === "text") node.textContent = v;
        else if (k === "className") node.className = v;
        else node.setAttribute(k, v === true ? "" : String(v));
      });
    }
    (children || []).forEach(function (c) {
      if (c) node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return node;
  }
  function pretty(v) {
    try { return JSON.stringify(v, null, 2); } catch (e) { return String(v); }
  }
  function ioBlock(label, value, open) {
    return el("details", { className: "io", open: open !== false }, [
      el("summary", { text: label }),
      el("pre", { className: "json", text: typeof value === "string" ? value : pretty(value) }),
    ]);
  }
  function statusBadge(status) {
    return el("span", { className: "status s-" + status, text: status });
  }

  // Collect same-origin file URLs from a tool output so images/PDFs show inline.
  var FILE_URL_RE = /^\/(files|uploads)\/[^\s"'<>]+$/;
  var IMG_URL_RE = /(\/card\/\d+|\/back\/|\/_previews\/|\/_symbols\/|^\/uploads\/|\.(png|jpe?g|webp|gif)(\?|$))/i;
  function collectUrls(v, out, depth) {
    if (out.length >= 48 || depth > 8 || v === null || v === undefined) return out;
    if (typeof v === "string") {
      if (FILE_URL_RE.test(v) && out.indexOf(v) < 0) out.push(v);
    } else if (Array.isArray(v)) {
      v.forEach(function (x) { collectUrls(x, out, depth + 1); });
    } else if (typeof v === "object") {
      Object.keys(v).forEach(function (k) { collectUrls(v[k], out, depth + 1); });
    }
    return out;
  }
  function mediaFor(output) {
    var urls = collectUrls(output, [], 0);
    if (!urls.length) return null;
    var imgs = el("div", { className: "result-media" });
    var files = el("ul", { className: "result-files" });
    urls.forEach(function (u) {
      if (IMG_URL_RE.test(u)) {
        imgs.appendChild(el("a", { href: u, target: "_blank", rel: "noopener" }, [
          el("img", { src: u, alt: "", loading: "lazy" }),
        ]));
      } else {
        var name = decodeURIComponent(u.split("?")[0].split("/").pop() || u);
        files.appendChild(el("li", null, [el("a", { href: u, download: name, text: "⬇ " + name })]));
      }
    });
    var wrap = el("div", { className: "result-extra" });
    if (imgs.childNodes.length) wrap.appendChild(imgs);
    if (files.childNodes.length) wrap.appendChild(files);
    return wrap;
  }

  // ---------- tool forms ----------
  function collectInputs(form) {
    var inputs = {};
    var fields = form.querySelectorAll("[data-kind][name]");
    for (var i = 0; i < fields.length; i++) {
      var f = fields[i];
      var kind = f.getAttribute("data-kind");
      var name = f.name;
      if (kind === "bool") {
        inputs[name] = f.type === "checkbox" ? f.checked : f.value === "true";
      } else if (kind === "int" || kind === "float") {
        if (f.value.trim() !== "") inputs[name] = Number(f.value);
      } else if (kind === "json") {
        var text = f.value.trim();
        if (text) {
          try { inputs[name] = JSON.parse(text); }
          catch (e) { throw new Error(name + " is not valid JSON: " + e.message); }
        }
      } else if (kind === "upload_images") {
        inputs[name] = Array.prototype.filter.call(f.options, function (o) { return o.selected; })
          .map(function (o) { return o.value; });
      } else {
        inputs[name] = f.value;
      }
    }
    return inputs;
  }

  function renderSync(box, data) {
    box.textContent = "";
    var ok = !(data.output && (data.output.success === false || (data.output.error && data.output.success !== true)));
    box.appendChild(el("p", { className: "result-head" }, [
      statusBadge(ok ? "done" : "error"), " ", el("code", { text: data.tool }),
    ]));
    if (!ok && data.output && data.output.error) {
      box.appendChild(el("p", { className: "flash error", text: String(data.output.error) }));
    }
    var media = mediaFor(data.output);
    if (media) box.appendChild(media);
    box.appendChild(ioBlock("Input", data.input, true));
    box.appendChild(ioBlock("Output", data.output, true));
    if (data.console) box.appendChild(ioBlock("Console", data.console, false));
  }

  function renderError(box, status, data, inputs) {
    box.textContent = "";
    var msg = (data && data.error) || ("Request failed (" + status + ")");
    var p = el("p", { className: "flash error", text: msg });
    if (data && data.needs_key) {
      p.appendChild(document.createTextNode(" "));
      p.appendChild(el("a", { href: "/profile#venice-key", text: "Add your Venice key →" }));
    }
    box.appendChild(p);
    box.appendChild(ioBlock("Input", (data && data.input) || inputs, true));
  }

  function submitTool(form, ev) {
    ev.preventDefault();
    var tool = form.getAttribute("data-tool");
    var box = form.querySelector(".tool-result");
    var btn = form.querySelector('button[type="submit"]');
    var inputs;
    try { inputs = collectInputs(form); }
    catch (e) { renderError(box, 0, { error: e.message }, {}); return; }
    box.textContent = "";
    box.appendChild(el("p", { className: "muted", text: "Running…" }));
    if (btn) btn.disabled = true;
    fetch("/api/tools/" + encodeURIComponent(tool), {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": CSRF, Accept: "application/json" },
      body: JSON.stringify({ inputs: inputs }),
    }).then(function (resp) {
      return resp.json().catch(function () { return {}; }).then(function (data) {
        if (!resp.ok) { renderError(box, resp.status, data, inputs); return; }
        if (data.mode === "job") {
          box.textContent = "";
          box.appendChild(ioBlock("Input", data.input, false));
          var host = el("div", { className: "job-host", "data-job-id": data.job_id, "data-tool": tool });
          box.appendChild(host);
          JobWidget(host, data.job_id, tool);
        } else {
          renderSync(box, data);
        }
      });
    }).catch(function (e) {
      renderError(box, 0, { error: "Network error: " + e.message }, inputs);
    }).then(function () { if (btn) btn.disabled = false; });
  }

  // ---------- live job widget (SSE with polling fallback) ----------
  function JobWidget(host, jobId, tool) {
    host.textContent = "";
    var head = el("p", { className: "job-head" });
    var status = statusBadge("queued");
    head.appendChild(status);
    head.appendChild(document.createTextNode(" "));
    head.appendChild(el("a", { href: "/jobs/" + jobId + "/view", text: "Job page" }));
    var progress = el("progress", { max: 1, value: 0, hidden: true });
    var progressLabel = el("span", { className: "muted small" });
    var gallery = el("div", { className: "job-gallery" });
    var events = el("ol", { className: "job-events" });
    var log = el("pre", { className: "job-log" });
    var outBox = el("div", { className: "job-output" });
    host.appendChild(head);
    host.appendChild(el("div", { className: "job-progress" }, [progress, progressLabel]));
    host.appendChild(gallery);
    host.appendChild(el("details", { className: "io" }, [el("summary", { text: "Events" }), events]));
    host.appendChild(el("details", { className: "io", open: true }, [el("summary", { text: "Live log" }), log]));
    host.appendChild(outBox);

    var seenEvents = 0, seenLog = 0, total = 0, done = 0, finished = false, pollTimer = null, es = null;
    var tiles = {};

    function setStatus(s) {
      status.className = "status s-" + s;
      status.textContent = s;
    }
    function addEvent(e) {
      var type = e.type || "event";
      if (type === "deck_started" && e.num_cards) { total = e.num_cards; progress.max = total; progress.hidden = false; }
      if (type === "card_started" && e.total && !total) { total = e.total; progress.max = total; progress.hidden = false; }
      if (type === "card_done" || type === "card_skipped") { done += 1; }
      if (total) { progress.value = Math.min(done, total); progressLabel.textContent = " " + done + " / " + total + " cards"; }
      var url = e.image_url || (e.card && e.card.image_url);
      if (url && e.position !== undefined) {
        var tile = tiles[e.position];
        if (!tile) {
          tile = el("figure", { className: "job-tile" }, [el("img", { alt: "", loading: "lazy" }), el("figcaption")]);
          tiles[e.position] = tile;
          gallery.appendChild(tile);
        }
        tile.querySelector("img").src = url;
        var title = (e.card && (e.card.venice_title || e.card.title)) || e.title || "";
        tile.querySelector("figcaption").textContent = e.position + (title ? " · " + title : "");
      }
      var summary = type + (e.position !== undefined ? " #" + e.position : "") + (e.title ? " — " + e.title : "");
      var li = el("li", null, [el("span", { text: summary })]);
      li.appendChild(el("details", null, [el("summary", { text: "data" }), el("pre", { className: "json", text: pretty(e) })]));
      events.appendChild(li);
    }
    function apply(u) {
      if (u.status) setStatus(u.status);
      (u.events || []).forEach(addEvent);
      seenEvents += (u.events || []).length;
      if (u.log) {
        seenLog += u.log.length;
        var atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 8;
        log.textContent += u.log;
        if (atBottom) log.scrollTop = log.scrollHeight;
      }
      if (u.output !== null && u.output !== undefined && !finished) finish(u);
    }
    function finish(u) {
      finished = true;
      if (es) { es.close(); es = null; }
      if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
      outBox.textContent = "";
      if (u.error) outBox.appendChild(el("p", { className: "flash error", text: u.error }));
      var media = mediaFor(u.output);
      if (media) outBox.appendChild(media);
      if (u.output !== null && u.output !== undefined) outBox.appendChild(ioBlock("Output", u.output, true));
      var deck = host.getAttribute("data-deck") || (u.deck || "");
      if (deck && u.status === "done") {
        outBox.appendChild(el("p", null, [el("a", { className: "btn small", href: "/decks/" + encodeURIComponent(deck), text: "Open deck →" })]));
      }
    }
    function poll() {
      fetch("/jobs/" + jobId + "?since_event=" + seenEvents + "&since_log=" + seenLog, {
        credentials: "same-origin", headers: { Accept: "application/json" },
      }).then(function (r) { return r.json(); }).then(function (v) {
        if (v.error && !v.status) { setStatus("error"); outBox.textContent = v.error; return; }
        var terminal = ["done", "error", "interrupted", "cancelled"].indexOf(v.status) >= 0;
        if (v.deck) host.setAttribute("data-deck", v.deck);
        apply({ status: v.status, events: v.events, log: v.log, output: terminal ? v.output : null, error: v.error, deck: v.deck });
        if (terminal && !finished) finish(v);
        if (!finished) pollTimer = setTimeout(poll, 1500);
      }).catch(function () { if (!finished) pollTimer = setTimeout(poll, 3000); });
    }
    if (window.EventSource) {
      es = new EventSource("/jobs/" + jobId + "/events");
      es.addEventListener("update", function (m) {
        try { apply(JSON.parse(m.data)); } catch (e) { /* ignore malformed frame */ }
      });
      es.addEventListener("done", function () { if (es) { es.close(); es = null; } if (!finished) poll(); });
      es.onerror = function () {
        if (es) { es.close(); es = null; }
        if (!finished && !pollTimer) poll();
      };
    } else {
      poll();
    }
  }

  // ---------- uploads ----------
  function addUploadEverywhere(u) {
    document.querySelectorAll("[data-upload-list]").forEach(function (list) {
      var li = el("li", { "data-id": u.id });
      if (u.url) li.appendChild(el("img", { src: u.url, alt: "", loading: "lazy" }));
      li.appendChild(el("code", { text: u.ref }));
      li.appendChild(document.createTextNode(" "));
      li.appendChild(el("span", { text: u.name + (u.kind === "symbols_json" ? " (symbols.json, " + u.symbols + " symbols)" : "") }));
      list.appendChild(li);
    });
    var sel = u.kind === "image" ? "select[data-upload-select]" : "select[data-symbols-select]";
    document.querySelectorAll(sel).forEach(function (s) {
      var label = u.kind === "image" ? u.name + " (" + u.id + ")" : "Uploaded file: " + u.name;
      s.appendChild(el("option", { value: u.ref, text: label }));
    });
  }
  function submitUpload(form, ev) {
    ev.preventDefault();
    var fd = new FormData(form);
    fd.append("kind", form.getAttribute("data-kind") || "image");
    var msg = form.querySelector(".upload-msg") || form.appendChild(el("p", { className: "upload-msg small" }));
    msg.textContent = "Uploading…";
    fetch("/uploads", {
      method: "POST", credentials: "same-origin", body: fd,
      headers: { "X-CSRF-Token": CSRF, Accept: "application/json" },
    }).then(function (r) { return r.json().catch(function () { return {}; }); }).then(function (data) {
      (data.uploads || []).forEach(addUploadEverywhere);
      var parts = [];
      if ((data.uploads || []).length) parts.push("Uploaded " + data.uploads.length + " file(s).");
      (data.errors || []).forEach(function (e) { parts.push(e.name + ": " + e.error); });
      if (data.error) parts.push(data.error);
      msg.textContent = parts.join(" ");
      if ((data.uploads || []).length) form.reset();
    }).catch(function (e) { msg.textContent = "Upload failed: " + e.message; });
  }

  // "Fill from my uploaded images" -> symbol definitions JSON
  function fillSymbols(btn) {
    var area = btn.parentNode.querySelector("textarea");
    if (!area) return;
    var seen = {};
    var defs = [];
    document.querySelectorAll("select[data-upload-select] option").forEach(function (o) {
      if (seen[o.value]) return;
      seen[o.value] = true;
      var name = (o.textContent || "").replace(/\s*\([^)]*\)\s*$/, "").replace(/\.[a-z0-9]+$/i, "")
        .replace(/[_-]+/g, " ").trim();
      defs.push({ name: name || o.value, image_path: o.value, description: "" });
    });
    area.value = defs.length ? JSON.stringify(defs, null, 2) : "";
    if (!defs.length) area.placeholder = "Upload some images first.";
  }

  // Keep every deck-name field on a page in sync (wizard).
  function syncDeckNames(src) {
    document.querySelectorAll('[data-sync="deckname"]').forEach(function (f) {
      if (f !== src) f.value = src.value;
    });
  }

  // ---------- wire up ----------
  document.addEventListener("submit", function (ev) {
    var form = ev.target;
    if (form.matches && form.matches("form.tool-form")) submitTool(form, ev);
    else if (form.matches && form.matches("form.upload-form")) submitUpload(form, ev);
  });
  document.addEventListener("click", function (ev) {
    var t = ev.target.closest ? ev.target.closest("[data-fill-symbols]") : null;
    if (t) { ev.preventDefault(); fillSymbols(t); }
  });
  document.addEventListener("input", function (ev) {
    if (ev.target.matches && ev.target.matches('[data-sync="deckname"]')) syncDeckNames(ev.target);
  });
  document.querySelectorAll(".job-host[data-job-id]").forEach(function (host) {
    JobWidget(host, host.getAttribute("data-job-id"), host.getAttribute("data-tool"));
  });
  document.querySelectorAll("form[data-confirm]").forEach(function (f) {
    f.addEventListener("submit", function (ev) {
      if (!window.confirm(f.getAttribute("data-confirm"))) ev.preventDefault();
    });
  });
})();
