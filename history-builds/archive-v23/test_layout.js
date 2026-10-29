// 独立航迹 + 运行时碰撞消解的仿真验证
// 与静态算法不同：必须真实逐帧推进 advance()，检查每帧结果
const fs = require("fs");
const vm = require("vm");
const dir = __dirname;
const argv = process.argv.slice(2);
const VW = +(argv[0] || 1440), VH = +(argv[1] || 900);
const dataJs = fs.readFileSync(dir + "/assets/data.js", "utf8");
const html = fs.readFileSync(dir + "/blackwater-plankton-archive.html", "utf8");
const js = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function mkEl() {
  const el = { style: {}, classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    dataset: {}, addEventListener() {}, appendChild() {}, querySelector() { const i = mkEl(); i.dataset.image = "https://x"; return i; }, remove() {},
    set src(v) {}, get src() { return ""; }, set alt(v) {},
    getContext() { return { clearRect() {}, beginPath() {}, arc() {}, fill() {},
      createRadialGradient() { return { addColorStop() {} }; }, set fillStyle(v) {} }; } };
  Object.defineProperty(el, "innerHTML", { set() {}, get() { return ""; } });
  return el;
}
const field = mkEl();
let FIELDH = 0;
Object.defineProperty(field.style, "height", {
  set(v) { FIELDH = parseFloat(v); }, get() { return FIELDH + "px"; }, configurable: true
});
const canvas = mkEl();
canvas.getContext = () => ({ clearRect() {}, beginPath() {}, arc() {}, fill() {}, set fillStyle(v) {} });
const doc = { getElementById: id => (id === "field" ? field : (id === "snow" || id === "fg") ? canvas : mkEl()), createElement: mkEl };
const ctx = vm.createContext({
  window: { innerWidth: VW, innerHeight: VH }, document: doc,
  Math, JSON, Object, Array, Set, Map, String, Number, Boolean, Date, RegExp,
  Image: function () { return { addEventListener() {}, set src(v) {} }; },
  parseFloat, parseInt, isNaN, console,
  setTimeout: () => 0, clearTimeout() {},
  innerWidth: VW, innerHeight: VH,
  addEventListener() {}, matchMedia: () => ({ matches: false }), requestAnimationFrame: () => 0,
});
vm.runInContext(dataJs, ctx);
vm.runInContext(js + "\n;globalThis.__T=tiles;", ctx);
const tiles = vm.runInContext("__T", ctx);

let fail = 0;
function check(name, cond, detail) {
  console.log((cond ? "PASS" : "FAIL") + "  " + name + (detail ? "  → " + detail : ""));
  if (!cond) fail++;
}
console.log(`== 视口 ${VW}x${VH} 长卷 ${(FIELDH / VH).toFixed(1)}屏 ==`);
check("tiles = 93", tiles.length === 93, tiles.length);
check("无共享洋流残留", !/CUR\.ax|const CUR =/.test(js));

/* 1. 运动独立性：各图频率/相位/半径均不同 */
const wxs = new Set(tiles.map(t => t.wx.toFixed(4)));
const rxs = new Set(tiles.map(t => t.rx.toFixed(1)));
const dirs90 = tiles.map(t => Math.sign((t.ox||0) + Math.sin(90 * t.wx + t.phx) * t.rx));
const leftN = dirs90.filter(d => d < 0).length, rightN = dirs90.filter(d => d > 0).length;
check("运动反同步（90s时左右方向都≥15张）", leftN >= 15 && rightN >= 15,
  `向左 ${leftN} / 向右 ${rightN} / 原地 ${93-leftN-rightN}`);

/* 2. 单图位移明显：每图在自己轨道上走的距离（2*rx）应可察觉 */
const travel = tiles.map(t => 2 * t.rx);   // 对称核行程
check("单图巡游距离明显（桌面≥40/手机≥24）",
  travel.sort((a, b) => a - b)[Math.floor(travel.length / 2)] >= (VW < 720 ? 24 : 40),
  `中位 ${Math.round(travel[Math.floor(travel.length / 2)])}px, 最大 ${Math.round(Math.max(...travel))}px`);

