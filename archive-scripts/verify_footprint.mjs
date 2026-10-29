#!/usr/bin/env node
/*
真实footprint 零相交验证 —— 按瓦片的实际旋转四边形做 SAT 判定。

为什么不能测 getBoundingClientRect()：
  瓦片 transform 为 translate3d(px,py,0) rotate(r)，实测旋转最大 8.74°。
  getBoundingClientRect() 返回的是旋转后的**轴对齐外接框（AABB）**，
  必然比真实footprint大，相邻瓦片的 AABB 会相交而实体并不相交。
  技能自带的 verify_layout.mjs 测的是布局模型（px/py/w/h，无旋转），
  与 DOM AABB 不是同一口径，不能互相替代。

正确做法：从 CSS transform 矩阵还原每个瓦片的**真实旋转四边形**，
再用分离轴定理（SAT）判定凸多边形是否真的相交，并算出真实穿透深度。

因为页面每次加载都会用 Math.random() 重排位置、且 v3.1 的刷新随机尺寸
机制会强制尺寸跳变，所以单次对比不构成等价性证据；本脚本对每个页面
跑 RUNS 次，报告分布。

用法：node verify_footprint.mjs <URL> [runs]
*/
import { spawn } from "node:child_process";

const TARGET = process.argv[2];
const RUNS = parseInt(process.argv[3] || "3", 10);
if (!TARGET) { console.error("用法：node verify_footprint.mjs <URL> [runs]"); process.exit(2); }

const chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* 页面内执行的测量：还原真实旋转四边形 + SAT 相交判定。
   只测 #field 下的 figure.tile（排除灯箱图与关联条带，那些重叠是设计使然）。 */
const MEASURE = `(() => {
  const field = document.getElementById('field');
  const fr = field.getBoundingClientRect();
  const ts = [...document.querySelectorAll('#field figure.tile')];

  function quadOf(t) {
    const w = t.offsetWidth, h = t.offsetHeight;
    if (w < 1 || h < 1) return null;
    const cs = getComputedStyle(t);
    if (cs.display === 'none' || cs.visibility === 'hidden') return null;
    let m = cs.transform;
    let a = 1, b = 0, c = 0, d = 1, e = 0, f = 0;
    if (m && m !== 'none') {
      const v = m.match(/matrix\\(([^)]+)\\)/);
      if (v) { const p = v[1].split(',').map(Number); a=p[0]; b=p[1]; c=p[2]; d=p[3]; e=p[4]; f=p[5]; }
      else if (/matrix3d/.test(m)) {
        const p = m.match(/matrix3d\\(([^)]+)\\)/)[1].split(',').map(Number);
        a=p[0]; b=p[1]; c=p[4]; d=p[5]; e=p[12]; f=p[13];
      }
    }
    // transform-origin，默认 50% 50%
    let ox = w / 2, oy = h / 2;
    const to = cs.transformOrigin;
    if (to) {
      const px = to.split(/\\s+/);
      const num = (s, dim) => s.endsWith('px') ? parseFloat(s)
        : s.endsWith('%') ? parseFloat(s) / 100 * dim : dim / 2;
      ox = num(px[0], w); oy = num(px[1] || px[0], h);
    }
    // p' = M·(p - O) + O，再加 #field 在视口中的位置
    const corners = [[0,0],[w,0],[w,h],[0,h]].map(([x,y]) => {
      const dx = x - ox, dy = y - oy;
      return [ fr.left + ox + (a*dx + c*dy + e), fr.top + oy + (b*dx + d*dy + f) ];
    });
    return corners;
  }

  const quads = ts.map(t => ({ id: t.dataset.id, q: quadOf(t) })).filter(x => x.q);

  // SAT：两个凸四边形是否相交；返回穿透深度（0 = 不相交）
  function satPen(p, q) {
    let minPen = Infinity;
    for (const poly of [p, q]) {
      for (let i = 0; i < poly.length; i++) {
        const j = (i + 1) % poly.length;
        const ex = poly[j][0] - poly[i][0], ey = poly[j][1] - poly[i][1];
        // 法轴
        const ax = -ey, ay = ex;
        const len = Math.hypot(ax, ay) || 1;
        const nx = ax / len, ny = ay / len;
        let pMin = Infinity, pMax = -Infinity, qMin = Infinity, qMax = -Infinity;
        for (const [x, y] of p) { const v = x*nx + y*ny; pMin = Math.min(pMin, v); pMax = Math.max(pMax, v); }
        for (const [x, y] of q) { const v = x*nx + y*ny; qMin = Math.min(qMin, v); qMax = Math.max(qMax, v); }
        const ovl = Math.min(pMax, qMax) - Math.max(pMin, qMin);
        if (ovl <= 0) return 0;              // 找到分离轴 → 不相交
        minPen = Math.min(minPen, ovl);
      }
    }
    return minPen === Infinity ? 0 : minPen;
  }

  // AABB 口径同时报出，用于对照
  function aabb(p) {
    const xs = p.map(v=>v[0]), ys = p.map(v=>v[1]);
    return { l: Math.min(...xs), t: Math.min(...ys), r: Math.max(...xs), b: Math.max(...ys) };
  }

  let satOv = 0, satMaxPen = 0, aabbOv = 0;
  const satPairs = [];
  for (let i = 0; i < quads.length; i++) for (let j = i+1; j < quads.length; j++) {
    const pen = satPen(quads[i].q, quads[j].q);
    if (pen > 0) { satOv++; if (pen > satMaxPen) satMaxPen = pen;
                   if (satPairs.length < 5) satPairs.push(quads[i].id + '~' + quads[j].id + ':' + pen.toFixed(1)); }
    const A = aabb(quads[i].q), B = aabb(quads[j].q);
    const x = Math.min(A.r,B.r) - Math.max(A.l,B.l), y = Math.min(A.b,B.b) - Math.max(A.t,B.t);
    if (x > 0.5 && y > 0.5) aabbOv++;
  }
  return JSON.stringify({ measured: quads.length, satOv, satMaxPen: +satMaxPen.toFixed(2), aabbOv, satPairs });
})()`;

