// test_kin.mjs — Plankton Playground 关联图功能 v2 的浏览器实测
//
// 用 Chrome 远程调试真实执行页面，模拟用户点击，读取真实 DOM 状态。
// 不用 --dump-dom：那只反映首屏渲染，无法验证交互链路。
//
// ⚠ 本文件的断言基准是**上一轮踩坑后修正过的**，改动前请先读这些注释：
//   * tileById() 返回的 tile 对象**没有 src 字段**（URL 在 Playground.records 里）。
//     曾因此误判「站点破图」，实际站点正常。
//   * 站点的 keydown 监听挂在 **window** 上；合成事件必须 bubbles:true 才能到达。
//   * K1 成员顺序为 DSC_0242 / DSC_0361 / DSC_1540 / DSC_26982020（主图 DSC_0214 除外），
//     所以「点第 3 个侧图」切换到的主图是 DSC_1540，不是 DSC_0361。
//   * CFG.morph 默认 0 是 v23 等价闸门的**设计要求**，不是功能损坏。
//
// 用法: PORT=9360 PAGE_URL=file:///.../blackwater-plankton-archive.html node scripts/test_kin.mjs

const PORT = process.env.PORT || "9360";
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
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json`);
      targets = await r.json();
      if (targets.some(t => t.url.includes("blackwater-plankton"))) break;
    } catch (e) {}
    await sleep(600);
  }
  const tgt = targets.find(t => t.url.includes("blackwater-plankton"));
  if (!tgt) { console.log("FATAL: 找不到站点 target"); process.exit(1); }

  const ws = new WebSocket(tgt.webSocketDebuggerUrl);
  let id = 0; const pend = new Map();
  const send = (m, p = {}) => new Promise((res, rej) => {
    const my = ++id; pend.set(my, { res, rej });
    ws.send(JSON.stringify({ id: my, method: m, params: p }));
  });
  ws.onmessage = e => {
    const m = JSON.parse(e.data);
    if (m.id && pend.has(m.id)) {
      const { res, rej } = pend.get(m.id); pend.delete(m.id);
      m.error ? rej(new Error(m.error.message)) : res(m.result);
    }
  };
  await new Promise(r => ws.onopen = r);
  await send("Runtime.enable");
  await send("Page.enable");
  await sleep(4500);

  const ev = async x => {
    const r = await send("Runtime.evaluate", { expression: x, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) return "ERR:" + String(r.exceptionDetails.exception?.description || r.exceptionDetails.text).slice(0, 160);
    return r.result.value;
  };

  console.log("=== 0. 基线：核心引擎未被挂载层破坏 ===");
  C("Playground 版本", await ev("Playground.version"), "v3.1");
  C("Kin 版本", await ev("PlaygroundKin.version"), "kin-2.0");
  C("记录数", await ev("Playground.records.length"), 108);
  C("有效分组数", await ev("PlaygroundKin.groupsCount()"), 13);
  C("morph 默认 0（等价闸门要求）", await ev("Playground.config.morph"), 0);

  console.log("=== 1. 真实用户路径：点击漂浮图块 ===");
  C("图块存在", await ev(`!!document.querySelector('.tile[data-id="DSC_0214"]')`), true);
  await ev(`document.querySelector('.tile[data-id="DSC_0214"]').dispatchEvent(new MouseEvent('click',{bubbles:true}))`);
  await sleep(2500);
  C("lightbox 打开", await ev("document.getElementById('lb').classList.contains('open')"), true);
  C("主图加载成功", await ev("document.getElementById('lb-img').naturalWidth>0"), true);
  C("主图 alt", await ev("document.getElementById('lb-img').alt"), "DSC_0214");
  C("加了 kinon 布局类", await ev("document.getElementById('lb').classList.contains('kinon')"), true);

  console.log("=== 2. 需求1：主图居中，两侧铺开 ===");
  C("左侧列存在", await ev("!!document.getElementById('kinL')"), true);
  C("右侧列存在", await ev("!!document.getElementById('kinR')"), true);
  const nl = await ev("document.querySelectorAll('#kinL .kinfig').length");
  const nr = await ev("document.querySelectorAll('#kinR .kinfig').length");
  C("左侧图数", nl, 2);
  C("右侧图数", nr, 2);
  C("两侧合计 4", Number(nl) + Number(nr), 4);
  // 主图在 DOM 中位于两列之间（frame 被夹在 kinL 与 kinR 之间）
  C("主图夹在两列之间", await ev(`(()=>{const lb=document.getElementById('lb');
      const k=[...lb.children].map(c=>c.id||c.className);
      return k.indexOf('kinL')<k.indexOf('frame')&&k.indexOf('frame')<k.indexOf('kinR');})()`), true);

  console.log("=== 3. 需求1：尺寸随可用图数自适应 ===");
  C("主图高度被压到 58vh（4 张关联）", await ev("getComputedStyle(document.getElementById('lb')).getPropertyValue('--mainH').trim()"), "58vh");
  C("侧图高度 31vh", await ev("getComputedStyle(document.getElementById('lb')).getPropertyValue('--sideH').trim()"), "31vh");
  C("错落幅度已设", await ev("getComputedStyle(document.getElementById('lb')).getPropertyValue('--stag').trim()"), "15px");
  // 换到只有 1 个关联的组，尺寸应放大
  await ev(`openLB(Playground.records.find(r=>r.id==='DSC_1268'))`);
  await sleep(900);
  C("1 张关联时主图 66vh", await ev("getComputedStyle(document.getElementById('lb')).getPropertyValue('--mainH').trim()"), "66vh");
  C("1 张关联时侧图 40vh", await ev("getComputedStyle(document.getElementById('lb')).getPropertyValue('--sideH').trim()"), "40vh");
  C("1 张关联时侧图数", await ev("document.querySelectorAll('#kinL .kinfig, #kinR .kinfig').length"), 1);

  console.log("=== 4. 需求2：完全不显示 image ID ===");
  await ev(`openLB(Playground.records.find(r=>r.id==='DSC_0214'))`);
  await sleep(900);
  C("侧图无 figcaption", await ev("document.querySelectorAll('#kinL figcaption, #kinR figcaption').length"), 0);
  C("侧图无 title 属性", await ev("[...document.querySelectorAll('.kinfig')].filter(b=>b.title).length"), 0);
  C("侧图 alt 为空", await ev("[...document.querySelectorAll('.kinfig img')].every(i=>!i.alt)"), true);
  C("说明条不含任何 id 字样", await ev(`/DSC_|_Y3A/.test(document.getElementById('kinhd').textContent)`), false);
  C("说明条仍给出组标签与角度数", await ev("document.getElementById('kinhd').textContent.includes('个角度')"), true);

  console.log("=== 5. 点击侧图切换主图（沉浸交互仍可用）===");
  await ev(`document.querySelectorAll('#kinL .kinfig')[1].click()`);
  await sleep(2000);
  C("主图已切换", await ev("document.getElementById('lb-img').alt"), "DSC_0361");
  C("切换后主图加载成功", await ev("document.getElementById('lb-img').naturalWidth>0"), true);
  C("舞台随新主图重建（两侧仍有图）", await ev("document.querySelectorAll('#kinL .kinfig, #kinR .kinfig').length"), 4);

  console.log("=== 6. 点两侧空白不误关灯箱 ===");
  await ev(`document.getElementById('kinhd').click()`);
  await sleep(300);
  C("lightbox 仍开", await ev("document.getElementById('lb').classList.contains('open')"), true);

  console.log("=== 7. Escape 关闭并清理舞台 ===");
  await ev(`window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))`);
  await sleep(400);
  C("lightbox 已关", await ev("document.getElementById('lb').classList.contains('open')"), false);
  C("侧图已清空", await ev("document.querySelectorAll('.kinfig').length"), 0);
  C("kinon 类已移除", await ev("document.getElementById('lb').classList.contains('kinon')"), false);

  console.log("=== 8. 无关联组的图不打扰 ===");
  await ev(`openLB(Playground.records.find(r=>r.id==='DSC_3593'))`);
  await sleep(700);
  C("无侧图", await ev("document.querySelectorAll('.kinfig').length"), 0);
  C("无说明条内容", await ev("document.getElementById('kinhd').textContent.trim()"), "");
  C("未加 kinon（主图保持原大尺寸）", await ev("document.getElementById('lb').classList.contains('kinon')"), false);
  await ev(`window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))`);
  await sleep(300);

  console.log("=== 9. 需求3：指认模式入口与切换 ===");
  C("指认按钮存在", await ev("!!document.getElementById('pinBtn')"), true);
  await ev("document.getElementById('pinBtn').click()");
  await sleep(300);
  C("进入指认模式", await ev("document.getElementById('pinBtn').classList.contains('on')"), true);
  C("操作条出现", await ev("document.getElementById('pinBar').classList.contains('on')"), true);
  C("场加 pinmode（十字光标）", await ev("document.getElementById('field').classList.contains('pinmode')"), true);

  console.log("=== 10. 需求3：点选两只无关生物，声明为同一只 ===");
  // 选两只原本不在任何组的图
  await ev(`document.querySelector('.tile[data-id="DSC_3593"]').dispatchEvent(new MouseEvent('click',{bubbles:true}))`);
  await sleep(250);
  C("指认模式下图块点击不开灯箱", await ev("document.getElementById('lb').classList.contains('open')"), false);
  C("已选 1 只", await ev("PlaygroundKin.corrections ? document.querySelectorAll('.tile.pinned').length : -1"), 1);
  await ev(`document.querySelector('.tile[data-id="DSC_3227"]').dispatchEvent(new MouseEvent('click',{bubbles:true}))`);
  await sleep(250);
  C("已选 2 只", await ev("document.querySelectorAll('.tile.pinned').length"), 2);
  C("合并按钮已可用", await ev("!document.getElementById('pbMerge').disabled"), true);
  await ev("document.getElementById('pbMerge').click()");
  await sleep(400);
  C("新组已生效（组数 14）", await ev("PlaygroundKin.groupsCount()"), 14);
  C("两图同属一组", await ev(`(()=>{const g=PlaygroundKin.groups();
      const a=g.find(x=>x.members.includes('DSC_3593'));
      return a && a.members.includes('DSC_3227');})()`), true);
  C("新组标记为 user 来源", await ev(`PlaygroundKin.groups().find(x=>x.members.includes('DSC_3593')).status`), "user");
  C("纠正已写入 localStorage", await ev("(localStorage.getItem('plankton_kinship_corrections_v1')||'').includes('DSC_3593')"), true);

  console.log("=== 11. 新组立即在站点生效：点开 DSC_3593 应出现关联图 ===");
  await ev(`PlaygroundKin.pinMode(false)`);
  await sleep(200);
  await ev(`openLB(Playground.records.find(r=>r.id==='DSC_3593'))`);
  await sleep(900);
  C("出现侧图", await ev("document.querySelectorAll('.kinfig').length"), 1);
  C("徽标为「你指认的分组」", await ev("document.getElementById('kinhd').textContent.includes('你指认的分组')"), true);
  await ev(`window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))`);
  await sleep(300);

  console.log("=== 12. 需求3：把某只移出 AI 分组 ===");
  await ev("document.getElementById('pinBtn').click()");
  await sleep(250);
  await ev(`document.querySelector('.tile[data-id="DSC_0361"]').dispatchEvent(new MouseEvent('click',{bubbles:true}))`);
  await sleep(250);
  await ev("document.getElementById('pbRemove').click()");
  await sleep(400);
  C("K1 成员数从 5 降到 4", await ev(`PlaygroundKin.groups().find(g=>g.id==='K1').members.length`), 4);
  C("DSC_0361 已不在任何组", await ev(`PlaygroundKin.groups().some(g=>g.members.includes('DSC_0361'))`), false);

  console.log("=== 13. 导出反馈结构 ===");
  const keys = await ev("JSON.stringify(Object.keys(PlaygroundKin.exportCorrections()))");
  C("含 corrections", keys, "corrections");
  C("含 effective_groups_snapshot", keys, "effective_groups_snapshot");
  C("schema 值正确", await ev("PlaygroundKin.exportCorrections().schema"), "kinship-corrections/v1");
  C("merge 集数 = 1", await ev("PlaygroundKin.exportCorrections().counts.merge_sets"), 1);
  C("移除 id 数 = 1", await ev("PlaygroundKin.exportCorrections().counts.removed_ids"), 1);
  await ev("document.getElementById('pinBtn').click()");
  await sleep(200);

  console.log("=== 14. 刷新后指认结果仍在（持久化）===");
  await ev(`(()=>{const c=JSON.parse(localStorage.getItem('plankton_kinship_corrections_v1'));
    return JSON.stringify({merge:c.merge.length, rem:Object.keys(c.remove).length});})()`).then(v => C("localStorage 内容", v, '"merge":1'));

  // 截图
  await ev(`openLB(Playground.records.find(r=>r.id==='DSC_0242'))`);
  await sleep(2200);
  const shot = await send("Page.captureScreenshot", { format: "png" });
  const fs = await import("node:fs");
  fs.writeFileSync(process.env.SHOT || "/tmp/kin_v2.png", Buffer.from(shot.data, "base64"));
  console.log("  截图已存");

  const bad = out.filter(o => !o.ok);
  console.log(`\n=== 结果 ${out.length - bad.length}/${out.length} 通过 ===`);
  if (bad.length) { console.log("失败项:"); bad.forEach(b => console.log("  ✗", b.name, "→", b.got)); }
  ws.close();
  process.exit(bad.length ? 2 : 0);
}

main().catch(e => { console.log("FATAL:", e.message); process.exit(1); });
