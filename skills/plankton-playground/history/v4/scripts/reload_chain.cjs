/**
 * reload_chain.cjs — 模拟连续刷新的接力验证。
 *
 * 机制：每次加载后把 __ppSizeMem（本次宽度表）取出，作为下一次加载的 __ppSizeMemSeed 注入，
 * 精确复刻真实浏览器「刷新 → 读记忆 → 强制跳变 → 写记忆」的链条。
 *
 * 验收判据（逐次刷新、逐图块）：
 *   1. 跳变保证：|w_new − w_prev| ≥ sizeJumpMin × w_prev，或落入"区间太窄"退化名单（须极少）
 *   2. 范围约束：所有宽度都在 [wLo, wHi] 且 h ≤ hCap（尺寸不越出既定范围）
 *   3. 多样性：连续多次加载不出现 A/B 两值乒乓（周期 ≤2 的振荡图块数应为 0）
 *   4. 位置随机：布局坐标每次不同（沿用 v2 机制，抽查即可）
 *
 * 用法: node reload_chain.cjs <入口.html> <configJSON> [vw] [vh] [reloadCount] [focusId]
 */
const fs = require("fs");
const vm = require("vm");

const html = fs.readFileSync(process.argv[2], "utf8");
const cfg = JSON.parse(process.argv[3] || "{}");
const vw = +(process.argv[4] || 1440), vh = +(process.argv[5] || 900);
const reloads = +(process.argv[6] || 12);
const focusId = process.argv[7] || "DSC_1297";

function mkEl() {
  const el = {
    style: {}, classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    dataset: {}, addEventListener() {}, appendChild() {}, querySelector() { const i = mkEl(); i.dataset.image = "x"; return i; },
    remove() {}, getContext() { return { clearRect() {}, beginPath() {}, arc() {}, fill() {}, createRadialGradient() { return { addColorStop() {} }; }, set fillStyle(v) {} }; },
  };
  Object.defineProperty(el, "innerHTML", { set() {}, get() { return ""; } });
  return el;
}
const blocks = html.match(/<script>([\s\S]*?)<\/script>/g) || [];
let ENGINE = "", RECORDS = null;
for (const b of blocks) {
  const body = b.replace(/^<script>|<\/script>$/g, "");
  if (body.indexOf("window.PLAYGROUND_DATA") >= 0 && body.indexOf("function layout") < 0) {
    const c = vm.createContext({ window: {}, JSON });
    vm.runInContext(body + "\n;globalThis.__W=window;", c);
    const d = vm.runInContext("__W.PLAYGROUND_DATA", c);
    if (d && d.records) RECORDS = d.records;
  }
  if (body.indexOf("function layout") >= 0) ENGINE = body;
}
if (!RECORDS || !ENGINE) throw new Error("未能取出引擎块或记录");

// 存储桩：模拟 localStorage
function mkStorage() {
  const m = new Map();
  return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: k => m.delete(k) };
}
const storage = mkStorage();   // 全链条共享同一存储，等价于同一浏览器

let memSeed = null;
const chain = [];              // 每次加载的 {id→w} 表
const posChain = [];           // 每次加载的 {id→[cx,cy]}（位置随机性抽查）

for (let load = 0; load < reloads; load++) {
  const field = mkEl();
  Object.defineProperty(field.style, "height", { set() {}, get() { return "6000px"; }, configurable: true });
  const win = { innerWidth: vw, innerHeight: vh, scrollY: 0, PLAYGROUND_DATA: { records: RECORDS, config: cfg } };
  if (memSeed) win.__ppSizeMemSeed = memSeed;
  const ctx = vm.createContext({
    window: win, localStorage: storage,
    document: { getElementById: id => (id === "field" ? field : mkEl()), createElement: mkEl },
    Math, JSON, Object, Array, Set, Map, WeakSet, String, Number, Boolean, Date, RegExp,
    Image: function () { return { addEventListener() {}, set src(v) {}, classList: { add() {} }, dataset: {} }; },
    parseFloat, parseInt, isNaN, console: { warn() {}, log() {} },
    setTimeout: () => 0, clearTimeout() {},
    innerWidth: vw, innerHeight: vh,
    addEventListener() {}, matchMedia: () => ({ matches: vw < 720 }), requestAnimationFrame: () => 0,
  });
  vm.runInContext(ENGINE + "\n;globalThis.__T=tiles;", ctx);
  const T = vm.runInContext("__T", ctx);
  const widths = {}, pos = {};
  for (const t of T) { widths[t.d.id] = t.w; pos[t.d.id] = [t.cx, t.cy]; }
  chain.push(widths); posChain.push(pos);
  // 记忆链通过 localStorage 桩传递（引擎 persist 步骤写入），等价于同一浏览器的连续刷新
  const rawMem = storage.getItem("pp.sizeMem.v1");
  memSeed = rawMem ? JSON.parse(rawMem) : null;
  if (!memSeed && cfg.sizeJumpMin > 0) { console.log("!! 引擎未写入记忆，接力中断"); break; }
}

