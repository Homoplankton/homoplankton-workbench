// test_wb_v2.mjs — 工作台五项改动的浏览器实测（2026-10-27 用户提出）
//
//  1. 左栏可编辑：⚙ 面板显隐分区、默认隐藏文献库/修正链（已有标签页）、持久化
//  2. 检查器显示整帧完整图（非主体裁剪）：aspect == 原图 aspect
//  3. 「未鉴定」红点替代三字旗标：flag 文本无「未鉴定」，且存在实心红点
//  4. 表格 / 关系树标签页可用且渲染
//  5. 文献库/修正链内容不再被埋在网格下方：#grid 真正隐藏、#empty 在视口顶部可见
//
// 第二批（2026-10-27 用户追加三项）：
//  6. 检查器主体虚线框移除（box_norm 数据仍留库里，只是不渲染）
//  7. 缩略图不再 overcrop：瓦片/表格/树叶子一律 object-fit:contain，零裁像素
//     （旧版 1:1 + cover 实测把竖图切掉 34%、横图切掉 33%）
//  8. 分类筛选后有**永不消失**的出口：页脚筛选提示可点、Esc 可清、空态有按钮；
//     即便把左栏「分类树」分区折叠（旧版唯一出口随之隐藏、只能刷新）也照样回得去
//
// ⚠ 踩坑记录：`node ... | tail` 的 $? 是 tail 的退出码；此处直接打印并 process.exit(fail)。
//    Node 内置 WebSocket 用 DOM API（onopen/onmessage），不是 ws 包的 .on()。
//    合成 click 不产生 user activation；本测试点击 tab 用真实鼠标手势。

import http from "node:http";
const PORT = process.env.PORT || 9410;
const sleep = ms => new Promise(r => setTimeout(r, ms));

let pass = 0, fail = 0;
function C(name, got, want) {
  const ok = String(JSON.stringify(got)).includes(String(want));
  ok ? pass++ : fail++;
  console.log(`  ${ok ? "✓" : "✗"} ${name}: ${JSON.stringify(got).slice(0, 100)}`);
}
function T(name, got) { const ok = !!got; ok ? pass++ : fail++; console.log(`  ${ok ? "✓" : "✗"} ${name}: ${JSON.stringify(got).slice(0, 100)}`); }

const ts = await (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json());
const page = ts.find(t => t.type === "page" && t.url.includes("workbench.html"));
if (!page) { console.error("找不到 workbench.html 页面"); process.exit(2); }
const ws = new WebSocket(page.webSocketDebuggerUrl);
let _id = 0; const pend = new Map();
const send = (m, p = {}) => new Promise((res, rej) => {
  const id = ++_id; pend.set(id, { res, rej });
  ws.send(JSON.stringify({ id, method: m, params: p }));
  setTimeout(() => { if (pend.has(id)) { pend.delete(id); rej(new Error("timeout " + m)); } }, 25000);
});
ws.onmessage = e => { const m = JSON.parse(e.data);
  if (m.id && pend.has(m.id)) { const { res, rej } = pend.get(m.id); pend.delete(m.id);
    m.error ? rej(new Error(m.error.message)) : res(m.result); } };
await new Promise(r => (ws.onopen = r));
await send("Runtime.enable"); await send("Page.enable");
// 注意：Input.enable 在 page target 上不存在（曾因此崩在启动处）；
// dispatchMouseEvent 不需要先 enable，直接派发即可。
await sleep(2000);
const ev = async x => { const r = await send("Runtime.evaluate",
  { expression: x, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) return "ERR:" + String(r.exceptionDetails.exception?.description || "").slice(0, 140);
  return r.result.value; };
async function clickAt(x, y) {
  await send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y }); await sleep(80);
  await send("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", clickCount: 1 });
  await sleep(50);
  await send("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", clickCount: 1 });
}
async function clickSel(sel) {
  const b = await ev(`(()=>{const e=document.querySelector('${sel}');if(!e)return null;
    const r=e.getBoundingClientRect();return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2),dis:e.disabled};})()`);
  if (!b) return null;
  if (b.dis) return { disabled: true };
  await clickAt(b.x, b.y); await sleep(700);
  return b;
}

