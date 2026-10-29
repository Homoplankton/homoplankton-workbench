/**
 * check_equivalence.mjs — 引擎改动后的回归门：
 * 证明 morph=0 时新模板与 v23 基线逐帧坐标一致（偏差 <0.01px）。
 * 用法: node check_equivalence.mjs <v23基线.html> <新模板.html> <data.sample.js> [vw] [vh] [seed]
 */
// 模板等价性验证：同一视口下，模板(morph=0)与 v23 原版逐帧坐标完全一致
const fs = require("fs");
const vm = require("vm");
const [, , v23Path, tplPath, dataPath, VW = "1440", VH = "900", SEED = "42"] = process.argv;
const vw = +VW, vh = +VH;

function mkEl() {
  const el = { style: {}, classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    dataset: {}, addEventListener() {}, appendChild() {}, querySelector() { const i = mkEl(); i.dataset.image = "https://x"; return i; }, remove() {},
    set src(v) {}, get src() { return ""; }, set alt(v) {},
    getContext() { return { clearRect() {}, beginPath() {}, arc() {}, fill() {}, createRadialGradient() { return { addColorStop() {} }; }, set fillStyle(v) {} }; } };
  Object.defineProperty(el, "innerHTML", { set() {}, get() { return ""; } });
  return el;
}
// 确定性随机：mulberry32 替换 Math.random
function seeded(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function load(htmlPath, asPlayground) {
  const html = fs.readFileSync(htmlPath, "utf8");
  const js = html.match(/<script>([\s\S]*?)<\/script>\s*<\/body>/) ? html.match(/<script>([\s\S]*?)<\/script>\s*<\/body>/)[1] : html.match(/<script>([\s\S]*?)<\/script>/g).pop().replace(/^<script>|<\/script>$/g, "");
  let fieldH = 0;
  const field = mkEl();
  Object.defineProperty(field.style, "height", { set(v) { fieldH = parseFloat(v); }, get() { return fieldH + "px"; }, configurable: true });
  const canvas = mkEl();
  const doc = { getElementById: id => (id === "field" ? field : canvas), createElement: mkEl };
  const ctx = vm.createContext({
    window: { innerWidth: vw, innerHeight: vh, scrollY: 0, PLAYGROUND_DATA: asPlayground ? JSON.parse(fs.readFileSync(dataPath, "utf8").replace(/^window\.PLAYGROUND_DATA\s*=\s*/, "").replace(/;\s*$/, "")) : undefined },
    document: doc, Math: Object.assign(Object.create(Math), { random: seeded(+SEED) }),
    JSON, Object, Array, Set, Map, String, Number, Boolean, Date, RegExp,
    Image: function () { return { addEventListener() {}, set src(v) {} }; },
    parseFloat, parseInt, isNaN, console: { warn() {} },
    setTimeout: () => 0, clearTimeout() {},
    innerWidth: vw, innerHeight: vh,
    addEventListener() {}, matchMedia: () => ({ matches: false }), requestAnimationFrame: () => 0,
  });
  // 同一份记录，按两种 schema 分别装载（v23 用 BW_DATA 数组，模板用 PLAYGROUND_DATA 对象）
  const sample = fs.readFileSync(dataPath, "utf8");
  const payload = JSON.parse(sample.replace(/^window\.PLAYGROUND_DATA\s*=\s*/, "").replace(/;\s*$/, ""));
  if (asPlayground) {
    ctx.window.PLAYGROUND_DATA = payload;
  } else {
    ctx.window.BW_DATA = payload.records.map(r => ({ id: r.id, u: r.src, fu: r.full, w: r.w, h: r.h, box: r.box }));
  }
  vm.runInContext(js + "\n;globalThis.__T=tiles;globalThis.__adv=advance;", ctx);
  return { ctx, fieldH: () => fieldH };
}
const a = load(v23Path, false);
const b = load(tplPath, true);
const ta = vm.runInContext("__T", a.ctx), tb = vm.runInContext("__T", b.ctx);
let fail = 0;
function chk(n, c, d) { console.log((c ? "PASS" : "FAIL") + "  " + n + (d ? "  → " + d : "")); if (!c) fail++; }
chk("记录数一致", ta.length === tb.length, `${ta.length} vs ${tb.length}`);
chk("画布高度一致", a.fieldH() === b.fieldH(), `${a.fieldH()} vs ${b.fieldH()}`);
// 逐帧比对 300 帧
let maxDiff = 0;
for (let step = 0; step <= 300; step++) {
  const s = step * 0.4;
  vm.runInContext(`__adv(${s},0.016)`, a.ctx);
  vm.runInContext(`__adv(${s},0.016)`, b.ctx);
  for (let i = 0; i < ta.length; i++) {
    maxDiff = Math.max(maxDiff, Math.abs(ta[i].px - tb[i].px), Math.abs(ta[i].py - tb[i].py));
  }
}
chk("300帧逐帧坐标一致（morph=0）", maxDiff < 0.01, "最大偏差 " + maxDiff.toFixed(4) + "px");
// API 存在性
const hasApi = vm.runInContext("typeof Playground==='object' && typeof Playground.on==='function' && typeof Playground.relayout==='function'", b.ctx);
chk("Playground API 已暴露", hasApi === true);
console.log(fail ? "==> " + fail + " 项失败" : "==> 全部通过");
process.exit(fail ? 1 : 0);
