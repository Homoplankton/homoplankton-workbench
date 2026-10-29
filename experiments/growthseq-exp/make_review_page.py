#!/usr/bin/env python3
"""make_review_page.py — 生成「两段式人在环」第二段的复核页。

目的：用户复核的是一段判断，不是一堆路径。所以这个页面把
  裁切图（高分辨率主体放大）+ 图像基本信息 + 我的分类/阶段判断 + 诊断依据 + 引用状态
并排呈现，并提供可编辑控件与「导出修改」按钮，使复核结果能以 JSON 回传，
而不必靠用户手打描述（易漏、易歧义）。

图片以 base64 内嵌 → 单文件、离线可开、可直接交付。
"""
import base64
import html
import json
import os

EXP = "/Users/jialingcai/Documents/qwen-agent/NZKKxizmz2/default/growthseq-exp"
DRAFT = os.path.join(EXP, "draft_annotations_v5.json")
MANIFEST = os.path.join(EXP, "sample_manifest.json")
OUT = os.path.join(EXP, "review_page.html")

# 核验分级：「有链接」≠「我读过」。三者必须可区分，否则用户无法判断该信多少。
TIER = {
    "opened":        ("已打开核验", "#5ec97f"),
    "bibliographic": ("书目已互证", "#6fa8dc"),
    "link_only":     ("仅有链接·待你核验", "#e0b252"),
}
# 链接可达性：反爬墙 403 不等于链接失效，但也不能标成「已核验可达」。
LINKST = {
    "opens_now":   ("现在可打开", "#5ec97f"),
    "bot_walled":  ("反爬墙挡住·未确认", "#e0b252"),
    "unreachable": ("当前不可达", "#e0685f"),
}


def b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def esc(s):
    return html.escape(str(s)) if s is not None else ""


def conf_class(c):
    if c >= 0.85:
        return "high"
    if c >= 0.6:
        return "mid"
    return "low"


def render_ref(x):
    """把 v5 的引用（dict，含 url/verify_level/link_status）渲染成可点击条目。

    兼容 v3 的纯字符串形式（历史数据）；两者混存时不崩。
    """
    if isinstance(x, str):
        cls = "pending" if x == "pending" else ""
        txt = "待检索补充" if x == "pending" else x
        return f"<li class='{cls}'>{esc(txt)}</li>"

    text = x.get("text") or ""
    url = x.get("url")
    tier, tcolor = TIER.get(x.get("verify_level"), TIER["link_only"])
    lst, lcolor = LINKST.get(x.get("link_status"), ("链接状态未知", "#9a9aa2"))
    code = x.get("http_code")
    badge = f'<span class="tier" style="color:{tcolor};border-color:{tcolor}55;background:{tcolor}14">{esc(tier)}</span>'
    link = (f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(text)}</a>'
            if url else f'<span class="nolink">{esc(text)}</span>')
    lnote = x.get("link_note") or ""
    note = f'<div class="lnote">{esc(lnote)}</div>' if lnote else ""
    codelbl = f" HTTP {esc(code)}" if code not in (None, "") else ""
    return (f'<li>{badge}<span class="lstat" style="color:{lcolor}">{esc(lst)}{codelbl}</span>'
            f'{link}{note}</li>')


