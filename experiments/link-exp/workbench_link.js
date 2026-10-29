/* ================================================================
   WORKBENCH 深链接接收层（实验版）
   ----------------------------------------------------------------
   作用：从 `workbench.html#img=<id>&from=archive` 进入时，
   自动定位到该图 —— 切到「全部图像」视图、选中该图、滚动到它、
   展开检查器，并给出一条来源提示。

   为什么先 setFilter('all','all') 再 select()：
     工作台默认筛选是「待我裁决」队列。若用户已裁决过该图，它就不在当前列表里，
     直接 select 会选中一张不在网格中的图（检查器有内容但网格无高亮、无法定位）。
     先切全量视图可保证目标一定在网格中。

   时序：本脚本在 </body> 前追加，晚于工作台主脚本的 init() IIFE，
   故 IMG/byId/select/setFilter 均已就绪。仍做 typeof 防御，
   避免将来主脚本改动导致本层抛错连累页面。

   连接键 = 图片 id。两个平台共用同一套 id（已核实 108/108 一致）。
   ================================================================ */
(function () {
  "use strict";

  function params() {
    var h = (location.hash || "").replace(/^#/, "");
    if (!h) return {};
    var out = {};
    h.split("&").forEach(function (kv) {
      var i = kv.indexOf("=");
      if (i < 0) return;
      try { out[decodeURIComponent(kv.slice(0, i))] = decodeURIComponent(kv.slice(i + 1)); }
      catch (e) { /* 非法编码就忽略该键，不让整页崩 */ }
    });
    return out;
  }

  var st = document.createElement("style");
  st.textContent = [
    "#dlBanner{position:fixed;left:50%;top:10px;transform:translateX(-50%) translateY(-8px);",
    "  z-index:120;display:none;align-items:center;gap:10px;padding:8px 15px;border-radius:11px;",
    "  background:rgba(20,26,20,.95);border:1px solid #3f7a48;color:#c3ebcd;",
    "  font:12.5px/1.4 -apple-system,'PingFang SC',sans-serif;",
    "  box-shadow:0 8px 30px rgba(0,0,0,.5);opacity:0;transition:opacity .3s,transform .3s}",
    "#dlBanner.on{display:inline-flex;opacity:1;transform:translateX(-50%) translateY(0)}",
    "#dlBanner code{background:#0e1a12;border:1px solid #2c4a35;color:#8fd3a0;",
    "  border-radius:4px;padding:1px 6px;font:11.5px ui-monospace,Menlo,monospace}",
    "#dlBanner button{background:#16241a;border:1px solid #3f7a48;color:#c3ebcd;",
    "  border-radius:7px;padding:3px 10px;cursor:pointer;font-size:11.5px}",
    "#dlBanner button:hover{background:#1e3325}"
  ].join("");
  document.head.appendChild(st);

  var banner = document.createElement("div");
  banner.id = "dlBanner";
  document.body.appendChild(banner);

  function showBanner(msg, idText) {
    banner.innerHTML = "<span>" + msg + "</span>" +
      (idText ? "<code>" + idText + "</code>" : "") +
      '<button id="dlClose">知道了</button>';
    banner.classList.add("on");
    var b = document.getElementById("dlClose");
    if (b) b.addEventListener("click", hideBanner);
    clearTimeout(banner._t);
    banner._t = setTimeout(hideBanner, 9000);
  }
  function hideBanner() {
    banner.classList.remove("on");
    clearTimeout(banner._t);
  }

  function apply(id, from) {
    if (typeof IMG === "undefined" || typeof select !== "function") {
      showBanner("深链接未能应用：工作台内部接口不可用", null);
      return { ok: false, reason: "api-missing" };
    }
    var hit = null;
    for (var i = 0; i < IMG.length; i++) if (IMG[i].image_id === id) { hit = IMG[i]; break; }
    if (!hit) {
      showBanner("找不到这张图（id 不在本库中，可能来自另一批素材）", id);
      return { ok: false, reason: "unknown-id" };
    }
    // 切全量视图，确保目标一定在网格中（默认队列可能已排除它）
    if (typeof setFilter === "function") setFilter("all", "all");
    select(id);
    // 滚动到网格中的该图块（select 内部已 scrollIntoView，这里再兜一次以确保可见）
    try {
      var el = document.querySelector('.tile[data-id="' + (window.CSS && CSS.escape ? CSS.escape(id) : id) + '"]');
      if (el) el.scrollIntoView({ block: "center", behavior: "smooth" });
    } catch (e) {}
    var label = null;
    try { label = (typeof taxonLabel === "function") ? taxonLabel(hit) : null; } catch (e) {}
    showBanner((from === "archive" ? "已从档案站跳转过来" : "已按链接定位") +
      (label ? "，当前分类 " + label : ""), id);
    return { ok: true, id: id, label: label };
  }

  var p = params();
  var result = null;
  if (p.img) result = apply(p.img, p.from);

  /* hash 变化时重新定位（同一标签内多次跳转） */
  addEventListener("hashchange", function () {
    var q = params();
    if (q.img) apply(q.img, q.from);
  });

  window.WorkbenchLink = {
    version: "link-0.1-experiment",
    direction: "workbench←archive",
    params: params,
    apply: apply,
    last: function () { return result; },
    /* 反向链接：回到档案站并定位同一张图（L1 的另一半，实验里一并验证） */
    backUrl: function (id) {
      return "archive.html#img=" + encodeURIComponent(id || (STATE && STATE.cur) || "") + "&from=workbench";
    },
    note: "实验版深链接接收层。支持 #img=<id>&from=archive；未知 id 显式提示而非静默失败。"
  };

  if (result && result.ok && typeof console !== "undefined") {
    console.info("[workbench-link] 已定位", result.id);
  }
})();
