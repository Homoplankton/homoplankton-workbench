/**
 * rsize_concentration.cjs — 量化「尺寸是否只在两三个值之间跳」。
 *
 * 上一版只数了 distinct 个数（桌面 22–36 个），却没看**分布集中度**：
 * 若 90% 的加载都落在同样两个值上，distinct 再多也等于「只有两档」，
 * 用户看到的就是来回切换。必须按可观察语义量：前 N 个高频值覆盖多少比例的加载。
 *
 * 同时验证成因假设：w 被 clamp 到带边界（W*loF / W*hiF）会产生精确重复的尖峰，
 * 而 screenScale 的乘子在 box 饱和时只有 0.82 / 1.036 两个取值。
 *
 * 用法: node rsize_concentration.cjs <入口.html> <configJSON> [vw] [vh] [loads]
 */
const fs = require("fs");
const vm = require("vm");

const html = fs.readFileSync(process.argv[2], "utf8");
const cfg = JSON.parse(process.argv[3] || "{}");
const vw = +(process.argv[4] || 1440), vh = +(process.argv[5] || 900), loads = +(process.argv[6] || 60);

function mkEl() {
  const el = {
    style: {}, classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    dataset: {}, addEventListener() {}, appendChild() {}, querySelector() { const i = mkEl(); i.dataset.image = "x"; return i; },
    remove() {}, getContext() { return { clearRect() {}, beginPath() {}, arc() {}, fill() {}, createRadialGradient() { return { addColorStop() {} }; }, set fillStyle(v) {} }; },
  };
  Object.defineProperty(el, "innerHTML", { set() {}, get() { return ""; } });
  return el;
}
function seeded(s) {
  let a = s >>> 0;
  return () => { a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
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

const MOB = vw < 720;
const loF0 = MOB ? 0.228 : 0.113, hiF0 = MOB ? 0.26 : 0.143;
const spread = cfg.sizeSpread || 1;
const C = (loF0 + hiF0) / 2, H = (hiF0 - loF0) / 2;
const loF = Math.max(0.045, C - H * spread), hiF = C + H * spread;
const wLo = Math.round(vw * loF), wHi = Math.round(vw * hiF);

function one(seed) {
  const field = mkEl();
  Object.defineProperty(field.style, "height", { set() {}, get() { return "6000px"; }, configurable: true });
  const ctx = vm.createContext({
    window: { innerWidth: vw, innerHeight: vh, scrollY: 0, PLAYGROUND_DATA: { records: RECORDS, config: cfg } },
    document: { getElementById: id => (id === "field" ? field : mkEl()), createElement: mkEl },
    Math: Object.assign(Object.create(Math), { random: seeded(seed) }),
    JSON, Object, Array, Set, Map, WeakSet, String, Number, Boolean, Date, RegExp,
    Image: function () { return { addEventListener() {}, set src(v) {}, classList: { add() {} }, dataset: {} }; },
    parseFloat, parseInt, isNaN, console: { warn() {}, log() {} },
    setTimeout: () => 0, clearTimeout() {},
    innerWidth: vw, innerHeight: vh,
    addEventListener() {}, matchMedia: () => ({ matches: MOB }), requestAnimationFrame: () => 0,
  });
  vm.runInContext(ENGINE + "\n;globalThis.__T=tiles;", ctx);
  return vm.runInContext("__T", ctx);
}

const byId = new Map();
for (let i = 0; i < loads; i++) {
  for (const t of one(1000 + i * 7919)) {
    if (!byId.has(t.d.id)) byId.set(t.d.id, { ws: [], d: t.d });
    byId.get(t.d.id).ws.push(t.w);
  }
}

console.log(`\n== ${vw}x${vh} · ${loads} 次加载 · 带边界 [${wLo}, ${wHi}]px · spread=${spread} ==`);

// 每张：按频次排序，看前1/前2/前3个值覆盖多少比例的加载
const cov1 = [], cov2 = [], cov3 = [], nDistinct = [];
const atBound = { lo: 0, hi: 0 };
const detail = [];
for (const [id, e] of byId) {
  const freq = new Map();
  for (const w of e.ws) freq.set(w, (freq.get(w) || 0) + 1);
  const sorted = [...freq.entries()].sort((a, b) => b[1] - a[1]);
  cov1.push(sorted[0][1] / loads);
  cov2.push(sorted.slice(0, 2).reduce((a, b) => a + b[1], 0) / loads);
  cov3.push(sorted.slice(0, 3).reduce((a, b) => a + b[1], 0) / loads);
  nDistinct.push(sorted.length);
  const loShare = (freq.get(wLo) || 0) / loads, hiShare = (freq.get(wHi) || 0) / loads;
  if (loShare > 0.3) atBound.lo++;
  if (hiShare > 0.3) atBound.hi++;
  detail.push({ id, sorted: sorted.slice(0, 4), n: sorted.length, cov2: cov2[cov2.length - 1], loShare, hiShare,
    ratio: (e.d.h || 3) / (e.d.w || 4), box: e.d.box });
}
const avg = xs => xs.reduce((a, b) => a + b, 0) / xs.length;
const srt = xs => xs.slice().sort((a, b) => a - b);
const c1 = srt(cov1), c2 = srt(cov2), c3 = srt(cov3), nd = srt(nDistinct);
const q = (xs, p) => xs[Math.floor(xs.length * p)];

console.log(`\n【分布集中度 —— 前 N 个高频值覆盖的加载比例】`);
console.log(`  前1个值覆盖: 中位 ${q(c1,0.5).toFixed(2)}  p90 ${q(c1,0.9).toFixed(2)}  最大 ${c1[c1.length-1].toFixed(2)}`);
console.log(`  前2个值覆盖: 中位 ${q(c2,0.5).toFixed(2)}  p90 ${q(c2,0.9).toFixed(2)}  最大 ${c2[c2.length-1].toFixed(2)}`);
console.log(`  前3个值覆盖: 中位 ${q(c3,0.5).toFixed(2)}  p90 ${q(c3,0.9).toFixed(2)}  最大 ${c3[c3.length-1].toFixed(2)}`);
console.log(`  不同取值个数: 中位 ${nd[nd.length>>1]}  最少 ${nd[0]}  最多 ${nd[nd.length-1]}`);
console.log(`\n【判定】`);
const bimodal = detail.filter(d => d.cov2 >= 0.75).length;
console.log(`  前2值覆盖 ≥75% 加载的图块: ${bimodal}/${detail.length} (${(bimodal/detail.length*100).toFixed(0)}%)  ← 用户说的「只有两档」`);
console.log(`  高频贴下界(${wLo}px)的图块: ${atBound.lo} 张   高频贴上界(${wHi}px)的图块: ${atBound.hi} 张`);

console.log(`\n【最集中的 12 张明细（前2值覆盖降序）】`);
detail.sort((a, b) => b.cov2 - a.cov2);
for (const d of detail.slice(0, 12)) {
  const top = d.sorted.map(([w, c]) => `${w}px×${(c/loads*100).toFixed(0)}%`).join(" ");
  console.log(`  ${d.id.padEnd(16)} 前2覆盖 ${(d.cov2*100).toFixed(0)}%  不同值${String(d.n).padStart(3)}个  [${top}]  贴下界${(d.loShare*100).toFixed(0)}% 贴上界${(d.hiShare*100).toFixed(0)}%`);
}

// screenScale 乘子是否饱和成两档
function screenScale(d) {
  if (!d.box) return 0.62;
  const f = Math.max(d.box[2] - d.box[0], (d.box[3] - d.box[1]) * 0.75);
  return Math.min(1.15, Math.max(0.55, 0.6 / Math.max(f, 0.18)));
}
const mults = [...byId.values()].map(e => +(0.82 + 0.36 * (screenScale(e.d) - 0.55)).toFixed(4));
const mf = new Map();
for (const m of mults) mf.set(m, (mf.get(m) || 0) + 1);
console.log(`\n【screenScale 乘子分布（决定 w 的缩放）】`);
console.log("  " + [...mf.entries()].sort((a,b)=>b[1]-a[1]).map(([m,c]) => `${m}×${c}张`).join("  "));
console.log("");
