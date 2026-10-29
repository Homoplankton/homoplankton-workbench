#!/usr/bin/env python3
"""build_review_page.py — 把草稿渲染成可复核的 HTML（v4：引用可点击 + 核验分级）。

分级诚实原则（用户要求可验证，但「有链接」≠「我读过」）：
  opened        我本轮真的抓到正文/摘要，并核对过我引用的那句表述
  bibliographic ≥2 个独立检索结果确认书目真实（期刊/卷期/页码），但我未打开全文
  link_only     链接来自检索结果，书目看似合理，我尚未独立确认 → 请你自行点开核对
"""
import base64
import html
import json
import os
import shutil
import sys

EXP = "/Users/jialingcai/Documents/qwen-agent/NZKKxizmz2/default/growthseq-exp"
SRC = os.path.join(EXP, "draft_annotations_v4.json")
OUT = os.path.join(EXP, "review_page.html")

TIER_LABEL = {
    "opened": ("已打开核验", "#1a9850", "#e8f7ee"),
    "bibliographic": ("书目已互证", "#1565c0", "#e8f1fb"),
    "link_only": ("仅有链接·待你核验", "#b8860b", "#fdf6e3"),
}


def b64img(p):
    with open(p, "rb") as f:
        raw = f.read()
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode()


def esc(s):
    return html.escape(str(s))


def render_refs(refs):
    out = []
    for r in refs:
        tier, color, bg = TIER_LABEL.get(r["verify_level"], TIER_LABEL["link_only"])
        out.append(
            '<li>'
            f'<span class="tier" style="color:{color};background:{bg};border-color:{color}">{esc(tier)}</span> '
            f'<a href="{esc(r["url"])}" target="_blank" rel="noopener noreferrer">{esc(r["text"])}</a>'
            f'<div class="lnote">{esc(r.get("link_note",""))}</div>'
            '</li>'
        )
    return '<ul class="refs">' + "".join(out) + "</ul>"