def main():
    draft = json.load(open(DRAFT, encoding="utf-8"))
    manifest = {m["id"]: m for m in json.load(open(MANIFEST, encoding="utf-8"))}
    recs = draft["records"]

    cards = []
    series_notes = []
    for r in recs:
        rid = r["id"]
        m = manifest.get(rid, {})
        img_path = os.path.join(EXP, r["image"]["crop"])
        data_uri = "data:image/jpeg;base64," + b64(img_path) if os.path.isfile(img_path) else ""
        t = r["taxonomy"]
        st = r["stage"]
        path_items = "".join(f'<span class="lvl">{esc(x)}</span>' for x in t["path"])
        alts = ""
        if t.get("alternatives"):
            alts = "<div class='alts'>替代假说：" + " · ".join(
                f"{esc(a[0])} ({a[1]:.2f})" for a in t["alternatives"]) + "</div>"
        diags = "".join(f"<li>{esc(d)}</li>" for d in r["diagnostics"])
        refs = "".join(render_ref(x) for x in r["references"])
        ver = r.get("_lv")
        lsv = r.get("_ls")
        if ver:
            ver_html = (
                f"<div class='verif'><b>引用核验分级</b>"
                f"已打开核验 {ver.get('opened', 0)} · 书目已互证 {ver.get('bibliographic', 0)} · "
                f"仅有链接待你核验 {ver.get('link_only', 0)}<br>"
                + (f"<span class='caveat'>链接可达性：现在可打开 {lsv.get('opens_now', 0)} · "
                   f"反爬墙未确认 {lsv.get('bot_walled', 0)} · "
                   f"当前不可达 {lsv.get('unreachable', 0)}</span>" if lsv else "")
                + "</div>")
        else:
            ver_html = ""
        note = r.get("reviewer_note")
        note_html = f"<div class='neednote'><b>需要你判断：</b>{esc(note)}</div>" if note else ""
        series = r.get("series_hypothesis")
        if series:
            series_notes.append((rid, series))
            series_html = f"<div class='series'><b>序列假设：</b>{esc(series)}</div>"
        else:
            series_html = ""

        # 阶段块：离散名 / 分期依据 / 指标 / 排序键 / 依据 / 文献说明
        if st.get("discrete_label"):
            stage_head = f"离散分期：<code>{esc(st['discrete_label'])}</code>"
        elif st.get("sort_key") is None:
            # 不硬编码「不适用」：能否进序列取决于文献结论，直接展示 continuum_note。
            # 早前此处写死「无后生动物发育序列」，导致与 s09 栉水母的撤销结论相矛盾。
            stage_head = f"阶段排序：<span class='nostage'>{esc(st.get('continuum_note') or '待定')}</span>"
        else:
            stage_head = "离散分期：<span class='nostage'>无（该类群发育连续，文献无离散分期）</span>"
        sk = st.get("sort_key")
        sk_html = (f"排序键 stage_order={sk['stage_order']}, within={sk['within']}"
                   if sk else "排序键：不适用")
        basis_row = (f"<div class='row'><span class='k'>分期依据</span>"
                     f"<span class='v'>{esc(st['label_basis'])}</span></div>"
                     if st.get("label_basis") else "")
        litnote_row = (f"<div class='litnote'><b>文献说明</b>{esc(st['literature_note'])}</div>"
                       if st.get("literature_note") else "")
        stage_body = f"""
          <div class='row'><span class='k'>阶段</span><span class='v'>{stage_head}</span></div>
          {basis_row}
          <div class='row'><span class='k'>指标</span><span class='v'>{esc(st.get('indicator') or '—')}</span></div>
          <div class='row'><span class='k'>排序键</span><span class='v'><code>{esc(sk_html)}</code></span></div>
          <div class='row'><span class='k'>依据</span><span class='v'>{esc(st.get('maturity_basis') or '—')}</span></div>
          <div class='row'><span class='k'>连续谱说明</span><span class='v'>{esc(st.get('continuum_note') or '—')}</span></div>
          <div class='row'><span class='k'>阶段置信</span><span class='v'>{st.get('confidence', 0):.2f}</span></div>
          {litnote_row}
        """

        ow, oh = m.get("orig", ["?", "?"])
        cw, ch = m.get("crop_size", ["?", "?"])
        bf = m.get("box_frac")
        info = f"""
          <div class='info'>
            <span>拍摄 <b>{esc(m.get('date','?'))}</b></span>
            <span>相机 <b>{esc(m.get('camera','?'))}</b></span>
            <span>原图 <b>{ow}×{oh}</b></span>
            <span>纵横比 <b>{m.get('aspect','?')}</b></span>
            <span>主体占比 <b>{bf if bf is not None else 'null（全暗帧）'}</b></span>
            <span>裁切 <b>{cw}×{ch}</b></span>
            <span>显示层 <b>{m.get('src_w','?')}×{m.get('src_h','?')}</b></span>
          </div>"""

        cards.append(f"""
      <article class="card" id="card-{esc(rid)}">
        <div class="shot">
          <img src="{data_uri}" alt="{esc(rid)}" loading="lazy">
        </div>
        <div class="meta">
          <header>
            <h2>{esc(rid)}</h2>
            <span class="badge {'need' if note else 'ok'}">{'待你判断' if note else '待确认'}</span>
            <span class="badge status">status: draft</span>
          </header>
          {info}
          <div class="row"><span class="k">分类路径</span><span class="v path">{path_items}</span></div>
          <div class="row"><span class="k">停层原因</span><span class="v">{esc(t.get('stop_reason','—'))}</span></div>
          <div class="row"><span class="k">分类置信</span>
            <span class="v"><span class="bar {conf_class(t['confidence'])}">
              <i style="width:{int(t['confidence']*100)}%"></i></span> {t['confidence']:.2f}</span></div>
          {alts}
          {stage_body}
          <div class="row"><span class="k">诊断特征</span><span class="v"><ul class="diag">{diags}</ul></span></div>
          <div class="row"><span class="k">引用</span><span class="v"><ul class="refs">{refs}</ul></span></div>
          {ver_html}
          {note_html}
          {series_html}

          <div class="review">
            <div class="rrow">
              <label>裁决</label>
              <select data-f="verdict">
                <option value="">—</option>
                <option value="confirm">认可（confirmed）</option>
                <option value="correct">需修改（我改下方路径）</option>
                <option value="reject">否决（判断错）</option>
              </select>
              <label>无发育序列</label>
              <input type="checkbox" data-f="no_sequence">
            </div>
            <div class="rrow">
              <label>分类路径改为</label>
              <input type="text" data-f="taxonomy_path" placeholder="例：Animalia/Mollusca/Cephalopoda/Octopoda/Argonautidae/Argonauta">
            </div>
            <div class="rrow">
              <label>离散分期改为</label>
              <input type="text" data-f="stage_label" placeholder="例：zoea II / veliger / megalopa；留空=维持">
            </div>
            <div class="rrow">
              <label>备注</label>
              <input type="text" data-f="note" placeholder="你的判断依据或纠正说明">
            </div>
          </div>
        </div>
      </article>""")

    n_need = sum(1 for r in recs if r.get("reviewer_note"))
    n_low = sum(1 for r in recs if r["taxonomy"]["confidence"] < 0.6)
    n_species = sum(1 for r in recs if len(r["taxonomy"]["path"]) >= 6)

    # v5 的引用是 dict（含 url），不可哈希；按书目文本去重。
    # 口径必须写清：n_refs = 引用出现次数（跨记录重复计数），n_uniq = 唯一文献数。
    all_refs = [x for r in recs for x in r["references"]]
    n_refs = len(all_refs)

    def ref_key(x):
        return x if isinstance(x, str) else (x.get("text") or "")
    n_uniq = len({ref_key(x) for x in all_refs})
    n_pending = sum(1 for x in all_refs if x == "pending")
    n_withurl = sum(1 for x in all_refs if isinstance(x, dict) and x.get("url"))

    tally_lv = {k: 0 for k in TIER}
    tally_ls = {k: 0 for k in LINKST}
    for x in all_refs:
        if isinstance(x, dict):
            tally_lv[x.get("verify_level") or "link_only"] += 1
            tally_ls[x.get("link_status") or "unreachable"] += 1
    n_opened = tally_lv["opened"]
    n_verified = n_opened          # 「已逐条打开核验」= opened 级引用数
    n_ref_verified = n_opened
    n_label = sum(1 for r in recs if r["stage"].get("discrete_label"))
    series_block = "".join(
        f"<li><b>{esc(a)}</b> — {esc(b)}</li>" for a, b in series_notes) or "<li>本批未浮现序列假设</li>"

    page = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>生长发育序列 · 草稿复核页（10 张探针批）</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0a0a0c;color:#e8e8ea;font-family:-apple-system,"PingFang SC","Helvetica Neue",Arial,sans-serif;
     line-height:1.55;padding:28px 20px 90px}}
