#!/usr/bin/env python3
"""
dashboard.py - live web dashboard for the PipeGen Action Engine (zero dependencies).

    python dashboard.py                    # reads run/state.json, serves http://localhost:8050
    python dashboard.py --state-dir run --port 8050

Run it next to action_engine.py. On WSL2 just open http://localhost:8050 in your Windows browser.
"""
import argparse
import http.server
import os

HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PipeGen Live</title>
<style>
:root{--bg:#0a0f1e;--panel:#111833;--panel2:#16204a;--text:#e7ebf7;--muted:#8b95b8;--line:#22305a;
--ok:#22c55e;--warn:#f59e0b;--crit:#ef4444;--info:#38bdf8;--nv:#76b900}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,Ubuntu,sans-serif}
header{display:flex;flex-wrap:wrap;align-items:center;gap:20px;padding:16px 22px;border-bottom:1px solid var(--line);
background:linear-gradient(90deg,#0f1838,#0a0f1e)}
.brand{flex:1;min-width:260px}
h1{margin:0;font-size:21px}
.sub{color:var(--muted);font-size:13px;margin-top:2px}
.tag{display:inline-block;margin-top:6px;font-size:11px;font-weight:700;color:var(--nv);border:1px solid rgba(118,185,0,.5);
border-radius:6px;padding:1px 7px}
.stat{text-align:right}
.stat b{display:block;font-size:20px;font-variant-numeric:tabular-nums}
.stat span{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.6px}
.pill{padding:5px 12px;border-radius:999px;font-weight:700;font-size:12px;white-space:nowrap}
.live{background:rgba(34,197,94,.14);color:var(--ok)}
.stale{background:rgba(239,68,68,.14);color:var(--crit)}
main{display:grid;grid-template-columns:repeat(12,1fr);gap:14px;padding:16px 22px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px 16px;min-width:0}
.card h3{margin:0 0 10px;font-size:12px;text-transform:uppercase;letter-spacing:.8px;color:var(--muted)}
.c4{grid-column:span 4}.c8{grid-column:span 8}.c12{grid-column:span 12}
@media(max-width:1000px){.c4,.c8{grid-column:span 12}}
.lvl{font-size:30px;font-weight:800;letter-spacing:.5px}
.lv0 .lvl{color:var(--ok)}.lv2 .lvl{color:var(--warn)}.lv3 .lvl{color:var(--crit)}
.lv2{border-color:var(--warn);background:linear-gradient(180deg,rgba(245,158,11,.18),var(--panel))}
.lv3{border-color:var(--crit);background:linear-gradient(180deg,rgba(239,68,68,.24),var(--panel));animation:pulse 1s infinite alternate}
@keyframes pulse{from{box-shadow:0 0 0 rgba(239,68,68,0)}to{box-shadow:0 0 26px rgba(239,68,68,.5)}}
.kv{display:flex;justify-content:space-between;gap:10px;border-bottom:1px dashed var(--line);padding:5px 0}
.kv span{color:var(--muted)}
.rules{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px}
.rule{background:var(--panel2);border:1px solid var(--line);border-left:4px solid var(--info);border-radius:10px;padding:10px 12px}
.rule.warn{border-left-color:var(--warn)}.rule.crit{border-left-color:var(--crit)}.rule.ok{border-left-color:var(--ok)}
.rhead{display:flex;justify-content:space-between;gap:8px;align-items:center}
.badge{font-size:10px;color:var(--muted);border:1px solid var(--line);border-radius:6px;padding:1px 6px;white-space:nowrap}
.big{font-size:28px;font-weight:800;margin-top:4px;font-variant-numeric:tabular-nums}
.muted{color:var(--muted)}.small{font-size:12px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.chip{background:#1d2a5c;border-radius:999px;padding:2px 9px;font-size:12px}
.lvl-warning{background:rgba(245,158,11,.2);color:var(--warn)}.lvl-critical{background:rgba(239,68,68,.2);color:var(--crit)}
.lvl-normal{background:rgba(34,197,94,.15);color:var(--ok)}
.zone{padding:8px 0;border-bottom:1px solid var(--line)}
.zrow{display:flex;justify-content:space-between;align-items:center}
.num{font-weight:800;font-size:18px}
.slots{display:grid;grid-template-columns:repeat(4,1fr);gap:4px;margin-top:8px}
.slot{text-align:center;border-radius:6px;padding:3px 0;font-size:11px;font-weight:700}
.slot.free{background:rgba(34,197,94,.18);color:var(--ok)}.slot.occ{background:rgba(239,68,68,.2);color:var(--crit)}
#spark rect{fill:var(--warn)}#spark text{fill:var(--muted);font-size:10px}
.feed{max-height:430px;overflow:auto}
.ev{display:grid;grid-template-columns:66px 74px 170px 1fr;gap:10px;padding:7px 9px;border-left:3px solid var(--info);
background:var(--panel2);border-radius:6px;margin-bottom:6px;align-items:baseline}
.ev.warn{border-left-color:var(--warn)}.ev.crit{border-left-color:var(--crit)}.ev.ok{border-left-color:var(--ok)}
.ev .t{color:var(--muted);font-variant-numeric:tabular-nums}
.ev .sev{font-size:11px;text-transform:uppercase;font-weight:700;color:var(--info)}
.ev.crit .sev{color:var(--crit)}.ev.warn .sev{color:var(--warn)}.ev.ok .sev{color:var(--ok)}
.ev .r{color:#c7d2fe;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
@media(max-width:700px){.ev{grid-template-columns:60px 1fr}.ev .sev,.ev .r{display:none}}
footer{color:var(--muted);font-size:12px;padding:4px 22px 18px}
code{background:#1d2a5c;padding:1px 5px;border-radius:4px}
</style></head><body>
<header>
  <div class="brand"><h1 id="title">PipeGen Live</h1><div class="sub" id="subtitle"></div>
    <span class="tag">PERCEPTION: PipeGen &rarr; DeepStream + TensorRT</span></div>
  <div class="stat"><b id="rate">0</b><span>msg / s</span></div>
  <div class="stat"><b id="frames">0</b><span>frames</span></div>
  <div class="stat"><b id="tracks">0</b><span>objects now</span></div>
  <div class="stat"><b id="alerts">0</b><span>alerts</span></div>
  <span id="status" class="pill stale">connecting...</span>
</header>
<main>
  <section class="card c4 lv0" id="act"><h3>Actuator state</h3>
    <div class="lvl" id="actLevel">ALL CLEAR</div><div id="actMsg" class="muted">No active alerts</div>
    <div class="muted small" style="margin-top:8px">What the siren / ESP32 / Telegram is doing right now</div></section>
  <section class="card c4"><h3>Edge performance <span class="small">(PipeGen report)</span></h3><div id="perf"></div></section>
  <section class="card c4"><h3>Alerts per minute &middot; last 30 min</h3>
    <svg id="spark" viewBox="0 0 300 74" preserveAspectRatio="none" style="width:100%;height:96px"></svg>
    <div class="muted small" id="source"></div></section>
  <section class="card c8"><h3>Rules</h3><div class="rules" id="rules"></div></section>
  <section class="card c4"><h3>Zones (live)</h3><div id="zones"></div>
    <h3 style="margin-top:14px">Detected right now</h3><div class="chips" id="classes"></div></section>
  <section class="card c12"><h3>Event feed</h3><div class="feed" id="events"></div></section>
</main>
<footer>PipeGen Action Engine &middot; rules run on every frame of PipeGen's MQTT / JSON output &middot; refreshes every second</footer>
<script>
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const SEV = {critical:"crit", warning:"warn", info:"info", clear:"ok"};
const LABELS = {model:"Model", precision:"Precision", fps:"FPS", latency_ms:"Latency (ms)", power_w:"GPU power (W)", gpu:"GPU", accuracy:"Accuracy (mAP)"};
const chips = o => Object.entries(o || {}).map(([k, v]) => `<span class="chip">${esc(k)} <b>${esc(v)}</b></span>`).join("");

function ruleCard(name, r) {
  let big = r.fired, sub = "alerts", extra = "", cls = SEV[r.severity] || "info";
  if (r.type === "count_threshold" || r.type === "crowd") {
    big = r.count; sub = "now in " + r.zone;
    const th = Object.entries(r.thresholds || {}).map(([k, v]) => esc(k) + " &ge; " + esc(v)).join(", ");
    extra = `<span class="chip lvl-${esc(r.level)}">${esc(r.level)}</span> <span class="muted small">${th}</span>`;
    cls = r.level === "critical" ? "crit" : r.level === "warning" ? "warn" : "ok";
  } else if (r.type === "slot_occupancy") {
    big = `${r.free}/${r.total}`; sub = "free";
    extra = `<div class="slots">${Object.entries(r.slots || {}).map(([k, v]) =>
      `<span class="slot ${v ? "occ" : "free"}">${esc(k)}</span>`).join("")}</div>`;
    cls = r.free === 0 ? "crit" : "ok";
  } else if (r.type === "line_cross") {
    const n = r.names || {L2R: "L2R", R2L: "R2L"};
    big = (r.L2R || 0) + (r.R2L || 0); sub = "crossings"; cls = "info";
    extra = `<span class="muted small">${esc(n.L2R)}: <b>${r.L2R}</b> &middot; ${esc(n.R2L)}: <b>${r.R2L}</b></span>`;
  } else if (r.type === "danger_zone" || r.type === "keypoint_zone") {
    big = r.state; sub = "machine"; cls = r.state === "BLOCKED" ? "crit" : "ok";
    extra = `<span class="muted small">blocks so far: <b>${r.fired}</b></span>`;
  } else if (r.type === "zone_conflict" || r.type === "yield_violation") {
    sub = "violations"; cls = r.fired ? "crit" : "ok";
    extra = `<span class="muted small">protected in ${esc(r.zone)} now: <b>${r.protected_now ?? 0}</b></span>`;
  } else if (r.now !== undefined) {
    extra = `<span class="muted small">in ${esc(r.zone)} now: <b>${r.now}</b></span>`;
  }
  return `<div class="rule ${cls}"><div class="rhead"><b>${esc(name)}</b><span class="badge">${esc(r.type)}</span></div>
    <div class="big">${esc(big)}</div><div class="muted small">${esc(sub)}${r.last ? " &middot; last " + esc(r.last) : ""}</div>
    <div style="margin-top:4px">${extra}</div></div>`;
}

function spark(arr) {
  const max = Math.max(1, ...arr), w = 300 / Math.max(arr.length, 1);
  $("spark").innerHTML = arr.map((v, i) => {
    const h = (v / max) * 62;
    return `<rect x="${i * w + 1}" y="${72 - h}" width="${Math.max(w - 2, 1)}" height="${h}" rx="1.5"></rect>`;
  }).join("") + `<text x="298" y="10" text-anchor="end">peak ${max}/min</text>`;
}

function render(s) {
  if (s.waiting) { $("status").textContent = "waiting for action_engine.py"; $("status").className = "pill stale"; return; }
  $("title").textContent = s.project || "PipeGen Live";
  $("subtitle").textContent = s.subtitle || "";
  document.title = (s.project || "PipeGen") + " - live";
  const age = s.last_message_age_s, live = s.messages > 0 && age !== null && age < 3;
  $("status").textContent = s.messages === 0 ? "waiting for detections" : (live ? "\u25CF LIVE" : `no data for ${Math.round(age)}s`);
  $("status").className = "pill " + (live ? "live" : "stale");
  $("rate").textContent = s.msg_rate; $("frames").textContent = s.frames;
  $("tracks").textContent = s.active_tracks; $("alerts").textContent = s.alerts_total;
  $("source").textContent = "source: " + (s.source || "-");
  const a = s.actuator || {level: 0}, lv = a.level || 0;
  $("act").className = "card c4 lv" + lv;
  $("actLevel").textContent = a.state || "ALL CLEAR";
  $("actMsg").textContent = lv ? a.message : "No active alerts";
  const p = s.perf || {}, keys = Object.keys(p);
  $("perf").innerHTML = keys.length ? keys.map(k => `<div class="kv"><span>${esc(LABELS[k] || k)}</span><b>${esc(p[k])}</b></div>`).join("")
    : '<div class="muted">Add a <code>perf:</code> block to your config with the numbers from PipeGen\'s TensorRT speed report.</div>';
  spark(s.alerts_per_min || []);
  $("rules").innerHTML = Object.entries(s.rules || {}).map(([n, r]) => ruleCard(n, r)).join("") || '<div class="muted">no rules</div>';
  $("zones").innerHTML = Object.entries(s.zones || {}).map(([z, v]) =>
    `<div class="zone"><div class="zrow"><b>${esc(z)}</b><span class="num">${v.count}</span></div><div class="chips">${chips(v.by_class)}</div></div>`
  ).join("") || '<div class="muted">no zones</div>';
  $("classes").innerHTML = chips(s.classes_now) || '<span class="muted">nothing right now</span>';
  $("events").innerHTML = (s.events || []).slice(0, 40).map(e =>
    `<div class="ev ${SEV[e.severity] || ""}"><span class="t">${esc(e.time)}</span><span class="sev">${esc(e.severity)}</span>` +
    `<span class="r">${esc(e.rule)}</span><span class="m">${esc(e.message)}</span></div>`
  ).join("") || '<div class="muted">No events yet - alerts appear here the moment a rule fires.</div>';
}

async function tick() {
  try {
    const r = await fetch("api/state?t=" + Date.now(), {cache: "no-store"});
    render(await r.json());
  } catch (e) {
    $("status").textContent = "dashboard server offline"; $("status").className = "pill stale";
  }
}
tick(); setInterval(tick, 1000);
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser(description="PipeGen Action Engine dashboard")
    ap.add_argument("--state-dir", default="run")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8050)
    args = ap.parse_args()
    state = os.path.join(args.state_dir, "state.json")
    page = HTML.encode("utf-8")

    class Handler(http.server.BaseHTTPRequestHandler):
        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path.endswith("/api/state") or path == "/api/state":
                try:
                    with open(state, "rb") as f:
                        body = f.read()
                except OSError:
                    body = b'{"waiting": true}'
                self._send(200, body, "application/json")
            elif path in ("/", "/index.html"):
                self._send(200, page, "text/html; charset=utf-8")
            else:
                self._send(404, b"not found", "text/plain")

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"dashboard: http://localhost:{args.port}  (reading {state})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
