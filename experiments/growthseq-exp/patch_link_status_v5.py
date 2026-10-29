#!/usr/bin/env python3
"""patch_link_status_v5.py — 用真实证据修正 probe 的误判。

为什么需要这一步：fix_links_v5.py 用 urllib 探测，而 MDPI 会挡 urllib 的 UA 返回 403，
导致 3 条我**本轮已经用浏览器级抓取打开全文并逐字核对过**的链接被误标成「打不开」。
探测工具不可信时，以我真实读到的内容为准，而不是以工具返回码为准。

修正依据（全部有本轮 WebFetch 实测记录，HTTP 200 + 正文关键词逐字命中）：
  https://www.mdpi.com/1424-2818-17-5/361  → 200，Kamatsos 全文，eggcase secretion 句逐字命中
  https://www.mdpi.com/1424-2818-16-6/320  → 200，Orosco 全文，A.argo/A.nouryi MOTU 逐字命中
  https://www.mdpi.com/2673-6500/6/1/15    → 200，Marco-Herrero 全文，grapsid zoea I 句逐字命中

另：pubmed 返回 203（非错误码，代理改写）→ 归为「能开但内容未核」；
CNKI 超时 → 知网需订阅，如实标反爬/需登录，绝不标成已核验。
"""
import json
import os
import sys

EXP = "/Users/jialingcai/Documents/qwen-agent/NZKKxizmz2/default/growthseq-exp"
SRC = os.path.join(EXP, "draft_annotations_v5.json")

CONFIRMED_200 = {
    "https://www.mdpi.com/1424-2818/17/5/361":
        "链接状态：本轮浏览器级抓取 HTTP 200，已读全文。（urllib 探测被 MDPI 挡为 403，"
        "以我实际读到的正文为准，非探测返回码。）",
    "https://www.mdpi.com/1424-2818/16/6/320":
        "链接状态：本轮浏览器级抓取 HTTP 200，已读全文。（urllib 探测被 MDPI 挡为 403，"
        "以我实际读到的正文为准。）",
    "https://www.mdpi.com/2673-6500/6/1/15":
        "链接状态：本轮浏览器级抓取 HTTP 200，已读全文。（urllib 探测被 MDPI 挡为 403，"
        "以我实际读到的正文为准。）",
}

SPECIAL = {
    "https://pubmed.ncbi.nlm.nih.gov/15186813/": (
        "opens_now", "链接状态：实测返回 HTTP 203（代理改写的非错误码），页面可达但我未逐字核对正文；"
                     "书目为 Inoue J.G. et al. 2004, Mol. Phylogenet. Evol.，请点开自行确认。"),
    "https://xuewen.cnki.net/CJFD-RDHY201004022.html#offline_html_corpas": (
        "bot_walled", "链接状态：知网需订阅/登录，本轮自动抓取超时无法打开，我未能核对内容。"
                      "该条为廖永岩等锈斑蟳幼体发育（中文期刊），请你在知网自行检索核对。"),
}


def main():
    d = json.load(open(SRC, encoding="utf-8"))
    n_fix = 0
    for r in d["records"]:
        for ref in r["references"]:
            u = ref["url"]
            if u in CONFIRMED_200:
                ref["link_status"] = "opens_now"
                ref["http_code"] = 200
                ref["link_note"] = ref.get("link_note", "").split(" ｜ 链接状态：")[0].rstrip(" ｜")
                ref["link_note"] = (ref["link_note"] + " ｜ " + CONFIRMED_200[u]).strip(" ｜")
                ref["link_note"] = ref["link_note"].replace(
                    "｜ ⚠️ 链接状态：实测返回 403，我未能打开，请你自行核对或另找出处。", "")
                n_fix += 1
            elif u in SPECIAL:
                st, note = SPECIAL[u]
                ref["link_status"] = st
                ref["link_note"] = ref.get("link_note", "").split(" ｜ 链接状态：")[0].split(" ｜ ⚠️ 链接状态：")[0].rstrip(" ｜")
                ref["link_note"] = (ref["link_note"] + " ｜ " + note).strip(" ｜")
                n_fix += 1
        # 重算
        refs = r["references"]
        if r.get("verification"):
            r["verification"]["link_status"] = {
                k: sum(1 for x in refs if x["link_status"] == k)
                for k in ("opens_now", "bot_walled", "unreachable")}

    json.dump(d, open(SRC, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    stat = {k: 0 for k in ("opens_now", "bot_walled", "unreachable")}
    lv = {k: 0 for k in ("opened", "bibliographic", "link_only")}
    tot = 0
    for r in d["records"]:
        for x in r["references"]:
            stat[x["link_status"]] += 1
            lv[x["verify_level"]] += 1
            tot += 1
    print(f"✅ 已修正 {n_fix} 条链接状态")
    print(f"   引用 {tot} 条")
    print(f"   链接可达性：现在能开 {stat['opens_now']} · 反爬/需订阅 {stat['bot_walled']} · 打不开 {stat['unreachable']}")
    print(f"   核验等级：全文已读 {lv['opened']} · 书目互证 {lv['bibliographic']} · 待你核 {lv['link_only']}")
    left = [(r["id"], x["url"], x["http_code"]) for r in d["records"]
            for x in r["references"] if x["link_status"] == "unreachable"]
    print(f"   仍标 unreachable 的: {len(left)}")
    for i, u, c in left:
        print(f"     [{i}] HTTP {c} {u}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
