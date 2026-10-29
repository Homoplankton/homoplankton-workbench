#!/usr/bin/env node
/**
 * verify_layout.mjs — 交付前强制验证门。
 *
 * 在无头 vm 中装载【真实页面脚本】（不是复刻品），定种随机，逐帧推进 advance()，
 * 检查图框零相交等硬约束。语法通过 ≠ 页面能看，此脚本是唯一可信的机械验证。
 *
 * 用法:
 *   node verify_layout.mjs <入口.html> <data.js> [--vw 1440] [--vh 900]
 *                          [--seeds 5] [--frames 601] [--quiet]
 * 退出码: 0 全过 / 1 有断言失败 / 2 用法或装载错误
 */
import fs from "node:fs";
import vm from "node:vm";

const argv = process.argv.slice(2);
function opt(name, dflt) {
  const i = argv.indexOf("--" + name);
  return i >= 0 && argv[i + 1] !== undefined ? argv[i + 1] : dflt;
}
const positional = argv.filter((a, i) => !a.startsWith("--") && argv[i - 1] !== undefined && !["vw", "vh", "seeds", "frames", "quiet"].includes(argv[i - 1]?.replace?.("--", "")));
const pos = argv.filter(a => !a.startsWith("--")).filter((a, i, arr) => {
  const prev = argv[argv.indexOf(a) - 1];
  return !(prev && prev.startsWith("--"));
});
if (pos.length < 2) {
  console.error("用法: node verify_layout.mjs <入口.html> <data.js> [--vw 1440 --vh 900 --seeds 5 --frames 601]");
  process.exit(2);
}
const ENTRY = pos[0], DATA = pos[1];
const VW = +opt("vw", 1440), VH = +opt("vh", 900);
const SEEDS = +opt("seeds", 5), FRAMES = +opt("frames", 601);
const QUIET = argv.includes("--quiet");

for (const f of [ENTRY, DATA]) if (!fs.existsSync(f)) { console.error("!! 文件不存在: " + f); process.exit(2); }

const html = fs.readFileSync(ENTRY, "utf8");
const scripts = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const js = scripts[scripts.length - 1];
if (!js) { console.error("!! 入口中找不到内联脚本"); process.exit(2); }
const dataJs = fs.readFileSync(DATA, "utf8");

