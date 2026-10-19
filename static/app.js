"use strict";
const $ = (id) => document.getElementById(id);
const C = { ref: "#4f8bff", usr: "#ff5d73", ok: "#2ed47a", warn: "#ffb020", late: "#a66bff", grid: "#2b3160", sub: "#9aa3d9" };
let levels = [], level = null, refData = null, result = null, userBlobUrl = null;
const refAudio = new Audio(), userAudio = new Audio();
const hz2c = (f) => (f && f > 0 ? 1200 * Math.log2(f / 440) : null);

// ---------- canvas helpers ----------
function ctx2d(cv) {
  const dpr = window.devicePixelRatio || 1, w = cv.clientWidth, h = cv.height / (cv._dpr || 1);
  cv._dpr = dpr; cv._h = cv._h || h;
  cv.width = w * dpr; cv.height = cv._h * dpr;
  const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, cv._h); return [g, w, cv._h];
}
function drawEnv(g, env, x0, x1, yMid, amp, color, alpha = 1, xmap = null) {
  const n = env.max.length; g.globalAlpha = alpha; g.fillStyle = color; g.beginPath();
  const X = (i) => { const t = (i / n) * env.dur; return xmap ? xmap(t) : x0 + (t / env.dur) * (x1 - x0); };
  for (let i = 0; i < n; i++) g.lineTo(X(i), yMid - env.max[i] * amp);
  for (let i = n - 1; i >= 0; i--) g.lineTo(X(i), yMid - env.min[i] * amp);
  g.fill(); g.globalAlpha = 1;
}
function drawLine(g, pts, X, Y, color, w = 2) {
  g.strokeStyle = color; g.lineWidth = w; g.beginPath(); let pen = false;
  for (const [t, v] of pts) { if (v == null) { pen = false; continue; } pen ? g.lineTo(X(t), Y(v)) : g.moveTo(X(t), Y(v)); pen = true; }
  g.stroke();
}
function centsRange(...lists) {
  const v = lists.flat().map((p) => p[1]).filter((x) => x != null);
  if (!v.length) return [-1200, 0];
  const lo = Math.min(...v), hi = Math.max(...v), pad = Math.max(150, (hi - lo) * 0.15);
  return [lo - pad, hi + pad];
}
function playhead(g, x, h, color = "#fff") { g.strokeStyle = color; g.lineWidth = 2; g.beginPath(); g.moveTo(x, 0); g.lineTo(x, h); g.stroke(); }

// ---------- levels ----------
async function loadLevels() {
  levels = await (await fetch("/api/levels")).json();
  const box = $("levels"); box.innerHTML = "";
  for (const l of levels) {
    const d = document.createElement("div"); d.className = "lv"; d.dataset.id = l.id;
    const best = Math.max(0, ...hist(l.id).map((h) => h.s));
    d.innerHTML = `<span class="best">${best ? best.toFixed(0) : ""}</span><b>${l.title}</b><small>${l.mode === "foreign" ? "外语发音" : "玩梗模仿"}</small>`;
    d.onclick = () => selectLevel(l.id); box.appendChild(d);
  }
  selectLevel(new URLSearchParams(location.search).get("level") || levels[0].id);
}
async function selectLevel(id) {
  level = levels.find((l) => l.id === id) || levels[0];
  document.querySelectorAll(".lv").forEach((e) => e.classList.toggle("on", e.dataset.id === level.id));
  $("modeBadge").textContent = level.mode === "foreign" ? "外语发音" : "玩梗模仿";
  $("modeBadge").className = "badge " + level.mode;
  $("lvTitle").textContent = level.title;
  $("lvText").textContent = level.text || "（哼唱，无歌词）";
  $("lvHint").textContent = level.hint;
  refAudio.src = level.ref_url; $("results").classList.add("hidden"); result = null;
  refData = null; refData = await (await fetch(`/api/levels/${level.id}/ref`)).json();
  refData.cents = refData.f0.map(([t, f]) => [t, hz2c(f)]);
  drawRef(); drawLive();
}

