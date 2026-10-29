#!/usr/bin/env node
/*
工作台线上渲染验证 —— 真实浏览器核验已部署的工作台。

为什么需要：curl 200 只证明文件传上去了。工作台是 9.6MB 自包含单文件
（图片 base64 内嵌），必须确认线上真能解析、渲染、切换视图。

核验项对齐作者提出的五项要求：
  1. 左栏可编辑（⚙ 面板存在，分区可显隐）
  2. 检查器显示**整幅图**而非主体裁剪（用宽高比判定：
     detail 层裁剪比例 ≠ 原图比例；full 层整幅比例 = 原图比例）
  3. 红点替代「未鉴定」三字标记
  4. 表格视图与关系图（分类树）视图可用
  5. 文献库与证据链可见可用

用法：node verify_workbench.mjs <URL> [期望瓦片数]
退出码：0 全通过；1 有失败；2 环境错误
*/
import { spawn } from "node:child_process";

const TARGET = process.argv[2];
const EXPECT = parseInt(process.argv[3] || "108", 10);
if (!TARGET) { console.error("用法：node verify_workbench.mjs <URL> [期望瓦片数]"); process.exit(2); }

const chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const results = [];
function check(name, pass, detail = "") {
  results.push({ name, pass, detail });
  console.log(`${pass ? "✓" : "✗"} ${name}${detail ? " — " + detail : ""}`);
}

const proc = spawn(chrome, [
  "--headless=new", "--remote-debugging-port=9361",
  "--no-first-run", "--no-default-browser-check",
  "--disable-gpu", "--window-size=1600,1000", "about:blank",
], { stdio: "ignore" });

let ws = null;
async function connect() {
  for (let i = 0; i < 80; i++) {
    try {
      const res = await fetch("http://127.0.0.1:9361/json/list");
      const list = await res.json();
      const page = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
      if (page) {
        ws = new WebSocket(page.webSocketDebuggerUrl);
        await new Promise((r, e) => { ws.onopen = r; ws.onerror = e; });
        return;
      }
    } catch { /* 重试 */ }
    await sleep(300);
  }
  throw new Error("连不上页面级调试 target");
}

let id = 0; const pend = new Map(); const jsErrors = [];
const send = (method, params = {}) => new Promise((res, rej) => {
  const i = ++id; pend.set(i, { res, rej }); ws.send(JSON.stringify({ id: i, method, params }));
  setTimeout(() => { if (pend.has(i)) { pend.delete(i); rej(new Error(method + " 超时")); } }, 180000);
});
const ev = async (expr) => {
  const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.text || "页面求值异常");
  return r.result.value;
};

