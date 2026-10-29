// test_kin3.mjs — Plankton Playground 关联图 v3（横向胶片条平移）浏览器实测
//
// 核心验证目标（用户 2026-10-27 需求）：
//   点击邻图 **不重建**，只**平移**（translateX 变、DOM 节点保持同一批）。
//   焦点图略大于两侧；居中锁定；保留错落；不显示 ID；指认机制仍在。
//
// ⚠ 断言基准沿用踩坑修正：tileById() 无 src（URL 在 records）；keydown 挂 window 需 bubbles；
//   CFG.morph 默认 0 是设计要求。
// 用法: PORT=9362 SHOT=/tmp/x.png node scripts/test_kin3.mjs

const PORT = process.env.PORT || "9362";
const sleep = ms => new Promise(r => setTimeout(r, ms));
const out = [];
const C = (name, got, want) => {
  const ok = String(got).includes(String(want));
  out.push({ name, got, ok });
  console.log(`  ${ok ? "✓" : "✗"} ${name}: ${got}`);
  return ok;
};

async function main() {
  let targets = [];
  for (let i = 0; i < 30; i++) {
    try { const r = await fetch(`http://127.0.0.1:${PORT}/json`); targets = await r.json();
      if (targets.some(t => t.url.includes("blackwater-plankton"))) break; } catch (e) {}
    await sleep(600);
  }
  const tgt = targets.find(t => t.url.includes("blackwater-plankton"));
  if (!tgt) { console.log("FATAL: 找不到站点 target"); process.exit(1); }
  const ws = new WebSocket(tgt.webSocketDebuggerUrl);
  let id = 0; const pend = new Map();
  const send = (m, p = {}) => new Promise((res, rej) => {
    const my = ++id; pend.set(my, { res, rej }); ws.send(JSON.stringify({ id: my, method: m, params: p })); });
  ws.onmessage = e => { const m = JSON.parse(e.data);
    if (m.id && pend.has(m.id)) { const { res, rej } = pend.get(m.id); pend.delete(m.id);
      m.error ? rej(new Error(m.error.message)) : res(m.result); } };
  await new Promise(r => ws.onopen = r);
  await send("Runtime.enable"); await send("Page.enable"); await sleep(4500);
  const ev = async x => { const r = await send("Runtime.evaluate",
    { expression: x, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) return "ERR:" + String(r.exceptionDetails.exception?.description || "").slice(0, 150);
    return r.result.value; };

  console.log("=== 0. 基线：核心引擎未被破坏 ===");
  C("Playground 版本", await ev("Playground.version"), "v3.1");
  C("Kin 版本 = v3", await ev("PlaygroundKin.version"), "kin-3.0");
  C("记录数", await ev("Playground.records.length"), 108);
  C("morph 默认 0", await ev("Playground.config.morph"), 0);

  console.log("=== 1. 真实路径点开 K1（5 成员）===");
  await ev(`document.querySelector('.tile[data-id="DSC_0214"]').dispatchEvent(new MouseEvent('click',{bubbles:true}))`);
  await sleep(2600);
  C("lightbox 打开", await ev("document.getElementById('lb').classList.contains('open')"), true);
  C("进入条带模式 kinon", await ev("document.getElementById('lb').classList.contains('kinon')"), true);
  C("引擎单图 frame 被隐藏", await ev("getComputedStyle(document.querySelector('#lb .frame')).display"), "none");
  C("条带出现 5 张", await ev("document.querySelectorAll('#kintrack .kinfig').length"), 5);
  C("strip 顺序含 5 成员", await ev("JSON.stringify(PlaygroundKin.strip())"), "DSC_0214");

  console.log("=== 2. 焦点=点开的图，且只略微放大 ===");
  C("初始焦点是 DSC_0214", await ev("PlaygroundKin.strip()[PlaygroundKin.focusIndex()]"), "DSC_0214");
  C("焦点图有 .focus 类", await ev("document.querySelectorAll('.kinfig.focus').length"), 1);
  const hF = await ev("getComputedStyle(document.querySelector('.kinfig.focus img')).height");
  const hN = await ev("getComputedStyle(document.querySelector('.kinfig:not(.focus) img')).height");
  const ratio = parseFloat(hF) / parseFloat(hN);
  const inRange = ratio >= 1.15 && ratio <= 1.45;
  C("焦点/邻居高度比 1.15~1.45（略大非英雄）", inRange ? "OK " + ratio.toFixed(2) : "FAIL " + ratio.toFixed(2), "OK");
  console.log(`      (焦点 ${hF} vs 邻居 ${hN} = ${ratio.toFixed(2)}×)`);

  console.log("=== 3. 居中锁定：焦点图几何中心≈容器正中 ===");
  const centered = await ev(`(()=>{const w=document.getElementById('kinwrap');
    const f=document.querySelector('.kinfig.focus');
    const wc=w.getBoundingClientRect(), fc=f.getBoundingClientRect();
    return Math.round((fc.left+fc.right)/2-(wc.left+wc.right)/2);})()`);
  C("焦点中心偏移<6px", Math.abs(centered) <= 6 ? "OK("+centered+")" : "FAIL("+centered+")", "OK");

  console.log("=== 4. 核心需求：点邻图只平移、不重建 DOM ===");
  // 给现有节点打标，点击后验证仍是同一批节点（未被重建）
  await ev(`document.querySelectorAll('#kintrack .kinfig').forEach((n,i)=>n.dataset.tag='T'+i)`);
  const beforeTx = await ev("getComputedStyle(document.getElementById('kintrack')).transform");
  // 点右侧第二张（焦点右移）
  await ev(`(()=>{const f=[...document.querySelectorAll('#kintrack .kinfig')];
    const fi=f.findIndex(n=>n.classList.contains('focus'));
    f[fi+2].dispatchEvent(new MouseEvent('click',{bubbles:true}));})()`);
  await sleep(900);
  C("焦点已右移 2 位", await ev("PlaygroundKin.focusIndex()"), 2);
  C("DOM 未重建（标记仍在）", await ev("[...document.querySelectorAll('#kintrack .kinfig')].every(n=>/^T\\d+$/.test(n.dataset.tag))"), true);
  const afterTx = await ev("getComputedStyle(document.getElementById('kintrack')).transform");
  C("track 已平移（transform 变化）", beforeTx !== afterTx ? "changed" : "same", "changed");
  C("仍是 5 张（无增删）", await ev("document.querySelectorAll('#kintrack .kinfig').length"), 5);
  // 居中探针：full-res 换图可能在动画窗口内触发二次 centerOn，读到瞬时 undefined。
  // 故多等一拍并带守卫重试，避免把偶发读取误判为功能失败（诊断已证实各焦点 off≈0）。
  const centered2 = await ev(`(async()=>{const probe=()=>{
      const w=document.getElementById('kinwrap'); const f=document.querySelector('.kinfig.focus');
      if(!w||!f) return null;
      const wc=w.getBoundingClientRect(), fc=f.getBoundingClientRect();
      if(!fc.width) return null;
      return Math.round((fc.left+fc.right)/2-(wc.left+wc.right)/2);};
    for(let i=0;i<12;i++){const v=probe(); if(v!==null) return v; await new Promise(r=>setTimeout(r,250));}
    return probe();})()`);
  C("平移后新焦点仍居中", (centered2 !== null && Math.abs(centered2) <= 6) ? "OK(" + centered2 + ")" : "FAIL(" + centered2 + ")", "OK");

  console.log("=== 5. 边界：滑到第一张，左侧留白、右箭头可见左箭头隐藏 ===");
  await ev("PlaygroundKin.setFocus(0)");
  await sleep(900);
  C("焦点回到 0", await ev("PlaygroundKin.focusIndex()"), 0);
  C("左箭头无 has（已到最左）", await ev("document.getElementById('kinnavL').classList.contains('has')"), false);
  C("右箭头有 has", await ev("document.getElementById('kinnavR').classList.contains('has')"), true);
  const firstLeft = await ev(`(()=>{const w=document.getElementById('kinwrap'),f=document.querySelector('.kinfig.focus');
    return Math.round(f.getBoundingClientRect().left-w.getBoundingClientRect().left);})()`);
  C("首图居中→左侧留白>0", Number(firstLeft) > 40 ? "leftgap" : "nogap("+firstLeft+")", "leftgap");

  console.log("=== 6. 键盘 ← → 平移 ===");
  await ev("window.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}))");
  await sleep(800);
  C("→ 焦点+1", await ev("PlaygroundKin.focusIndex()"), 1);
  await ev("window.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true}))");
  await sleep(800);
  C("← 焦点-1", await ev("PlaygroundKin.focusIndex()"), 0);

  console.log("=== 7. 需求2：完全不显示 image ID ===");
  C("无 figcaption", await ev("document.querySelectorAll('#kintrack figcaption').length"), 0);
  C("无 title 属性", await ev("[...document.querySelectorAll('.kinfig')].filter(b=>b.title).length"), 0);
  C("alt 全空", await ev("[...document.querySelectorAll('.kinfig img')].every(i=>!i.alt)"), true);
  C("说明条无 id 字样", await ev(`/DSC_|_Y3A/.test(document.getElementById('kinhd').textContent)`), false);
  C("说明条含角度数", await ev("document.getElementById('kinhd').textContent.includes('个角度')"), true);

  console.log("=== 8. 保留错落：奇偶纵向偏移不同 ===");
  const stag = await ev(`(()=>{const f=[...document.querySelectorAll('#kintrack .kinfig')].filter(n=>!n.classList.contains('focus'));
    const ys=f.map(n=>getComputedStyle(n).getPropertyValue('--off').trim());
    return JSON.stringify([...new Set(ys)]);})()`);
  C("存在两种以上错落偏移", (stag.match(/-/g)||[]).length >= 1 ? "staggered:"+stag : "flat:"+stag, "staggered");

  console.log("=== 9. 无关联组的图不进入条带（保持引擎默认单图）===");
  await ev(`window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))`);
  await sleep(400);
  await ev(`openLB(Playground.records.find(r=>r.id==='DSC_3593'))`);
  await sleep(700);
  C("未加 kinon", await ev("document.getElementById('lb').classList.contains('kinon')"), false);
  C("无条带图", await ev("document.querySelectorAll('.kinfig').length"), 0);
  C("引擎单图 frame 可见", await ev("getComputedStyle(document.querySelector('#lb .frame')).display") !== "none", true);
  await ev(`window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))`);
  await sleep(400);

  console.log("=== 10. 指认机制在 v3 仍工作 ===");
  await ev("PlaygroundKin.pinMode(true)");
  await sleep(250);
  C("进入指认模式", await ev("document.getElementById('pinBtn').classList.contains('on')"), true);
  await ev(`document.querySelector('.tile[data-id="DSC_3185"]').dispatchEvent(new MouseEvent('click',{bubbles:true}))`);
  await sleep(200);
  await ev(`document.querySelector('.tile[data-id="DSC_3227"]').dispatchEvent(new MouseEvent('click',{bubbles:true}))`);
  await sleep(200);
  C("已选 2 只", await ev("document.querySelectorAll('.tile.pinned').length"), 2);
  await ev("document.getElementById('pbMerge').click()");
  await sleep(400);
  C("合并后组数 14", await ev("PlaygroundKin.groupsCount()"), 14);
  C("两图同组", await ev(`(()=>{const g=PlaygroundKin.groups().find(x=>x.members.includes('DSC_3185'));
      return g&&g.members.includes('DSC_3227');})()`), true);
  C("导出 schema 正确", await ev("PlaygroundKin.exportCorrections().schema"), "kinship-corrections/v1");
  await ev("PlaygroundKin.pinMode(false)");
  await sleep(200);

  console.log("=== 11. 指认的新组能以条带打开 ===");
  await ev(`openLB(Playground.records.find(r=>r.id==='DSC_3185'))`);
  await sleep(900);
  C("新组进入条带", await ev("document.querySelectorAll('#kintrack .kinfig').length"), 2);
  C("徽标为你指认的分组", await ev("document.getElementById('kinhd').textContent.includes('你指认的分组')"), true);
  await ev(`window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))`);
  await sleep(300);

  // 截图：打开 K2（5 成员）平移到中间态
  await ev(`openLB(Playground.records.find(r=>r.id==='DSC_0878-Edit'))`);
  await sleep(1500);
  await ev("PlaygroundKin.setFocus(2)");
  await sleep(1200);
  const shot = await send("Page.captureScreenshot", { format: "png" });
  const fs = await import("node:fs");
  fs.writeFileSync(process.env.SHOT || "/tmp/kin_v3.png", Buffer.from(shot.data, "base64"));
  console.log("  截图已存");

  const bad = out.filter(o => !o.ok);
  console.log(`\n=== 结果 ${out.length - bad.length}/${out.length} 通过 ===`);
  if (bad.length) { console.log("失败项:"); bad.forEach(b => console.log("  ✗", b.name, "→", b.got)); }
  ws.close(); process.exit(bad.length ? 2 : 0);
}
main().catch(e => { console.log("FATAL:", e.message); process.exit(1); });