console.log("=== 0. 基线 ===");
C("载入 108 张", await ev("IMG.length"), 108);
C("初始模式=图库", await ev("STATE.mode"), "gallery");

console.log("=== 1. 左栏：默认隐藏文献库/修正链分区（已有标签页）===");
C("左栏无文献库分区", await ev(`!!document.querySelector('#nav .nsec[data-sec="refs"]')`), false);
C("左栏无修正链分区", await ev(`!!document.querySelector('#nav .nsec[data-sec="revs"]')`), false);
C("左栏有待办队列分区", await ev(`!!document.querySelector('#nav .nsec[data-sec="queue"]')`), true);
C("左栏分区总数=3", await ev(`document.querySelectorAll('#nav .nsec').length`), 3);
const gear = await clickSel("#navCfgBtn");
T("⚙ 面板打开", gear && await ev(`document.getElementById('navCfg').classList.contains('on')`));
C("面板列出 5 个分区", await ev(`document.querySelectorAll('#navCfg input[data-sec]').length`), 5);
C("文献库复选默认未勾", await ev(`document.querySelector('#navCfg input[data-sec="refs"]').checked`), false);
// 勾选文献库 → 左栏出现该分区
await ev(`document.querySelector('#navCfg input[data-sec="refs"]').click()`);
await sleep(500);
C("勾选后左栏出现文献库分区", await ev(`!!document.querySelector('#nav .nsec[data-sec="refs"]')`), true);
// 调顺序：选中 taxon 并上移
await ev(`(()=>{const r=document.querySelector('#navCfg input[name="navpick"][value="taxon"]');r.checked=true;
  document.querySelector('#navCfg [data-nav="up"]').click();})()`);
await sleep(500);
C("taxon 上移后成为第一分区", await ev(`document.querySelector('#nav .nsec').dataset.sec`), "taxon");
// 恢复默认并关面板
await ev(`document.querySelector('#navCfg [data-nav="reset"]').click()`);
await sleep(400);
C("恢复默认后第一分区=queue", await ev(`document.querySelector('#nav .nsec').dataset.sec`), "queue");
C("恢复默认后文献库分区再隐藏", await ev(`!!document.querySelector('#nav .nsec[data-sec="refs"]')`), false);
await ev(`document.querySelector('#navCfg [data-nav="close"]').click()`);
await sleep(300);
C("面板已关", await ev(`document.getElementById('navCfg').classList.contains('on')`), false);
C("设置已持久化", await ev(`(localStorage.getItem('plankton_wb_navcfg_v1')||'').includes('order')`), true);

console.log("=== 2. 检查器显示整帧完整图（非主体裁剪）===");
await ev(`select('DSC_0214')`); await sleep(900);
const shot = await ev(`(()=>{const i=document.querySelector('#shot img');
  return {w:i.naturalWidth,h:i.naturalHeight,src:i.src.slice(0,24)};})()`);
console.log("    检查器图:", JSON.stringify(shot));
const orig = await ev(`(()=>{const im=IMG.find(x=>x.image_id==='DSC_0214');return im.source?im.source:{a:im.asset.orig_w,b:im.asset.orig_h};})()`);
const aspShot = shot.w / shot.h;
const db = await ev(`(()=>{const im=IMG.find(x=>x.image_id==='DSC_0214');return im.asset?im.asset.aspect:null;})()`);
T("检查器图比例≈原图比例（整帧，未裁）", Math.abs(aspShot - (db || aspShot)) < 0.02);
C("caption 写明整帧", await ev(`document.querySelector('#shot .cap').textContent`), "整帧完整展示");
C("caption 不再说主体裁剪", await ev(`/主体裁剪/.test(document.querySelector('#shot .cap').textContent)`), false);
C("img object-fit=contain（不裁切）", await ev(`getComputedStyle(document.querySelector('#shot img')).objectFit`), "contain");
C("主体虚线框已移除（用户要求）", await ev(`!!document.querySelector('#shot .box')`), false);
C("caption 不再提虚线框", await ev(`/虚线框/.test(document.querySelector('#shot .cap').textContent)`), false);
C("box_norm 数据仍保留在库里（只是不渲染）", await ev(`(()=>{const im=IMG.find(x=>x.asset&&x.asset.box_norm);return im?im.image_id:'none';})()`), "DSC_");

