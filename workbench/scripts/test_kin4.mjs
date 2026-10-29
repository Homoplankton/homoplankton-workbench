// test_kin4.mjs — v4 三项修复的浏览器实测
//
// 验证目标（用户 2026-10-27 提出）：
//  1. 触控板滑动 → 条带平移 + 抬手吸附居中（用 WheelEvent 模拟，deltaX/deltaY 都测）
//  2. v4.1 回退：条带 img.src 是整帧展示层照片（r.src），不再用主体裁剪
//  3. 关闭无闪烁：closeLB 后 460ms 内 .kinon 仍在（.frame 保持隐藏），之后才清理
// 回归：点邻图仍只平移不重建；指认机制仍工作。
//
// 用法：先手动启动 Chrome（--remote-debugging-port），再 node scripts/test_kin4.mjs

import http from "node:http";
const PORT = process.env.PORT || 9371;

function getJSON(path) {
  return new Promise((res, rej) => {
    http.get({ host: "127.0.0.1", port: PORT, path }, (r) => {
      let b = ""; r.on("data", (c) => (b += c)); r.on("end", () => res(JSON.parse(b)));
    }).on("error", rej);
  });
}
// ⚠ Node 内置 WebSocket 用 DOM 风格 API（onopen/onmessage），不是 ws 包的 .on()。
//   上一版误用 .on() 直接崩在 connect()。此实现与已验证可跑的 test_kin.mjs 一致。
const targets = await getJSON("/json/list");
const page = targets.find((t) => t.type === "page" && t.url.includes("blackwater-plankton-archive"));
if (!page) { console.error("找不到站点页面，先启动 Chrome 载入站点"); process.exit(2); }

const ws = new WebSocket(page.webSocketDebuggerUrl);
let _id = 0;
const pend = new Map();
function send(method, params = {}) {
  const id = ++_id;
  return new Promise((res, rej) => {
    pend.set(id, { res, rej });
    ws.send(JSON.stringify({ id, method, params }));
    setTimeout(() => {
      if (pend.has(id)) { pend.delete(id); rej(new Error("timeout " + method)); }
    }, 25000);
  });
}
ws.onmessage = (e) => {
  const m = JSON.parse(e.data);
  if (m.id && pend.has(m.id)) {
    const { res, rej } = pend.get(m.id);
    pend.delete(m.id);
    m.error ? rej(new Error(m.error.message)) : res(m.result);
  }
};
await new Promise((r) => (ws.onopen = r));
await send("Runtime.enable");

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
await sleep(1500);

async function ev(expr) {
  const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || JSON.stringify(r.exceptionDetails));
  return r.result.value;
}

let pass = 0, fail = 0;
function C(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  ok ? pass++ : fail++;
  console.log(`  ${ok ? "✓" : "✗"} ${name}${ok ? "" : `: got=${JSON.stringify(got)} want=${JSON.stringify(want)}`}`);
}
function T(name, got) { const ok = !!got; ok ? pass++ : fail++; console.log(`  ${ok ? "✓" : "✗"} ${name}: ${JSON.stringify(got)}`); }

// 打开 K3（红胸樱虾，用户点名的组）：DSC_1060
console.log("=== 1. 打开 K3 条带 ===");
await ev(`openLB(Playground.records.find(r=>r.id==='DSC_1060'))`);
await sleep(1200);
C("条带 4 张", await ev(`document.querySelectorAll('.kinfig').length`), 4);
T("kinon 激活", await ev(`document.getElementById('lb').classList.contains('kinon')`));

console.log("=== 2. v4.1 回退：条带用整帧展示层照片（不再用主体裁剪）===");
const srcMatch = await ev(`
(() => {
  const fs = Array.from(document.querySelectorAll('.kinfig'));
  return fs.every(f => {
    const r = Playground.records.find(x => x.id === f.dataset.kid);
    return r && f.querySelector('img').src === r.src;
  });
})()`);
C("4 张 src 均等于记录展示层（整帧）", srcMatch, true);
C("无 data URI 裁剪残留", await ev(`Array.from(document.querySelectorAll('.kinfig img')).every(i=>!i.src.startsWith('data:image'))`), true);

