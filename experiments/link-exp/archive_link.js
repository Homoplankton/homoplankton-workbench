/* ================================================================
   ARCHIVE → WORKBENCH 链接层（实验版，只挂在实验副本上）
   ----------------------------------------------------------------
   作用：在档案站灯箱里提供一个极低调入口，跳到工作台并定位到同一张图。
   连接键：图片 id（两个平台共用同一套 id，已核实 108/108 一致）。
   传参方式：URL fragment（`workbench.html#img=<id>`）。
     为什么用 fragment 而不是 localStorage / postMessage：
       * 无状态、跨标签页、不依赖同源存储（file:// 下 localStorage 按目录分区，
         两个文件不同名，共享不可靠）；
       * 刷新后仍可复现（链接本身就是完整状态），也便于人把链接发给别人。

   不碰核心引擎、不碰 kinship 挂载：只用既有 lightbox:open/close 钩子，
   且把按钮挂在 document.body 上（不塞进 #lb 内部，避免被挂载层的清理逻辑波及）。

   沉浸约束（用户明确要求过）：**任何位置都不显示 image ID**。
   按钮文案是动作，不是数据；ID 只存在于跳转 URL 里。
   ================================================================ */
(function () {
  "use strict";

  /* 工作台地址：同目录相对路径。已实测 file:// 同目录跳转 + fragment 传参可用。
     若两个文件不同目录，把这里改成实际相对/绝对路径即可（见 references 说明）。 */
  var WB_URL = "workbench.html";

  var st = document.createElement("style");
  st.textContent = [
    "#wbLink{position:fixed;right:16px;bottom:64px;z-index:82;",
    "  display:none;align-items:center;gap:7px;padding:7px 13px;border-radius:20px;",
    "  border:1px solid rgba(255,255,255,.14);background:rgba(12,12,14,.62);",
    "  color:#9aa0a8;font:11.5px/1 -apple-system,'PingFang SC',sans-serif;",
    "  text-decoration:none;cursor:pointer;opacity:.32;backdrop-filter:blur(6px);",
    "  transition:opacity .3s,border-color .3s,color .3s,transform .2s}",
    "#wbLink:hover{opacity:1;color:#dfe3e8;border-color:rgba(255,255,255,.34);transform:translateY(-1px)}",
    "#wbLink.on{display:inline-flex}",
    "#wbLink .ic{font-size:13px;line-height:1}",
    /* 指认按钮在 bottom:16，本按钮上移避开；条带打开时不遮挡左右箭头 */
    "@media(max-width:900px){#wbLink{right:12px;bottom:56px;padding:6px 11px}}"
  ].join("");
  document.head.appendChild(st);

  var a = document.createElement("a");
  a.id = "wbLink";
  /* target 必须存在：原生导航靠它开新标签。缺了它点击会**替换当前标签**，
     档案站的漂浮状态（滚动位置、随机尺寸、已加载的图）就全丢了。 */
  a.target = "_blank";
  a.rel = "noopener";
  a.title = "在工作台中核验这只生物（新标签打开，档案站保持不变）";
  a.innerHTML = '<span class="ic">⌕</span><span>在工作台核验</span>';
  document.body.appendChild(a);

  var cur = null;

  /* 用**原生锚点导航**而不是 window.open()。
     实测依据（CDP 捕获 Page.windowOpen 事件）：
       * 无用户手势调用 window.open → 返回 null，被拦（gesture=false）
       * 真实鼠标手势下 window.open → 成功（gesture=true）
       * 原生 <a target="_blank"> 点击 → 成功，且不依赖手势判定
     原生锚点更稳：不受弹窗拦截策略影响，还天然支持中键/⌘点击、
     右键「在新标签打开」、复制链接地址。故这里只维护 href，
     不做 preventDefault、不调用 window.open。 */
  function urlFor(id) {
    return WB_URL + "#img=" + encodeURIComponent(id) + "&from=archive";
  }

  /* 同标签跳转（用户明确要求「彻底离开档案站」时）：Alt/⌘+点击 */
  a.addEventListener("click", function (e) {
    if (e.altKey || e.metaKey) {
      e.preventDefault();
      if (cur) location.href = urlFor(cur);
    }
    /* 其余情况不拦截：让浏览器执行原生 target="_blank" 导航 */
  });

  if (typeof on === "function") {
    on("lightbox:open", function (p) {
      cur = p && p.id;
      if (!cur) return;
      a.href = urlFor(cur);          // 原生导航所需
      a.classList.add("on");
    });
    on("lightbox:close", function () {
      cur = null;
      a.removeAttribute("href");
      a.classList.remove("on");
    });
  }

  window.PlaygroundLink = {
    version: "link-0.2-experiment",
    direction: "archive→workbench",
    target: WB_URL,
    current: function () { return cur; },
    url: function () { return cur ? urlFor(cur) : null; },
    /* 供测试与未来程序化调用（注意：程序化 window.open 无手势会被拦，
       测试须用真实鼠标手势或读取 a.href 断言） */
    open: function (newTab) {
      if (!cur) return null;
      var u = urlFor(cur);
      if (newTab === false) { location.href = u; return u; }
      return window.open(u, "_blank", "noopener");
    },
    note: "实验版单向链接（档案站→工作台），原生锚点导航。反向与查询链接（L2）尚未实现。"
  };
})();