console.log("=== 3. 状态点语义：未鉴定红点 → 分诊后 0 张 ===");
// 分诊回填后全部 108 张都有处置：43 draft（琥珀）+ 64 skipped（暗色空心）+ 1 contested。
// 「未鉴定红点」= 0 是**目标状态**（SOP 已给每张一个可防守的处置），不是缺陷。
await ev(`setFilter('all','all'); renderStage();`); await sleep(500);
C("瓦片旗标无「未鉴定」文字", await ev(`[...document.querySelectorAll('.tile .flag')].some(f=>f.textContent.includes('未鉴定'))`), false);
C("分诊后无未鉴定红点（全部已处置）", await ev(`document.querySelectorAll('.tile .s-dot-unresolved').length`), 0);
C("存在 draft 待确认点（琥珀）", await ev(`document.querySelectorAll('.tile .s-dot-draft').length > 0`), true);
C("存在 skipped 已分诊跳过点", await ev(`document.querySelectorAll('.tile .s-dot-skipped').length > 0`), true);
const draftDot = await ev(`(()=>{const d=document.querySelector('.tile .s-dot-draft');const s=getComputedStyle(d);return s.backgroundColor;})()`);
const skipDot = await ev(`(()=>{const d=document.querySelector('.tile .s-dot-skipped');const s=getComputedStyle(d);return {bg:s.backgroundColor,bs:s.borderStyle};})()`);
console.log("    draft点:", draftDot, " skipped点:", JSON.stringify(skipDot));
T("draft 点为琥珀实心（非透明）", draftDot && draftDot !== "rgba(0, 0, 0, 0)");
T("skipped 点为暗色空心（透明底+实线边，刻意不用红/琥珀）",
  skipDot && skipDot.bg === "rgba(0, 0, 0, 0)" && skipDot.bs === "solid");

console.log("=== 3b. 分诊跳过语义（skip 不冒充待办）===");
// 5 张图同时带早先会话的 AI 草案分类 + 本轮 skip 处置：skip 应压过草案（人工裁决仍最高）
C("DSC_0361 聚合状态=skipped（skip 压过旧 AI 草案）", await ev(`statusOf(IMG.find(x=>x.image_id==='DSC_0361'))`), "skipped");
C("DSC_0933 聚合状态=skipped（放射虫=原生生物）", await ev(`statusOf(IMG.find(x=>x.image_id==='DSC_0933'))`), "skipped");
C("DSC_3058 聚合状态=contested（人工争议优先于 skip）", await ev(`statusOf(IMG.find(x=>x.image_id==='DSC_3058'))`), "contested");
// 跳过图不进任何待办队列（否则 65 张会灌满「待我裁决」噪声）
C("skipped 图不在 to_decide 队列", await ev(`!buildQueues().to_decide.some(im=>statusOf(im)==='skipped')`), true);
C("skipped 图不在 unidentified 队列", await ev(`!buildQueues().unidentified.some(im=>statusOf(im)==='skipped')`), true);
C("skipped 队列计数>0（独立可查）", await ev(`buildQueues().skipped.length > 0`), true);
C("unidentified 队列=0（无未处置图）", await ev(`buildQueues().unidentified.length`), 0);
// triage_note 断言卡片渲染（跳过原因可读，非裸露 JSON）
await ev(`select('DSC_0361')`); await sleep(700);
T("检查器渲染 triage_note 卡片", await ev(`!!document.querySelector('#insp .claim [data-pred="triage_note"], #insp .claim') && [...document.querySelectorAll('#insp .claim .cp')].some(e=>e.textContent==='triage_note')`));
T("triage_note 卡片显示「已分诊跳过」中文", await ev(`document.getElementById('insp').textContent.includes('已分诊跳过')`));
// draft 分类图渲染：路径 + 停层原因 + 组文献证据
await ev(`select('DSC_2193')`); await sleep(700);
C("draft 图分类路径渲染", await ev(`document.getElementById('insp').textContent.includes('Pleuronectiformes')`), true);
T("draft 图显示停层原因", await ev(`document.getElementById('insp').textContent.includes('停层原因')`));
T("draft 图挂 3 条组文献证据", await ev(`(claimOf(IMG.find(x=>x.image_id==='DSC_2193'),'taxon_is').evidence.references||[]).length`) === 3);
T("draft 图溯源标为 AI 草案", await ev(`provOf(IMG.find(x=>x.image_id==='DSC_2193'))`) === "ai_draft");