console.log("=== 3. 焦点放大是纯 transform（布局零位移）===");
const posBefore = await ev(`Array.from(document.querySelectorAll('.kinfig')).map(f=>f.offsetLeft)`);
await ev(`PlaygroundKin.setFocus(2)`);
await sleep(800);
const posAfter = await ev(`Array.from(document.querySelectorAll('.kinfig')).map(f=>f.offsetLeft)`);
C("offsetLeft 全不变（scale 不占布局）", posAfter, posBefore);
T("focus 图 scale>1", await ev(`getComputedStyle(document.querySelectorAll('.kinfig')[2]).transform !== 'none'`));
C("focus 索引=2", await ev(`PlaygroundKin.focusIndex()`), 2);
// 居中锁定：焦点在正中
const off = await ev(`
(() => {
  const f = document.querySelectorAll('.kinfig')[PlaygroundKin.focusIndex()];
  const c = f.offsetLeft + f.offsetWidth/2 + PlaygroundKin.panX();
  return Math.round(c - document.getElementById('kinwrap').clientWidth/2);
})()`);
C("焦点居中（off≈0）", off, 0);

console.log("=== 4. 触控板滑动：wheel 事件平移 + 吸附 ===");
await ev(`PlaygroundKin.setFocus(1)`);
await sleep(700);
const pan0 = await ev(`PlaygroundKin.panX()`);
// 模拟触控板双指左滑（deltaX 为正的连续事件）
await ev(`
(() => {
  const w = document.getElementById('kinwrap');
  for (let i = 0; i < 6; i++)
    w.dispatchEvent(new WheelEvent('wheel', { deltaX: 60, deltaY: 0, bubbles: true, cancelable: true }));
})()`);
await sleep(120);
const panMid = await ev(`PlaygroundKin.panX()`);
T(`滑动中 panX 变化（${pan0.toFixed(0)}→${panMid.toFixed(0)}）`, Math.abs(panMid - pan0) > 30);
// 抬手（160ms 无事件）→ 吸附到最近图并居中
await sleep(900);
const panSnap = await ev(`PlaygroundKin.panX()`);
const off2 = await ev(`
(() => {
  const f = document.querySelectorAll('.kinfig')[PlaygroundKin.focusIndex()];
  const c = f.offsetLeft + f.offsetWidth/2 + PlaygroundKin.panX();
  return Math.round(c - document.getElementById('kinwrap').clientWidth/2);
})()`);
C("吸附后焦点居中（off≈0）", off2, 0);
T(`焦点已移动（1→${await ev("PlaygroundKin.focusIndex()")}）`, (await ev(`PlaygroundKin.focusIndex()`)) !== 1);
// deltaY（纵向滚动）也映射为横向平移
const panA = await ev(`PlaygroundKin.panX()`);
await ev(`document.getElementById('kinwrap').dispatchEvent(new WheelEvent('wheel',{deltaX:0,deltaY:80,bubbles:true,cancelable:true}))`);
await sleep(150);
T("deltaY 也触发平移", await ev(`Math.abs(PlaygroundKin.panX() - ${panA}) > 10`));
await sleep(900);

console.log("=== 5. 点击邻图仍只平移不重建 ===");
await ev(`
(() => {
  document.querySelectorAll('.kinfig').forEach(f => f._tag = Math.random().toString(36).slice(2));
})()`);
await ev(`document.querySelectorAll('.kinfig')[0].click()`);
await sleep(800);
C("DOM 节点保持同一批", await ev(`Array.from(document.querySelectorAll('.kinfig')).every(f=>!!f._tag)`), true);
C("焦点=0", await ev(`PlaygroundKin.focusIndex()`), 0);

