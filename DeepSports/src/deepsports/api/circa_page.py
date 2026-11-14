"""`GET /circa`: a temporary, self-contained upload page for Circa screenshots on home Wi-Fi (until
BetDesk > Circa is deployed). Inline CSS/JS, no external resources. The upload code is kept in
localStorage and sent only as the X-Circa-Upload-Code header, never in a URL."""

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Circa Upload">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="color-scheme" content="light dark">
<meta name="referrer" content="no-referrer">
<title>Circa Upload</title>
<style>
:root {
  --bg: #f6f6f4; --card: #ffffff; --fg: #1c1c1e; --muted: #6b6b70; --line: #dcdcd8;
  --accent: #1f6feb; --accent-fg: #ffffff; --ok: #1a7f37; --err: #c62828;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #111113; --card: #1c1c1f; --fg: #ececee; --muted: #9a9aa2; --line: #333338;
    --accent: #4c8dff; --accent-fg: #0b0b0c; --ok: #4ac26b; --err: #ff6b6b;
  }
}
* { box-sizing: border-box; }
html, body { margin: 0; background: var(--bg); color: var(--fg); }
body {
  font: 16px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  padding: max(16px, env(safe-area-inset-top)) 16px max(24px, env(safe-area-inset-bottom));
  max-width: 560px; margin: 0 auto;
}
h1 { font-size: 22px; margin: 4px 0 12px; }
.card {
  background: var(--card); border: 1px solid var(--line); border-radius: 12px;
  padding: 14px; margin-bottom: 12px;
}
.muted { color: var(--muted); font-size: 14px; }
label { display: block; font-weight: 600; margin-bottom: 6px; }
input[type=text] {
  width: 100%; font-size: 20px; letter-spacing: 2px; padding: 10px 12px;
  border: 1px solid var(--line); border-radius: 8px; background: var(--bg); color: var(--fg);
}
button {
  width: 100%; font-size: 17px; font-weight: 600; padding: 12px; margin-top: 10px;
  border: 0; border-radius: 10px; background: var(--accent); color: var(--accent-fg);
}
button:disabled { opacity: .45; }
.pick {
  display: block; text-align: center; padding: 18px 12px; border: 2px dashed var(--line);
  border-radius: 10px; font-weight: 600;
}
.pick input { display: none; }
.thumbs { display: grid; grid-template-columns: repeat(auto-fill, minmax(84px, 1fr)); gap: 8px;
  margin-top: 10px; }
.thumbs img { width: 100%; aspect-ratio: 3 / 4; object-fit: cover; border-radius: 6px;
  border: 1px solid var(--line); }
progress { width: 100%; height: 10px; margin-top: 10px; }
.msg { margin-top: 10px; min-height: 1.4em; }
.ok { color: var(--ok); } .err { color: var(--err); }
.hidden { display: none; }
</style>
</head>
<body>
<h1>Circa screenshots</h1>

<div class="card" id="status"><span class="muted">Loading today's status...</span></div>

<div class="card hidden" id="codeCard">
  <label for="code">Upload code</label>
  <input id="code" type="text" inputmode="numeric" autocomplete="off" placeholder="1234 5678">
  <div class="muted">Shown on the Mac with <code>deepsports circa code</code>.
    Saved on this phone.</div>
  <button id="saveCode" type="button">Save code</button>
</div>

<div class="card">
  <label class="pick">Choose screenshots
    <input id="files" type="file" accept="image/*" multiple>
  </label>
  <div class="thumbs" id="thumbs"></div>
  <button id="upload" type="button" disabled>Upload</button>
  <progress id="bar" class="hidden" max="100" value="0"></progress>
  <div class="msg" id="msg"></div>
</div>