console.log(`\n== 接力刷新 ${chain.length} 次 · ${vw}x${vh} · sizeJumpMin=${cfg.sizeJumpMin} sizeSpread=${cfg.sizeSpread} ==`);

const j = cfg.sizeJumpMin;
let viol = 0, violTiles = new Set(), degrade = 0;
for (let k = 1; k < chain.length; k++) {
  for (const id of Object.keys(chain[k])) {
    const p = chain[k - 1][id], n = chain[k][id];
    if (p == null || n == null) continue;
    if (Math.abs(n - p) < j * p - 0.5) {
      // 允许 ±0.5px 舍入误差；再查是否属于"区间太窄"退化（无法区分，计入 viol 供人工看）
      viol++; violTiles.add(id);
    }
  }
}
console.log(`\n【1. 跳变保证】相邻两次加载差距 < ${j}×prev 的事件: ${viol} 次（涉及 ${violTiles.size} 张）`);
if (violTiles.size) console.log("   涉及图块: " + [...violTiles].slice(0, 12).join(" "));

// 2. 范围约束
const MOB = vw < 720;
const loF0 = MOB ? 0.228 : 0.113, hiF0 = MOB ? 0.26 : 0.143;
const C = (loF0 + hiF0) / 2, H = (hiF0 - loF0) / 2, sp = cfg.sizeSpread || 1;
const wLo = Math.round(vw * Math.max(0.045, C - H * sp)), wHi = Math.round(vw * (C + H * sp));
const hCap = Math.round(vh * 0.42);
let outOfRange = 0, hOver = 0;
for (const widths of chain) {
  for (const [id, w] of Object.entries(widths)) {
    if (w < wLo - 1 || w > wHi + 1) outOfRange++;
    const rec = RECORDS.find(r => r.id === id);
    const ratio = rec ? (rec.h || 3) / (rec.w || 4) : 0.75;
    if (Math.round(w * ratio) > hCap + 1) hOver++;
  }
}
console.log(`【2. 范围约束】[${wLo}, ${wHi}]px 越界事件: ${outOfRange}   高度帽(${hCap}px)超限: ${hOver}`);

// 3. 乒乓振荡检测：某图块序列是否只有 ≤2 个不同值（A/B 来回弹）
let pingpong = 0;
for (const id of Object.keys(chain[0])) {
  const seq = chain.map(c => c[id]).filter(x => x != null);
  if (new Set(seq).size <= 2) pingpong++;
}
console.log(`【3. 无乒乓】跨 ${chain.length} 次加载取值 ≤2 个的图块: ${pingpong} 张（应为 0）`);

// 4. 位置随机性抽查（focus 图块的坐标是否每次都变）
const fseq = posChain.map(p => p[focusId] ? p[focusId].join(",") : "?");
console.log(`【4. 位置随机】${focusId} 各次加载坐标: ${fseq.slice(0, 6).join(" | ")}${fseq.length > 6 ? " | …" : ""}`);
console.log(`   坐标不同次数: ${new Set(fseq).size}/${fseq.length}`);

// focus 图块的宽度序列（用户指认的图）
const wseq = chain.map(c => c[focusId]).filter(x => x != null);
console.log(`\n【${focusId} 宽度序列】${wseq.join(" → ")}`);
console.log(`   不同值 ${new Set(wseq).size} 个 / ${wseq.length} 次加载   范围 ${Math.min(...wseq)}–${Math.max(...wseq)}px`);
const deltas = [];
for (let k = 1; k < wseq.length; k++) deltas.push(Math.abs(wseq[k] - wseq[k - 1]) / wseq[k - 1]);
console.log(`   相邻变化率: 最小 ${(Math.min(...deltas) * 100).toFixed(1)}%  中位 ${(deltas.slice().sort((a, b) => a - b)[deltas.length >> 1] * 100).toFixed(1)}%  最大 ${(Math.max(...deltas) * 100).toFixed(1)}%`);
console.log("");