console.log("=== 4. 表格 / 关系树标签页 ===");
const tb = await clickSel('[data-mode="table"]');
T("表格 tab 可点（非 disabled）", tb && !tb.disabled);
C("模式=table", await ev("STATE.mode"), "table");
// filter=all 下表格渲染全量 108 行（renderTable 用 currentList，不按状态过滤）
C("渲染行数=108（filter=all）", await ev(`document.querySelectorAll('table.wb tbody tr').length`), 108);
C("表头 11 列", await ev(`document.querySelectorAll('table.wb th').length`), 11);
// 分诊后无未鉴定 → rdot=0 是目标状态；改为验证跳过图在表格里显示「已分诊跳过」而非空白
C("分诊后表格无未鉴定红点（全部已处置）", await ev(`document.querySelectorAll('table.wb .rdot').length`), 0);
T("表格分类列对跳过图显示「已分诊跳过」", await ev(`document.querySelector('table.wb tbody').textContent.includes('已分诊跳过')`));
// 行点击 → 选中并回检查器（用一张 draft 图，确保在 all 视图且可选中）
await ev(`document.querySelector('table.wb tbody tr[data-id="DSC_2193"]').scrollIntoView()`);
const rowB = await ev(`(()=>{const r=document.querySelector('table.wb tbody tr[data-id="DSC_2193"]');
  if(!r) return null; const b=r.getBoundingClientRect();return {x:Math.round(b.x+b.width/2),y:Math.round(b.y+b.height/2)};})()`);
T("DSC_2193 行在表格 DOM 中", rowB);
if (rowB) { await clickAt(rowB.x, rowB.y); await sleep(600); }
C("点行选中 DSC_2193", await ev("STATE.cur"), "DSC_2193");
// 关系树
const tr = await clickSel('[data-mode="tree"]');
T("关系树 tab 可点", tr && !tr.disabled);
C("模式=tree", await ev("STATE.mode"), "tree");
C("根节点存在", await ev(`document.querySelectorAll('#treeWrap .tnode').length > 3`), true);
C("根节点不直接平铺叶子（未鉴定不在根部堆）", await ev(`(()=>{
  const root=document.querySelector('#treeWrap .tnode');
  return root.querySelectorAll(':scope > .tkids > .tleaf').length;})()`), 0);
C("叶子总数=有分类路径的图（43 draft + 5 skip 带路径）", await ev(`document.querySelectorAll('#treeWrap .tleaf').length`), 48);
C("未定节点存在", await ev(`document.querySelectorAll('#treeWrap .tnode.tent').length > 0`), true);
C("说明标注非系统发育树", await ev(`document.getElementById('treeWrap').textContent.includes('不是')`), true);
// 点节点 → 回图库并筛选（先滚入视口，避免坐标在折叠线外）
await ev(`(()=>{const r=[...document.querySelectorAll('.trow')].find(x=>x.dataset.taxon==='Mollusca');
  if(r) r.scrollIntoView({block:'center'});})()`);