<script>
(function () {
  "use strict";
  var KEY = "circaUploadCode";
  var BATCH_BYTES = 50 * 1024 * 1024;  // the server takes up to 60 MB per request
  var $ = function (id) { return document.getElementById(id); };
  var files = [];

  function getCode() { try { return localStorage.getItem(KEY) || ""; } catch (e) { return ""; } }
  function setCode(v) { try { localStorage.setItem(KEY, v); } catch (e) {} }
  function clearCode() { try { localStorage.removeItem(KEY); } catch (e) {} }
  function digits(s) { return (s || "").replace(/[^0-9]/g, ""); }
  function showCode(show) { $("codeCard").classList.toggle("hidden", !show); }
  function say(text, cls) {
    var m = $("msg"); m.textContent = text; m.className = "msg " + (cls || "");
  }

  var memCode = getCode();  // still works for this visit if storage is blocked
  showCode(!memCode);

  $("saveCode").addEventListener("click", function () {
    var d = digits($("code").value);
    if (d.length !== 8) { say("The code has 8 digits.", "err"); return; }
    memCode = d; setCode(d); $("code").value = ""; showCode(false); say("Code saved.", "ok");
  });

  function hhmm(iso) {
    var t = new Date(iso);
    return isNaN(t) ? iso : t.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }
  function loadStatus() {
    fetch("/api/circa/screenshots/today", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (s) {
        var el = $("status"); el.textContent = "";
        var a = document.createElement("div");
        a.textContent = s.count + " screenshot" + (s.count === 1 ? "" : "s") +
          " today (" + s.date + ")" + (s.latest_at ? ", last at " + hhmm(s.latest_at) : "");
        var b = document.createElement("div"); b.className = "muted";
        b.textContent = s.read ? "Read at " + hhmm(s.read.read_at) + ": " + s.read.lines +
          " lines, " + s.read.matched + " matched to games"
          : "Not read yet (the 2 PM picks read them).";
        el.appendChild(a); el.appendChild(b);
      })
      .catch(function () { $("status").textContent = "Status unavailable."; });
  }

  $("files").addEventListener("change", function (ev) {
    files = Array.prototype.slice.call(ev.target.files || []);
    var t = $("thumbs"); t.textContent = "";
    files.forEach(function (f) {
      var img = document.createElement("img");
      img.alt = ""; img.src = URL.createObjectURL(f);
      img.onload = function () { URL.revokeObjectURL(img.src); };
      t.appendChild(img);
    });
    $("upload").disabled = files.length === 0;
    say(files.length ? files.length + " selected" : "");
  });

  function batches(list) {
    var out = [], cur = [], size = 0;
    list.forEach(function (f) {
      if (cur.length && size + f.size > BATCH_BYTES) { out.push(cur); cur = []; size = 0; }
      cur.push(f); size += f.size;
    });
    if (cur.length) out.push(cur);
    return out;
  }

  function send(batch, doneBytes, totalBytes) {
    return new Promise(function (resolve, reject) {
      var fd = new FormData();
      batch.forEach(function (f) { fd.append("file", f, f.name); });
      var x = new XMLHttpRequest();
      x.open("POST", "/api/circa/screenshots");
      if (memCode) x.setRequestHeader("X-Circa-Upload-Code", memCode);
      x.upload.onprogress = function (e) {
        if (e.lengthComputable) $("bar").value = 100 * (doneBytes + e.loaded) / totalBytes;
      };
      x.onload = function () {
        var body = {}; try { body = JSON.parse(x.responseText); } catch (e) {}
        if (x.status === 200) resolve(body);
        else reject({ status: x.status, body: body });
      };
      x.onerror = function () { reject({ status: 0, body: {} }); };
      x.send(fd);
    });
  }

  $("upload").addEventListener("click", function () {
    if (!files.length) return;
    var list = batches(files), total = 0, done = 0, saved = 0;
    files.forEach(function (f) { total += f.size; });
    $("upload").disabled = true; $("bar").classList.remove("hidden"); $("bar").value = 0;
    say("Uploading...");
    var chain = Promise.resolve();
    list.forEach(function (b) {
      chain = chain.then(function () {
        return send(b, done, total).then(function (r) {
          b.forEach(function (f) { done += f.size; });
          saved += (r.saved || []).length;
        });
      });
    });
    chain.then(function () {
      say("Uploaded " + saved + ". Thanks!", "ok");
      files = []; $("files").value = ""; $("thumbs").textContent = "";
    }).catch(function (e) {
      if (e.status === 403) {
        memCode = ""; clearCode(); showCode(true);
        say("Wrong or missing upload code.", "err");
      } else {
        var d = e.body && (e.body.detail || e.body.error);
        say((saved ? "Uploaded " + saved + ", then: " : "") +
          (d || (e.status ? "Upload failed (" + e.status + ")" : "Can't reach the Mac")), "err");
      }
      $("upload").disabled = files.length === 0;
    }).then(function () { $("bar").classList.add("hidden"); loadStatus(); });
  });

  loadStatus();
})();
</script>
</body>
</html>
"""
