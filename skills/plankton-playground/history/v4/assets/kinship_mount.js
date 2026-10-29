/* ================================================================
   KINSHIP MOUNT v4 — 胶片条平移 + 主体裁剪对齐 + 无闪烁关闭
   ----------------------------------------------------------------
   v4 变更（用户 2026-10-27 提出三项修复）：
     1. 触控板双指滑动 → 胶片条自由平移，抬手吸附到最近一张并居中。
        鼠标滚轮同样生效（deltaY 映射为横向平移）。
     2. 对齐：v4 曾改用主体居中裁剪，实测过裁+放大失真，v4.1 已回退为
        整帧展示层照片（r.src）与上一版尺寸；保留触控板平移与无闪烁关闭。
     3. 关闭无闪烁：closeLB 时保留条带至 #lb 淡出结束（460ms）再清理，
        引擎单图 .frame 全程保持隐藏，不再闪现上一张主图。

   仍保留：完全不显示 image ID、指认纠正机制（P/◎）、localStorage
   持久化、导出反馈 JSON、居中锁定、奇偶错落。核心引擎零改动。
   ================================================================ */
(function () {
  "use strict";

  /* ---------------- 分组数据（人工目视核验产物，构建期注入） ----------------
     技能本体**不携带**任何具体图片的分组结果——那是每个项目自己的产物，
     由 scripts/inject_kinship.py 在构建时写入 window.__KIN_GROUPS__。
     格式见 references/kinship.md。

     未注入分组时整体静默关闭：不建任何 DOM、不挂任何监听，站点退回纯漂浮长卷。
     这是「还没有分组数据」时的正确降级——绝不显示空条带或半成品 UI。 */
  var BASE_GROUPS = (window.__KIN_GROUPS__ && window.__KIN_GROUPS__.groups) || [];
  if (!BASE_GROUPS.length) {
    window.PlaygroundKin = {
      version: "kin-4.1",
      groups: function () { return []; },
      groupsCount: function () { return 0; },
      corrections: function () { return { merge: [], remove: {} }; },
      exportCorrections: function () { return null; },
      pinMode: function () {},
      strip: function () { return []; },
      focusIndex: function () { return 0; },
      setFocus: function () {},
      note: "未注入分组数据（window.__KIN_GROUPS__ 为空）：关联条带与指认模式整体关闭。"
    };
    return;
  }

  /* v4.1 回退（用户 2026-10-27 晚）：条带**不再用主体居中裁剪**。
     640px 紧裁剪把生物放大到占满画框、显得不真实且损失分辨率（用户截图确认）。
     改回上一版的整帧展示层照片（r.src）：生物在画面中保持原始比例与黑水语境。
     代价：横/竖构图差异带来的位置参差回到上一版的样子——用户明确选择接受。
     （无裁剪的对齐改良方案另行讨论，未经要求不擅自加。） */

  var BADGE = {
    "visual": ["人工目视确认", "#5ec97f"],
    "visual+burst": ["目视＋连拍双重确认", "#5ec97f"],
    "visual+taxonomy": ["目视＋分类学确认", "#5ec97f"],
    "burst": ["连拍时间确认", "#6fa8dc"],
    "uncertain": ["相似·待你确认", "#e0b252"],
    "user": ["你指认的分组", "#c39cf0"]
  };

  /* ---------------- 纠正覆盖层（localStorage 持久化） ---------------- */
  var LS = "plankton_kinship_corrections_v1";
  var COR = { merge: [], remove: {} };
  try {
    var raw = localStorage.getItem(LS);
    if (raw) { var o = JSON.parse(raw); if (o && Array.isArray(o.merge)) COR = o; }
  } catch (e) { COR = { merge: [], remove: {} }; }
  function saveCOR() { try { localStorage.setItem(LS, JSON.stringify(COR)); } catch (e) {} }

  function effectiveGroups() {
    var gs = BASE_GROUPS.map(function (g) {
      var rm = (COR.remove[g.id]) || [];
      return { id: g.id, label: g.label, status: g.status,
               members: g.members.filter(function (m) { return rm.indexOf(m) < 0; }),
               origin: "base" };
    }).filter(function (g) { return g.members.length > 0; });

    COR.merge.forEach(function (set, i) {
      var ids = set.ids || [];
      if (ids.length < 2) return;
      var hit = [], rest = [];
      gs.forEach(function (g) {
        (g.members.some(function (m) { return ids.indexOf(m) >= 0; }) ? hit : rest).push(g);
      });
      var members = [];
      hit.forEach(function (g) { g.members.forEach(function (m) { if (members.indexOf(m) < 0) members.push(m); }); });
      ids.forEach(function (m) { if (members.indexOf(m) < 0) members.push(m); });
      var labels = hit.map(function (g) { return g.label; }).filter(function (v, k, a) { return a.indexOf(v) === k; });
      rest.push({ id: "U" + (i + 1), label: labels.length ? labels.join("＋") : "你指认的分组",
                  status: "user", members: members, origin: "user", note: set.note || null });
      gs = rest;
    });
    return gs;
  }

  var IDX = {};
  function reindex() { IDX = {}; effectiveGroups().forEach(function (g) { g.members.forEach(function (m) { IDX[m] = g; }); }); }
  reindex();

  function rec(id) {
    var rs = (window.Playground && Playground.records) || [];
    for (var i = 0; i < rs.length; i++) if (rs[i].id === id) return rs[i];
    return null;
  }

  /* ================= 样式 ================= */
  var st = document.createElement("style");
  st.textContent = [
    "#lb.kinon .frame{display:none}",
    "#kinwrap{position:absolute;inset:0;overflow:hidden;display:none;align-items:center;",
    "  pointer-events:auto;cursor:grab}",
    "#kinwrap.panning{cursor:grabbing}",
    "#lb.kinon #kinwrap{display:flex}",
    "#kintrack{display:flex;align-items:center;gap:clamp(14px,2.6vw,46px);",
    "  transform:translateX(0);transition:transform .62s cubic-bezier(.22,.86,.24,1);",
    "  will-change:transform;padding:0 40px}",
    /* 焦点放大改为纯 transform scale：布局零位移，平移数学稳定 */
    ".kinfig{position:relative;flex:0 0 auto;cursor:pointer;background:none;border:0;padding:0;",
    "  transform:translateY(var(--off,0px));transition:transform .45s cubic-bezier(.2,.9,.25,1);",
    "  line-height:0}",
    ".kinfig img{display:block;height:var(--h,34vh);width:auto;max-width:38vw;object-fit:contain;",
    "  border-radius:0;box-shadow:none;opacity:.8;filter:brightness(.84) contrast(1.04);",
    "  transition:opacity .35s,filter .35s,box-shadow .35s;",
    "  -webkit-mask-image:radial-gradient(120% 120% at 50% 50%,#000 54%,rgba(0,0,0,.5) 80%,transparent 98%);",
    "          mask-image:radial-gradient(120% 120% at 50% 50%,#000 54%,rgba(0,0,0,.5) 80%,transparent 98%)}",
    ".kinfig.focus{transform:translateY(0) scale(1.22);z-index:2}",
    ".kinfig.focus img{opacity:1;filter:brightness(1) contrast(1.05);",
    "  box-shadow:0 0 60px 6px rgba(120,160,210,.10)}",
    ".kinfig:not(.focus):hover{transform:translateY(calc(var(--off,0px) - 6px)) scale(1.04)}",
    ".kinfig:not(.focus):hover img{opacity:.95;filter:brightness(.94)}",
    ".kinfig.pinned{box-shadow:0 0 0 2px #a98cf0,0 0 34px 5px rgba(169,140,240,.34);border-radius:10px}",
    ".kinfig:nth-child(odd){--off:calc(var(--stag,12px) * -1)}",
    ".kinfig:nth-child(even){--off:var(--stag,12px)}",
    ".kinfig.focus{--off:0px}",
    ".kinfig{opacity:0;animation:kfin .6s ease forwards}",
    "@keyframes kfin{to{opacity:1}}",
    "#kinhd{position:absolute;left:50%;bottom:12px;transform:translateX(-50%);z-index:3;",
    "  display:flex;align-items:center;gap:10px;font:11px/1.4 -apple-system,'PingFang SC',sans-serif;",
    "  color:#9aa0a8;opacity:.16;transition:opacity .35s;pointer-events:none;white-space:nowrap;",
    "  text-shadow:0 0 8px #000;max-width:94vw;overflow:hidden}",
    "#lb:hover #kinhd{opacity:.92}",
    "#kinhd .kb{padding:2px 8px;border-radius:20px;border:1px solid}",
    "#kinnavL,#kinnavR{position:absolute;top:50%;transform:translateY(-50%);z-index:4;",
    "  width:34px;height:34px;border-radius:50%;border:1px solid rgba(255,255,255,.14);",
    "  background:rgba(12,12,14,.5);color:#9aa0a8;cursor:pointer;font-size:15px;line-height:1;",
    "  opacity:0;transition:opacity .3s;backdrop-filter:blur(5px)}",
    "#kinnavL{left:12px}#kinnavR{right:12px}",
    "#lb.kinon:hover #kinnavL.has,#lb.kinon:hover #kinnavR.has{opacity:.75}",
    "#kinnavL:hover,#kinnavR:hover{opacity:1 !important;color:#dfe3e8;border-color:rgba(255,255,255,.3)}",

    /* 指认模式 chrome（沿用 v2/v3） */
    "#pinBtn{position:fixed;right:16px;bottom:16px;z-index:80;width:38px;height:38px;",
    "  border-radius:50%;border:1px solid rgba(255,255,255,.14);background:rgba(12,12,14,.62);",
    "  color:#8d949d;cursor:pointer;font-size:16px;line-height:1;opacity:.30;",
    "  transition:opacity .3s,transform .2s,border-color .3s,color .3s;backdrop-filter:blur(6px)}",
    "#pinBtn:hover{opacity:1;transform:scale(1.08);color:#cfd4da;border-color:rgba(255,255,255,.3)}",
    "#pinBtn.on{opacity:1;background:#241e33;border-color:#8a6fd0;color:#c39cf0}",
    "#pinBar{position:fixed;left:50%;top:14px;transform:translateX(-50%);z-index:81;",
    "  display:none;align-items:center;gap:12px;padding:9px 15px;border-radius:12px;",
    "  background:rgba(16,14,24,.9);border:1px solid #4a3a70;backdrop-filter:blur(9px);",
    "  font:12px/1.4 -apple-system,'PingFang SC',sans-serif;color:#d6cfe8;",
    "  box-shadow:0 10px 40px rgba(0,0,0,.6);max-width:96vw;flex-wrap:wrap;justify-content:center}",
    "#pinBar.on{display:flex}",
    "#pinBar b{color:#c39cf0}",
    "#pinBar button{background:#1e1a2c;border:1px solid #4a3a70;color:#d6cfe8;",
    "  border-radius:8px;padding:5px 11px;cursor:pointer;font-size:11.5px}",
    "#pinBar button:hover{background:#2a2440;border-color:#7a62c0}",
    "#pinBar button:disabled{opacity:.38;cursor:not-allowed}",
    "#pinBar button.go{background:#2a2040;border-color:#8a6fd0;color:#e2d8ff;font-weight:600}",
    "#pinBar .cnt{font-variant-numeric:tabular-nums;color:#a89fd0}",
    "#field.pinmode .tile{cursor:crosshair}",
    ".tile.pinned .body{box-shadow:0 0 0 2px #a98cf0,0 0 40px 6px rgba(169,140,240,.34);border-radius:10px}",
    ".tile.pinned{z-index:70 !important}",
    "#expPanel{position:fixed;inset:0;z-index:90;display:none;align-items:center;",
    "  justify-content:center;background:rgba(0,0,0,.86);backdrop-filter:blur(4px)}",
    "#expPanel.on{display:flex}",
    "#expPanel .box{width:min(760px,92vw);background:#121218;border:1px solid #3a3a48;",
    "  border-radius:14px;padding:18px;font:13px/1.6 -apple-system,'PingFang SC',sans-serif;color:#dfe3e8}",
    "#expPanel h3{margin:0 0 8px;font-size:15px;font-weight:600}",
    "#expPanel p{margin:0 0 10px;color:#9aa0a8;font-size:12px}",
    "#expPanel textarea{width:100%;height:230px;background:#0b0b0f;border:1px solid #33333f;",
    "  border-radius:9px;padding:10px;color:#a8d8c8;font:11.5px/1.5 ui-monospace,Menlo,monospace}",
    "#expPanel .row{display:flex;gap:9px;margin-top:12px;flex-wrap:wrap}",
    "#expPanel button{background:#1c2734;border:1px solid #33506f;color:#bcd6f0;",
    "  border-radius:8px;padding:7px 14px;cursor:pointer;font-size:12.5px}",
    "#expPanel button:hover{background:#243447}",
    "#expPanel button.pri{background:#2a4d2f;border-color:#3f7a48;color:#c3ebcd}",
    "#kinToast{position:fixed;left:50%;bottom:64px;transform:translateX(-50%) translateY(12px);",
    "  z-index:95;background:rgba(20,18,30,.94);border:1px solid #4a3a70;color:#d6cfe8;",
    "  border-radius:10px;padding:8px 15px;font:12.5px/1.4 -apple-system,'PingFang SC',sans-serif;",
    "  opacity:0;pointer-events:none;transition:.25s;max-width:80vw;text-align:center}",
    "#kinToast.on{opacity:1;transform:translateX(-50%) translateY(0)}",
    "#kinToast.ok{border-color:#3f7a48;color:#c3ebcd}",
    "@media(max-width:900px){",
    "  #kintrack{gap:12px;padding:0 12px}",
    "  .kinfig img{height:var(--h,24vh);max-width:52vw}",
    "  #kinhd,#kinnavL,#kinnavR{display:none}",
    "}"
  ].join("");
  document.head.appendChild(st);

  /* ================= 尺寸策略：与上一版（v3）一致 ================= */
  function sizing(n) {
    if (n <= 2) return { h: "44vh", stag: "14px" };
    if (n <= 3) return { h: "40vh", stag: "14px" };
    if (n <= 4) return { h: "36vh", stag: "13px" };
    if (n <= 6) return { h: "30vh", stag: "12px" };
    if (n <= 8) return { h: "25vh", stag: "10px" };
    return { h: "21vh", stag: "9px" };
  }

  /* ================= 胶片条舞台 ================= */
  var lb = null, wrap = null, track = null, hd = null, navL = null, navR = null;
  var STRIP = [];
  var FOCUS = 0;
  var PANX = 0;            // 当前 translateX（px），单一事实来源
  var SNAP_T = null;       // 滑动吸附定时器
  var CLOSE_T = null;      // 延迟清理定时器（防关闭闪烁）

  function ensureStage() {
    lb = document.getElementById("lb");
    if (!lb) return false;
    if (!wrap) {
      wrap = document.createElement("div"); wrap.id = "kinwrap";
      track = document.createElement("div"); track.id = "kintrack";
      wrap.appendChild(track);
      navL = document.createElement("button"); navL.id = "kinnavL"; navL.textContent = "‹";
      navR = document.createElement("button"); navR.id = "kinnavR"; navR.textContent = "›";
      navL.addEventListener("click", function (e) { e.stopPropagation(); stepFocus(-1); });
      navR.addEventListener("click", function (e) { e.stopPropagation(); stepFocus(1); });
      hd = document.createElement("div"); hd.id = "kinhd";
      hd.addEventListener("click", function (e) { e.stopPropagation(); });
      lb.appendChild(wrap); lb.appendChild(navL); lb.appendChild(navR); lb.appendChild(hd);
      bindWheel();
    }
    return true;
  }

  function clearStage() {
    clearTimeout(SNAP_T); SNAP_T = null;
    if (track) { track.innerHTML = ""; track.style.transform = "translateX(0px)"; }
    if (hd) hd.innerHTML = "";
    STRIP = []; FOCUS = 0; PANX = 0;
    if (lb) lb.classList.remove("kinon");
    if (wrap) wrap.classList.remove("panning");
  }

  function buildStrip(openId) {
    if (!ensureStage()) return;
    clearTimeout(CLOSE_T); CLOSE_T = null;   // 取消待执行的延迟清理，防止误清新条带
    clearStage();
    var g = IDX[openId];
    if (!g) return;
    var members = g.members.filter(function (m) { return !!rec(m); });
    if (members.length < 2) return;

    var s = sizing(members.length);
    lb.style.setProperty("--h", s.h);
    lb.style.setProperty("--stag", s.stag);

    STRIP = members.slice();
    FOCUS = Math.max(0, STRIP.indexOf(openId));

    var loaded = 0;
    STRIP.forEach(function (mid, i) {
      var r = rec(mid); if (!r) return;
      var b = document.createElement("button");
      b.className = "kinfig"; b.dataset.kid = mid; b.dataset.idx = String(i);
      b.style.animationDelay = (Math.abs(i - FOCUS) * 55) + "ms";
      var img = document.createElement("img");
      img.src = r.src;                        // 整帧展示层（v4.1 回退：不再用主体裁剪）
      img.alt = ""; img.draggable = false;
      img.addEventListener("load", function () {
        loaded++;
        if (loaded === STRIP.length) centerOn(FOCUS, false);   // 全部就位后精确居中
      });
      b.appendChild(img);
      b.addEventListener("click", function (e) {
        e.stopPropagation();
        if (PIN.on) { togglePin(mid); return; }
        setFocus(i);
      });
      track.appendChild(b);
    });

    var b = BADGE[g.status] || BADGE.uncertain;
    hd.innerHTML = '<span class="kb" style="color:' + b[1] + ';border-color:' + b[1] +
      '55;background:' + b[1] + '12">' + b[0] + '</span>' +
      '<span>同一生物 · 同发育期 · ' + STRIP.length + ' 个角度</span>' +
      '<span style="color:#6f757e">' + esc(g.label) + '</span>' +
      '<span style="color:#565a62">触控板滑动或点击平移</span>' +
      (PIN.on ? '<span style="color:#c39cf0">· 指认模式：点击可勾选</span>' : '');

    lb.classList.add("kinon");
    applyFocus(false);
  }

  /* ---------------- 平移几何 ---------------- */
  function figs() { return track ? track.querySelectorAll(".kinfig") : []; }
  function centerTarget(i) {
    var f = figs(), el = f[i];
    if (!el || !wrap) return 0;
    return wrap.clientWidth / 2 - (el.offsetLeft + el.offsetWidth / 2);
  }
  function bounds() {
    var f = figs(); if (!f.length) return { lo: 0, hi: 0 };
    var hi = centerTarget(0), lo = centerTarget(f.length - 1);
    return lo < hi ? { lo: lo, hi: hi } : { lo: hi, hi: lo };
  }
  function nearestIndex() {
    var f = figs(), best = 0, bd = Infinity;
    for (var i = 0; i < f.length; i++) {
      var c = f[i].offsetLeft + f[i].offsetWidth / 2 + PANX;
      var d = Math.abs(c - wrap.clientWidth / 2);
      if (d < bd) { bd = d; best = i; }
    }
    return best;
  }
  function applyPan() { track.style.transform = "translateX(" + PANX + "px)"; }

  function centerOn(idx, animate) {
    if (!wrap || !track) return;
    PANX = centerTarget(idx);
    if (animate === false) {
      track.style.transition = "none";
      applyPan();
      void track.offsetWidth;                 // 强制回流，跳过动画
      track.style.transition = "";
    } else {
      track.style.transition = "";            // 清掉滑动期间设的 none，让 CSS 过渡接管
      applyPan();
    }
  }

  /* 焦点图为什么不升级到 r.full（实测结论，勿再改回）：
     r.full 是**整帧**高清图（实测 2745×4117，比例 0.667），不是主体裁剪；
     而条带用的是主体居中裁剪（640×355，比例 1.803）。若焦点图换成 r.full：
       1. 生物回到整帧中的原始位置 → 重新出现用户报的「对不齐/很偏」；
       2. 长宽比从 1.8 跳到 0.67 → 焦点图突然变成竖长条，条带布局跳动；
       3. 实测焦点图显示仅约 423px 高（38vh × 1.22），640px 源是 0.66× **缩小**，
          根本不存在放大模糊。为此下载 2745×4117 是纯浪费。
     因此焦点放大只用 transform scale，不换图源。 */
  function applyFocus(animate) {
    var f = figs();
    for (var i = 0; i < f.length; i++) f[i].classList.toggle("focus", i === FOCUS);
    centerOn(FOCUS, animate);
    updateNav();
    paintStripPins();
  }

  function setFocus(idx) {
    if (idx < 0 || idx >= STRIP.length || idx === FOCUS) return;
    FOCUS = idx;
    applyFocus(true);
  }
  function stepFocus(d) { setFocus(Math.min(STRIP.length - 1, Math.max(0, FOCUS + d))); }

  /* ---------------- 触控板 / 滚轮：自由平移 + 抬手吸附 ---------------- */
  function bindWheel() {
    wrap.addEventListener("wheel", function (e) {
      if (!lb.classList.contains("kinon") || STRIP.length < 2) return;
      e.preventDefault();
      var d = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
      if (!d) return;
      if (e.deltaMode === 1) d *= 16; else if (e.deltaMode === 2) d *= 400;
      d = Math.max(-160, Math.min(160, d));    // 单次事件限幅，防触控板惯性猛冲
      panBy(-d);
    }, { passive: false });
  }

  function panBy(delta) {
    var bd = bounds();
    PANX = Math.min(bd.hi, Math.max(bd.lo, PANX + delta));
    track.style.transition = "none";           // 跟手：平移期间关掉动画
    applyPan();
    wrap.classList.add("panning");
    var near = nearestIndex();                 // 滑动中即时更新焦点高亮（不居中）
    if (near !== FOCUS) {
      FOCUS = near;
      var f = figs();
      for (var i = 0; i < f.length; i++) f[i].classList.toggle("focus", i === FOCUS);
      updateNav();
    }
    clearTimeout(SNAP_T);
    SNAP_T = setTimeout(function () {           // 抬手（160ms 无新事件）→ 吸附居中
      SNAP_T = null;
      wrap.classList.remove("panning");
      centerOn(FOCUS, true);
    }, 160);
  }

  function updateNav() {
    if (!navL || !navR) return;
    navL.classList.toggle("has", FOCUS > 0);
    navR.classList.toggle("has", FOCUS < STRIP.length - 1);
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /* ================= 指认模式（沿用 v2/v3，未改语义） ================= */
  var PIN = { on: false, picked: [] };
  var pinBtn = null, pinBar = null, expPanel = null, toastEl = null;

  function toast(msg, ok) {
    if (!toastEl) { toastEl = document.createElement("div"); toastEl.id = "kinToast"; document.body.appendChild(toastEl); }
    toastEl.textContent = msg; toastEl.className = "on" + (ok ? " ok" : "");
    clearTimeout(toastEl._h); toastEl._h = setTimeout(function () { toastEl.className = ""; }, 2800);
  }

  function buildChrome() {
    if (!pinBtn) {
      pinBtn = document.createElement("button"); pinBtn.id = "pinBtn";
      pinBtn.title = "指认模式：点选几只生物，声明它们是同一只（或某只不属于本组）";
      pinBtn.textContent = "◎";
      pinBtn.addEventListener("click", togglePinMode);
      document.body.appendChild(pinBtn);
    }
    if (!pinBar) { pinBar = document.createElement("div"); pinBar.id = "pinBar"; document.body.appendChild(pinBar); }
    if (!expPanel) {
      expPanel = document.createElement("div"); expPanel.id = "expPanel";
      expPanel.innerHTML =
        '<div class="box"><h3>导出你的指认结果</h3>' +
        '<p>把下面这段 JSON 发给我（AI），我会据此更新分组数据并重新构建站点。' +
        '你的改动已即时生效在本页，也已存在浏览器里，不会丢。</p>' +
        '<textarea id="expTa" readonly></textarea>' +
        '<div class="row"><button class="pri" id="expCopy">复制</button>' +
        '<button id="expDl">下载 JSON</button><button id="expClose">关闭</button>' +
        '<button id="expReset" style="margin-left:auto;border-color:#6b3a3a;color:#e8b0b0">清空全部指认</button></div></div>';
      document.body.appendChild(expPanel);
      expPanel.addEventListener("click", function (e) { if (e.target === expPanel) closeExp(); });
      document.getElementById("expCopy").addEventListener("click", function () {
        var ta = document.getElementById("expTa"); ta.select();
        try { navigator.clipboard.writeText(ta.value); toast("已复制到剪贴板", true); }
        catch (e) { toast("请手动全选复制（Ctrl/⌘+C）"); }
      });
      document.getElementById("expDl").addEventListener("click", function () {
        var blob = new Blob([document.getElementById("expTa").value], { type: "application/json" });
        var a = document.createElement("a"); a.href = URL.createObjectURL(blob);
        a.download = "kinship_corrections.json"; a.click();
        setTimeout(function () { URL.revokeObjectURL(a.href); }, 4000);
      });
      document.getElementById("expClose").addEventListener("click", closeExp);
      document.getElementById("expReset").addEventListener("click", function () {
        COR = { merge: [], remove: {} }; saveCOR(); reindex(); renderPinBar();
        if (curOpenId) buildStrip(curOpenId);
        paintFieldPins(); toast("已清空全部指认，恢复 AI 原分组");
      });
    }
  }
  function openExp() {
    buildChrome();
    document.getElementById("expTa").value = JSON.stringify(exportCorrections(), null, 1);
    expPanel.classList.add("on");
  }
  function closeExp() { expPanel.classList.remove("on"); }

  function togglePinMode() {
    buildChrome();
    PIN.on = !PIN.on;
    if (!PIN.on) PIN.picked = [];
    pinBtn.classList.toggle("on", PIN.on);
    pinBtn.textContent = PIN.on ? "◉" : "◎";
    document.getElementById("field").classList.toggle("pinmode", PIN.on);
    renderPinBar(); paintFieldPins(); paintStripPins();
    if (PIN.on) toast("指认模式：点击漂浮的生物选中它，选 2 只以上可声明「同一只」", true);
  }

  function renderPinBar() {
    if (!pinBar) return;
    if (!PIN.on) { pinBar.classList.remove("on"); return; }
    var n = PIN.picked.length, canMerge = n >= 2;
    var pg = {}; PIN.picked.forEach(function (id) { var g = IDX[id]; if (g) pg[g.id] = g; });
    var inGroup = Object.keys(pg);
    pinBar.classList.add("on");
    pinBar.innerHTML =
      '<span><b>指认模式</b> 已选 <span class="cnt">' + n + '</span> 只</span>' +
      '<button class="go" id="pbMerge" ' + (canMerge ? "" : "disabled") + '>声明为同一只生物</button>' +
      '<button id="pbRemove" ' + (n >= 1 && inGroup.length ? "" : "disabled") + '>移出所属分组</button>' +
      '<button id="pbClear" ' + (n ? "" : "disabled") + '>取消选择</button>' +
      '<button id="pbExport">导出反馈</button><button id="pbExit">退出</button>' +
      (inGroup.length ? '<span style="color:#8d949d">已选图所属组：' +
        inGroup.map(function (k) { return esc(pg[k].label); }).join("、") + '</span>' : '');
    document.getElementById("pbMerge").addEventListener("click", doMerge);
    document.getElementById("pbRemove").addEventListener("click", doRemove);
    document.getElementById("pbClear").addEventListener("click", function () {
      PIN.picked = []; renderPinBar(); paintFieldPins(); paintStripPins();
    });
    document.getElementById("pbExport").addEventListener("click", openExp);
    document.getElementById("pbExit").addEventListener("click", togglePinMode);
  }

  function togglePin(id) {
    var i = PIN.picked.indexOf(id);
    if (i >= 0) PIN.picked.splice(i, 1); else PIN.picked.push(id);
    renderPinBar(); paintFieldPins(); paintStripPins();
  }
  function paintFieldPins() {
    var ts = document.querySelectorAll("#field .tile");
    for (var i = 0; i < ts.length; i++) ts[i].classList.toggle("pinned", PIN.picked.indexOf(ts[i].dataset.id) >= 0);
  }
  function paintStripPins() {
    var f = figs();
    for (var i = 0; i < f.length; i++) f[i].classList.toggle("pinned", PIN.picked.indexOf(f[i].dataset.kid) >= 0);
  }

  function doMerge() {
    var ids = PIN.picked.slice(); if (ids.length < 2) return;
    var dup = COR.merge.some(function (s) { return s.ids.length === ids.length && ids.every(function (x) { return s.ids.indexOf(x) >= 0; }); });
    if (!dup) COR.merge.push({ ids: ids, at: new Date().toISOString(), source: "user_pin" });
    saveCOR(); reindex();
    var g = IDX[ids[0]];
    toast("已声明 " + ids.length + " 只为同一生物" + (g ? "（组：" + g.label + "）" : ""), true);
    PIN.picked = []; renderPinBar(); paintFieldPins(); paintStripPins();
    if (curOpenId) buildStrip(curOpenId);
  }
  function doRemove() {
    var n = 0;
    PIN.picked.forEach(function (id) {
      var g = IDX[id]; if (!g || g.origin === "user") return;
      var arr = COR.remove[g.id] || (COR.remove[g.id] = []);
      if (arr.indexOf(id) < 0) { arr.push(id); n++; }
    });
    if (!n) { toast("所选图不在任何 AI 分组内，无法移出"); return; }
    saveCOR(); reindex();
    toast("已把 " + n + " 只移出所属分组", true);
    PIN.picked = []; renderPinBar(); paintFieldPins(); paintStripPins();
    if (curOpenId) buildStrip(curOpenId);
  }

  function exportCorrections() {
    var nRem = Object.keys(COR.remove).reduce(function (s, k) { return s + COR.remove[k].length; }, 0);
    return {
      schema: "plankton-playground/kinship-corrections/v1",
      exported_at: new Date().toISOString(),
      site: "blackwater-plankton-archive (PlanktonTest 108)",
      counts: { merge_sets: COR.merge.length, removed_ids: nRem },
      note: ("merge = 用户声明这些图是同一只生物（可跨原有分组合并）；" +
             "remove = 用户声明该图不属于该 AI 分组。" +
             "AI 应据此更新 kinship.json 并重新注入站点。"),
      corrections: COR,
      effective_groups_snapshot: effectiveGroups().map(function (g) {
        return { id: g.id, label: g.label, status: g.status, origin: g.origin, members: g.members };
      })
    };
  }

  /* ---- 捕获阶段拦截场中点击：指认模式下不打开灯箱 ---- */
  var FIELD = document.getElementById("field");
  if (FIELD) {
    FIELD.addEventListener("click", function (e) {
      if (!PIN.on) return;
      var t = e.target.closest ? e.target.closest(".tile") : null;
      if (!t) return;
      e.stopPropagation(); e.preventDefault();
      togglePin(t.dataset.id);
    }, true);
  }

  /* ---- 键盘：← → 平移焦点；P 指认模式；Esc 退出/关闭 ---- */
  addEventListener("keydown", function (e) {
    var tag = document.activeElement && document.activeElement.tagName;
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(tag)) return;
    if ((e.key === "ArrowLeft") && lb && lb.classList.contains("kinon")) { e.preventDefault(); stepFocus(-1); return; }
    if ((e.key === "ArrowRight") && lb && lb.classList.contains("kinon")) { e.preventDefault(); stepFocus(1); return; }
    if (e.key === "p" || e.key === "P") { togglePinMode(); return; }
    if (e.key === "Escape") {
      if (expPanel && expPanel.classList.contains("on")) { closeExp(); e.stopImmediatePropagation(); }
      else if (PIN.on) { togglePinMode(); e.stopImmediatePropagation(); }
    }
  }, true);

  addEventListener("resize", function () { if (lb && lb.classList.contains("kinon")) centerOn(FOCUS, false); });

  /* ================= 挂载到既有钩子 ================= */
  var curOpenId = null;
  if (typeof on === "function") {
    on("lightbox:open", function (p) { curOpenId = p && p.id; buildStrip(curOpenId); });
    on("lightbox:close", function () {
      curOpenId = null;
      /* 防闪烁：#lb 有 .4s 淡出过渡。立即拆条带会让引擎单图 .frame 带着
         上一张主图重新可见并跟着淡出——那就是用户看到的 ~0.1s 闪烁。
         改为保留 .kinon（.frame 持续隐藏）至淡出结束后再清理。 */
      clearTimeout(CLOSE_T);
      CLOSE_T = setTimeout(function () { CLOSE_T = null; clearStage(); }, 460);
    });
  }
  buildChrome();

  window.PlaygroundKin = {
    version: "kin-4.1",
    groups: function () { return effectiveGroups(); },
    groupsCount: function () { return effectiveGroups().length; },
    corrections: function () { return COR; },
    exportCorrections: exportCorrections,
    pinMode: function (on) { if (!!on !== PIN.on) togglePinMode(); },
    strip: function () { return STRIP.slice(); },
    focusIndex: function () { return FOCUS; },
    panX: function () { return PANX; },
    setFocus: setFocus,
    note: "v4.1：回退主体裁剪，条带用整帧展示层+上一版尺寸；保留触控板平移吸附与无闪烁关闭。"
  };
})();