await sleep(400);
const nodeB = await ev(`(()=>{const r=[...document.querySelectorAll('.trow')].find(x=>x.dataset.taxon==='Mollusca');
  if(!r) return null; const b=r.getBoundingClientRect();
  return {x:Math.round(b.x+40),y:Math.round(b.y+b.height/2)};})()`);
T("Mollusca 节点在 DOM 中", nodeB);
if (nodeB) { await clickAt(nodeB.x, nodeB.y); await sleep(700); }
C("点 Mollusca 节点回图库", await ev("STATE.mode"), "gallery");
C("且筛选=Mollusca", await ev("STATE.filter"), "Mollusca");

console.log("=== 5. 文献库/修正链不再被埋在网格下方 ===");
const rb = await clickSel('[data-mode="refs"]');
T("文献库 tab 可点", rb && !rb.disabled);
C("模式=refs", await ev("STATE.mode"), "refs");
C("#grid 真正隐藏(computed none)", await ev(`getComputedStyle(document.getElementById('grid')).display`), "none");
C("#empty 可见", await ev(`getComputedStyle(document.getElementById('empty')).display !== 'none'`), true);
C("文献内容在视口顶部（不被网格推下）", await ev(`(()=>{const r=document.getElementById('empty').getBoundingClientRect();
  return r.top < 120;})()`), true);
C("82 条文献渲染（原 34 + 本轮 16 组×3）", await ev(`document.querySelectorAll('#empty ul.refs li').length`), 82);
const vb = await clickSel('[data-mode="revisions"]');
C("8 条修正链渲染（原 6 + 推翻留痕 1 + 本轮汇总 1）", await ev(`document.querySelectorAll('#empty .rev').length`), 8);
C("修正链在视口顶部", await ev(`(()=>{return document.getElementById('empty').getBoundingClientRect().top < 120;})()`), true);
// 回图库确认网格恢复。注意：切模式**保留当前筛选**（设计如此），
// 上一步停在 Mollusca 筛选，故须先重置到全量再数瓦片。
await clickSel('[data-mode="gallery"]'); await sleep(400);
await ev(`setFilter('all','all')`); await sleep(500);
C("回图库网格恢复", await ev(`getComputedStyle(document.getElementById('grid')).display`), "grid");
C("108 瓦片", await ev(`document.querySelectorAll('.tile').length`), 108);

console.log("=== 6. 核心功能回归 ===");
C("检查器断言仍在", await ev(`document.querySelectorAll('#insp .claim').length > 0`), true);
C("键盘 J 移动", await (async () => { const b = await ev("STATE.cur");
  await send("Input.dispatchKeyEvent", { type: "keyDown", key: "j", windowsVirtualKeyCode: 74 });
  await send("Input.dispatchKeyEvent", { type: "keyUp", key: "j", windowsVirtualKeyCode: 74 });
  await sleep(400); return (await ev("STATE.cur")) !== b; })(), true);
C("导出仍含 schema", await ev("Object.keys(exportPayload()).includes('schema')"), true);

console.log("=== 7. 缩略图零裁切（overcrop 修复）===");
// 旧版 1:1 + cover：竖图切掉 34%、横图切掉 33%。现在三处一律 contain。
C("图库瓦片 object-fit=contain", await ev(`getComputedStyle(document.querySelector('.tile img')).objectFit`), "contain");
await ev(`setMode('table')`); await sleep(500);
C("表格缩略图 object-fit=contain", await ev(`(()=>{const e=document.querySelector('table.wb .mini');
  return e?getComputedStyle(e).objectFit:'NO-ELEMENT';})()`), "contain");
await ev(`setMode('tree')`); await sleep(500);
C("关系树叶子缩略图 object-fit=contain", await ev(`(()=>{const e=document.querySelector('.tleaf img');
  return e?getComputedStyle(e).objectFit:'NO-ELEMENT';})()`), "contain");