.wrap{{max-width:1180px;margin:0 auto}}
h1{{font-size:22px;font-weight:600;letter-spacing:.02em;margin-bottom:6px}}
.sub{{color:#9a9aa2;font-size:13px;margin-bottom:18px}}
.sub code{{color:#c9d4e0;background:#15171c;padding:1px 5px;border-radius:4px}}
.summary{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin:16px 0 22px}}
.stat{{background:#121318;border:1px solid #23252c;border-radius:10px;padding:12px 14px}}
.stat b{{display:block;font-size:22px;font-weight:600;color:#fff}}
.stat span{{font-size:12px;color:#9a9aa2}}
.stat.warn b{{color:#ffb454}}
.stat.ok b{{color:#5ec97f}}
.policy{{background:#121318;border:1px solid #23252c;border-left:3px solid #4a9eff;border-radius:8px;
        padding:12px 16px;margin-bottom:20px;font-size:13px;color:#c4c8cf}}
.policy b{{color:#e8e8ea}}
.policy ul{{margin:6px 0 0 18px}}
.series{{background:#14120c;border:1px solid #3a3220;border-radius:8px;padding:10px 14px;
        margin-bottom:20px;font-size:13px}}
.series b{{color:#ffcf7a}} .series ul{{margin:6px 0 0 18px;color:#c4c8cf}}
.card{{display:grid;grid-template-columns:minmax(280px,400px) 1fr;gap:20px;background:#101116;
      border:1px solid #23252c;border-radius:14px;padding:16px;margin-bottom:18px}}
.shot{{background:#000;border-radius:10px;overflow:hidden;display:flex;align-items:center;justify-content:center;min-height:260px}}
.shot img{{width:100%;height:auto;display:block;cursor:zoom-in;transition:transform .3s ease}}
.shot img:active{{transform:scale(1.6)}}
.meta{{min-width:0}}
header{{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:10px}}
h2{{font-size:17px;font-weight:600;color:#fff;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}}
.badge{{font-size:11px;padding:2px 8px;border-radius:20px;border:1px solid}}
.badge.need{{color:#ffb454;border-color:#5c4520;background:#241a0c}}
.badge.ok{{color:#8fd3a0;border-color:#2c4a35;background:#0f1c14}}
.badge.status{{color:#9a9aa2;border-color:#303339;background:#16181d}}
.info{{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:11.5px;color:#8b8e96;
      padding:8px 10px;background:#0c0d11;border-radius:8px;margin-bottom:12px}}
.info b{{color:#c9cdd4;font-weight:500}}
.row{{display:grid;grid-template-columns:88px 1fr;gap:10px;font-size:12.5px;padding:4px 0;
     border-bottom:1px solid #1b1d23}}
.row .k{{color:#7f828a}}
.row .v{{color:#d6d9de;min-width:0;word-break:break-word}}
.path{{display:flex;flex-wrap:wrap;gap:4px}}
.lvl{{background:#1a2432;color:#a8c8ec;border:1px solid #26374d;border-radius:5px;
     padding:1px 7px;font-size:11.5px;font-family:ui-monospace,Menlo,monospace}}
.lvl:last-child{{background:#233348;color:#d6e6fa;border-color:#3c5c86;font-weight:600}}
.bar{{display:inline-block;width:64px;height:6px;background:#22242a;border-radius:4px;overflow:hidden;vertical-align:middle}}
.bar i{{display:block;height:100%}}
.bar.high i{{background:#5ec97f}} .bar.mid i{{background:#e8b64c}} .bar.low i{{background:#e0685f}}
.alts,.neednote,.litnote{{font-size:12.5px;margin:8px 0;padding:8px 11px;border-radius:7px}}
.alts{{background:#161318;color:#c4b8d4;border:1px solid #2e2738}}
.neednote{{background:#1e1508;color:#ffd9a0;border:1px solid #4a3a1c}}
.litnote{{background:#101820;color:#a9cfe8;border:1px solid #23404f;line-height:1.6}}
.litnote b{{display:block;color:#d6eaf7;font-size:11.5px;letter-spacing:.06em;margin-bottom:4px}}
ul.refs{{font-size:12px}} ul.refs li{{margin-bottom:6px;color:#b9c6d2}}
ul.refs a{{color:#8fc0f0;text-decoration:none;border-bottom:1px dotted #4a6a8a}}
ul.refs a:hover{{color:#cfe6ff;border-bottom-color:#cfe6ff}}
ul.refs .nolink{{color:#b9c6d2}}
.tier{{display:inline-block;font-size:10px;font-weight:700;padding:1px 6px;border:1px solid;
      border-radius:4px;margin-right:6px;vertical-align:1px;white-space:nowrap}}
.lstat{{font-size:10.5px;margin-right:6px;white-space:nowrap}}
.lnote{{color:#7d8189;font-size:10.5px;margin-top:2px;padding-left:2px;line-height:1.5}}
.verif{{background:#0e1a13;color:#a8dcc0;border:1px solid #24483280;border-radius:7px;
       padding:8px 11px;margin:8px 0;font-size:12px;line-height:1.6}}
.verif b{{display:block;color:#7fd8a4;font-size:11.5px;letter-spacing:.06em;margin-bottom:4px}}
.verif .caveat{{color:#c9b98a;display:block;margin-top:4px}}
code{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;
     background:#171a20;color:#a8d8c8;padding:1px 5px;border-radius:4px}}
.nostage{{color:#7f828a;font-style:italic}}
ul.diag,ul.refs{{margin-left:16px}} ul.diag li,ul.refs li{{margin-bottom:2px}}
ul.refs li.pending{{color:#8b7a5c;font-style:italic}}
.review{{margin-top:14px;background:#0c0d11;border:1px solid #26282f;border-radius:10px;padding:12px}}
.rrow{{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px}}
.rrow:last-child{{margin-bottom:0}}
.rrow label{{font-size:11.5px;color:#8b8e96;min-width:76px}}
.rrow select,.rrow input[type=text]{{background:#15171c;border:1px solid #2c2f37;color:#e8e8ea;
     border-radius:6px;padding:5px 8px;font-size:12px;font-family:inherit}}
.rrow input[type=text]{{flex:1;min-width:200px}}
.rrow select:focus,.rrow input:focus{{outline:none;border-color:#4a9eff}}
.rrow input[type=checkbox]{{width:16px;height:16px;accent-color:#e0685f}}
.bar2{{position:fixed;left:0;right:0;bottom:0;background:rgba(10,10,12,.96);
      border-top:1px solid #26282f;padding:12px 20px;display:flex;gap:12px;align-items:center;
      justify-content:center;flex-wrap:wrap;backdrop-filter:blur(8px);z-index:50}}
.bar2 button{{background:#1c2734;border:1px solid #33506f;color:#bcd6f0;padding:8px 16px;
      border-radius:8px;font-size:13px;cursor:pointer;font-family:inherit}}
.bar2 button:hover{{background:#243447}}
.bar2 button.primary{{background:#2a4d2f;border-color:#3f7a48;color:#c3ebcd}}
.bar2 span{{font-size:12px;color:#8b8e96}}
#out{{width:100%;max-width:900px;margin:18px auto 0;display:none}}
#out textarea{{width:100%;height:300px;background:#0c0d11;border:1px solid #2c2f37;color:#a8d8c8;
      border-radius:10px;padding:12px;font-family:ui-monospace,Menlo,monospace;font-size:12px}}
.hint{{font-size:12px;color:#8b8e96;margin-top:6px}}
@media (max-width:860px){{.card{{grid-template-columns:1fr}}}}
</style></head><body><div class="wrap">
<h1>生长发育序列 · 草稿复核页</h1>
<div class="sub">10 张探针批 · 素材源 <code>PlanktonTest</code>（108 张中分层抽样）· 草稿 <code>{esc(draft.get('schema',''))}</code> · 生成于 2026-10-26 ·
全部记录 <code>status: draft</code>，等你裁决后才写入 confirmed 库</div>

<div class="summary">
  <div class="stat"><b>{len(recs)}</b><span>草稿记录</span></div>
  <div class="stat {'warn' if n_pending else 'ok'}"><b>{n_uniq}</b><span>唯一文献（{n_refs} 次引用，{n_withurl} 条附链接）</span></div>
  <div class="stat {'warn' if n_pending else 'ok'}"><b>{n_pending}</b><span>仍标 pending 的引用</span></div>
  <div class="stat"><b>{n_label}</b><span>有文献定义的离散分期</span></div>
  <div class="stat ok"><b>{n_opened}</b><span>已打开全文核验的引用</span></div>
  <div class="stat"><b>{tally_lv['bibliographic']}</b><span>书目已互证（未读全文）</span></div>
  <div class="stat warn"><b>{tally_lv['link_only']}</b><span>仅有链接·待你核验</span></div>
  <div class="stat warn"><b>{tally_ls['unreachable']}</b><span>链接当前不可达</span></div>
  <div class="stat warn"><b>{n_need}</b><span>标了「需要你判断」</span></div>
  <div class="stat warn"><b>{n_low}</b><span>分类置信 &lt; 0.60</span></div>
  <div class="stat"><b>{n_species}</b><span>能定到属级或更细</span></div>
  <div class="stat"><b>0</b><span>能定到种级</span></div>
</div>

<div class="policy">
  <b>本页遵循的三条原则（你定的）：</b>
  <ul>
    <li><b>分类停层不硬凑</b>：鉴定到置信度最高的层级即停，<code>停层原因</code> 一栏说明为什么停在那里。
        门级都定不了的就只标 Animalia 并列出替代假说。</li>
    <li><b>两级阶段模型</b>：<code>discrete_label</code> 只填文献定义的离散分期（zoea / veliger / megalopa /
        leptocephalus）；同一期内的相对成熟度用 <code>sort_key(stage_order, within)</code> 表达。
        插入新图只影响排序结果，<b>不需要手工重标编号</b>。</li>
    <li><b>引用不编造</b>：只填本轮真实检索到的文献，并区分层级 ——
        同行评议 &gt; 专著/技术报告 &gt; 定义层（Coastal Wiki / WoRMS）&gt; 科普（显式标注，仅作线索不作依据）。
        <b>检索改变了三处结论</b>（不只是装饰）：① 栉水母「直接发育→排除序列」的判断被撤销，因
        Edgar 2022 与 Soto-Angel 2024 结论冲突，能否进序列取决于类群；② 两张头足类由「无离散分期」
        升级为可引用的 <code>paralarva</code>（Young &amp; Harman 1988 术语定义）；③ 多毛类升级为
        <code>nectochaeta 或更晚期</code>（疣足幼体有文献定义，本个体刚毛与疣足已发育）。</li>
    <li><b>「有链接」≠「我读过」</b>：每条引用前的色标是分级诚实标注 ——
        <span style="color:#5ec97f">已打开核验</span>＝我确实抓到全文并核对过我引用的那句表述；
        <span style="color:#6fa8dc">书目已互证</span>＝有两个以上独立来源确认期刊/卷期/页码真实，但我未打开全文；
        <span style="color:#e0b252">仅有链接·待你核验</span>＝链接来自检索结果、书目看着合理，我尚未独立确认。
        链接可达性单独标注：出版社反爬墙返回 403 时，你在浏览器里点开大概率正常，但我不会把它标成「已核验可达」。</li>
  </ul>
</div>

<div class="series"><b>本批浮现的序列假设（同种性未经确认，需你裁）</b><ul>{series_block}</ul></div>

{"".join(cards)}

<div id="out"><textarea id="jsonout" readonly></textarea>
  <div class="hint">全选复制上面这段 JSON，发回给我即可。我只会把你裁决为 <code>confirm</code>/<code>correct</code>
  的记录写入 confirmed 库；标了「无发育序列」的会被排除出序列装配。</div></div>
</div>

<div class="bar2">
  <span>已填裁决：<b id="cnt">0</b> / {len(recs)}</span>
  <button class="primary" onclick="exportJson()">导出我的裁决 JSON</button>
  <button onclick="markAll()">全部认可（仅想快速通过时）</button>
  <button onclick="window.scrollTo({{top:0,behavior:'smooth'}})">回到顶部</button>
</div>

<script>
const IDS = {json.dumps([r['id'] for r in recs], ensure_ascii=False)};
function collect(){{
  const out = [];
  IDS.forEach(id => {{
    const card = document.getElementById('card-' + id);
    const g = f => card.querySelector('[data-f="' + f + '"]');
    const rec = {{
      id: id,
      verdict: g('verdict').value || null,
      no_sequence: g('no_sequence').checked || null,
      taxonomy_path: g('taxonomy_path').value.trim() || null,
      stage_label: g('stage_label').value.trim() || null,
      note: g('note').value.trim() || null
    }};
    if (rec.verdict || rec.no_sequence || rec.taxonomy_path || rec.stage_label || rec.note) out.push(rec);
  }});
  return out;
}}
function refresh(){{ document.getElementById('cnt').textContent = collect().length; }}
function exportJson(){{
  const recs = collect();
  const payload = {{ schema: "growth-sequence/review-v1", reviewed_at: new Date().toISOString(),
                     batch: "probe-10", reviewer: "user", records: recs }};
  const ta = document.getElementById('jsonout');
  ta.value = JSON.stringify(payload, null, 1);
  document.getElementById('out').style.display = 'block';
  ta.scrollIntoView({{behavior:'smooth', block:'center'}});
  ta.select();
  try {{ navigator.clipboard.writeText(ta.value); }} catch(e) {{}}
}}
function markAll(){{
  IDS.forEach(id => {{
    const s = document.querySelector('#card-' + CSS.escape(id) + ' [data-f="verdict"]');
    if (s && !s.value) s.value = 'confirm';
  }});
  refresh(); exportJson();
}}
document.addEventListener('change', refresh);
document.addEventListener('input', refresh);
</script>
</body></html>"""

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"✅ 复核页已生成: {OUT}")
    print(f"   体积: {os.path.getsize(OUT)/1024/1024:.2f} MB（含 {len(recs)} 张内嵌裁切图）")
    print(f"   待你判断: {n_need} 张 · 分类置信<0.6: {n_low} 张 · 到属级或更细: {n_species} 张 · 到种级: 0 张")


if __name__ == "__main__":
    main()