// ---------- reference panel ----------
function drawRef(tNow = null) {
  if (!refData) return;
  const [g, w, h] = ctx2d($("refCanvas")), dur = refData.wave.dur;
  drawEnv(g, refData.wave, 0, w, h / 2, h * 0.45, C.ref, 0.35);
  const [lo, hi] = centsRange(refData.cents);
  drawLine(g, refData.cents, (t) => (t / dur) * w, (c) => h - ((c - lo) / (hi - lo)) * h, "#9fc0ff", 2.5);
  if (tNow != null) playhead(g, (tNow / dur) * w, h);
}
$("btnPlayRef").onclick = () => { refAudio.currentTime = 0; refAudio.play(); anim(() => { drawRef(refAudio.currentTime); return !refAudio.paused; }, () => drawRef()); };
function anim(step, done) { const f = () => (step() ? requestAnimationFrame(f) : done && done()); requestAnimationFrame(f); }

// ---------- live recording ----------
let rec = null, live = { cols: [], peak: 0, t0: 0 }, actx = null;
function drawLive() {
  if (!refData) return;
  const [g, w, h] = ctx2d($("liveCanvas"));
  const rd = refData.wave.dur, tEnd = live.cols.length ? live.cols.at(-1)[0] : 0;
  const span = Math.max(rd, tEnd + 0.3);           // extend timeline past the reference if needed
  const X = (t) => (t / span) * w, mid = h / 2, amp = h * 0.46;
  drawEnv(g, refData.wave, 0, X(rd), mid, amp, C.ref, 0.3);
  if (tEnd > rd) { g.strokeStyle = C.grid; g.setLineDash([3, 4]); g.beginPath(); g.moveTo(X(rd), 0); g.lineTo(X(rd), h); g.stroke(); g.setLineDash([]);
    g.fillStyle = C.sub; g.font = "12px sans-serif"; g.fillText("示范结束", X(rd) + 4, 14); }
  // live user waveform: peak min/max per pixel column, auto-gain to running peak
  const gain = 1 / Math.max(0.05, live.peak), cols = new Map();
  for (const [t, mn, mx] of live.cols) { const x = Math.floor(X(t)); const c = cols.get(x); if (c) { c[0] = Math.min(c[0], mn); c[1] = Math.max(c[1], mx); } else cols.set(x, [mn, mx]); }
  g.fillStyle = "rgba(255,93,115,0.75)";
  const xs = [...cols.keys()]; // fill to the next column so slow frames don't leave gaps
  xs.forEach((x, i) => { const [mn, mx] = cols.get(x), cw = Math.min(8, Math.max(1.2, (xs[i + 1] ?? x + 1) - x + 0.3));
    const y1 = mid - Math.min(1, mx * gain) * amp, y2 = mid - Math.max(-1, mn * gain) * amp; g.fillRect(x, y1, cw, Math.max(1, y2 - y1)); });
  if (rec) playhead(g, X(tEnd), h, "#ffffffcc");
}
async function startRec() {
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false } }); }
  catch (e) { $("status").textContent = "无法打开麦克风：" + e.message + "（可改用上传）"; return; }
  actx = new AudioContext(); const src = actx.createMediaStreamSource(stream), an = actx.createAnalyser();
  an.fftSize = 1024; src.connect(an); const buf = new Float32Array(an.fftSize);
  const chunks = []; const mr = new MediaRecorder(stream);
  mr.ondataavailable = (e) => chunks.push(e.data);
  mr.onstop = () => { stream.getTracks().forEach((t) => t.stop()); actx.close(); submit(new Blob(chunks, { type: mr.mimeType }), "rec.webm"); };
  live = { cols: [], peak: 0, t0: performance.now() }; rec = mr; mr.start();
  $("btnRec").textContent = "■ 停止并打分"; $("btnRec").classList.add("rec"); $("status").textContent = "";
  const maxDur = Math.max(4, refData.wave.dur * 2.5) * 1000;
  anim(() => {
    if (!rec) return false;
    const t = (performance.now() - live.t0) / 1000;
    an.getFloatTimeDomainData(buf);
    let mn = 0, mx = 0, s = 0; for (const v of buf) { if (v < mn) mn = v; if (v > mx) mx = v; s += v * v; }
    const rms = Math.sqrt(s / buf.length);
    live.cols.push([t, mn, mx]); live.peak = Math.max(live.peak, mx, -mn);
    $("meterBar").style.width = Math.min(100, rms * 400) + "%";
    $("recTime").textContent = t.toFixed(1) + "s";
    drawLive();
    if (t * 1000 > maxDur) stopRec();
    return true;
  });
}
function stopRec() { if (!rec) return; const r = rec; rec = null; r.stop(); $("btnRec").textContent = "● 开始录音"; $("btnRec").classList.remove("rec"); $("meterBar").style.width = "0"; }
$("btnRec").onclick = () => (rec ? stopRec() : startRec());
$("fileIn").onchange = (e) => { const f = e.target.files[0]; if (f) submit(f, f.name); e.target.value = ""; };

