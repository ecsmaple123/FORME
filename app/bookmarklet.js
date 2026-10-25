(function () {
  var APP = "__APP__";
  var d = document, found = [], seen = {}, title = "", brand = "";
  function add(u) {
    if (!u || typeof u !== "string") { return; }
    try { u = new URL(u.trim(), location.href).href; } catch (e) { return; }
    if (!/^https?:/i.test(u) || seen[u] || u.length > 1500) { return; }
    seen[u] = 1; found.push(u);
  }
  function meta(n) {
    var e = d.querySelector('meta[property="' + n + '"],meta[name="' + n + '"]');
    return e ? (e.getAttribute("content") || "") : "";
  }
  function walk(n) {
    if (Array.isArray(n)) { n.forEach(walk); return; }
    if (!n || typeof n !== "object") { return; }
    var types = [].concat(n["@type"] || []).join(" ").toLowerCase();
    if (types.indexOf("product") >= 0) {
      if (!title && n.name) { title = String(n.name); }
      var b = [].concat(n.brand || [])[0];
      if (!brand && b) { brand = typeof b === "string" ? b : String(b.name || ""); }
      [].concat(n.image || []).forEach(function (i) {
        add(typeof i === "string" ? i : (i && (i.contentUrl || i.url)));
      });
    }
    ["@graph", "mainEntity", "itemListElement", "item", "hasVariant"].forEach(function (k) {
      if (n[k]) { walk(n[k]); }
    });
  }
  add(meta("og:image:secure_url")); add(meta("og:image")); add(meta("twitter:image"));
  [].forEach.call(d.querySelectorAll('script[type*="ld+json"]'), function (s) {
    try { walk(JSON.parse(s.textContent)); } catch (e) { }
  });
  [].slice.call(d.images).filter(function (i) {
    var hint = (i.currentSrc || i.src) + " " + i.className + " " + i.alt;
    return i.naturalWidth >= 200 && i.naturalHeight >= 200 && !/logo|icon|sprite|avatar|badge/i.test(hint);
  }).sort(function (a, b) {
    return b.naturalWidth * b.naturalHeight - a.naturalWidth * a.naturalHeight;
  }).slice(0, 8).forEach(function (i) { add(i.currentSrc || i.src); });
  title = title || meta("og:title") || d.title || "";
  brand = brand || meta("product:brand") || meta("og:brand") || "";
  var q = "url=" + encodeURIComponent(location.href) +
    "&title=" + encodeURIComponent(title.trim().slice(0, 200)) +
    "&brand=" + encodeURIComponent(String(brand).trim().slice(0, 100));
  found.slice(0, 10).forEach(function (u) { q += "&img=" + encodeURIComponent(u); });
  var target = APP + "/add/bookmark?" + q;
  if (!window.open(target, "_blank")) { location.href = target; }
})();
