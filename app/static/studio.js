// Studio: put closet items on a 3:4 board, arrange them, and save the board as an outfit.
// The board is a list of {item_id, x, y, w}, back to front: x/y are the top-left corner and w the
// width, as fractions of the board (see app/services/outfits.py). A new outfit's unsaved board is
// kept in this browser (localStorage) so an idea survives leaving the page.
(function () {
  "use strict";
  var data = JSON.parse(document.getElementById("studio-data").textContent);
  var boardEl = document.getElementById("board");
  var tools = document.getElementById("tools");
  var form = document.getElementById("save-form");
  var DRAFT = data.outfit ? null : "forme-studio-draft";
  var DEFAULT_W = 0.45, MIN_W = 0.08, MAX_W = 1.2;

  function info(id) { return data.items[String(id)]; }
  function clamp(v, lo, hi) { return Math.min(Math.max(v, lo), hi); }

  function loadDraft() {
    if (!DRAFT) return [];
    try { return JSON.parse(localStorage.getItem(DRAFT) || "[]"); } catch (e) { return []; }
  }
  function saveDraft() {
    if (!DRAFT) return;
    try { localStorage.setItem(DRAFT, JSON.stringify(state)); } catch (e) { /* private mode */ }
  }

  var start = data.board.length ? data.board : loadDraft();
  var state = (Array.isArray(start) ? start : []).filter(function (p) {
    return p && info(p.item_id);  // items deleted since are dropped
  }).map(function (p) {
    return { item_id: Number(p.item_id), x: Number(p.x) || 0, y: Number(p.y) || 0,
             w: clamp(Number(p.w) || DEFAULT_W, MIN_W, MAX_W) };
  });
  var selected = null;

  function find(id) {
    for (var i = 0; i < state.length; i++) if (state[i].item_id === id) return i;
    return -1;
  }
  function place(el, p) {
    el.style.left = (p.x * 100) + "%";
    el.style.top = (p.y * 100) + "%";
    el.style.width = (p.w * 100) + "%";
  }

  function render() {
    boardEl.querySelectorAll(".placed").forEach(function (el) { el.remove(); });
    state.forEach(function (p, i) {
      var el = document.createElement("div");
      el.className = "placed";
      el.dataset.id = p.item_id;
      el.style.zIndex = i + 1;
      place(el, p);
      var img = document.createElement("img");
      img.src = info(p.item_id).src;
      img.alt = info(p.item_id).name;
      img.draggable = false;
      el.appendChild(img);
      var handle = document.createElement("span");
      handle.className = "resize";
      handle.setAttribute("aria-hidden", "true");
      el.appendChild(handle);
      boardEl.appendChild(el);
    });
    boardEl.classList.toggle("is-empty", state.length === 0);
    document.querySelectorAll(".tray-item").forEach(function (b) {
      b.classList.toggle("on-board", find(Number(b.dataset.id)) >= 0);
    });
    showSelection();
    saveDraft();
  }

  function showSelection() {
    if (selected !== null && find(selected) < 0) selected = null;
    boardEl.querySelectorAll(".placed").forEach(function (el) {
      el.classList.toggle("selected", Number(el.dataset.id) === selected);
    });
    tools.querySelectorAll("button").forEach(function (b) {
      b.disabled = b.dataset.act === "clear" ? state.length === 0 : selected === null;
    });
  }

  function add(id, x, y) {
    var at = find(id);
    if (at >= 0) { selected = id; showSelection(); return; }
    if (state.length >= data.max) { alert("An outfit can have at most " + data.max + " items."); return; }
    var n = state.length;
    state.push({
      item_id: id, w: DEFAULT_W,
      x: x !== undefined ? clamp(x, -0.3, 0.9) : 0.275 + ((n % 3) - 1) * 0.12,
      y: y !== undefined ? clamp(y, -0.3, 0.9) : 0.08 + (n % 4) * 0.1
    });
    selected = id;
    render();
  }

  // ---- moving and resizing on the board (mouse, touch and pen) ----
  boardEl.addEventListener("pointerdown", function (e) {
    var el = e.target.closest(".placed");
    if (!el) { selected = null; showSelection(); return; }
    var id = Number(el.dataset.id), p = state[find(id)];
    selected = id;
    showSelection();
    var rect = boardEl.getBoundingClientRect();
    var resizing = e.target.classList.contains("resize");
    var sx = e.clientX, sy = e.clientY, px = p.x, py = p.y, pw = p.w;
    el.setPointerCapture(e.pointerId);
    e.preventDefault();
    function move(ev) {
      var dx = (ev.clientX - sx) / rect.width, dy = (ev.clientY - sy) / rect.height;
      if (resizing) p.w = clamp(pw + dx, MIN_W, MAX_W);
      else { p.x = clamp(px + dx, -0.5, 1); p.y = clamp(py + dy, -0.5, 1); }
      place(el, p);
    }
    function up() {
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", up);
      saveDraft();
    }
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
  });

  boardEl.addEventListener("keydown", function (e) {
    if (selected === null) return;
    var p = state[find(selected)], step = e.shiftKey ? 0.05 : 0.01;
    var moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    if (moves[e.key]) {
      p.x = clamp(p.x + moves[e.key][0], -0.5, 1);
      p.y = clamp(p.y + moves[e.key][1], -0.5, 1);
      render();
      e.preventDefault();
    } else if (e.key === "Delete" || e.key === "Backspace") {
      act("remove");
      e.preventDefault();
    }
  });

  // ---- toolbar ----
  function act(name) {
    var i = selected === null ? -1 : find(selected);
    if (name === "clear") {
      if (state.length && confirm("Take everything off the board?")) { state = []; selected = null; render(); }
      return;
    }
    if (i < 0) return;
    var p = state[i];
    if (name === "smaller" || name === "bigger") {
      var w = clamp(p.w * (name === "bigger" ? 1.15 : 1 / 1.15), MIN_W, MAX_W);
      p.x += (p.w - w) / 2;  // keep it centred
      p.w = w;
    } else if (name === "front") {
      state.push(state.splice(i, 1)[0]);
    } else if (name === "back") {
      state.unshift(state.splice(i, 1)[0]);
    } else if (name === "remove") {
      state.splice(i, 1);
      selected = null;
    }
    render();
  }
  tools.addEventListener("click", function (e) {
    var b = e.target.closest("button");
    if (b) act(b.dataset.act);
  });

  // ---- the closet tray: tap to add, or drag onto the board (mouse) ----
  var tray = document.getElementById("tray");
  if (tray) {
    tray.addEventListener("click", function (e) {
      var b = e.target.closest(".tray-item");
      if (b) add(Number(b.dataset.id));
    });
    tray.addEventListener("dragstart", function (e) {
      var b = e.target.closest(".tray-item");
      if (b) e.dataTransfer.setData("text/plain", b.dataset.id);
    });
  }
  boardEl.addEventListener("dragover", function (e) { e.preventDefault(); });
  boardEl.addEventListener("drop", function (e) {
    e.preventDefault();
    var id = Number(e.dataTransfer.getData("text/plain"));
    if (!info(id)) return;
    var rect = boardEl.getBoundingClientRect();
    var x = (e.clientX - rect.left) / rect.width - DEFAULT_W / 2;
    var y = (e.clientY - rect.top) / rect.height - 0.15;
    var at = find(id);
    if (at >= 0) { state[at].x = x; state[at].y = y; selected = id; render(); }
    else add(id, x, y);
  });

  function filterTray() {
    var cat = (document.querySelector('input[name="tray-cat"]:checked') || {}).value || "";
    var q = document.getElementById("tray-q").value.trim().toLowerCase();
    document.querySelectorAll("#tray li").forEach(function (li) {
      li.hidden = (cat && li.dataset.cat !== cat) || (q && li.dataset.name.indexOf(q) < 0);
    });
  }
  document.querySelectorAll('input[name="tray-cat"]').forEach(function (r) {
    r.addEventListener("change", filterTray);
  });
  document.getElementById("tray-q").addEventListener("input", filterTray);

  // ---- saving ----
  form.addEventListener("submit", function (e) {
    if (!state.length) {
      e.preventDefault();
      alert("Put at least one item on the board first.");
      return;
    }
    document.getElementById("layout").value = JSON.stringify(state);
    if (DRAFT) { try { localStorage.removeItem(DRAFT); } catch (err) { /* ignore */ } }
  });

  render();
})();