/** mulberry32 定种随机，保证可复现 */
function rng(seed) {
  let a = seed >>> 0;
  return () => { a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
function mkEl() {
  const el = {
    style: {}, dataset: {},
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    addEventListener() {}, appendChild() {}, remove() {},
    querySelector() { const i = mkEl(); i.dataset.image = "https://x"; return i; },
    set src(v) {}, get src() { return ""; }, set alt(v) {},
    getContext() { return { clearRect() {}, beginPath() {}, arc() {}, fill() {}, createRadialGradient() { return { addColorStop() {} }; }, set fillStyle(v) {} }; },
  };
  Object.defineProperty(el, "innerHTML", { set() {}, get() { return ""; } });
  return el;
}

function runSeed(seed) {
  let fieldH = 0;
  const field = mkEl();
  Object.defineProperty(field.style, "height", { set(v) { fieldH = parseFloat(v) || 0; }, get() { return fieldH + "px"; }, configurable: true });
  const canvas = mkEl();
  const doc = { getElementById: id => (id === "field" ? field : canvas), createElement: mkEl };
  const M = Object.create(Math); M.random = rng(seed);
  const ctx = vm.createContext({
    window: { innerWidth: VW, innerHeight: VH, scrollY: 0 },
    document: doc, Math: M, JSON, Object, Array, Set, Map, String, Number, Boolean, Date, RegExp,
    Image: function () { return { addEventListener() {}, set src(v) {} }; },
    parseFloat, parseInt, isNaN, console: { warn() {}, error() {} },
    setTimeout: () => 0, clearTimeout() {}, setInterval: () => 0,
    innerWidth: VW, innerHeight: VH,
    addEventListener() {}, matchMedia: () => ({ matches: false }), requestAnimationFrame: () => 0,
  });
  vm.runInContext(dataJs, ctx);
  vm.runInContext(js + "\n;globalThis.__T=tiles;globalThis.__adv=advance;", ctx);
  const tiles = vm.runInContext("__T", ctx);
  const H0 = fieldH;

  const R = { seed, H0, tiles: tiles.length, fold: 0, cover: 0, travel: [], speed: [], weakSpd: 0, weakThr: 0, speedMin: 0, frozen: 0, envBad: 0, zoneBad: 0, pen: 0, penFrames: 0, outFrames: 0, fallback: 0, segW: [], dirL: 0, dirR: 0 };
  const E = VW < 720 ? 4 : 6, MX = VW < 720 ? 24 : 70;

  R.fold = tiles.filter(t => t.cy < VH && t.cy + t.h > 0).length;
  R.cover = tiles.filter(t => t.cy < VH && t.cy + t.h > 0).reduce((a, t) => a + t.w * t.h, 0) / (VW * VH);
  R.travel = tiles.map(t => 2 * (t.rx || 0)).sort((a, b) => a - b);
  /* 速度 = 角频率 × 振幅：sin(s·w+φ)·r 的最大速率为 w·r，两轴合成取模。
     旧版只量 2*rx（振幅），无法表达「运动是否明显」——密度提高必然压缩间隙，
     而轨道半径 = 间隙/2，故振幅必然变小；此时振幅断言会把「更快但更近」误判为退步，
     而用户要的是速度。见 lessons #9：阈值要绑定用户可观察语义，不绑定实现中间量。 */
  R.speed = tiles.map(t => Math.hypot((t.wx || 0) * (t.rx || 0), (t.wy || 0) * (t.ry || 0))).sort((a, b) => a - b);
  /* 逐图块「弱动」判定 —— 必须看最差值，不能看中位数：
     中位数天然掩盖少数被包夹的图块，而用户一眼就能看到那几张"锁住不动"的图。
     旧版两处都错：静止阈值 1px（远低于可感知下限）、断言只看中位。
     阈值按视口宽比例给，尺度无关：桌面 1440 → 约 2.6px/s，手机 390 → 约 0.7px/s。 */
  const WEAK_SPD = Math.max(1.5, VW * 0.0018);
  R.weakSpd = tiles.filter(t => Math.hypot((t.wx || 0) * (t.rx || 0), (t.wy || 0) * (t.ry || 0)) < WEAK_SPD).length;
  R.weakThr = WEAK_SPD;
  R.speedMin = R.speed[0] || 0;
  R.frozen = tiles.filter(t => Math.hypot(t.rx || 0, t.ry || 0) < 1).length;   // 完全不动的图块
  // 轨道包络与禁飞区（静态）
  for (const t of tiles) {
    if (t.cx + (t.ox || 0) - (t.rx || 0) < -1 || t.cx + (t.ox || 0) + (t.rx || 0) + t.w > VW + 1 ||
        t.cy + (t.oy || 0) - (t.ry || 0) < -1 || t.cy + (t.oy || 0) + (t.ry || 0) + t.h > H0 + 1) R.envBad++;
    if (t.cx + (t.ox || 0) - (t.rx || 0) < MX - 1 || t.cx + (t.ox || 0) + (t.rx || 0) + t.w > VW - MX + 1) R.zoneBad++;
  }
  // 纵向十等分平均宽度
  const seg = Array.from({ length: 10 }, () => ({ n: 0, w: 0 }));
  for (const t of tiles) { const k = Math.min(9, Math.floor(t.cy / (H0 / 10))); seg[k].n++; seg[k].w += t.w; }
  R.segW = seg.map(s => s.n ? Math.round(s.w / s.n) : 0);
  // 底部堆积
  R.lastThird = seg.slice(7).reduce((a, s) => a + s.n, 0) / 3;
  R.perSeg = tiles.length / 10;
  // 逐帧
  for (let f = 0; f <= FRAMES; f++) {
    const s = f * (120 / FRAMES) * 1;   // 覆盖 120 秒
    vm.runInContext(`__adv(${s}, 0.016)`, ctx);
    let cnt = 0;
    for (let i = 0; i < tiles.length; i++) {
      const a = tiles[i];
      for (let j = i + 1; j < tiles.length; j++) {
        const b = tiles[j];
        const ox = Math.min(a.px + a.w, b.px + b.w) - Math.max(a.px, b.px);
        if (ox <= 1) continue;
        const oy = Math.min(a.py + a.h, b.py + b.h) - Math.max(a.py, b.py);
        if (oy <= 1) continue;
        cnt++; R.pen = Math.max(R.pen, Math.min(ox, oy));
      }
      if (a.px < -1 || a.py < -1 || a.px + a.w > VW + 1 || a.py + a.h > H0 + 1) R.outFrames++;
    }
    if (cnt) R.penFrames++;
    if (f === Math.floor(FRAMES * 0.75)) {   // 反同步采样
      for (const t of tiles) { const v = Math.cos(s * t.wx + t.phx) * (t.rx || 0); if (v < -0.5) R.dirL++; else if (v > 0.5) R.dirR++; }
    }
  }
  try { R.fallback = vm.runInContext("typeof FALLBACK_N==='number'?FALLBACK_N:0", ctx); } catch { R.fallback = 0; }
  return R;
}

let fail = 0, pass = 0;
function chk(name, cond, detail) {
  if (cond) { pass++; if (!QUIET) console.log("PASS  " + name + (detail ? "  → " + detail : "")); }
  else { fail++; console.log("FAIL  " + name + (detail ? "  → " + detail : "")); }
}
console.log(`== ${VW}x${VH} · ${SEEDS} seeds · ${FRAMES} frames ==`);
const runs = [];
for (let i = 0; i < SEEDS; i++) runs.push(runSeed(1000 + i * 7919));

const r0 = runs[0];
const N = r0.tiles;
chk("记录数 > 0", N > 0, N);
// 画布高度断言的职责是抓「高度公式失控」事故（历史上曾算出 2 万像素级页面导致整页全黑），
// 不是限制正常规模。屏数 ∝ 张数 × 视口面积，故上限随 N 伸缩，另设绝对像素兜底。
// 密度是否合理由「首屏覆盖率」与「每屏密度」两条尺度无关断言负责。
const screensCap = Math.max(20, Math.ceil(N * 0.25));
chk(`画布高度合理（可滚动且未失控：1.5–${screensCap} 屏、< 400000px）`,
  runs.every(r => r.H0 > VH * 1.5 && r.H0 < VH * screensCap && r.H0 < 400000),
  runs.map(r => (r.H0 / VH).toFixed(1)).join("/") + " 屏");
chk("图框零相交（全部 seed × 全部帧）", runs.every(r => r.penFrames === 0 && r.pen <= 1),
  "最深 " + Math.max(...runs.map(r => r.pen)).toFixed(1) + "px, 相交帧 " + runs.reduce((a, r) => a + r.penFrames, 0));
chk("轨道包络不越画布", runs.every(r => r.envBad === 0), runs.reduce((a, r) => a + r.envBad, 0) + " 张");
chk("左右禁飞区零侵犯", runs.every(r => r.zoneBad === 0), runs.reduce((a, r) => a + r.zoneBad, 0) + " 张");
chk("推进中不越界", runs.every(r => r.outFrames === 0), runs.reduce((a, r) => a + r.outFrames, 0) + " 帧");
chk("兜底放置 = 0", runs.every(r => r.fallback === 0), runs.map(r => r.fallback).join("/"));

/* —— 以下阈值随记录数自适应：小文件夹的几何上限本就低，不能套用大库的绝对值 —— */
const avgArea = runs.reduce((s, r) => s + r.cover, 0) / runs.length;   // 首屏覆盖率均值
// 几何上限：全部图块塞进首屏时的覆盖率（用平均图块面积估算）
const tileArea = (VW < 720 ? 0.085 : 0.126) ** 2 * VW * VH * 1.2;       // 单块平均面积近似
const ceiling = Math.min(0.9, (N * tileArea) / (VW * VH));
const covTarget = Math.min(0.35, ceiling * 0.55);
chk(`首屏覆盖 ≥ ${(covTarget * 100).toFixed(0)}%（几何上限 ${(ceiling * 100).toFixed(0)}%）`,
  avgArea >= covTarget, (avgArea * 100).toFixed(1) + "%");
// 尺度无关的密度断言：每屏密度应与 N/屏数 同量级（防聚簇导致的局部稀疏），
// 另设绝对下限（防整页空白类事故）。绝对张数阈值会随张数/视口失真，已废弃。
const screensMean = runs.reduce((s, r) => s + r.H0 / VH, 0) / runs.length;
const densExpected = N / screensMean;
const foldMean = runs.reduce((s, r) => s + r.fold, 0) / runs.length;
chk(`首屏密度合理（≥0.7×每屏均值 ${densExpected.toFixed(1)} 张，且最少 ≥4 张）`,
  foldMean >= densExpected * 0.7 && Math.min(...runs.map(r => r.fold)) >= 4,
  runs.map(r => r.fold).join("/") + ` 张，均值 ${foldMean.toFixed(1)}（每屏 ${densExpected.toFixed(1)}）`);
const travMed = runs.map(r => r.travel[Math.floor(r.travel.length / 2)]);
/* 运动是否明显：用「速度 ÷ 图块宽度」作尺度无关量，而不是绝对像素振幅。
   标定依据（v23 实测）：桌面 4.84 px/s ÷ 约184px ≈ 0.026，手机 3.05 ÷ 约95px ≈ 0.032；
   取下限 0.020（约为 v23 的 62–77%），既拦住「几乎不动」，又不因密度提高、
   间隙变小导致振幅自然收缩而误判失败。绝对像素阈值会随张数/视口失真，已废弃。 */
const SPD_FLOOR = 0.020;
const spdRel = runs.map(r => {
  const ws = r.segW.filter(x => x);
  const wScale = ws.length ? ws.reduce((a, b) => a + b, 0) / ws.length : 1;
  return r.speed[Math.floor(r.speed.length / 2)] / wScale;
});
const spdMed = runs.map(r => r.speed[Math.floor(r.speed.length / 2)]);
chk(`运动明显（速度中位 ≥ ${SPD_FLOOR}×图块宽，即 ≥${(SPD_FLOOR * 100).toFixed(0)}% 宽/秒）`,
  Math.min(...spdRel) >= SPD_FLOOR,
  spdMed.map((x, i) => `${x.toFixed(2)}px/s(${(spdRel[i]).toFixed(3)})`).join(" "));
/* 逐图块弱动断言：中位数天然掩盖少数被四面包夹的图块，而用户一眼就看到那几张「锁住不动」的图。
   标定依据（桌面 1440×900 实测）：正常图块峰值速度中位 5.97px/s，最弱 1.72px/s；
   阈值 max(1.5, VW×0.0018) → 桌面约 2.6px/s，正好落在「最弱」与「p5」之间。 */
const weakThr = runs[0].weakThr;
const weakCnt = runs.map(r => r.weakSpd);
chk(`无弱动图块（逐块峰值速度 ≥ ${weakThr.toFixed(2)}px/s）`,
  runs.every(r => r.weakSpd === 0),
  weakCnt.join("/") + " 张" + (Math.max(...weakCnt) ? ` · 全体最慢 ${Math.min(...runs.map(r => r.speedMin)).toFixed(2)}px/s` : ` · 最慢 ${Math.min(...runs.map(r => r.speedMin)).toFixed(2)}px/s`));
chk("无静止图块（振幅 <1px 的张数 = 0）",
  runs.every(r => r.frozen === 0), runs.map(r => r.frozen).join("/") + " 张");
const grad = runs.map(r => { const v = r.segW.filter(x => x); return Math.max(...v) / Math.min(...v); });
chk("纵向大小均匀（梯度 < 1.5）", Math.max(...grad) < 1.5, Math.max(...grad).toFixed(2));
const pile = runs.map(r => r.lastThird / r.perSeg);
chk("底部无堆积（末3段 ≤ 1.4×均值）", Math.max(...pile) <= 1.4, Math.max(...pile).toFixed(2) + "×");
const dirMin = Math.max(2, Math.round(N * 0.12));
const sync = runs.every(r => r.dirL >= dirMin && r.dirR >= dirMin);
chk(`运动反同步（两向各 ≥${dirMin} 张）`, sync, runs[0].dirL + " 左 / " + runs[0].dirR + " 右");

console.log(fail ? `\n==> ${fail} 项失败（${pass} 通过）` : `\n==> 全部通过（${pass} 项 × ${SEEDS} seeds）`);
process.exit(fail ? 1 : 0);