async function oneRun(url, port) {
  const proc = spawn(chrome, [
    "--headless=new", `--remote-debugging-port=${port}`,
    "--no-first-run", "--no-default-browser-check",
    "--disable-gpu", "--window-size=1440,900", "about:blank",
  ], { stdio: "ignore" });

  let ws = null;
  for (let i = 0; i < 60; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/json/list`);
      const list = await res.json();
      const page = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
      if (page) { ws = new WebSocket(page.webSocketDebuggerUrl); await new Promise((r, e) => { ws.onopen = r; ws.onerror = e; }); break; }
    } catch { /* 重试 */ }
    await sleep(300);
  }
  if (!ws) { proc.kill(); throw new Error("连不上调试端口"); }

  let id = 0; const pend = new Map();
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pend.has(m.id)) { const { res, rej } = pend.get(m.id); pend.delete(m.id); m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result); }
  };
  const send = (method, params = {}) => new Promise((res, rej) => {
    const i = ++id; pend.set(i, { res, rej }); ws.send(JSON.stringify({ id: i, method, params }));
    setTimeout(() => { if (pend.has(i)) { pend.delete(i); rej(new Error(method + " 超时")); } }, 120000);
  });
  const ev = async (expr) => {
    const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.text);
    return r.result.value;
  };

  await send("Runtime.enable");
  await send("Page.enable");
  await send("Page.navigate", { url });
  await sleep(9000);
  const h = await ev(`Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)`);
  for (let y = 0; y < h + 600; y += 600) { await ev(`window.scrollTo(0, ${y})`); await sleep(300); }
  await sleep(4000);
  await ev(`window.scrollTo(0, 0)`);
  await sleep(2500);

  const out = JSON.parse(await ev(MEASURE));
  try { ws.close(); } catch { /* 忽略 */ }
  proc.kill();
  return out;
}

try {
  console.log(`目标：${TARGET}\n每次加载布局都会随机重排，故跑 ${RUNS} 次报告分布\n`);
  let allZero = true;
  for (let r = 1; r <= RUNS; r++) {
    const o = await oneRun(TARGET, 9350 + r);
    console.log(`第 ${r} 次：测量 ${o.measured}/108 瓦片 | 真实footprint 相交对 ${o.satOv}（最深 ${o.satMaxPen}px） | 对照 AABB 相交对 ${o.aabbOv}`);
    if (o.satPairs.length) console.log(`        相交样本：${o.satPairs.join(", ")}`);
    if (o.satOv !== 0 || o.measured !== 108) allZero = false;
  }
  console.log(`\n${allZero
    ? "✅ 真实footprint 零相交成立（SAT 口径，108/108 瓦片均测到）"
    : "❌ 存在真实相交或测量不全，需定位"}`);
  process.exit(allZero ? 0 : 1);
} catch (e) {
  console.error("脚本自身出错：", e.message);
  process.exit(2);
}
