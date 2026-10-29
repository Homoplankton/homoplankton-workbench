// test_cdp.mjs — 用真实浏览器交互验证工作台（非仅渲染检查）
// 方法：Chrome 远程调试 + WebSocket，注入 JS 事件模拟点击/键盘，读取真实 DOM 状态。
// 为什么不用 --dump-dom：那只能看首屏渲染，无法验证交互链路。
const PORT = process.env.PORT || 9333;
const URL_PAGE = process.env.PAGE || "";
const OUT = process.env.OUTDIR || ".";

const sleep = ms => new Promise(r => setTimeout(r, ms));
const results = [];
const check = (name, got, want) => {
  const ok = String(got).includes(String(want));
  results.push({ name, got, want, ok });
  console.log(`  ${ok ? "✓" : "✗"} ${name}: got=${got} want~${want}`);
  return ok;
};

async function main() {
  // 找到工作台 target
  let targets = [];
  for (let i = 0; i < 30; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json`);
      targets = await r.json();
      if (targets.some(t => t.url.includes("workbench.html"))) break;
    } catch (e) {}
    await sleep(700);
  }
  const tgt = targets.find(t => t.url.includes("workbench.html"));
  if (!tgt) { console.log("FATAL: 找不到工作台 target"); process.exit(1); }

  const ws = new WebSocket(tgt.webSocketDebuggerUrl);
  let id = 0; const pending = new Map();
  const send = (method, params = {}) => new Promise((res, rej) => {
    const myid = ++id;
    pending.set(myid, { res, rej });
    ws.send(JSON.stringify({ id: myid, method, params }));
  });
  ws.onmessage = ev => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) {
      const { res, rej } = pending.get(m.id); pending.delete(m.id);
      m.error ? rej(new Error(m.error.message)) : res(m.result);
    }
  };
  await new Promise(r => ws.onopen = r);
  await send("Runtime.enable");
  await send("Page.enable");
  await sleep(2500);   // 等首屏渲染完成

  const ev = async expr => {
    const r = await send("Runtime.evaluate",
      { expression: expr, returnByValue: true, awaitPromise: false });
    if (r.exceptionDetails) throw new Error("EVAL: " + JSON.stringify(r.exceptionDetails.exception?.description || r.exceptionDetails.text));
    return r.result.value;
  };

  console.log("=== 1. 首屏基础 ===");
  check("图块数", await ev("document.querySelectorAll('.tile').length"), 108);
  check("检查器当前图", await ev("document.querySelector('#insp h2')?.textContent"), "DSC_0077");

  console.log("=== 2. 点击图块选中 ===");
  await ev(`document.querySelector('.tile[data-id="DSC_0214"]').click()`);
  await sleep(200);
  check("点击后检查器切换到 DSC_0214", await ev("document.querySelector('#insp h2')?.textContent"), "DSC_0214");

  console.log("=== 3. 键盘流：1=认可 并自动跳下一条 ===");
  const before = await ev("STATE.cur");
  await ev(`document.dispatchEvent(new KeyboardEvent('keydown',{key:'1',bubbles:true}))`);
  await sleep(200);
  const ov = await ev(`JSON.stringify(OVERLAY[${JSON.stringify("DSC_0214")}]||null)`);
  check("OVERLAY 记录 verdict=confirm", ov, '"verdict":"confirm"');
  check("认可后自动跳到下一条", await ev("STATE.cur !== " + JSON.stringify(before)), "true");
  check("进度条已更新", await ev("document.getElementById('progTxt').textContent"), "1 /");
  check("localStorage 已写", await ev("(localStorage.getItem('plankton_workbench_overlay_v1')||'').includes('DSC_0214')"), "true");

  console.log("=== 4. 否决 + 清除 ===");
  await ev(`select('DSC_0933')`);
  await sleep(120);
  await ev(`document.dispatchEvent(new KeyboardEvent('keydown',{key:'3',bubbles:true}))`);
  await sleep(150);
  check("DSC_0933 已否决", await ev(`(OVERLAY['DSC_0933']||{}).verdict`), "reject");
  await ev(`delete OVERLAY['DSC_0933']; delete OVERLAY['DSC_0214']; persist(); renderNav(); renderStage(); renderInsp(); updateProgress();`);
  await sleep(150);
  check("清除后进度归零", await ev("document.getElementById('progTxt').textContent"), "0 /");

  console.log("=== 5. 待办队列筛选 ===");
  await ev(`setFilter('queue','contested')`);
  await sleep(200);
  check("contested 队列 2 张", await ev("document.querySelectorAll('.tile').length"), 2);
  check("contested 队列含 DSC_3058", await ev(`[...document.querySelectorAll('.tile')].map(t=>t.dataset.id).join(',')`), "DSC_3058");
  await ev(`setFilter('queue','lowconf')`);
  await sleep(150);
  check("lowconf 队列 6 张", await ev("document.querySelectorAll('.tile').length"), 6);
  await ev(`setFilter('queue','unidentified')`);
  await sleep(150);
  check("unidentified 队列 98 张", await ev("document.querySelectorAll('.tile').length"), 98);

  console.log("=== 6. 分类树与潜次筛选 ===");
  await ev(`setFilter('taxon','Cephalopoda')`);
  await sleep(150);
  const nc = await ev("document.querySelectorAll('.tile').length");
  check("Cephalopoda 筛选有结果", Number(nc) > 0, "true");
  await ev(`setFilter('dive','2019:12:21#1')`);
  await sleep(150);
  check("潜次 2019:12:21#1 = 5 张", await ev("document.querySelectorAll('.tile').length"), 5);

  console.log("=== 7. 搜索 ===");
  await ev(`setFilter('all','all')`);
  await sleep(120);
  await ev(`const q=document.getElementById('q'); q.value='DSC_0077'; q.dispatchEvent(new Event('input'))`);
  await sleep(200);
  check("搜索 ID 命中 1 张", await ev("document.querySelectorAll('.tile').length"), 1);
  await ev(`const q2=document.getElementById('q'); q2.value=''; q2.dispatchEvent(new Event('input'))`);
  await sleep(150);

  console.log("=== 8. 文献库 / 修正链 视图 ===");
  await ev(`setMode('refs')`);
  await sleep(200);
  check("文献库渲染 34 条唯一书目", await ev("document.querySelectorAll('#empty ul.refs li').length"), 34);
  check("文献链接带 href(34)", await ev("document.querySelectorAll('#empty ul.refs a[href^=\\'http\\' i], #empty ul.refs a').length") , 34);
  await ev(`setMode('revisions')`);
  await sleep(200);
  check("修正链渲染 6 条", await ev("document.querySelectorAll('#empty .rev').length"), 6);
  await ev(`setMode('gallery'); setFilter('queue','to_decide')`);
  await sleep(200);

  console.log("=== 9. 导出结构 ===");
  const keys = await ev(`JSON.stringify(Object.keys(exportPayload()))`);
  check("导出含 overlay/schema", keys, "overlay");
  check("导出含决策数", keys, "decisions_count");

  console.log("=== 10. 浅色模式切换 ===");
  await ev(`document.getElementById('themeBtn').click()`);
  await sleep(300);
  check("data-theme=light", await ev("document.documentElement.dataset.theme"), "light");

  // 截图（浅色）
  const shotL = await send("Page.captureScreenshot", { format: "png" });
  require0(OUT + "/wb_light.png", shotL.data);
  await ev(`document.getElementById('themeBtn').click()`);
  await sleep(300);
  const shotD = await send("Page.captureScreenshot", { format: "png" });
  require0(OUT + "/wb_dark2.png", shotD.data);
  console.log("  截图已保存 wb_light.png / wb_dark2.png");

  const bad = results.filter(r => !r.ok);
  console.log(`\n=== 结果 ${results.length - bad.length}/${results.length} 通过 ===`);
  if (bad.length) { console.log("失败项:"); bad.forEach(b => console.log("  ✗", b.name, "got=", b.got)); process.exit(2); }
  ws.close(); process.exit(0);
}

import { writeFileSync } from "node:fs";
function require0(p, b64) { writeFileSync(p, Buffer.from(b64, "base64")); }

main().catch(e => { console.log("FATAL:", e.message); process.exit(1); });
