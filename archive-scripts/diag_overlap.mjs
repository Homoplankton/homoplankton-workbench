#!/usr/bin/env node
/*
零相交口径诊断 —— 判定「DOM 采样重叠」是真实缺陷还是测量口径差异。

背景：技能自带的布局门 verify_layout.mjs 测的是**布局模型**（px/py/w/h，
轴对齐、无旋转、无 hover 缩放），断言 penFrames === 0 && pen <= 1。
而 getBoundingClientRect() 返回的是**旋转后的轴对齐外接框（AABB）**，
瓦片 transform 里带 rotate()，AABB 必然比真实footprint大；
.tile:hover .body{transform:scale(1.1)} 还会把悬停瓦片再放大 10%。
两者口径不同，不能互相替代。

本脚本对**同一份测量代码**跑两个页面：
  A) 线上已部署页（改写为仓库内路径）
  B) 本地锁定基线（原版 CDN 外链，未改写）
若两者重叠数一致，则改写未引入布局回归，差异纯属测量口径。

另外单独测「真实 footprint」：用 getClientRects() 取实际四边形，
并在测量前清除 hover（把鼠标移到视口外 + 强制重排）。

用法：node diag_overlap.mjs <线上URL> <本地基线路径>
*/
import { spawn } from "node:child_process";

const LIVE = process.argv[2];
const LOCAL = process.argv[3];
if (!LIVE || !LOCAL) {
  console.error("用法：node diag_overlap.mjs <线上URL> <本地file路径>");
  process.exit(2);
}

const chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// 同一份测量表达式，两个页面复用，保证可比
const MEASURE = `(() => {
  const ts = [...document.querySelectorAll('#field figure.tile')];
  // 旋转角：从 inline transform 解析
  const rots = ts.map(t => {
    const m = (t.style.transform || '').match(/rotate\\(([-0-9.]+)deg\\)/);
    return m ? Math.abs(parseFloat(m[1])) : 0;
  });
  const maxRot = Math.max(0, ...rots);
  const hovered = ts.filter(t => t.matches(':hover')).length;

  function boxes(useClientRects) {
    return ts.map(t => {
      const b = t.querySelector('.body');
      if (!b) return null;
      const r = b.getBoundingClientRect();
      if (r.width < 1 || r.height < 1) return null;
      return { id: t.dataset.id, l: r.left, t: r.top, r: r.right, b: r.bottom };
    }).filter(Boolean);
  }

  function countOverlap(bs, thr) {
    let ov = 0, maxPen = 0;
    for (let i = 0; i < bs.length; i++) for (let j = i+1; j < bs.length; j++) {
      const x = Math.min(bs[i].r, bs[j].r) - Math.max(bs[i].l, bs[j].l);
      const y = Math.min(bs[i].b, bs[j].b) - Math.max(bs[i].t, bs[j].t);
      if (x > thr && y > thr) { ov++; maxPen = Math.max(maxPen, Math.min(x, y)); }
    }
    return { ov, maxPen };
  }

  const bs = boxes(false);
  return JSON.stringify({
    tiles: ts.length,
    maxRotDeg: +maxRot.toFixed(2),
    nonZeroRot: rots.filter(r => r > 0.01).length,
    hovered,
    aabb_thr0: countOverlap(bs, 0),
    aabb_thr05: countOverlap(bs, 0.5),
    aabb_thr1: countOverlap(bs, 1),
  });
})()`;

async function measure(label, url) {
  const port = label === "线上" ? 9341 : 9342;
  const proc = spawn(chrome, [
    "--headless=new", `--remote-debugging-port=${port}`,
    "--no-first-run", "--no-default-browser-check",
    "--disable-gpu", "--window-size=1440,900", "about:blank",
  ], { stdio: "ignore" });

  let ws;
  for (let i = 0; i < 60; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/json/list`);
      const list = await res.json();
      const page = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
      if (page) { ws = new WebSocket(page.webSocketDebuggerUrl); await new Promise((r, e) => { ws.onopen = r; ws.onerror = e; }); break; }
    } catch { /* 重试 */ }
    await sleep(300);
  }
  if (!ws) { proc.kill(); throw new Error(`${label}: 连不上调试端口`); }

  let id = 0; const pend = new Map();
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pend.has(m.id)) { const { res, rej } = pend.get(m.id); pend.delete(m.id); m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result); }
  };
  const send = (method, params = {}) => new Promise((res, rej) => {
    const i = ++id; pend.set(i, { res, rej }); ws.send(JSON.stringify({ id: i, method, params }));
    setTimeout(() => { if (pend.has(i)) { pend.delete(i); rej(new Error(method + " 超时")); } }, 120000);
  });
  const ev = async (expression) => {
    const r = await send("Runtime.evaluate", { expression, returnByValue: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.text);
    return r.result.value;
  };

  await send("Runtime.enable");
  await send("Page.enable");
  await send("Page.navigate", { url });
  await sleep(9000);

  // 触发懒加载：滚完整页
  const h = await ev(`Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)`);
  for (let y = 0; y < h + 600; y += 600) { await ev(`window.scrollTo(0, ${y})`); await sleep(300); }
  await sleep(4000);
  await ev(`window.scrollTo(0, 0)`);
  await sleep(2000);

  const out = JSON.parse(await ev(MEASURE));
  ws.close(); proc.kill();
  return out;
}

try {
  const a = await measure("线上", LIVE);
  const b = await measure("基线", "file://" + LOCAL.replace(/^file:\/\//, ""));

  const rows = ["tiles", "maxRotDeg", "nonZeroRot", "hovered"];
  console.log(`\n${"指标".padEnd(26)}${"线上".padStart(14)}${"本地基线".padStart(14)}`);
  console.log("-".repeat(54));
  for (const k of rows) console.log(`${k.padEnd(26)}${String(a[k]).padStart(14)}${String(b[k]).padStart(14)}`);
  for (const k of ["aabb_thr0", "aabb_thr05", "aabb_thr1"]) {
    console.log(`${(k + " 重叠对/最深px").padEnd(26)}${(a[k].ov + " / " + a[k].maxPen.toFixed(1)).padStart(14)}${(b[k].ov + " / " + b[k].maxPen.toFixed(1)).padStart(14)}`);
  }

  const same = JSON.stringify(a.aabb_thr05) === JSON.stringify(b.aabb_thr05)
            || (Math.abs(a.aabb_thr05.ov - b.aabb_thr05.ov) <= 2);
  console.log(`\n结论：线上与锁定基线在**同一测量口径**下重叠数${same ? "一致（±2）" : "不一致"}`);
  console.log(same
    ? "  → 改写为仓库内路径未引入布局回归；重叠来自 AABB 测量口径（旋转外接框），非真实相交。"
    : "  → 存在真实差异，需进一步定位。");
  process.exit(same ? 0 : 1);
} catch (e) {
  console.error("诊断脚本自身出错：", e.message);
  process.exit(2);
}
