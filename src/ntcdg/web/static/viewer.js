/* Public card viewer: swipe / arrow keys / buttons move through the deck (wrapping),
   updating the page in place and the address bar via history.replaceState.
   Without JS the prev/next links still work as plain navigation. */
(function () {
  "use strict";
  var root = document.querySelector("[data-viewer]");
  if (!root || !window.fetch) return;

  var deckSlug = root.getAttribute("data-deck-slug");
  var cache = {};
  var busy = false;

  function $(field) { return root.querySelector('[data-field="' + field + '"]'); }
  function jsonUrl(slug) { return "/p/" + encodeURIComponent(deckSlug) + "/" + encodeURIComponent(slug) + ".json"; }

  function load(slug) {
    if (!slug) return Promise.reject(new Error("no slug"));
    if (!cache[slug]) {
      cache[slug] = fetch(jsonUrl(slug), { headers: { Accept: "application/json" } }).then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      });
      cache[slug].catch(function () { delete cache[slug]; });
    }
    return cache[slug];
  }

  function prefetch(slug) {
    load(slug).then(function (c) {
      if (c.image_url) { var img = new Image(); img.src = c.image_url; }
    }).catch(function () { /* ignore */ });
  }

  function setText(field, text) {
    var node = $(field);
    if (!node) return;
    node.textContent = text || "";
    node.hidden = !text;
  }
  function setSection(name, field, text) {
    var section = root.querySelector('[data-section="' + name + '"]');
    var p = $(field);
    if (p) p.textContent = text || "";
    if (section) section.hidden = !text;
  }

  function render(c) {
    var img = $("image");
    var placeholder = $("noimage");
    if (img) {
      if (c.image_url) { img.src = c.image_url; img.alt = c.title; img.hidden = false; }
      else { img.removeAttribute("src"); img.hidden = true; }
    }
    if (placeholder) placeholder.hidden = !!c.image_url;
    var title = $("title");
    if (title) title.textContent = c.title;
    setText("arcana", c.arcana || c.card_type);
    setText("suit", c.suit);
    setText("original_title", c.original_title && c.original_title !== c.title ? "traditionally " + c.original_title : "");
    setSection("upright", "upright_interpretation", c.upright_interpretation);
    setSection("reversed", "reversed_interpretation", c.reversed_interpretation);
    setSection("description", "description", c.description);
    var symList = $("symbols");
    var symbols = typeof c.symbols === "string" ? (c.symbols ? [c.symbols] : []) : (c.symbols || []);
    if (symList) {
      symList.textContent = "";
      symbols.forEach(function (s) {
        var li = document.createElement("li");
        li.textContent = typeof s === "string" ? s : JSON.stringify(s);
        symList.appendChild(li);
      });
    }
    var symSection = root.querySelector('[data-section="symbols"]');
    if (symSection) symSection.hidden = !symbols.length;
    var counter = document.querySelector('[data-field="counter"]');
    if (counter) counter.textContent = c.position + " / " + c.total;
    var prev = $("prev"), next = $("next");
    if (prev) prev.href = c.prev_url || c.next_url;
    if (next) next.href = c.next_url;
    root.setAttribute("data-card-slug", c.card_slug);
    root.setAttribute("data-prev-slug", c.prev_card_slug || "");
    root.setAttribute("data-next-slug", c.next_card_slug || "");
    var canonical = document.querySelector('link[rel="canonical"]');
    if (canonical && c.canonical_url) canonical.href = c.canonical_url;
    document.title = c.title + " · " + c.deck_title;
    try { history.replaceState({ slug: c.card_slug }, "", c.url); } catch (e) { /* ignore */ }
  }

  function go(dir) {
    if (busy) return;
    var slug = root.getAttribute(dir > 0 ? "data-next-slug" : "data-prev-slug");
    var link = $(dir > 0 ? "next" : "prev");
    if (!slug) { if (link) window.location.href = link.href; return; }
    busy = true;
    root.classList.remove("slide-next", "slide-prev");
    load(slug).then(function (c) {
      render(c);
      void root.offsetWidth; // restart the CSS animation
      root.classList.add(dir > 0 ? "slide-next" : "slide-prev");
      window.scrollTo({ top: 0, behavior: "smooth" });
      prefetch(c.next_card_slug);
      prefetch(c.prev_card_slug);
    }).catch(function () {
      if (link) window.location.href = link.href;
    }).then(function () { busy = false; });
  }

  // Buttons
  ["prev", "next"].forEach(function (name) {
    var a = $(name);
    if (a) a.addEventListener("click", function (ev) {
      if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.button !== 0) return;
      ev.preventDefault();
      go(name === "next" ? 1 : -1);
    });
  });

  // Keyboard
  document.addEventListener("keydown", function (ev) {
    if (ev.altKey || ev.metaKey || ev.ctrlKey) return;
    var t = ev.target;
    if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
    if (document.querySelector("dialog[open]")) return;
    if (ev.key === "ArrowRight") { ev.preventDefault(); go(1); }
    else if (ev.key === "ArrowLeft") { ev.preventDefault(); go(-1); }
  });

  // Swipe (horizontal only; vertical scrolling stays native)
  var sx = 0, sy = 0, tracking = false;
  root.addEventListener("touchstart", function (ev) {
    if (ev.touches.length !== 1) { tracking = false; return; }
    sx = ev.touches[0].clientX; sy = ev.touches[0].clientY; tracking = true;
  }, { passive: true });
  root.addEventListener("touchend", function (ev) {
    if (!tracking) return;
    tracking = false;
    var t = ev.changedTouches[0];
    var dx = t.clientX - sx, dy = t.clientY - sy;
    if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.5) go(dx < 0 ? 1 : -1);
  }, { passive: true });

  prefetch(root.getAttribute("data-next-slug"));
  prefetch(root.getAttribute("data-prev-slug"));
})();