/* 3. 纵向分布均匀：大小不按 y 分层 */
const H0 = FIELDH;
const seg = Array.from({ length: 10 }, () => ({ n: 0, wsum: 0 }));
for (const t of tiles) { const k = Math.min(9, Math.floor(t.cy / (H0 / 10))); seg[k].n++; seg[k].wsum += t.w; }
const segW = seg.map(s => s.n ? Math.round(s.wsum / s.n) : 0);
const grad = Math.max(...segW) / Math.min(...segW.filter(x => x));
check("纵向大小均匀（梯度<1.5）", grad < 1.5, segW.join(",") + " 比 " + grad.toFixed(2));
const last3 = seg.slice(7).reduce((a, s) => a + s.n, 0) / 3;
check("底部无堆积（末3段均值≤全卷1.4倍）", last3 <= (tiles.length / 10) * 1.4,
  `末3段 ${last3.toFixed(1)} vs 均值 ${(tiles.length / 10).toFixed(1)} 张/段`);

/* 4. 首屏密度 */
const fold = tiles.filter(t => t.cy < VH && t.cy + t.h > 0).length;
check("首屏 ≥ 10 张（均值目标由屏数断言保证）", fold >= 10, fold);

/* 5. 逐帧推进：真实运行 advance()，检查每帧碰撞与越界 */
let worstOverlap = 0, overlapFrames = 0, outFrames = 0;
/* 硬标准：图框矩形在每一帧零相交（±1px 容差） */
const SUB0 = 0;
for (let step = 0; step <= 600; step++) {
  const s = step * 0.2;
  vm.runInContext(`advance(${s})`, ctx);
  const pos = tiles.map(t => ({
    x: t.cx + (t.ox||0) + Math.sin(s * t.wx + t.phx) * t.rx,
    y: t.cy + (t.oy||0) + Math.sin(s * t.wy + t.phy) * t.ry,
    w: t.w, h: t.h }));
  let pen = 0, cnt = 0;
  for (let i = 0; i < pos.length; i++)
    for (let j = i + 1; j < pos.length; j++) {
      const a = pos[i], b = pos[j];
      const ox = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
      if (ox <= 1) continue;
      const oy = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
      if (oy <= 1) continue;
      cnt++; pen = Math.max(pen, Math.min(ox, oy));
    }
  if (cnt) overlapFrames++;
  worstOverlap = Math.max(worstOverlap, pen);
  const out = pos.some(p => p.x < -1 || p.y < -1 || p.x + p.w > VW + 1 || p.y + p.h > H0 + 1);
  if (out) outFrames++;
}
check("600帧推进无越界(图框)", outFrames === 0, outFrames + " 帧");
check("图框零相交（600帧·穿透≤1px）", worstOverlap <= 1 && overlapFrames === 0,
  `最深 ${worstOverlap.toFixed(1)}px, 有相交帧 ${overlapFrames}/601`);
/* 禁飞区：锚点与轨道全区间都不得进入左右 MX 带 */
const MXb = VW < 720 ? 24 : 70;
let zoneBad = 0;
for (const t of tiles) {
  if (t.cx + (t.ox||0) - t.rx < MXb - 1 || t.cx + (t.ox||0) + t.rx + t.w > VW - MXb + 1) zoneBad++;
}
check("左右禁飞区零侵犯", zoneBad === 0, zoneBad + " 张越区");
check("兜底放置 = 0（画布容量充足）", (vm.runInContext("typeof FALLBACK_N", ctx) === "undefined") || vm.runInContext("FALLBACK_N", ctx) === 0);
console.log(fail ? "==> " + fail + " 项失败" : "==> 全部通过");
process.exit(fail ? 1 : 0);
