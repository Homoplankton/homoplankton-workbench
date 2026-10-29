// test_link.mjs — L1 单向链接（档案站 → 工作台）端到端实测
//
// ⚠ 两个已踩过的坑，改动前必读：
//  1. **必须用真实鼠标手势**（CDP Input.dispatchMouseEvent）触发点击。
//     合成 `.click()` 不产生 user activation，window.open 会返回 null 被拦，
//     导致「新标签打不开」的假失败（实测确认：无手势 gesture=false 被拦，
//     真实手势 gesture=true 成功）。
//  2. **断言不要用 JSON.stringify 包两边**。C(name, got, want) 内部已做
//     JSON.stringify(got).includes(JSON.stringify(want))，若 want 再包一层
//     会变成带引号字面量的匹配，产生假失败（上一版「URL 含 id」就栽在这）。
//  3. 汇报前直接检查本脚本退出码，不要经 `| tail`（管道吃掉退出码，见 lessons #14/#24）。

import http from "node:http";
const PORT = process.env.PORT || 9392;
const sleep = ms => new Promise(r => setTimeout(r, ms));

let pass = 0, fail = 0;
// 注意：got 会被 stringify，want 作为裸子串匹配（不再二次 stringify）
function C(name, got, want) {
  const ok = String(JSON.stringify(got)).includes(String(want));
  ok ? pass++ : fail++;
  console.log(`  ${ok ? "✓" : "✗"} ${name}: ${JSON.stringify(got).slice(0, 90)}`);
}
function T(name, got) { const ok = !!got; ok ? pass++ : fail++; console.log(`  ${ok ? "✓" : "✗"} ${name}: ${JSON.stringify(got).slice(0, 90)}`); }

async function targets() { return (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()); }

function attach(wsUrl) {
  return new Promise((res, rej) => {
    const ws = new WebSocket(wsUrl);
    let id = 0; const pend = new Map();
    const send = (m, pa = {}) => new Promise(r => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method: m, params: pa })); });
    ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result); pend.delete(m.id); } };
    ws.onerror = rej;
    ws.onopen = async () => {
      await send("Runtime.enable"); await send("Page.enable");
      res({
        ws, send,
        ev: async x => {
          const r = await send("Runtime.evaluate", { expression: x, returnByValue: true, awaitPromise: true });
          if (r.exceptionDetails) return "ERR:" + String(r.exceptionDetails.exception?.description || "").slice(0, 120);
          return r.result.value;
        },
        // 真实鼠标手势：移动 + 按下 + 抬起，产生 user activation
        click: async (x, y) => {
          await send("Input.enable").catch(() => {});
          await send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y });
          await sleep(120);
          await send("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", clickCount: 1 });
          await sleep(60);
          await send("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", clickCount: 1 });
        }
      });
    };
  });
}

let ts = await targets();
let p = ts.find(t => t.type === "page" && t.url.includes("archive.html"));
if (!p) { console.error("找不到 archive.html，先启动 Chrome 载入实验副本"); process.exit(2); }
const A = await attach(p.webSocketDebuggerUrl);
await sleep(2800);

console.log("=== 1. 档案站副本三层共存（引擎 + kinship + link）===");
C("引擎", await A.ev("Playground.version"), "v3.1");
C("kinship 挂载", await A.ev("PlaygroundKin.version"), "kin-4.1");
C("链接层", await A.ev("PlaygroundLink.version"), "link-0.2");
C("记录数", await A.ev("Playground.records.length"), "108");

console.log("=== 2. 灯箱未开 → 入口隐藏（不破坏漂浮沉浸感）===");
C("入口 display", await A.ev("getComputedStyle(document.getElementById('wbLink')).display"), "none");
C("锚点无 href（未选图时不可点）", await A.ev("document.getElementById('wbLink').getAttribute('href')"), null);

console.log("=== 3. 点开生物 → 入口出现且 href 带 id ===");
await A.ev(`openLB(Playground.records.find(r=>r.id==='DSC_0214'))`);
await sleep(1600);
C("灯箱打开", await A.ev("document.getElementById('lb').classList.contains('open')"), true);
C("入口可见", await A.ev("getComputedStyle(document.getElementById('wbLink')).display"), "flex");
C("当前 id", await A.ev("PlaygroundLink.current()"), "DSC_0214");
C("href 指向工作台且带 id", await A.ev("document.getElementById('wbLink').getAttribute('href')"), "workbench.html#img=DSC_0214");
C("target=_blank（新标签，不替换档案站）", await A.ev("document.getElementById('wbLink').getAttribute('target')"), "_blank");
C("入口文案不含 image ID（沉浸约束）", await A.ev(`/DSC_|_Y3A/.test(document.getElementById('wbLink').textContent)`), false);

