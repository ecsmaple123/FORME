/* Touch up a cutout: erase leftover background, restore missing parts, correct the lighting.
   Works on the photo with its background (display size) and its mask (white = item); Save sends
   the mask as a PNG plus the white-balance gains, and the server rebuilds the cutout. */
(function () {
  "use strict";
  var data = JSON.parse(document.getElementById("touchup-data").textContent);
  var stage = document.getElementById("tu-stage");
  var canvas = document.getElementById("tu-canvas");
  var ctx = canvas.getContext("2d");
  var hint = document.getElementById("tu-hint");
  var errorBox = document.getElementById("tu-error");
  var sizeInput = document.getElementById("tu-size");
  var tolInput = document.getElementById("tu-tol");
  var showInput = document.getElementById("tu-show");
  var undoBtn = document.getElementById("tu-undo");
  var saveBtn = document.getElementById("tu-save");
  var lightReset = document.getElementById("tu-light-reset");

  var HINTS = {
    area: "Tap a leftover patch of background to erase it. Lower “How similar” if it takes too much.",
    erase: "Paint over what should go.",
    restore: "Paint over parts of the item that were cut away.",
    light: "Tap something that should be white or grey (paper, a white floor) to correct the lighting.",
    move: "Drag to move around the zoomed photo."
  };
  var ZOOMS = [1, 1.5, 2, 3, 4];
  var UNDO_MAX = 15;
  var SHOW_REMOVED = 0.3;  // how visible removed parts are with "Show removed parts"

  var W = 0, H = 0, base = null, mask = null, view = null;
  var gains = parseGains(data.wb);
  var tool = "area", zoom = 0, undo = [], changed = false, stroke = null;

  function parseGains(text) {
    var g = (text || "").split(",").map(Number);
    return g.length === 3 && g.every(function (v) { return v >= 0.5 && v <= 2; }) ? g : [1, 1, 1];
  }
  function gainsText() {
    if (gains.every(function (g) { return Math.abs(g - 1) < 0.005; })) return "";
    return gains.map(function (g) { return g.toFixed(3); }).join(",");
  }
  function loadImage(src) {
    return new Promise(function (resolve, reject) {
      var im = new Image();
      im.onload = function () { resolve(im); };
      im.onerror = function () { reject(new Error("couldn't load " + src)); };
      im.src = src;
    });
  }
  function pixels(im) {
    var c = document.createElement("canvas");
    c.width = W; c.height = H;
    var cx = c.getContext("2d");
    cx.drawImage(im, 0, 0, W, H);
    return cx.getImageData(0, 0, W, H).data;
  }
  function showError(text) {
    errorBox.textContent = text;
    errorBox.hidden = !text;
  }

  // ---------- drawing ----------
  function render(x0, y0, x1, y1) {
    x0 = Math.max(0, Math.floor(x0)); y0 = Math.max(0, Math.floor(y0));
    x1 = Math.min(W, Math.ceil(x1)); y1 = Math.min(H, Math.ceil(y1));
    if (x1 <= x0 || y1 <= y0) return;
    var out = view.data, show = showInput.checked, gr = gains[0], gg = gains[1], gb = gains[2];
    for (var y = y0; y < y1; y++) {
      for (var x = x0, i = y * W + x0; x < x1; x++, i++) {
        var j = i * 4, a = mask[i];
        out[j] = base[j] * gr; out[j + 1] = base[j + 1] * gg; out[j + 2] = base[j + 2] * gb;
        out[j + 3] = show ? a + (255 - a) * SHOW_REMOVED : a;
      }
    }
    ctx.putImageData(view, 0, 0, x0, y0, x1 - x0, y1 - y0);
  }
  function renderAll() { render(0, 0, W, H); }

  function fit() {
    var avail = stage.clientWidth;
    var maxH = Math.max(240, window.innerHeight * 0.68);
    var scale = Math.min(avail / W, maxH / H) * ZOOMS[zoom];
    canvas.style.width = Math.round(W * scale) + "px";
    canvas.style.height = Math.round(H * scale) + "px";
    document.getElementById("tu-out").disabled = zoom === 0;
    document.getElementById("tu-in").disabled = zoom === ZOOMS.length - 1;
  }
  function setZoom(next) {
    var cx = (stage.scrollLeft + stage.clientWidth / 2) / canvas.clientWidth;
    var cy = (stage.scrollTop + stage.clientHeight / 2) / canvas.clientHeight;
    zoom = Math.max(0, Math.min(ZOOMS.length - 1, next));
    fit();
    stage.scrollLeft = cx * canvas.clientWidth - stage.clientWidth / 2;
    stage.scrollTop = cy * canvas.clientHeight - stage.clientHeight / 2;
  }

  // ---------- undo ----------
  function remember(withMask) {
    undo.push({ mask: withMask ? mask.slice() : null, gains: gains.slice() });
    if (undo.length > UNDO_MAX) undo.shift();
    undoBtn.disabled = false;
  }
  function touched() {
    changed = true;
    saveBtn.disabled = false;
    lightReset.hidden = gainsText() === "";
  }
  undoBtn.addEventListener("click", function () {
    var last = undo.pop();
    if (!last) return;
    if (last.mask) mask = last.mask;
    gains = last.gains;
    undoBtn.disabled = undo.length === 0;
    touched();
    renderAll();
  });

  // ---------- tools ----------
  function colorAt(x, y, radius) {  // average displayed color around a point
    var sum = [0, 0, 0], n = 0;
    for (var yy = Math.max(0, y - radius); yy <= Math.min(H - 1, y + radius); yy++) {
      for (var xx = Math.max(0, x - radius); xx <= Math.min(W - 1, x + radius); xx++) {
        var j = (yy * W + xx) * 4;
        sum[0] += base[j]; sum[1] += base[j + 1]; sum[2] += base[j + 2]; n++;
      }
    }
    return sum.map(function (v) { return v / n; });
  }

  function eraseArea(sx, sy) {
    var seed = sy * W + sx;
    if (mask[seed] < 128) { hint.textContent = "That spot is already removed."; return; }
    var c = colorAt(sx, sy, 2).map(function (v, k) { return v * gains[k]; });
    var tol = Number(tolInput.value);
    var tol2 = tol * tol, step2 = tol * tol / 4, far2 = tol * tol * 6.25;
    function toSeed(i) {
      var j = i * 4, dr = base[j] * gains[0] - c[0], dg = base[j + 1] * gains[1] - c[1], db = base[j + 2] * gains[2] - c[2];
      return dr * dr + dg * dg + db * db;
    }
    function step(a, b) {
      var ja = a * 4, jb = b * 4, dr = (base[ja] - base[jb]) * gains[0],
          dg = (base[ja + 1] - base[jb + 1]) * gains[1], db = (base[ja + 2] - base[jb + 2]) * gains[2];
      return dr * dr + dg * dg + db * db;
    }
    // A pixel joins if it's close to the tapped color, or close to the neighbor it's reached from
    // and not too far from the tapped color (creases, shine and shadows in the background).
    var hitMap = new Uint8Array(W * H), stack = [seed];
    var minX = sx, maxX = sx, minY = sy, maxY = sy;
    hitMap[seed] = 1;
    function visit(from, n) {
      if (hitMap[n] || mask[n] === 0) return;
      var d = toSeed(n);
      if (d <= tol2 || (d <= far2 && step(from, n) <= step2)) { hitMap[n] = 1; stack.push(n); }
    }
    while (stack.length) {
      var i = stack.pop(), x = i % W, y = (i - x) / W;
      if (x < minX) minX = x; if (x > maxX) maxX = x;
      if (y < minY) minY = y; if (y > maxY) maxY = y;
      if (x > 0) visit(i, i - 1);
      if (x < W - 1) visit(i, i + 1);
      if (y > 0) visit(i, i - W);
      if (y < H - 1) visit(i, i + W);
    }
    // Specks the erased area almost surrounds go too (bright creases, bits of shine).
    var x0 = Math.max(0, minX - 3), x1 = Math.min(W - 1, maxX + 3);
    var y0 = Math.max(0, minY - 3), y1 = Math.min(H - 1, maxY + 3);
    for (var pass = 0; pass < 2; pass++) {
      var add = [];
      for (var yy = y0 + 2; yy <= y1 - 2; yy++) {
        for (var xx = x0 + 2; xx <= x1 - 2; xx++) {
          var p = yy * W + xx;
          if (hitMap[p] || mask[p] === 0) continue;
          var around = 0;
          for (var oy = -2; oy <= 2; oy++) for (var ox = -2; ox <= 2; ox++) around += hitMap[p + oy * W + ox];
          if (around >= 15 && toSeed(p) <= far2) add.push(p);
        }
      }
      for (var a = 0; a < add.length; a++) hitMap[add[a]] = 1;
    }
    remember(true);
    for (var k = y0 * W; k <= y1 * W + x1; k++) if (hitMap[k]) mask[k] = 0;
    touched();
    render(x0, y0, x1 + 1, y1 + 1);
    hint.textContent = HINTS.area;
  }

  function dab(x, y, value, r) {
    var r2 = r * r;
    for (var yy = Math.max(0, Math.floor(y - r)); yy <= Math.min(H - 1, Math.ceil(y + r)); yy++) {
      for (var xx = Math.max(0, Math.floor(x - r)); xx <= Math.min(W - 1, Math.ceil(x + r)); xx++) {
        var dx = xx - x, dy = yy - y;
        if (dx * dx + dy * dy <= r2) mask[yy * W + xx] = value;
      }
    }
  }
  function paintTo(x, y) {
    var value = tool === "erase" ? 0 : 255, r = stroke.r;
    var dx = x - stroke.x, dy = y - stroke.y, dist = Math.sqrt(dx * dx + dy * dy);
    var steps = Math.max(1, Math.ceil(dist / (r / 2)));
    for (var s = 1; s <= steps; s++) dab(stroke.x + dx * s / steps, stroke.y + dy * s / steps, value, r);
    render(Math.min(x, stroke.x) - r - 1, Math.min(y, stroke.y) - r - 1,
           Math.max(x, stroke.x) + r + 2, Math.max(y, stroke.y) + r + 2);
    stroke.x = x; stroke.y = y;
  }

  function setLighting(x, y) {
    var c = colorAt(x, y, 4);
    if (Math.min(c[0], c[1], c[2]) < 25) {
      hint.textContent = "That spot is too dark. Tap something white or light grey.";
      return;
    }
    var mean = (c[0] + c[1] + c[2]) / 3;
    remember(false);
    gains = c.map(function (v) { return Math.max(0.5, Math.min(2, mean / v)); });
    touched();
    renderAll();
    hint.textContent = "Lighting corrected. Tap another spot to try again, or Undo.";
  }
  lightReset.addEventListener("click", function () {
    remember(false);
    gains = [1, 1, 1];
    touched();
    renderAll();
  });

  // ---------- pointer ----------
  function point(e) {
    var rect = canvas.getBoundingClientRect();
    return {
      x: Math.min(W - 1, Math.max(0, Math.floor((e.clientX - rect.left) * W / rect.width))),
      y: Math.min(H - 1, Math.max(0, Math.floor((e.clientY - rect.top) * H / rect.height))),
      perPx: W / rect.width
    };
  }
  canvas.addEventListener("pointerdown", function (e) {
    if (!mask || tool === "move" || (e.pointerType === "mouse" && e.button !== 0)) return;
    e.preventDefault();
    var p = point(e);
    if (tool === "erase" || tool === "restore") {
      canvas.setPointerCapture(e.pointerId);
      remember(true);
      stroke = { x: p.x, y: p.y, r: Number(sizeInput.value) / 2 * p.perPx, id: e.pointerId };
      paintTo(p.x, p.y);
      touched();
    } else {
      stroke = { x: p.x, y: p.y, sx: e.clientX, sy: e.clientY, id: e.pointerId, tap: true };
    }
  });
  canvas.addEventListener("pointermove", function (e) {
    if (!stroke || e.pointerId !== stroke.id) return;
    if (stroke.tap) {
      if (Math.abs(e.clientX - stroke.sx) + Math.abs(e.clientY - stroke.sy) > 10) stroke = null;
      return;
    }
    var p = point(e);
    paintTo(p.x, p.y);
  });
  function end(e) {
    if (!stroke || e.pointerId !== stroke.id) return;
    var s = stroke;
    stroke = null;
    if (!s.tap || e.type === "pointercancel") return;
    if (tool === "area") eraseArea(s.x, s.y);
    else if (tool === "light") setLighting(s.x, s.y);
  }
  canvas.addEventListener("pointerup", end);
  canvas.addEventListener("pointercancel", end);

  function setTool(next) {
    tool = next;
    hint.textContent = HINTS[tool];
    document.getElementById("tu-size-row").hidden = !(tool === "erase" || tool === "restore");
    document.getElementById("tu-tol-row").hidden = tool !== "area";
    canvas.style.touchAction = tool === "move" ? "auto" : "none";
    canvas.classList.toggle("is-moving", tool === "move");
    if (tool === "restore" && !showInput.checked) { showInput.checked = true; if (mask) renderAll(); }
  }
  document.querySelectorAll('input[name="tu-tool"]').forEach(function (r) {
    r.addEventListener("change", function () { if (r.checked) setTool(r.value); });
  });
  showInput.addEventListener("change", function () { if (mask) renderAll(); });
  document.getElementById("tu-in").addEventListener("click", function () { setZoom(zoom + 1); });
  document.getElementById("tu-out").addEventListener("click", function () { setZoom(zoom - 1); });
  window.addEventListener("resize", function () { if (mask) fit(); });

  // ---------- save ----------
  saveBtn.addEventListener("click", function () {
    showError("");
    saveBtn.disabled = true;
    saveBtn.textContent = "Saving…";
    var c = document.createElement("canvas");
    c.width = W; c.height = H;
    var cx = c.getContext("2d"), img = cx.createImageData(W, H), d = img.data;
    for (var i = 0, j = 0; i < mask.length; i++, j += 4) {
      d[j] = d[j + 1] = d[j + 2] = mask[i]; d[j + 3] = 255;
    }
    cx.putImageData(img, 0, 0);
    c.toBlob(function (blob) {
      var form = new FormData();
      form.append("mask", blob, "mask.png");
      form.append("white_balance", gainsText());
      fetch(data.save, { method: "POST", body: form, credentials: "same-origin" })
        .then(function (r) { return r.json().catch(function () { return { error: "Saving failed (" + r.status + ")." }; }); })
        .then(function (res) {
          if (res.url) { changed = false; window.location.href = res.url; return; }
          throw new Error(res.error || "Saving failed.");
        })
        .catch(function (err) {
          showError(err.message || "Saving failed. Check the connection and try again.");
          saveBtn.disabled = false;
          saveBtn.textContent = "Save";
        });
    }, "image/png");
  });
  window.addEventListener("beforeunload", function (e) {
    if (changed) { e.preventDefault(); e.returnValue = ""; }
  });

  // ---------- start ----------
  setTool("area");
  Promise.all([loadImage(data.base), loadImage(data.mask)]).then(function (ims) {
    W = ims[0].naturalWidth; H = ims[0].naturalHeight;
    canvas.width = W; canvas.height = H;
    base = pixels(ims[0]);
    var m = pixels(ims[1]);
    mask = new Uint8Array(W * H);
    for (var i = 0; i < mask.length; i++) mask[i] = m[i * 4];
    view = ctx.createImageData(W, H);
    document.getElementById("tu-loading").hidden = true;
    lightReset.hidden = gainsText() === "";
    fit();
    renderAll();
  }).catch(function () {
    showError("The photo couldn't be loaded. Reload the page to try again.");
  });
})();