async function submit(blob, name) {
  $("status").textContent = "⏳ 打分中…（首次需加载语音识别模型）";
  if (userBlobUrl) URL.revokeObjectURL(userBlobUrl);
  userBlobUrl = URL.createObjectURL(blob); userAudio.src = userBlobUrl;
  const fd = new FormData(); fd.append("audio", blob, name); fd.append("level_id", level.id);
  const r = await fetch("/api/score", { method: "POST", body: fd });
  const j = await r.json();
  if (!r.ok) { $("status").textContent = "❌ " + (j.detail || r.status); return; }
  $("status").textContent = ""; result = j; addHist(level.id, j.overall); renderResults();
  $("results").scrollIntoView({ behavior: "smooth" });
}

// ---------- history ----------
const hist = (id) => JSON.parse(localStorage.getItem("hist_" + id) || "[]");
function addHist(id, s) { const h = hist(id); h.push({ s, t: Date.now() }); localStorage.setItem("hist_" + id, JSON.stringify(h.slice(-20))); loadBest(); }
function loadBest() { document.querySelectorAll(".lv").forEach((e) => { const b = Math.max(0, ...hist(e.dataset.id).map((h) => h.s)); e.querySelector(".best").textContent = b ? b.toFixed(0) : ""; }); }

// ---------- results ----------
const dimColor = { similarity: "#7cd4ff", pace: C.warn, fluency: C.late, loudness: "#9fe6a0", rhythm: C.ok, contour: C.usr };
let view = "wave", sel = null; // sel = [t0,t1] in ref time
function renderResults() {
  const R = result; $("results").classList.remove("hidden");
  let n = 0; const target = R.overall; anim(() => { n = Math.min(target, n + target / 30 + 0.5); $("ovNum").textContent = n.toFixed(0); return n < target; });
  $("elapsed").textContent = R.elapsed_ms != null ? `· ${R.elapsed_ms}ms` : "";
  $("gates").innerHTML = `<span class="gate ${R.passed ? "pass" : "fail"}">${R.passed ? "✓ 通过" : "✗ 未通过"}</span>` +
    R.gates.map((g) => `<span class="gate ${g.pass ? "pass" : "fail"}">${g.pass ? "✓" : "✗"} ${g.name}</span>`).join("");
  $("dims").innerHTML = Object.entries(R.dims).map(([k, d]) =>
    `<div class="dim"><div class="h"><span>${d.name} <i>权重 ${Math.round(d.weight * 100)}%</i></span><b>${d.score.toFixed(0)}</b></div><div class="bar"><div style="width:0;background:${dimColor[k] || C.ref}" data-w="${d.score}"></div></div></div>`).join("");
  requestAnimationFrame(() => document.querySelectorAll(".bar div").forEach((e) => (e.style.width = e.dataset.w + "%")));
  $("acChecks").innerHTML = R.anti_cheat.checks.map((c) => `<span class="${c.pass ? "ok" : "bad"}">${c.pass ? "✓" : "✗"} ${c.name} <small>${c.value}</small></span>`).join("");
  $("tips").innerHTML = R.tips.map((t) => `<li>${t}</li>`).join("");
  drawRadar();
  const foreign = R.mode === "foreign";
  $("foreignCard").classList.toggle("hidden", !foreign);
  if (foreign) {
    const r = Math.max(0.4, Math.min(2, R.detail.ratio));
    $("paceMark").style.left = `calc(${((r - 0.4) / 1.6) * 100}% - 2px)`;
  }
  sel = null; $("segInfo").textContent = ""; redrawAll();
}
function redrawAll() { drawMain(); drawStrip(); drawPitchCmp(); drawRhythm(); drawHistory(); }
function drawRadar() {
  const cv = $("radar"), g = cv.getContext("2d"), W = cv.width, cx = W / 2, cy = W / 2, rad = W / 2 - 34;
  g.clearRect(0, 0, W, W); const ds = Object.values(result.dims), n = ds.length;
  const P = (i, r) => [cx + r * Math.sin((2 * Math.PI * i) / n), cy - r * Math.cos((2 * Math.PI * i) / n)];
  g.strokeStyle = C.grid; for (const f of [0.25, 0.5, 0.75, 1]) { g.beginPath(); for (let i = 0; i <= n; i++) g.lineTo(...P(i % n, rad * f)); g.stroke(); }
  g.fillStyle = "#ff5d7355"; g.strokeStyle = C.usr; g.lineWidth = 2; g.beginPath();
  ds.forEach((d, i) => g.lineTo(...P(i, (rad * d.score) / 100))); g.closePath(); g.fill(); g.stroke();
  g.fillStyle = C.sub; g.font = "12px sans-serif"; g.textAlign = "center";
  ds.forEach((d, i) => { const [x, y] = P(i, rad + 18); g.fillText(d.name, x, y + 4); });
}
function u2r(t) { const m = result.series.time_map; if (t <= m[0][0]) return m[0][1];
  for (let i = 1; i < m.length; i++) if (m[i][0] >= t) { const [a, b] = [m[i - 1], m[i]]; const k = b[0] === a[0] ? 0 : (t - a[0]) / (b[0] - a[0]); return a[1] + k * (b[1] - a[1]); } return m.at(-1)[1]; }