console.log("=== 4. 关联条带与链接入口共存 ===");
C("条带 5 张", await A.ev("document.querySelectorAll('.kinfig').length"), "5");
const box = await A.ev(`(()=>{const r=document.getElementById('wbLink').getBoundingClientRect();
  return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2),w:Math.round(r.width)};})()`);
T("入口有可见尺寸", box && box.w > 40);
console.log("    入口中心坐标:", JSON.stringify(box));

console.log("=== 5. 真实鼠标手势点击 → 新标签打开工作台 ===");
await A.click(box.x, box.y);
await sleep(4200);
ts = await targets();
const pages = ts.filter(t => t.type === "page");
const wbp = pages.find(t => t.url.includes("workbench.html"));
C("新标签已打开工作台", pages.length, 2);
T("工作台 URL 带 img 参数", wbp && wbp.url.includes("img=DSC_0214"));
C("档案站标签仍在", ts.some(t => t.url.includes("archive.html")), true);
C("档案站灯箱仍开着（状态未丢）", await A.ev("document.getElementById('lb').classList.contains('open')"), true);
C("档案站滚动位置保留", await A.ev("typeof scrollY==='number'"), true);

if (!wbp) { console.error("工作台未打开，后续断言跳过"); console.log(`\n=== ${pass}/${pass + fail} ===`); A.ws.close(); process.exit(1); }

const B = await attach(wbp.webSocketDebuggerUrl);
await sleep(3800);

console.log("=== 6. 工作台按参数自动定位同一张图 ===");
C("工作台载入", await B.ev("typeof IMG!=='undefined' && IMG.length"), "108");
C("接收层在", await B.ev("WorkbenchLink.version"), "link-0.1");
C("解析出 img 参数", await B.ev("WorkbenchLink.params().img"), "DSC_0214");
C("解析出 from 参数", await B.ev("WorkbenchLink.params().from"), "archive");
C("STATE.cur = 目标图", await B.ev("STATE.cur"), "DSC_0214");
C("检查器标题 = 目标图", await B.ev("(document.querySelector('#insp h2')||{}).textContent"), "DSC_0214");
C("已切全量视图（目标必在网格中）", await B.ev("STATE.filterKind"), "all");
C("该图块标为当前", await B.ev(`document.querySelector('.tile[data-id="DSC_0214"]').getAttribute('aria-current')`), "true");
C("提示条说明来源", await B.ev("document.getElementById('dlBanner').textContent"), "已从档案站跳转过来");
C("检查器渲染了断言", await B.ev("document.querySelectorAll('#insp .claim').length > 0"), true);
C("检查器大图已加载", await B.ev("(()=>{const i=document.querySelector('#shot img');return i?i.naturalWidth>0:false})()"), true);

console.log("=== 7. 边界：未知 id 显式提示而非静默失败 ===");
C("未知 id 返回原因", await B.ev(`WorkbenchLink.apply('DSC_9999','archive').reason`), "unknown-id");
C("未知 id 提示可见", await B.ev("document.getElementById('dlBanner').textContent"), "找不到这张图");
C("未知 id 不改当前选中", await B.ev("STATE.cur"), "DSC_0214");

console.log("=== 8. 边界：无 hash 直接进入 → 不干扰正常启动 ===");
C("backUrl 可生成（反向预留）", await B.ev(`WorkbenchLink.backUrl('DSC_0214')`), "archive.html#img=DSC_0214");

console.log("=== 9. 工作台核心功能未被接收层破坏 ===");
C("待办队列可用", await B.ev(`typeof setFilter==='function'`), true);
await B.ev(`setFilter('queue','contested')`); await sleep(400);
C("争议队列筛选生效", await B.ev("document.querySelectorAll('.tile').length"), "2");
await B.ev(`setFilter('all','all')`); await sleep(300);
C("回到全量 108 张", await B.ev("document.querySelectorAll('.tile').length"), "108");

B.ws.close(); A.ws.close();
console.log(`\n=== 结果 ${pass}/${pass + fail} 通过 ===`);
process.exit(fail ? 1 : 0);
