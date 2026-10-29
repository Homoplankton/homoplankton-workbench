// test_kinship.mjs — 关联条带（kinship filmstrip）浏览器实测
//
// 验证目标：
//  1. 触控板滑动 → 条带平移 + 抬手吸附居中（WheelEvent 模拟，deltaX/deltaY 都测）
//  2. 图源 = 整帧展示层照片 r.src（非主体裁剪；裁剪版曾过裁失真，已废弃）
//  3. 关闭无闪烁：closeLB 后淡出期间 .kinon 仍在、.frame 持续隐藏，之后才清理
//  4. 焦点放大是纯 transform（布局零位移）；点邻图只平移不重建 DOM
//  5. 无关联组的图不进条带，回退引擎默认单图；指认机制可合并分组并即时生效
//
// 测试组**动态选取**（取注入分组里成员最多的一组），不硬编码任何项目专属 id，
// 因此同一份测试可复用于任意 playground 项目。
//
// 用法：
//   CHROME --headless=new --remote-debugging-port=<PORT> file://<站点.html> &
//   PORT=<PORT> MATCH=<站点文件名子串> node scripts/test_kinship.mjs
//   （MATCH 默认 "blackwater-plankton-archive"；用其他文件名时务必传入）
//
// ⚠ 汇报结论前先看**未过滤的原始输出尾部并检查 node 的退出码**。
//   `... | tail` 管道下 `$?` 取到的是 tail 的退出码，会把失败读成成功（lessons #14）。

import http from "node:http";
const PORT = process.env.PORT || 9371;
// MATCH：页面 URL 需包含的子串。默认取常见入口名；用其他文件名时必须显式传入，
// 否则本脚本会「找不到站点页面」而退出 2 —— 此时不要误读成测试通过。
const MATCH = process.env.MATCH || "blackwater-plankton-archive";

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
const page = targets.find((t) => t.type === "page" && t.url.includes(MATCH));
if (!page) {
  console.error(`找不到站点页面（URL 需含 ${JSON.stringify(MATCH)}）。`);
  console.error("请确认 Chrome 已用 --remote-debugging-port 载入站点，或用 MATCH=<文件名子串> 指定。");
  process.exit(2);
}

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

// 动态选测试组：取成员最多的组（≥2），从注入的分组里取样，不硬编码任何项目专属 id。
const TG = await ev(`
(() => {
  const gs = PlaygroundKin.groups().filter(g => g.members.length >= 2);
  if (!gs.length) return null;
  gs.sort((a,b) => b.members.length - a.members.length);
  const g = gs[0];
  return { id: g.id, label: g.label, n: g.members.length, first: g.members[0], mid: g.members[1] };
})()`);
if (!TG) { console.error("没有可用分组（未注入 __KIN_GROUPS__？）"); process.exit(2); }
console.log(`=== 测试组：${TG.id}「${TG.label}」${TG.n} 张，从 ${TG.first} 打开 ===`);
const N = TG.n;                      // 该组成员数，条带应正好渲染这么多张
const midIdx = Math.min(2, N - 1);   // 焦点测试用的中间下标（≥3 张时取 2，否则取末位）

console.log("=== 1. 打开条带 ===");
await ev(`openLB(Playground.records.find(r=>r.id==='${TG.first}'))`);
await sleep(1200);
C(`条带 ${N} 张`, await ev(`document.querySelectorAll('.kinfig').length`), N);
T("kinon 激活", await ev(`document.getElementById('lb').classList.contains('kinon')`));

console.log("=== 2. 图源=整帧展示层照片（非主体裁剪）===");
const srcMatch = await ev(`
(() => {
  const fs = Array.from(document.querySelectorAll('.kinfig'));
  return fs.every(f => {
    const r = Playground.records.find(x => x.id === f.dataset.kid);
    return r && f.querySelector('img').src === r.src;
  });
})()`);
C("所有 src 均等于记录展示层（整帧）", srcMatch, true);
C("无 data URI 裁剪残留", await ev(`Array.from(document.querySelectorAll('.kinfig img')).every(i=>!i.src.startsWith('data:image'))`), true);

console.log("=== 3. 焦点放大是纯 transform（布局零位移）===");
const posBefore = await ev(`Array.from(document.querySelectorAll('.kinfig')).map(f=>f.offsetLeft)`);
await ev(`PlaygroundKin.setFocus(${midIdx})`);
await sleep(800);
const posAfter = await ev(`Array.from(document.querySelectorAll('.kinfig')).map(f=>f.offsetLeft)`);
C("offsetLeft 全不变（scale 不占布局）", posAfter, posBefore);
T("focus 图 scale>1", await ev(`getComputedStyle(document.querySelectorAll('.kinfig')[${midIdx}]).transform !== 'none'`));
C(`focus 索引=${midIdx}`, await ev(`PlaygroundKin.focusIndex()`), midIdx);
// 居中锁定：焦点在正中
const off = await ev(`
(() => {
  const f = document.querySelectorAll('.kinfig')[PlaygroundKin.focusIndex()];
  const c = f.offsetLeft + f.offsetWidth/2 + PlaygroundKin.panX();
  return Math.round(c - document.getElementById('kinwrap').clientWidth/2);
})()`);
C("焦点居中（off≈0）", off, 0);

console.log("=== 4. 触控板滑动：wheel 事件平移 + 吸附 ===");
const startIdx = N >= 3 ? 1 : 0;
await ev(`PlaygroundKin.setFocus(${startIdx})`);
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
const off2 = await ev(`
(() => {
  const f = document.querySelectorAll('.kinfig')[PlaygroundKin.focusIndex()];
  const c = f.offsetLeft + f.offsetWidth/2 + PlaygroundKin.panX();
  return Math.round(c - document.getElementById('kinwrap').clientWidth/2);
})()`);
C("吸附后焦点居中（off≈0）", off2, 0);
T(`焦点已离开起始位（${startIdx}→${await ev("PlaygroundKin.focusIndex()")}）`, (await ev(`PlaygroundKin.focusIndex()`)) !== startIdx);
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
C("淡出中条带未拆", during.stripStill, N);
await sleep(600);  // 460ms 清理已执行
const after = await ev(`({ kinon: document.getElementById('lb').classList.contains('kinon'), strip: document.querySelectorAll('.kinfig').length })`);
C("清理后 kinon 移除", after.kinon, false);
C("清理后条带拆除", after.strip, 0);

console.log("=== 7. 重开正常 + 无关联组回退引擎单图 ===");
await ev(`openLB(Playground.records.find(r=>r.id==='${TG.mid}'))`);
await sleep(900);
C("重开条带张数一致", await ev(`document.querySelectorAll('.kinfig').length`), N);
await ev(`closeLB()`); await sleep(700);
const freeId = await ev(`
(() => {
  const inGroup = new Set(PlaygroundKin.groups().flatMap(g=>g.members));
  const f = Playground.records.find(r => !inGroup.has(r.id));
  return f ? f.id : null;
})()`);
if (freeId) {
  await ev(`openLB(Playground.records.find(r=>r.id==='${freeId}'))`);
  await sleep(700);
  C("无关联组不加 kinon", await ev(`document.getElementById('lb').classList.contains('kinon')`), false);
  C("引擎单图 frame 可见", await ev(`getComputedStyle(document.querySelector('#lb .frame')).display !== 'none'`), true);
  await ev(`closeLB()`); await sleep(700);
} else {
  console.log("  ⚠ 全部图片都已入组，跳过「无关联组回退」两条断言");
}

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