console.log("=== 6. 关闭无闪烁：淡出期间条带保留、引擎 frame 隐藏 ===");
await ev(`closeLB()`);
await sleep(120);  // #lb 正在 0.4s 淡出
const during = await ev(`
({
  kinon: document.getElementById('lb').classList.contains('kinon'),
  frameHidden: getComputedStyle(document.querySelector('#lb .frame')).display === 'none',
  stripStill: document.querySelectorAll('.kinfig').length
})`);
C("淡出中 .kinon 仍在", during.kinon, true);
C("淡出中引擎 frame 隐藏（无闪图）", during.frameHidden, true);
C("淡出中条带未拆", during.stripStill, 4);
await sleep(600);  // 460ms 清理已执行
const after = await ev(`({ kinon: document.getElementById('lb').classList.contains('kinon'), strip: document.querySelectorAll('.kinfig').length })`);
C("清理后 kinon 移除", after.kinon, false);
C("清理后条带拆除", after.strip, 0);

console.log("=== 7. 重开正常 + 无关联组回退引擎单图 ===");
await ev(`openLB(Playground.records.find(r=>r.id==='DSC_1010'))`);
await sleep(900);
C("重开 K3 条带", await ev(`document.querySelectorAll('.kinfig').length`), 4);
await ev(`closeLB()`); await sleep(700);
await ev(`openLB(Playground.records.find(r=>r.id==='DSC_9999') || Playground.records.find(r=>!PlaygroundKin.groups().some(g=>g.members.includes(r.id))))`);
await sleep(700);
C("无关联组不加 kinon", await ev(`document.getElementById('lb').classList.contains('kinon')`), false);
C("引擎单图 frame 可见", await ev(`getComputedStyle(document.querySelector('#lb .frame')).display !== 'none'`), true);
await ev(`closeLB()`); await sleep(700);

console.log("=== 8. 指认机制回归 ===");
await ev(`PlaygroundKin.pinMode(true)`);
await sleep(300);
T("进入指认模式", await ev(`document.getElementById('pinBtn').classList.contains('on')`));
const free2 = await ev(`
(() => {
  const inGroup = new Set(PlaygroundKin.groups().flatMap(g=>g.members));
  const free = Playground.records.filter(r=>!inGroup.has(r.id)).slice(0,2).map(r=>r.id);
  return free;
})()`);
await ev(`
(() => {
  const t1 = document.querySelector(\`#field .tile[data-id="${free2[0]}"]\`);
  const t2 = document.querySelector(\`#field .tile[data-id="${free2[1]}"]\`);
  t1.dispatchEvent(new MouseEvent('click',{bubbles:true}));
  t2.dispatchEvent(new MouseEvent('click',{bubbles:true}));
})()`);
await sleep(300);
await ev(`document.getElementById('pbMerge').click()`);
await sleep(600);
T("合并后两图同组", await ev(`
(() => {
  const g1 = PlaygroundKin.groups().find(g=>g.members.includes('${free2[0]}'));
  return g1 && g1.members.includes('${free2[1]}');
})()`));
await ev(`openLB(Playground.records.find(r=>r.id==='${free2[0]}'))`);
await sleep(900);
C("指认组以条带打开", await ev(`document.querySelectorAll('.kinfig').length`), 2);
T("指认组用整帧展示层", await ev(`
(() => {
  const f = document.querySelector('.kinfig');
  const r = Playground.records.find(x => x.id === f.dataset.kid);
  return f.querySelector('img').src === r.src;
})()`));
await ev(`closeLB()`); await sleep(700);
await ev(`PlaygroundKin.pinMode(false); localStorage.removeItem('plankton_kinship_corrections_v1')`);

console.log(`\n=== 结果 ${pass}/${pass + fail} 通过 ===`);
ws.close();
process.exit(fail ? 1 : 0);