await ev(`setMode('gallery')`); await sleep(500);
// 实测「有没有像素被切」：contain 下内容框必然 ≤ 元素框，且内容比例==原图比例。
// 抽一张竖图、一张横图，用 contain 数学算出实际显示尺寸再核对。
// letterboxPct = 瓦片里留给黑边的面积占比。**这是留白不是裁切**：
// 旧版 cover 是「切掉照片像素填满方格」，新版 contain 是「照片整张缩进方格、四周留黑」。
// 黑边与纯黑画布同色不可见，且照片像素一张都没丢——字段改名就是为了不把留白误读成裁剪。
const crop = await ev(`(()=>{
  const pick=(wantPortrait)=>{
    const t=[...document.querySelectorAll('.tile img')];
    return t.find(i=>i.naturalWidth&&i.naturalHeight&&((i.naturalWidth<i.naturalHeight)===wantPortrait));
  };
  const probe=(i)=>{ if(!i) return null;
    const b=i.getBoundingClientRect(); const nw=i.naturalWidth, nh=i.naturalHeight;
    if(!b.width||!b.height) return null;
    const s=Math.min(b.width/nw, b.height/nh);        // contain 的缩放系数
    const cw=nw*s, ch=nh*s;                            // 实际显示的内容尺寸
    const ratioShown=cw/ch, ratioSrc=nw/nh;
    return {id:i.closest('.tile').dataset.id, nat:nw+'x'+nh,
            shownFitsBox: cw<=b.width+0.5 && ch<=b.height+0.5,
            ratioOk: Math.abs(ratioShown-ratioSrc)<0.01,
            pxLost: Math.round(nw*nh - (cw/s)*(ch/s)),   // 源像素被切掉的数量：必须为 0
            letterboxPct: +(100*(1-(cw*ch)/(b.width*b.height))).toFixed(1)};
  };
  return {portrait:probe(pick(true)), landscape:probe(pick(false))};
})()`);
console.log("    竖图:", JSON.stringify(crop.portrait), "\n    横图:", JSON.stringify(crop.landscape));
T("竖图零像素被切（内容完整落在框内、比例未变）",
  crop.portrait && crop.portrait.shownFitsBox && crop.portrait.ratioOk && crop.portrait.pxLost === 0);
T("横图零像素被切（内容完整落在框内、比例未变）",
  crop.landscape && crop.landscape.shownFitsBox && crop.landscape.ratioOk && crop.landscape.pxLost === 0);
// 全量核对：每张瓦片的图源比例都等于库里的 aspect（证明用的是整帧层，不是裁剪层）。
// ⚠ 踩坑：懒加载下未进视口的图 naturalWidth=0，须先触发加载。
//    但**不能**一次性 decode() 全部 108 张 base64 图——那会撑爆 CDP 25s 超时（本轮实测崩在这）。
//    正确做法：逐屏滚动让浏览器自己按需加载，再读 naturalWidth（纯属性读取，不触发解码等待）。
await ev(`(async()=>{const s=document.getElementById('stage');
  for(let y=0;y<s.scrollHeight;y+=Math.round(s.clientHeight*0.7)){
    s.scrollTop=y; await new Promise(r=>setTimeout(r,110)); }
  s.scrollTop=0; return 'scrolled';})()`);
await sleep(1500);
C("108 张图源比例均与库内 aspect 一致", await ev(`(()=>{
  let bad=0,n=0,notLoaded=0;
  for(const im of IMG){ const a=Number(im.asset&&im.asset.aspect); if(!a) continue;
    const t=document.querySelector('.tile[data-id="'+CSS.escape(im.image_id)+'"] img'); if(!t) continue;
    if(!t.naturalWidth){ notLoaded++; continue; }
    n++;
    if(Math.abs(t.naturalWidth/t.naturalHeight - a) > 0.02) bad++; }
  if(notLoaded>0) return 'still-lazy:'+notLoaded;
  return bad===0 ? 'all-ok('+n+')' : bad+'/'+n+' 不一致';})()`), "all-ok(108)");