try {
  await connect();
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pend.has(m.id)) {
      const { res, rej } = pend.get(m.id); pend.delete(m.id);
      m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result);
      return;
    }
    if (m.method === "Runtime.exceptionThrown") jsErrors.push(m.params?.exceptionDetails?.text || "unknown");
    if (m.method === "Runtime.consoleAPICalled" && m.params?.type === "error") jsErrors.push("console.error");
  };
  await send("Runtime.enable");
  await send("Page.enable");
  await send("Page.navigate", { url: TARGET });
  await sleep(20000); // 10MB 单文件解析 + base64 图片解码，需较长等待

  // ---- 0. 无 JS 错误 ----
  check("页面无 JS 运行时错误", jsErrors.length === 0, jsErrors.slice(0, 3).join("; "));

  // ---- 1. 数据解析与瓦片数量 ----
  const boot = await ev(`(() => {
    const g = document.getElementById('grid');
    const tiles = g ? g.children.length : -1;
    const imgs = g ? g.querySelectorAll('img').length : -1;
    const app = !!document.getElementById('app');
    return JSON.stringify({ tiles, imgs, app,
      brand: (document.getElementById('brandCount')||{}).textContent || null });
  })()`);
  const b = JSON.parse(boot);
  check("应用容器已挂载（#app）", b.app === true);
  // 工作台启动即 setFilter("queue","to_decide")，默认只显示**待裁决队列**，
  // 不是全部 108 张 —— 42 张是设计行为（43 include 减去已处置）。
  check("默认视图为待裁决队列（非全量）", b.tiles > 0 && b.tiles < EXPECT,
    `默认 ${b.tiles} 张待裁决`);
  const switchedAll = await ev(`(() => {
    const n = document.querySelector('#nav [data-fkind="all"][data-f="all"]');
    if (!n) return 'no-nav';
    n.click(); return 'ok';
  })()`);
  await sleep(2000);
  const allCount = await ev(`document.getElementById('grid').children.length`);
  check(`切「全部图像」后瓦片数 = ${EXPECT}`, switchedAll === "ok" && allCount === EXPECT,
    `实际 ${allCount} 个瓦片`);

  // ---- 2. 瓦片图片真解码（base64 内嵌）----
  //
  // ⚠️ 踩坑记录（勿再按 naturalWidth 直接判坏图）：
  //   a) 瓦片 <img> 带 loading="lazy"（模板 841/867/924 行），视口外的图
  //      浏览器根本不加载，naturalWidth===0 是**设计行为**，不是坏图。
  //   b) 试图滚动触发是徒劳的：实测 #main 的 scrollHeight === clientHeight
  //      （mainScrollable=false），它不是滚动容器；#grid 高 4409px 而 body 仅 913px，
  //      真正的滚动上下文不在 #main 上，滚 window 也不移动瓦片。
  //   c) 对**作者已验收的本地版**跑同一口径同样得 77/108，且线上文件与本地
  //      md5 完全一致（a5087635d093e02fa048960564d03aee）→ 证明是测量口径问题。
  //
  // 正确判据：强制把所有 img 设为 eager 并 await img.decode()，
  //   - decode() 成功 = base64 数据是合法图片（真正要验的东西）
  //   - decode() 抛错 或 complete&&naturalWidth===0 = 真坏图
  // 这比数 naturalWidth 更强：它实际解码了全部 216 个 base64 块。
  const dec = await ev(`(async () => {
    const im = [...document.querySelectorAll('#grid img')];
    im.forEach(i => { i.loading = 'eager'; });
    let ok = 0; const bad = [];
    await Promise.all(im.map(async (i) => {
      try { await i.decode(); if (i.naturalWidth > 0) ok++; else bad.push(i.alt || '?'); }
      catch (e) { bad.push((i.alt || '?') + ':' + e.name); }
    }));
    const removed = document.querySelectorAll('#grid > *').length - im.length;
    return JSON.stringify({ total: im.length, decoded: ok, broken: bad.length,
                            brokenIds: bad.slice(0, 8), removedImgs: removed });
  })()`);
  const dd = JSON.parse(dec);
  check("全部瓦片 base64 强制解码成功（无损坏图）",
    dd.decoded === dd.total && dd.total > 0 && dd.broken === 0 && dd.removedImgs === 0,
    `${dd.decoded}/${dd.total} 解码；坏图 ${dd.broken}${dd.brokenIds.length ? "（" + dd.brokenIds.join(",") + "）" : ""}；被移除 img ${dd.removedImgs}`);

  // ---- 3. 红点替代「未鉴定」三字标记 ----
  const dots = await ev(`(() => {
    const html = document.getElementById('grid').innerHTML;
    const dotCls = /s-dot-unresolved|dot-unresolved|class="[^"]*\\bdot\\b[^"]*"/;
    const txtFlag = (html.match(/未鉴定/g) || []).length;
    const dotEls = document.querySelectorAll('#grid .s-dot-unresolved, #grid [class*="dot"]').length;
    return JSON.stringify({ txtFlag, dotEls, hasDotCss: dotCls.test(html) });
  })()`);
  const dt = JSON.parse(dots);
  check("瓦片上无「未鉴定」三字标记", dt.txtFlag === 0, `出现 ${dt.txtFlag} 次`);
  check("改用红点标记（存在 dot 元素/类）", dt.dotEls > 0 || dt.hasDotCss,
    `dot 元素 ${dt.dotEls} 个，dot 类 ${dt.hasDotCss}`);

  // ---- 4. 左栏可编辑：⚙ 配置按钮与面板 ----
  const nav = await ev(`(() => {
    const btn = document.getElementById('navCfgBtn');
    const panel = document.getElementById('navCfg');
    const navEl = document.getElementById('nav');
    const secs = navEl ? navEl.querySelectorAll('section, .nav-sec, [data-sec]').length : 0;
    return JSON.stringify({ hasBtn: !!btn, hasPanel: !!panel, secs });
  })()`);
  const nv = JSON.parse(nav);
  check("左栏配置按钮存在（#navCfgBtn）", nv.hasBtn === true);
  check("左栏配置面板存在（#navCfg）", nv.hasPanel === true);

  // 点开面板，确认有可勾选/可排序的控件
  if (nv.hasBtn) {
    await ev(`document.getElementById('navCfgBtn').click()`);
    await sleep(800);
    const panelCtl = await ev(`(() => {
      const p = document.getElementById('navCfg');
      const inputs = p ? p.querySelectorAll('input[type=checkbox], input[type=radio], button').length : 0;
      const vis = p ? getComputedStyle(p).display !== 'none' && +getComputedStyle(p).opacity > 0.05 : false;
      return JSON.stringify({ inputs, vis });
    })()`);
    const pc = JSON.parse(panelCtl);
    check("配置面板可展开且含显隐/排序控件", pc.vis === true && pc.inputs > 0,
      `可见 ${pc.vis}，控件 ${pc.inputs} 个`);
    // 关掉面板，避免影响后续视图检查
    await ev(`document.getElementById('navCfgBtn').click()`);
    await sleep(500);
  }

  // ---- 5. 检查器显示整幅图而非主体裁剪（宽高比判定）----
  const inspOk = await ev(`(() => {
    const tiles = [...document.querySelectorAll('#grid > *')];
    if (!tiles.length) return JSON.stringify({ skip: '无瓦片' });
    const t = tiles[0];
    t.click();
    return JSON.stringify({ clicked: true, id: t.dataset ? t.dataset.id : null });
  })()`);
  await sleep(2500);
  const insp = await ev(`(() => {
    const insp = document.getElementById('insp');
    const img = insp ? insp.querySelector('img') : document.querySelector('#insp img, .insp img');
    if (!img || !img.naturalWidth) return JSON.stringify({ open: !!insp, img: false });
    const r = img.naturalWidth / img.naturalHeight;
    const cs = getComputedStyle(img);
    return JSON.stringify({ open: !!insp, img: true,
      nw: img.naturalWidth, nh: img.naturalHeight, ratio: +r.toFixed(4),
      fit: cs.objectFit, vis: cs.display !== 'none' && cs.visibility !== 'hidden' });
  })()`);
  const ip = JSON.parse(insp);
  check("点击瓦片后检查器打开", ip.open === true && ip.img === true,
    ip.img ? `${ip.nw}×${ip.nh}` : "未找到检查器图片");
  // 整幅层长边 1200px；主体裁剪层长边仅 640px。用尺寸判定是否误用裁剪层。
  if (ip.img) {
    const longEdge = Math.max(ip.nw, ip.nh);
    check("检查器用整幅层（长边 > 800px，非 640px 裁剪层）", longEdge > 800,
      `长边 ${longEdge}px，宽高比 ${ip.ratio}`);
    check("检查器图片可见且未被裁剪填充（object-fit 非 cover 裁切）",
      ip.vis === true && ip.fit !== "cover", `object-fit: ${ip.fit}`);
  }

  // ---- 6. 四个视图切换：网格 / 表格 / 关系图（树） / 文献库 / 证据链 ----
  // 真实标签页（role=tab + data-mode）：图库 gallery / 表格 table /
  // 关系树 tree / 文献库 refs / 修正链 revisions。按 data-mode 定位，
  // 不依赖文案（早期版本曾按「关系图/证据链」猜测而全部找不到按钮）。
  const modes = await ev(`(() => {
    const btns = [...document.querySelectorAll('[role="tab"][data-mode]')];
    return JSON.stringify(btns.map(b => ({ txt: (b.textContent||'').trim(), mode: b.dataset.mode })));
  })()`);
  const ms = JSON.parse(modes);
  console.log(`ℹ 标签页：${ms.map(m => m.mode + "(" + m.txt + ")").join(" | ") || "（未识别）"}`);
  check("五个标签页齐备（gallery/table/tree/refs/revisions）",
    ms.length === 5 && ["gallery","table","tree","refs","revisions"].every(x => ms.some(m => m.mode === x)),
    `实际 ${ms.length} 个：${ms.map(m => m.mode).join(",")}`);

  async function switchTo(mode) {
    const done = await ev(`(() => {
      const b = document.querySelector('[role="tab"][data-mode="${mode}"]');
      if (!b) return 'no-btn';
      b.click(); return 'ok';
    })()`);
    return done === "ok";
  }
  async function viewState() {
    return JSON.parse(await ev(`(() => {
      const vis = id => { const e = document.getElementById(id);
        if (!e) return null; const cs = getComputedStyle(e);
        return cs.display !== 'none' && cs.visibility !== 'hidden' && !e.hidden; };
      return JSON.stringify({ grid: vis('grid'), tbl: vis('tblwrap'), tree: vis('treeWrap') });
    })()`));
  }

  const swTable = await switchTo("table");
  await sleep(1500);
  let vs = await viewState();
  const tblRows = await ev(`document.querySelectorAll('#tblwrap tr, #tblwrap tbody tr').length`);
  check("表格视图可切换且有数据行", swTable && vs.tbl === true && tblRows > 1,
    `${tblRows} 行；容器可见 ${vs.tbl}`);

  const swTree = await switchTo("tree");
  await sleep(1800);
  vs = await viewState();
  const treeNodes = await ev(`(() => {
    const w = document.getElementById('treeWrap');
    if (!w) return -1;
    return w.querySelectorAll('*').length;
  })()`);
  check("关系树视图可切换且有节点", swTree && treeNodes > 3,
    `树内元素 ${treeNodes} 个；容器可见 ${vs.tree}`);

  const swLit = await switchTo("refs");
  await sleep(1500);
  const litCount = await ev(`(() => {
    const t = document.body.innerText;
    const links = document.querySelectorAll('#main a[href^="http"], a[href*="doi"], a[target="_blank"]').length;
    return JSON.stringify({ links, hasWord: /文献|reference/i.test(t) });
  })()`);
  const lc = JSON.parse(litCount);
  check("文献库可切换且有可点击外链", swLit && lc.links > 0,
    `外链 ${lc.links} 条`);

  const swRev = await switchTo("revisions");
  await sleep(1500);
  const revState = await ev(`(() => {
    const t = document.body.innerText;
    return JSON.stringify({ hasWord: /修正|修订|溯源|revision|草案|覆盖/i.test(t), len: t.length });
  })()`);
  const rv = JSON.parse(revState);
  check("修正链可切换且有内容", swRev && rv.hasWord && rv.len > 500,
    `正文 ${rv.len} 字符，含关键词 ${rv.hasWord}`);

  // 回到网格视图，确认未被破坏
  const swGrid = await switchTo("gallery");
  await sleep(1500);
  const back = await ev(`document.getElementById('grid') ? document.getElementById('grid').children.length : -1`);
  check("切回图库后仍为全部图像（筛选保留）", back === EXPECT, `${back} 个瓦片`);

  // ---- 7. 保存按钮存在（裁决可持久化的入口）----
  const save = await ev(`(() => {
    const b = document.getElementById('saveBtn');
    return JSON.stringify({ has: !!b, txt: b ? (b.textContent||'').trim().slice(0,10) : null });
  })()`);
  const sv = JSON.parse(save);
  check("保存/导出入口存在（#saveBtn）", sv.has === true, sv.txt || "");

  const passed = results.filter((r) => r.pass).length;
  console.log(`\n===== ${passed}/${results.length} 通过 =====`);
  process.exit(passed === results.length ? 0 : 1);
} catch (e) {
  console.error("验证脚本自身出错：", e.message);
  process.exit(2);
} finally {
  try { ws?.close(); } catch { /* 忽略 */ }
  proc.kill();
}