function r2u(t) { const m = result.series.time_map; for (let i = 1; i < m.length; i++) if (m[i][1] >= t) { const [a, b] = [m[i - 1], m[i]]; const k = b[1] === a[1] ? 0 : (t - a[1]) / (b[1] - a[1]); return a[0] + k * (b[0] - a[0]); } return m.at(-1)[0]; }
// similarity 0..100 -> green..yellow..red
function simColor(s, a = 1) { const x = 1 - s / 100; const r = x < 0.5 ? 46 + (255 - 46) * x * 2 : 255, gg = x < 0.5 ? 212 + (209 - 212) * x * 2 : 209 - (209 - 93) * (x - 0.5) * 2, b = x < 0.5 ? 122 - 20 * x * 2 : 102 + 13 * (x - 0.5) * 2; return `rgba(${r|0},${gg|0},${b|0},${a})`; }
const simAt = (t) => { const st = result.series.sim_strip; return st.sim[Math.min(st.sim.length - 1, Math.max(0, Math.floor(t / st.seg_dur)))]; };
let headRefT = null;
function envGain(e) { let s = 0; for (const v of e.max) s += v * v; return Math.sqrt(s / e.max.length) || 1; }
function drawMain() {
  const S = result.series, [g, w, h] = ctx2d($("mainCmp")), rd = S.ref_wave.dur, ud = S.user_wave.dur, X = (t) => (t / rd) * w;
  const st = S.sim_strip;
  if (view === "wave") {
    // red background where mismatch high
    st.sim.forEach((s, i) => { if (s < 60) { g.fillStyle = `rgba(255,93,115,${(0.35 * (60 - s)) / 60})`; g.fillRect(X(i * st.seg_dur), 0, X(st.seg_dur) + 1, h); } });
    // pauses of user (mapped)
    g.fillStyle = "#ffffff14"; for (const [a, b] of S.pauses_user) g.fillRect(X(u2r(a)), h - 6, X(u2r(b)) - X(u2r(a)), 6);
    const k = envGain(S.ref_wave) / envGain(S.user_wave); // loudness normalization (RMS of envelope)
    const uScaled = { dur: ud, max: S.user_wave.max.map((v) => v * k), min: S.user_wave.min.map((v) => v * k) };
    g.globalCompositeOperation = "lighter";
    drawEnv(g, S.ref_wave, 0, w, h / 2, h * 0.46, C.ref, 0.55);
    drawEnv(g, uScaled, 0, w, h / 2, h * 0.46, C.usr, 0.55, (t) => X(u2r(t)));
    g.globalCompositeOperation = "source-over";
  } else {
    // spectrogram rows: ref | user (DTW-mapped in JS) | difference
    const M = S.mel, nT = M.ref.length, nB = M.ref[0].length, rowH = h / 3, cw = w / nT, ch = rowH / nB;
    const heat = (v) => `hsl(${250 - v * 2.2},80%,${12 + v * 0.5}%)`;
    for (let i = 0; i < nT; i++) {
      const t = (i / (nT - 1)) * rd, j = Math.round((r2u(t) / ud) * (nT - 1));
      const ur = M.user[Math.min(nT - 1, Math.max(0, j))];
      for (let b = 0; b < nB; b++) {
        const y = rowH - (b + 1) * ch;
        g.fillStyle = heat(M.ref[i][b]); g.fillRect(i * cw, y, cw + 0.6, ch + 0.6);
        g.fillStyle = heat(ur[b]); g.fillRect(i * cw, y + rowH, cw + 0.6, ch + 0.6);
        const d = Math.min(99, Math.abs(M.ref[i][b] - ur[b]) * 1.6);
        g.fillStyle = simColor(100 - d, 0.25 + d / 130); g.fillRect(i * cw, y + 2 * rowH, cw + 0.6, ch + 0.6);
      }
    }
    g.fillStyle = "#fff"; g.font = "11px sans-serif";
    g.fillText("示范 log-mel", 6, 13); g.fillText("我的（对齐后）", 6, rowH + 13); g.fillText("差异图（红=差别大）", 6, 2 * rowH + 13);
  }
  if (sel) { g.fillStyle = "#ffffff22"; g.fillRect(X(sel[0]), 0, X(sel[1]) - X(sel[0]), h); g.strokeStyle = "#fff"; g.strokeRect(X(sel[0]), 0.5, X(sel[1]) - X(sel[0]), h - 1); }
  if (headRefT != null) playhead(g, X(headRefT), h);
}
function drawStrip() {
  const st = result.series.sim_strip, [g, w, h] = ctx2d($("diffStrip")), rd = result.series.ref_wave.dur;
  st.sim.forEach((s, i) => { g.fillStyle = simColor(s); g.fillRect((i * st.seg_dur / rd) * w, 0, (st.seg_dur / rd) * w + 1, h); });
  if (sel) { g.strokeStyle = "#fff"; g.lineWidth = 2; g.strokeRect((sel[0] / rd) * w, 1, ((sel[1] - sel[0]) / rd) * w, h - 2); }
  if (headRefT != null) playhead(g, (headRefT / rd) * w, h);
}
function clickSeg(ev) {
  const cv = ev.currentTarget, x = ev.offsetX / cv.clientWidth, rd = result.series.ref_wave.dur, t = x * rd;
  // grow selection around click across neighbouring segments of similar (mis)match, min 0.4s
  const st = result.series.sim_strip, i0 = Math.floor(t / st.seg_dur), bad = st.sim[i0] < 60;
  let a = i0, b = i0; while (a > 0 && (st.sim[a - 1] < 60) === bad && (i0 - a) * st.seg_dur < 0.6) a--; while (b < st.sim.length - 1 && (st.sim[b + 1] < 60) === bad && (b - i0) * st.seg_dur < 0.6) b++;
  let t0 = a * st.seg_dur, t1 = (b + 1) * st.seg_dur; if (t1 - t0 < 0.4) { t0 = Math.max(0, t - 0.2); t1 = Math.min(rd, t + 0.2); }
  sel = [t0, t1]; $("segInfo").textContent = `  ${t0.toFixed(1)}–${t1.toFixed(1)}s · 相似度 ${Math.round(simAt(t))}`;
  playSegment(t0, t1);
}
async function playSegment(t0, t1) {
  who = "seg"; refAudio.pause(); userAudio.pause();
  const run = (a, s, e, toRef, label) => new Promise((res) => {
    a.currentTime = s; a.play(); $("pbWho").textContent = label;
    anim(() => { if (who !== "seg") { a.pause(); res(false); return false; } headRefT = toRef(a.currentTime); drawMain(); drawStrip();
      if (a.currentTime >= e || a.paused) { a.pause(); res(true); return false; } return true; });
  });
  if (await run(refAudio, t0, t1, (x) => x, "▶ 示范这段")) {
    await new Promise((r) => setTimeout(r, 250));
    if (who === "seg") await run(userAudio, r2u(t0), r2u(t1), u2r, "▶ 我的这段");
  }
  if (who === "seg") { who = null; $("pbWho").textContent = ""; }
}
$("mainCmp").onclick = clickSeg; $("diffStrip").onclick = clickSeg;
$("vWave").onclick = () => { view = "wave"; $("vWave").classList.add("on"); $("vSpec").classList.remove("on"); drawMain(); };
$("vSpec").onclick = () => { view = "spec"; $("vSpec").classList.add("on"); $("vWave").classList.remove("on"); drawMain(); };
document.querySelectorAll("details").forEach((d) => d.addEventListener("toggle", () => result && redrawAll()));
let who = null;
function playSync(which, fromRefT = 0) {
  refAudio.pause(); userAudio.pause(); who = which;
  const a = which === "ref" ? refAudio : userAudio;
  a.currentTime = which === "ref" ? fromRefT : r2u(fromRefT); a.play();
  $("pbWho").textContent = which === "ref" ? "正在播放：示范" : "正在播放：我的";
  anim(() => { if (a.paused || who !== which) return false; headRefT = which === "ref" ? a.currentTime : u2r(a.currentTime); drawMain(); drawStrip(); drawPitchCmp(); return true; },
    () => { if (who === which) $("pbWho").textContent = ""; });
}
$("pbRef").onclick = () => playSync("ref"); $("pbUser").onclick = () => playSync("user");
$("pbAB").onclick = () => playSync(who === "ref" ? "user" : "ref", headRefT || 0);
$("pbStop").onclick = () => { who = null; refAudio.pause(); userAudio.pause(); $("pbWho").textContent = ""; };
function drawPitchCmp() {
  const S = result.series, [g, w, h] = ctx2d($("pitchCmp")), rd = S.ref_wave.dur;
  const X = (t) => (t / rd) * w, [lo, hi] = centsRange(S.ref_cents, S.user_cents_aligned), Y = (c) => h - 8 - ((c - lo) / (hi - lo)) * (h - 16);
  // deviation shading: sample ref curve at user times
  const refAt = (t) => { const a = S.ref_cents; let best = null, bd = 1e9; for (const p of a) { const d = Math.abs(p[0] - t); if (d < bd) { bd = d; best = p[1]; } } return bd < 0.05 ? best : null; };
  for (const [t, v] of S.user_cents_aligned) { if (v == null) continue; const r = refAt(t); if (r == null) continue;
    g.fillStyle = Math.abs(v - r) > 100 ? "#ff5d7340" : "#2ed47a26"; g.fillRect(X(t) - 1.5, Math.min(Y(v), Y(r)), 3, Math.abs(Y(v) - Y(r)) + 1); }
  for (let c = Math.ceil(lo / 100) * 100; c < hi; c += 100) { g.strokeStyle = c % 1200 === 0 ? "#3a4180" : "#1f2448"; g.beginPath(); g.moveTo(0, Y(c)); g.lineTo(w, Y(c)); g.stroke(); }
  drawLine(g, S.ref_cents, X, Y, C.ref, 3); drawLine(g, S.user_cents_aligned, X, Y, C.usr, 2);
  g.fillStyle = C.sub; g.font = "11px sans-serif";
  const ks = result.detail.key_shift_cents; if (ks != null) g.fillText(`整体${ks > 0 ? "高" : "低"} ${Math.abs(ks / 100).toFixed(1)} 个半音（已扣除，不计分）`, 6, 13);
  if (headRefT != null) playhead(g, X(headRefT), h);
}
function drawRhythm() {
  const S = result.series, [g, w, h] = ctx2d($("rhythmCmp")), rd = S.ref_wave.dur, ud = S.user_wave.dur;
  const Xr = (t) => 10 + (t / rd) * (w - 20), Xu = (t) => 10 + (t / ud) * (w - 20), yR = 28, yU = h - 28;
  g.strokeStyle = C.grid; g.beginPath(); g.moveTo(0, yR); g.lineTo(w, yR); g.moveTo(0, yU); g.lineTo(w, yU); g.stroke();
  for (const L of S.onset_links) { const d = L.u / ud - L.r / rd; g.strokeStyle = Math.abs(d) < 0.04 ? C.ok : d < 0 ? C.warn : C.late; g.lineWidth = 1.5;
    g.beginPath(); g.moveTo(Xr(L.r), yR); g.lineTo(Xu(L.u), yU); g.stroke(); }
  g.fillStyle = C.ref; for (const t of S.onsets_ref) { g.beginPath(); g.arc(Xr(t), yR, 5, 0, 7); g.fill(); }
  g.fillStyle = C.usr; for (const t of S.onsets_user) { g.beginPath(); g.arc(Xu(t), yU, 5, 0, 7); g.fill(); }
  g.fillStyle = C.sub; g.font = "11px sans-serif"; g.fillText(`示范 ${S.onsets_ref.length} 个起音`, 10, 12); g.fillText(`我的 ${S.onsets_user.length} 个起音`, 10, h - 6);
}
function drawHistory() {
  const H = hist(level.id), [g, w, h] = ctx2d($("history")); if (!H.length) return;
  const X = (i) => 20 + (H.length === 1 ? (w - 40) / 2 : (i / (H.length - 1)) * (w - 40)), Y = (s) => h - 14 - (s / 100) * (h - 28);
  g.strokeStyle = C.grid; g.setLineDash([3, 4]); g.beginPath(); g.moveTo(0, Y(60)); g.lineTo(w, Y(60)); g.stroke(); g.setLineDash([]);
  g.strokeStyle = C.warn; g.lineWidth = 2; g.beginPath(); H.forEach((p, i) => g.lineTo(X(i), Y(p.s))); g.stroke();
  g.fillStyle = "#fff"; g.font = "11px sans-serif"; g.textAlign = "center";
  H.forEach((p, i) => { g.beginPath(); g.arc(X(i), Y(p.s), 3.5, 0, 7); g.fill(); g.fillText(p.s.toFixed(0), X(i), Y(p.s) - 7); });
}
window.addEventListener("resize", () => { drawRef(); drawLive(); if (result) redrawAll(); });
loadLevels();