console.log("=== 8. 分类筛选后有永不消失的出口 ===");
// 复现用户报告的死角：点分类筛选 → 把左栏「分类树」分区折叠 → 旧版唯一入口随之隐藏，只能刷新
await ev(`setFilter('taxon','Ctenophora')`); await sleep(500);
C("已筛选 Ctenophora（5 张）", await ev(`document.querySelectorAll('#grid .tile').length`), 5);
await ev(`document.querySelector('.nsec[data-sec="taxon"] .nhead').click()`); await sleep(400);
C("分类树分区已折叠", await ev(`document.querySelector('.nsec[data-sec="taxon"]').dataset.open`), "0");
C("折叠后左栏「全部图像」入口不可见（旧死角成立）", await ev(`(()=>{const e=document.querySelector('[data-fkind=\"all\"]');
  return e? String(e.offsetParent===null) : 'GONE';})()`), "true");
// 出口 1：页脚筛选提示常驻可见且可点
C("页脚筛选提示仍可见（不随折叠消失）", await ev(`(()=>{const e=document.getElementById('filterTxt');
  return e?String(e.offsetParent!==null):'GONE';})()`), "true");
C("页脚提示已标记为可清除状态", await ev(`document.getElementById('filterTxt').classList.contains('active')`), true);
C("清除按钮在页脚可见", await ev(`(()=>{const e=document.querySelector('#filterTxt .clr');
  return e?String(e.offsetParent!==null):'GONE';})()`), "true");
const fb = await clickSel("#filterTxt");
T("点页脚提示可点中", fb);
await sleep(600);
C("点击后回到全部 108 张", await ev(`document.querySelectorAll('#grid .tile').length`), 108);
C("且筛选已重置为全部", await ev(`STATE.filterKind+':'+STATE.filter`), "all:all");
C("页脚提示恢复非可清除态", await ev(`document.getElementById('filterTxt').classList.contains('active')`), false);
// 出口 2：Esc 清筛选
await ev(`setFilter('taxon','Mollusca')`); await sleep(500);
C("再次筛选 Mollusca（7 张）", await ev(`document.querySelectorAll('#grid .tile').length`), 7);
await send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", windowsVirtualKeyCode: 27 });
await send("Input.dispatchKeyEvent", { type: "keyUp", key: "Escape", windowsVirtualKeyCode: 27 });
await sleep(600);
C("Esc 清筛选后回到 108 张", await ev(`document.querySelectorAll('#grid .tile').length`), 108);
// 出口 3：清除筛选保留当前视图。
// ⚠ 前提纠正：setFilter() 内部会强制 STATE.mode='gallery'（见模板 setFilter），
//    所以「先切表格再调 setFilter」不是真实用户路径——那样测出来是图库，
//    而 #empty 里还残留着上一次表格的 DOM（隐藏但 querySelectorAll 数得到），
//    旧断言因此误数到 108 行「通过」。真实路径是：图库里筛好 → 点「表格」标签 → 在表格里清除。
//    下面一律用 offsetParent!==null 只数**可见**元素，避免再被隐藏残留骗到。
const visRows = `[...document.querySelectorAll('table.wb tbody tr')].filter(r=>r.offsetParent!==null).length`;
await ev(`setFilter('taxon','Mollusca')`); await sleep(500);
C("图库里筛选 Mollusca（7 张）", await ev(`document.querySelectorAll('#grid .tile').length`), 7);
await ev(`setMode('table')`); await sleep(500);
C("切到表格仍保留该筛选（7 行）", await ev(visRows), 7);
await ev(`clearFilter()`); await sleep(700);
C("表格视图下清除后恢复 108 行", await ev(visRows), 108);
C("且仍停在表格视图（未被踢回图库）", await ev(`STATE.mode`), "table");
C("图库网格此刻确实隐藏（无残留计数）", await ev(`document.getElementById('grid').offsetParent===null`), true);
// 出口 4：零结果空态里直接给按钮（搜一个不存在的词）
await ev(`setMode('gallery')`); await sleep(400);
await ev(`(()=>{const q=document.getElementById('q');q.value='zzz-no-such-thing';
  q.dispatchEvent(new Event('input',{bubbles:true}));})()`); await sleep(600);
