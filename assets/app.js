/* RSS SietekMalut — katalog feed statis.
   Tidak ada dependensi, tidak ada backend: halaman ini hanya membaca
   feeds/index.json dan feeds/*.xml yang dihasilkan GitHub Actions. */

(function () {
  "use strict";

  var REPO = "SietekMalut/sietekmalut.github.io";
  var BRANCH = "main";
  var FALLBACK_SITE = "https://sietekmalut.github.io";

  var state = { feeds: [], filter: "", site: FALLBACK_SITE };
  var previewCache = new Map();

  var el = {
    grid: document.getElementById("feedGrid"),
    empty: document.getElementById("emptyState"),
    notice: document.getElementById("catalogNotice"),
    search: document.getElementById("search"),
    statFeeds: document.getElementById("statFeeds"),
    statItems: document.getElementById("statItems"),
    statUpdated: document.getElementById("statUpdated"),
    toast: document.getElementById("toast"),
    form: document.getElementById("builderForm"),
    result: document.getElementById("builderResult"),
    resultSlug: document.getElementById("resultSlug"),
    resultUrl: document.getElementById("resultUrlPreview"),
    resultJson: document.getElementById("resultJson"),
    publish: document.getElementById("publishLink"),
    copyRequest: document.getElementById("copyRequest"),
    theme: document.getElementById("themeToggle")
  };

  /* ------------------------------------------------------------------ */
  /* helpers                                                            */
  /* ------------------------------------------------------------------ */

  function slugify(value) {
    return String(value || "")
      .trim()
      .toLowerCase()
      .replace(/^https?:\/\//, "")
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/-{2,}/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60) || "feed";
  }

  function fmtDate(value) {
    if (!value) return "—";
    var date = new Date(value);
    if (isNaN(date.getTime())) return "—";
    return new Intl.DateTimeFormat("id-ID", {
      day: "numeric", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit"
    }).format(date);
  }

  function fmtRelative(value) {
    if (!value) return "";
    var date = new Date(value);
    if (isNaN(date.getTime())) return "";
    var diff = (date.getTime() - Date.now()) / 1000;
    var abs = Math.abs(diff);
    var units = [
      ["year", 31536000], ["month", 2592000], ["week", 604800],
      ["day", 86400], ["hour", 3600], ["minute", 60]
    ];
    for (var i = 0; i < units.length; i++) {
      if (abs >= units[i][1]) {
        return new Intl.RelativeTimeFormat("id-ID", { numeric: "auto" })
          .format(Math.round(diff / units[i][1]), units[i][0]);
      }
    }
    return "baru saja";
  }

  var toastTimer = null;
  function toast(message) {
    el.toast.textContent = message;
    el.toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.toast.classList.remove("show"); }, 2200);
  }

  function copyText(text, doneLabel) {
    var done = function () { toast(doneLabel || "Disalin ke papan klip"); };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done).catch(function () { fallbackCopy(text, done); });
    } else {
      fallbackCopy(text, done);
    }
  }

  function fallbackCopy(text, done) {
    var area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    try { document.execCommand("copy"); done(); }
    catch (err) { toast("Gagal menyalin — salin manual dari kotak URL"); }
    document.body.removeChild(area);
  }

  function node(tag, className, text) {
    var element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  /* ------------------------------------------------------------------ */
  /* theme                                                              */
  /* ------------------------------------------------------------------ */

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem("rss-theme", theme); } catch (err) { /* private mode */ }
    el.theme.setAttribute("aria-label", theme === "dark" ? "Ganti ke tema terang" : "Ganti ke tema gelap");
  }

  function initTheme() {
    var saved = null;
    try { saved = localStorage.getItem("rss-theme"); } catch (err) { /* ignore */ }
    var prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    applyTheme(saved || (prefersDark ? "dark" : "light"));
    el.theme.addEventListener("click", function () {
      applyTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark");
    });
  }

  /* ------------------------------------------------------------------ */
  /* catalog                                                            */
  /* ------------------------------------------------------------------ */

  function loadCatalog() {
    // Pakai kunci cache per menit supaya isi baru tetap muncul tanpa
    // membebani GitHub Pages pada setiap muat halaman.
    var bucket = Math.floor(Date.now() / 60000);
    return fetch("feeds/index.json?v=" + bucket, { cache: "no-cache" })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(function (data) {
        state.site = (data.site || FALLBACK_SITE).replace(/\/$/, "");
        state.feeds = Array.isArray(data.feeds) ? data.feeds : [];
        renderCatalog(data);
      })
      .catch(function (error) {
        el.grid.innerHTML = "";
        el.notice.hidden = false;
        el.notice.textContent =
          "Katalog belum bisa dimuat (" + error.message + "). Jika Anda membuka file ini langsung dari disk, " +
          "jalankan server lokal: python -m http.server 8000 — lalu buka http://localhost:8000/";
        el.statFeeds.textContent = "0";
        el.statItems.textContent = "0";
        el.statUpdated.textContent = "—";
      });
  }

  function renderCatalog(data) {
    var totalItems = state.feeds.reduce(function (sum, feed) {
      return sum + (Number(feed.items) || 0);
    }, 0);

    el.statFeeds.textContent = String(state.feeds.length);
    el.statItems.textContent = totalItems.toLocaleString("id-ID");
    el.statUpdated.textContent = data.generated ? fmtRelative(data.generated) : "—";

    renderGrid();

    if (!state.feeds.length) {
      el.notice.hidden = false;
      el.notice.textContent =
        "Belum ada feed. Buka bagian “Buat feed” untuk menambahkan sumber pertama.";
    }
  }

  function matches(feed) {
    if (!state.filter) return true;
    var haystack = [feed.name, feed.title, feed.description, feed.source_url, feed.slug]
      .join(" ").toLowerCase();
    return haystack.indexOf(state.filter) !== -1;
  }

  function renderGrid() {
    var visible = state.feeds.filter(matches);
    el.grid.innerHTML = "";

    visible.forEach(function (feed) {
      el.grid.appendChild(buildCard(feed));
    });

    el.empty.hidden = visible.length !== 0 || state.feeds.length === 0;
  }

  function buildCard(feed) {
    var card = node("article", "feed-card");
    card.dataset.stale = feed.stale ? "true" : "false";
    card.dataset.search = [feed.name, feed.title, feed.source_url].join(" ").toLowerCase();

    var head = node("div", "feed-card-head");
    head.appendChild(node("h3", null, feed.name || feed.slug));

    var badge;
    if (feed.stale) {
      badge = node("span", "badge badge-warn", "tertahan");
      badge.title = feed.error || "Sumber sedang tidak bisa diakses; file lama dipertahankan.";
    } else if (feed.status === "error") {
      badge = node("span", "badge badge-warn", "gagal");
      badge.title = feed.error || "";
    } else {
      badge = node("span", "badge badge-ok", feed.mode === "native" || feed.mode === "feed" ? "rss asli" : "html");
      badge.title = feed.mode === "native" || feed.mode === "feed"
        ? "Sumber sudah menyediakan RSS/Atom; isinya dinormalkan."
        : "Item dibaca langsung dari HTML halaman.";
    }
    head.appendChild(badge);
    card.appendChild(head);

    if (feed.title && feed.title !== feed.name) {
      card.appendChild(node("p", "feed-title", feed.title));
    }

    var meta = node("p", "feed-meta");
    meta.appendChild(node("span", null, (feed.items || 0) + " item"));
    meta.appendChild(node("span", null, "diperbarui " + fmtRelative(feed.updated)));
    if (feed.latest) {
      meta.appendChild(node("span", null, "terbaru " + fmtRelative(feed.latest)));
    }
    card.appendChild(meta);

    var urlRow = node("div", "url-row");
    var code = node("code", null, feed.xml_url);
    code.title = feed.xml_url;
    var copy = node("button", "copy-btn", "Salin");
    copy.type = "button";
    copy.addEventListener("click", function () {
      copyText(feed.xml_url, "Link XML disalin");
      copy.classList.add("done");
      copy.textContent = "Tersalin";
      setTimeout(function () { copy.classList.remove("done"); copy.textContent = "Salin"; }, 1800);
    });
    urlRow.appendChild(code);
    urlRow.appendChild(copy);
    card.appendChild(urlRow);

    var actions = node("div", "card-actions");
    var open = node("a", "btn btn-sm", "Buka XML");
    open.href = feed.xml_url;
    open.target = "_blank";
    open.rel = "noopener";
    actions.appendChild(open);

    var previewBtn = node("button", "btn btn-sm", "Pratinjau");
    previewBtn.type = "button";
    previewBtn.setAttribute("aria-expanded", "false");
    actions.appendChild(previewBtn);

    var jsonUrl = feed.json_url || feed.xml_url.replace(/\.xml$/, ".json");
    var jsonLink = node("a", "link-quiet", "JSON");
    jsonLink.href = jsonUrl;
    jsonLink.target = "_blank";
    jsonLink.rel = "noopener";
    jsonLink.title = "Versi JSON Feed 1.1 — lebih mudah dipakai untuk scraping";
    actions.appendChild(jsonLink);

    if (feed.site_url) {
      var visit = node("a", "link-quiet", "Kunjungi situs ↗");
      visit.href = feed.site_url;
      visit.target = "_blank";
      visit.rel = "noopener";
      actions.appendChild(visit);
    }
    card.appendChild(actions);

    var preview = node("div", "preview");
    preview.hidden = true;
    card.appendChild(preview);

    previewBtn.addEventListener("click", function () {
      var expanded = previewBtn.getAttribute("aria-expanded") === "true";
      if (expanded) {
        previewBtn.setAttribute("aria-expanded", "false");
        previewBtn.textContent = "Pratinjau";
        preview.hidden = true;
        return;
      }
      previewBtn.setAttribute("aria-expanded", "true");
      previewBtn.textContent = "Tutup";
      preview.hidden = false;
      loadPreview(feed, preview);
    });

    return card;
  }

  function loadPreview(feed, target) {
    if (previewCache.has(feed.slug)) {
      paintPreview(target, previewCache.get(feed.slug));
      return;
    }
    target.textContent = "Memuat pratinjau…";
    fetch(feed.xml_url, { cache: "no-cache" })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.text();
      })
      .then(function (xml) {
        var doc = new DOMParser().parseFromString(xml, "application/xml");
        if (doc.querySelector("parsererror")) throw new Error("XML tidak valid");
        var entries = Array.prototype.slice.call(doc.querySelectorAll("item")).slice(0, 5)
          .map(function (item) {
            var pick = function (tag) {
              var found = item.querySelector(tag);
              return found ? found.textContent.trim() : "";
            };
            return { title: pick("title"), link: pick("link"), date: pick("pubDate") };
          });
        previewCache.set(feed.slug, entries);
        paintPreview(target, entries);
      })
      .catch(function (error) {
        target.textContent = "Pratinjau gagal dimuat: " + error.message;
      });
  }

  function paintPreview(target, entries) {
    target.innerHTML = "";
    if (!entries.length) {
      target.textContent = "Feed ini belum berisi item.";
      return;
    }
    var list = node("ol");
    entries.forEach(function (entry) {
      var item = node("li");
      var link = node("a", null, entry.title);
      link.href = entry.link;
      link.target = "_blank";
      link.rel = "noopener";
      item.appendChild(link);
      if (entry.date) item.appendChild(node("time", null, fmtDate(entry.date)));
      list.appendChild(item);
    });
    target.appendChild(list);
  }

  /* ------------------------------------------------------------------ */
  /* builder                                                            */
  /* ------------------------------------------------------------------ */

  function buildRequest(form) {
    var url = form.url.value.trim();
    if (!url) { toast("Alamat halaman masih kosong"); form.url.focus(); return; }
    if (!/^https?:\/\//i.test(url)) url = "https://" + url;
    var parsed;
    try { parsed = new URL(url); }
    catch (err) { toast("Alamat tidak valid"); form.url.focus(); return; }
    if (!/^https?:$/.test(parsed.protocol) || !parsed.hostname.includes(".")) {
      toast("Gunakan alamat http(s) yang lengkap");
      form.url.focus();
      return;
    }

    var name = form.name.value.trim() || parsed.hostname.replace(/^www\./, "");
    var limit = Math.min(100, Math.max(5, parseInt(form.limit.value, 10) || 30));
    var mode = form.mode.value || "auto";
    var slug = slugify(name);

    var payload = { name: name, url: url, limit: limit };
    if (mode !== "auto") payload.mode = mode;
    var json = JSON.stringify(payload, null, 2) + "\n";

    var xmlUrl = state.site + "/feeds/" + slug + ".xml";
    var github =
      "https://github.com/" + REPO + "/new/" + BRANCH +
      "?filename=" + encodeURIComponent("requests/" + slug + ".json") +
      "&value=" + encodeURIComponent(json) +
      "&message=" + encodeURIComponent("feat(feed): tambah " + name);

    el.resultSlug.textContent = slug;
    el.resultUrl.textContent = xmlUrl;
    el.resultUrl.title = xmlUrl;
    el.resultJson.textContent = json;
    el.publish.href = github;
    el.result.hidden = false;
    el.result.scrollIntoView({ block: "nearest", behavior: "smooth" });
    el.publish.focus({ preventScroll: true });
  }

  function initBuilder() {
    el.form.addEventListener("submit", function (event) {
      event.preventDefault();
      buildRequest(el.form);
    });

    el.copyRequest.addEventListener("click", function () {
      copyText(el.resultJson.textContent, "JSON permintaan disalin");
    });

    // Dukungan tautan cepat: index.html?url=https://contoh.com
    var params = new URLSearchParams(window.location.search);
    var url = params.get("url");
    var name = params.get("name");
    if (url) {
      el.form.url.value = url;
      if (name) el.form.name.value = name;
      window.requestAnimationFrame(function () {
        document.getElementById("buat").scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }
  }

  /* ------------------------------------------------------------------ */
  /* boot                                                               */
  /* ------------------------------------------------------------------ */

  function init() {
    initTheme();
    initBuilder();
    loadCatalog();

    el.search.addEventListener("input", function () {
      state.filter = el.search.value.trim().toLowerCase();
      renderGrid();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