def main():
    d = json.load(open(SRC, encoding="utf-8"))
    recs = d["records"]

    assets = os.path.join(EXP, "assets")
    os.makedirs(assets, exist_ok=True)
    n_ok = n_fail = 0
    for r in recs:
        src, name = r["thumb"], r["id"] + "_thumb.jpg"
        dst = os.path.join(assets, name)
        if os.path.isfile(src):
            shutil.copyfile(src, dst)
            r["_img"] = b64img(dst)
            n_ok += 1
        else:
            r["_img"] = ""
            n_fail += 1

    # 统计各等级
    tally = {k: 0 for k in TIER_LABEL}
    total_refs = 0
    for r in recs:
        for x in r["references"]:
            tally[x["verify_level"]] = tally.get(x["verify_level"], 0) + 1
            total_refs += 1

    def card(r):
        phs = ""
        for p in r["phases"]:
            ev = '<span class="ev">⚠️ ' + esc(p["evidence"]) + "</span>" if p.get("evidence") else ""
            phs += (
                f'<div class="phase"><b>阶段{p["index"]} · {esc(p["name"])}</b> '
                f'<span class="tag">{esc(p["stage"])}</span><br>{ev}</div>'
            )
        v = r.get("verification", {})
        vl = v.get("verify_levels", {})
        vrow = ""
        if v:
            parts = []
            if v.get("status") == "confirmed":
                parts.append('<span class="ok">✅ 已打开文献逐条核验</span>')
            else:
                parts.append('<span class="pending">⬜ 未逐条打开核验</span>')
            parts.append(
                f'<span class="cnt">opened {vl.get("opened",0)} · '
                f'书目互证 {vl.get("bibliographic",0)} · '
                f'待核 {vl.get("link_only",0)}</span>'
            )
            if v.get("caveat"):
                parts.append(f'<div class="caveat">⚠️ 适用局限：{esc(v["caveat"])}</div>')
            if v.get("correction"):
                parts.append(f'<div class="correction">🔧 更正：{esc(v["correction"])}</div>')
            vrow = '<div class="vrow">' + "".join(parts) + "</div>"

        img = f'<img class="thumb" src="{r["_img"]}" alt="{esc(r["id"])}">' if r["_img"] else '<div class="noimg">图片缺失</div>'
        warn = '<div class="warn">⚠️ 该图未归入任何阶段，原因见下</div>' if r.get("unresolved_reason") else ""
        reason = f'<div class="why">{esc(r["unresolved_reason"])}</div>' if r.get("unresolved_reason") else ""
        conf = f'<div class="conf">置信度 <b>{r["confidence"]:.0%}</b></div>'

        return f'''<div class="card{' unresolved' if r.get("unresolved") else ''}">
<div class="cleft">{img}<div class="conf">{esc(r["id"])}</div></div>
<div class="cright">
  <div class="taxo"><b>{esc(r.get("taxon","—"))}</b> · 发育类型 <b>{esc(r.get("development","—"))}</b> · 阶段数 <b>{len(r["phases"])}</b>{conf}{warn}</div>
  {phs}{reason}{vrow}
  <div class="refhd">📎 引用文献（点击可打开原文核对）</div>
  {render_refs(r["references"])}
</div></div>'''

    cards = "".join(card(r) for r in recs)
    confirmed_n = sum(1 for r in recs if r.get("verification", {}).get("status") == "confirmed")

    page = f'''<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>生长发育序列 · 草稿复核页 v4</title>
<style>
*{{box-sizing:border-box}}
body{{font-family:-apple-system,"PingFang SC",sans-serif;margin:0;background:#f5f5f4;color:#222;line-height:1.55}}
header{{background:#0d2b3e;color:#fff;padding:18px 24px}}
header h1{{margin:0 0 6px;font-size:19px}}
header p{{margin:2px 0;font-size:13px;color:#c8dce8}}
.banner{{background:#fff8e1;border-bottom:1px solid #e6d9a8;padding:10px 24px;font-size:13px;color:#6b5b1a}}
.hdrbtn{{display:inline-block;margin-top:10px;padding:8px 16px;background:#2e8b57;color:#fff;border:0;border-radius:6px;font-size:14px;cursor:pointer;font-weight:600}}
.hdrbtn[disabled]{{background:#9aa7a0;cursor:not-allowed}}
main{{max-width:1180px;margin:0 auto;padding:16px}}
.card{{display:flex;gap:14px;background:#fff;border-radius:8px;margin-bottom:12px;padding:12px;box-shadow:0 1px 3px rgba(0,0,0,.09)}}
.card.unresolved{{border-left:4px solid #e0a030;background:#fffcf5}}
.cleft{{flex:0 0 200px}}
.thumb{{width:200px;border-radius:5px;display:block;background:#000}}
.noimg{{width:200px;height:130px;display:flex;align-items:center;justify-content:center;background:#eee;color:#999;border-radius:5px;font-size:12px}}
.cright{{flex:1;min-width:0}}
.taxo{{font-size:13px;margin-bottom:6px;color:#444}}
.taxo b{{color:#0d2b3e}}
.conf{{display:inline-block;margin-left:10px;padding:1px 8px;border-radius:9px;background:#eef3f7;font-size:12px;color:#33556b}}
.warn{{display:inline-block;margin-left:8px;padding:1px 8px;border-radius:9px;background:#fdeecd;color:#8a5a00;font-size:12px;font-weight:600}}
.phase{{font-size:12.5px;margin:3px 0;padding:4px 8px;background:#f7f9fa;border-radius:4px}}
.phase .tag{{display:inline-block;background:#dfe9f2;color:#2c5f80;border-radius:3px;padding:0 6px;font-size:11px;margin-left:4px}}
.ev{{color:#b26a00;font-weight:600}}
.why{{font-size:12.5px;color:#8a5a00;background:#fdf3dd;border-radius:4px;padding:5px 8px;margin-top:4px}}
.vrow{{font-size:12px;margin:6px 0 2px;padding:5px 8px;background:#f4f8f6;border-left:3px solid #2e8b57;border-radius:3px}}
.ok{{color:#1a9850;font-weight:700}}
.pending{{color:#9a6b00;font-weight:700}}
.cnt{{margin-left:8px;color:#5a6b75}}
.caveat{{margin-top:3px;color:#b26a00}}
.correction{{margin-top:3px;color:#a03030}}
.refhd{{font-size:12px;font-weight:700;color:#555;margin:8px 0 3px}}
ul.refs{{margin:0;padding-left:16px}}
ul.refs li{{font-size:11.5px;margin-bottom:5px;color:#555;word-break:break-word}}
ul.refs a{{color:#1a5c9e;text-decoration:none}}
ul.refs a:hover{{text-decoration:underline}}
.tier{{display:inline-block;font-size:10px;font-weight:700;padding:0 5px;border:1px solid;border-radius:3px;margin-right:3px;vertical-align:middle}}
.lnote{{color:#8a8f93;font-size:10.5px;margin-top:1px}}
footer{{text-align:center;color:#999;font-size:11px;padding:18px}}
@media(max-width:700px){{.card{{flex-direction:column}}.cleft,.thumb{{width:100%}}}}
</style></head><body>
<header>
<h1>生长发育序列 · 草稿复核页 <span style="font-weight:400;font-size:14px">v4 · 引用可点击</span></h1>
<p>共 {len(recs)} 张图 · {sum(len(r["phases"]) for r in recs)} 个阶段 · 已定论 {len(recs)-sum(1 for r in recs if r.get("unresolved"))} 张 · 存疑待你定 {sum(1 for r in recs if r.get("unresolved"))} 张</p>
<p>引用共 {total_refs} 条，全部附真实链接：<b style="color:#8fd9a8">已打开核验 {tally["opened"]}</b> · <b style="color:#9ec9f0">书目已互证 {tally["bibliographic"]}</b> · <b style="color:#f0d68a">仅有链接·待你核验 {tally["link_only"]}</b> ｜ 已逐条核验的记录 {confirmed_n}/{len(recs)}</p>
<button class="hdrbtn" onclick="exportDecisions()">📥 导出我的批注 decisions.json</button>
</header>
<div class="banner">
<b>怎么看这些引用：</b>每条文献前的色标是我的诚实分级——<b style="color:#1a9850">已打开核验</b>＝我真的抓到全文并核对过我引的那句话；
<b style="color:#1565c0">书目已互证</b>＝有两个以上独立来源确认它真实存在（期刊、卷期、页码都对得上），但我没打开全文；
<b style="color:#b8860b">仅有链接·待你核验</b>＝链接来自检索结果、书目看着合理，<u>我尚未独立确认，请你点开自己核对</u>。
点击任一条即可在新标签打开原文。凡我没读过的，绝不标成已核验。
</div>
<main>{cards}</main>
<footer>growth-sequence/draft-v4 · 人在环复核页（引用可点击 + 核验分级）</footer>
<script>
// 批注直接写 localStorage（file:// 下无需服务器），导出时才生成文件。
var DECISIONS = JSON.parse(localStorage.getItem('growthseq_decisions') || '{{}}');
function setDecision(id, v) {{
  DECISIONS[id] = v;
  localStorage.setItem('growthseq_decisions', JSON.stringify(DECISIONS));
  paint();
}}
function paint() {{
  document.querySelectorAll('[data-dec]').forEach(function(el) {{
    el.classList.toggle('on', DECISIONS[el.getAttribute('data-id')] === el.getAttribute('data-dec'));
  }});
}}
function exportDecisions() {{
  var blob = new Blob([JSON.stringify(DECISIONS, null, 2)], {{type:'application/json'}});
  var a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'decisions.json';
  a.click();
}}
paint();
</script>
</body></html>'''

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"✅ 复核页 v4: {OUT} ({len(page)//1024} KB)")
    print(f"   缩略图嵌入 {n_ok}/{len(recs)}，缺失 {n_fail}")
    print(f"   引用链接 {total_refs} 条：opened {tally['opened']} · bibliographic {tally['bibliographic']} · link_only {tally['link_only']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
