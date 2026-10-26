/* "Pick from photo" on the item form: tap the photo where the color looks right; the color
   fields take the average of that spot (transparent pixels of a cutout don't count). */
(function () {
  "use strict";
  var btn = document.getElementById("color-from-photo");
  var img = document.getElementById("form-photo");
  if (!btn || !img) return;
  var hint = document.getElementById("color-pick-hint");
  var RADIUS = 4;  // the spot is (2 * RADIUS + 1) px square in the photo
  var picking = false, px = null;

  function pixels() {
    if (!px && img.complete && img.naturalWidth) {
      var c = document.createElement("canvas");
      c.width = img.naturalWidth; c.height = img.naturalHeight;
      var cx = c.getContext("2d");
      cx.drawImage(img, 0, 0);
      px = cx.getImageData(0, 0, c.width, c.height);
    }
    return px;
  }
  function hex(v) { return ("0" + Math.round(v).toString(16)).slice(-2); }
  function stop() {
    picking = false;
    img.classList.remove("picking");
    btn.textContent = "Pick from photo";
  }

  btn.addEventListener("click", function () {
    if (picking) { stop(); hint.hidden = true; return; }
    picking = true;
    img.classList.add("picking");
    btn.textContent = "Cancel";
    hint.textContent = "Tap the photo where the color looks right.";
    hint.hidden = false;
    img.scrollIntoView({ behavior: "smooth", block: "center" });
  });

  img.addEventListener("click", function (e) {
    if (!picking) return;
    var data = pixels();
    if (!data) return;
    e.preventDefault();
    var r = img.getBoundingClientRect();
    var x = Math.floor((e.clientX - r.left - img.clientLeft) * data.width / img.clientWidth);
    var y = Math.floor((e.clientY - r.top - img.clientTop) * data.height / img.clientHeight);
    var sum = [0, 0, 0], n = 0;
    for (var yy = Math.max(0, y - RADIUS); yy <= Math.min(data.height - 1, y + RADIUS); yy++) {
      for (var xx = Math.max(0, x - RADIUS); xx <= Math.min(data.width - 1, x + RADIUS); xx++) {
        var j = (yy * data.width + xx) * 4;
        if (data.data[j + 3] < 128) continue;
        sum[0] += data.data[j]; sum[1] += data.data[j + 1]; sum[2] += data.data[j + 2]; n++;
      }
    }
    if (!n) { hint.textContent = "That spot is background. Tap the item itself."; return; }
    var value = "#" + sum.map(function (v) { return hex(v / n); }).join("");
    document.getElementById("color_pick").value = value;
    document.getElementById("color_hex").value = value;
    document.getElementById("color_name").value = "";  // named again on save
    stop();
    hint.textContent = "Picked " + value + ". The name is filled in when you save.";
    document.getElementById("color_hex").scrollIntoView({ behavior: "smooth", block: "center" });
  });
})();
