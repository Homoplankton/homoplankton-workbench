// measure_focus.mjs — 实测焦点图的显示尺寸 vs 裁剪原始尺寸，判断是否需要更高分辨率
// 同时确认 r.full 是「整帧照片」还是「主体裁剪」——若是整帧，焦点图不能用它（会重新错位）
const PORT = process.env.PORT || "9372";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const targets = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
const page = targets.find((t) => t.type === "page" && t.url.includes("blackwater-plankton-archive"));
if (!page) { console.error("找不到站点页面"); process.exit(2); }

const ws = new WebSocket(page.webSocketDebuggerUrl);
let _id = 0; const pend = new Map();
const send = (method, params = {}) => new Promise((res, rej) => {
  const id = ++_id; pend.set(id, { res, rej });
  ws.send(JSON.stringify({ id, method, params }));
  setTimeout(() => { if (pend.has(id)) { pend.delete(id); rej(new Error("timeout " + method)); } }, 25000);
});
ws.onmessage = (e) => {
  const m = JSON.parse(e.data);
  if (m.id && pend.has(m.id)) { const { res, rej } = pend.get(m.id); pend.delete(m.id); m.error ? rej(new Error(m.error.message)) : res(m.result); }
};
await new Promise((r) => (ws.onopen = r));
await send("Runtime.enable");
const ev = async (x) => {
  const r = await send("Runtime.evaluate", { expression: x, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || JSON.stringify(r.exceptionDetails));
  return r.result.value;
};
await sleep(1500);

console.log("视口:", JSON.stringify(await ev(`({ w: innerWidth, h: innerHeight })`)));

// 打开 K3（4 张组，h=38vh）
await ev(`openLB(Playground.records.find(r=>r.id==='DSC_1060'))`);
await sleep(1600);

const meas = await ev(`
(() => {
  const fs = Array.from(document.querySelectorAll('.kinfig'));
  const fi = PlaygroundKin.focusIndex();
  return fs.map((f, i) => {
    const im = f.querySelector('img');
    const cs = getComputedStyle(f);
    return {
      idx: i, focus: i === fi,
      显示: [Math.round(im.clientWidth), Math.round(im.clientHeight)],
      原图: [im.naturalWidth, im.naturalHeight],
      放大倍数: +(im.clientHeight / im.naturalHeight).toFixed(2),
      scale: cs.transform
    };
  });
})()`);
console.log("\n=== 焦点图/邻图 显示尺寸 vs 裁剪原始尺寸 ===");
meas.forEach((m) => console.log(`  [${m.idx}]${m.focus ? " 焦点" : "     "} 显示 ${m.显示}  原图 ${m.原图}  放大 ${m.放大倍数}×  transform=${m.scale}`));

// r.full 到底是什么：整帧还是裁剪？用长宽比与 records 的 w/h 比对
const fullProbe = await ev(`
(() => {
  const r = Playground.records.find(x=>x.id==='DSC_1060');
  return { keys: Object.keys(r), src: (r.src||'').slice(-46), full: (r.full||'').slice(-46),
           recWH: [r.w, r.h] };
})()`);
console.log("\n=== record 字段（判断 r.full 语义）===");
console.log(" ", JSON.stringify(fullProbe, null, 1));

// 实测 r.full 的真实像素尺寸与长宽比
const fullDims = await ev(`
new Promise(res => {
  const r = Playground.records.find(x=>x.id==='DSC_1060');
  const url = r.full || r.src;
  const im = new Image();
  im.onload = () => res({ url尾: url.slice(-40), w: im.naturalWidth, h: im.naturalHeight,
                          比: +(im.naturalWidth/im.naturalHeight).toFixed(3) });
  im.onerror = () => res({ error: true, url尾: url.slice(-40) });
  im.src = url;
})`);
console.log("\n=== r.full 实测尺寸 ===");
console.log(" ", JSON.stringify(fullDims));

// 裁剪图的长宽比（对比用）
const cropDims = await ev(`
(() => {
  const im = document.querySelector('.kinfig img');
  return { w: im.naturalWidth, h: im.naturalHeight, 比: +(im.naturalWidth/im.naturalHeight).toFixed(3) };
})()`);
console.log("  裁剪图尺寸:", JSON.stringify(cropDims));

ws.close();
process.exit(0);