C("零结果时进入空态", await ev(`document.querySelectorAll('#grid .tile').length`), 0);
T("空态里给了清除按钮", await ev(`!!document.querySelector('#empty .clrbtn')`));
await ev(`(()=>{const b=document.querySelector('#empty .clrbtn'); if(b) b.click(); return 'clicked';})()`);
await sleep(700);
C("点空态按钮后恢复 108 张", await ev(`document.querySelectorAll('#grid .tile').length`), 108);
C("搜索词已被清空", await ev(`document.getElementById('q').value`), "");
// 还原折叠状态，避免影响后续人工查看
await ev(`(()=>{const s=document.querySelector('.nsec[data-sec=\"taxon\"]'); if(s&&s.dataset.open!=='1')
  s.querySelector('.nhead').click(); return 'restored';})()`); await sleep(300);

/* ---------- 第九组：导入面板（浏览器内自动填充） ---------- */
console.log("\n--- 导入面板 ---");
T("顶栏有导入按钮", await ev(`!!document.getElementById('importBtn')`));
await ev(`document.getElementById('importBtn').click()`); await sleep(200);
T("面板可开", await ev(`document.getElementById('importPanel').classList.contains('on')`));
T("面板说明写明分类/分期/文献走离线回填", await ev(
  `document.getElementById('impNote').textContent.includes('离线')`));
// 造一张合成图走完整导入管线
await ev(`(async()=>{ const cv=document.createElement('canvas'); cv.width=600; cv.height=400;
  const g=cv.getContext('2d'); g.fillStyle='#000'; g.fillRect(0,0,600,400);
  g.fillStyle='#e07030'; g.beginPath(); g.ellipse(300,200,120,90,0,0,7); g.fill();
  const blob=await new Promise(r=>cv.toBlob(r,'image/png'));
  window.__impFile=new File([blob],'IMPTEST_0001.png',{type:'image/png'}); })()`); await sleep(400);
await ev(`importFiles([window.__impFile])`); await sleep(1500);
C("导入后图库 109 张", await ev(`IMG.length`), 109);
T("导入图带 EXIF 断言（capture_context）", await ev(
  `IMG.some(im=>im.image_id==='IMPTEST_0001'&&im.claims.some(c=>c.predicate==='capture_context'))`));
T("导入图带派生断言（auto_derived 含 pigment_detected）", await ev(
  `(()=>{const im=IMG.find(i=>i.image_id==='IMPTEST_0001'); const ad=im&&im.claims.find(c=>c.predicate==='auto_derived');
    return !!(ad&&ad.value&&ad.value.pigment_detected===true&&ad.value.box_norm);})()`));
T("导入图进待鉴定队列（unidentified）", await ev(
  `buildQueues().unidentified.some(im=>im.image_id==='IMPTEST_0001')`));
C("IndexedDB 里持久化 1 条", await ev(`impAll().then(r=>r.length)`), 1);
T("进度行显示已入库", await ev(
  `document.querySelector('#impList .it.done')!==null`));
// 清掉测试导入，避免污染后续人工查看
await ev(`(async()=>{ const db=await impOpen();
  await new Promise(res=>{const tx=db.transaction('imgs','readwrite');
    tx.objectStore('imgs').delete('IMPTEST_0001'); tx.oncomplete=()=>{db.close();res();};});
  const i=IMG.findIndex(im=>im.image_id==='IMPTEST_0001'); if(i>=0) IMG.splice(i,1);
  renderNav(); renderStage(); return 'cleaned'; })()`); await sleep(400);
C("清理后图库回到 108", await ev(`IMG.length`), 108);
C("IndexedDB 清空", await ev(`impAll().then(r=>r.length)`), 0);

console.log(`\n=== 结果 ${pass}/${pass + fail} 通过 ===`);
ws.close();
process.exit(fail ? 1 : 0);
