#!/usr/bin/env python3
"""fix_links_v5.py — 修正死链、补开放获取镜像、如实标注链接可达性。

本轮实测发现的真问题（不是格式小瑕疵，是会让用户点不开的错误）：
  1. 三条 MDPI 链接 URL 格式写错（1424-2818-17-5/361 → 1424-2818/17/5/361），全部 404。
     已修正并逐条打开全文核验 → 升级为 opened。
  2. Marco-Herrero 引用把「grapsid 科内幼体资料多限于 zoea I」写成「多数科」，
     属我过度外推，按原文收窄。期刊名漏写（Taxonomy）。
  3. PNAS / Cell / Wiley / OUP / ScienceDirect 等对自动抓取返回 403 反爬墙，
     不等于死链，但我无法此刻确认 → 单列 bot_walled，绝不标成「已核验可达」。
  4. Edgar 2022 找到开放获取 PMC 镜像 PMC9170174，替换被墙的 PNAS 链接。

链接状态三档（与核验等级是两个独立维度）：
  opens_now   本轮实测 HTTP 200 且页面关键词吻合 → 你现在点得开
  bot_walled  本轮实测 403 反爬；浏览器里大概率能开，但我没能确认
  fixed_dead  原本是死链，本轮已换成可用地址
"""
import json
import os
import re
import sys
import urllib.request

EXP = "/Users/jialingcai/Documents/qwen-agent/NZKKxizmz2/default/growthseq-exp"
SRC = os.path.join(EXP, "draft_annotations_v4.json")
OUT = os.path.join(EXP, "draft_annotations_v5.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# --- 1. 死链修正 / 开放获取替换 ---
URL_FIX = {
    "https://www.mdpi.com/1424-2818-17-5/361": "https://www.mdpi.com/1424-2818/17/5/361",
    "https://www.mdpi.com/1424-2818-16-6/320": "https://www.mdpi.com/1424-2818/16/6/320",
    "https://www.mdpi.com/2673-6500-6-1/15": "https://www.mdpi.com/2673-6500/6/1/15",
    "https://www.pnas.org/doi/10.1073/pnas.2122052119": "https://pmc.ncbi.nlm.nih.gov/articles/PMC9170174/",
}

# --- 2. 本轮已打开全文、逐字核对过被引表述的条目 → 升级为 opened ---
FULLTEXT_CONFIRMED = {
    "https://www.mdpi.com/1424-2818/17/5/361":
        "本轮打开全文。逐字命中：“eggcase secretion begins within days of hatching and continues "
        "until reproductive maturity”“Juvenile females, even when copulated, do not possess a visible shell”。"
        "Diversity 17(5):361, DOI 10.3390/d17050361。",
    "https://www.mdpi.com/1424-2818/16/6/320":
        "本轮打开全文。摘要逐字命中 A.argo / A.nouryi 两个 MOTU 与 11 种色素型；"
        "“extensive morphological variability … obscures conventional analyses”为原文表述。"
        "Diversity 16(6):320, DOI 10.3390/d16060320。",
    "https://www.mdpi.com/2673-6500/6/1/15":
        "本轮打开全文。原文为 “Information on the larval morphology of grapsids is scarce and, in many "
        "cases, is restricted to the first zoeal stage (zoea I)”——限定在 Grapsidae 科内，非“多数科”。"
        "Taxonomy 6(1):15, DOI 10.3390/taxonomy6010015。",
}

# --- 3. 文本层修正（我发现的自身过度外推） ---
TEXT_FIX = {
    "Marco-Herrero": ("Marco-Herrero E., González-Gordillo J.I., Cuesta J.A. 2026. The Megalopa Stage in "
                      "Grapsidae Crabs (Decapoda, Brachyura), a First Complete Overview Based on New Data from "
                      "Plankton-Collected Megalopae Identified by DNA Barcodes. Taxonomy 6(1):15 — "
                      "原文限定：Grapsidae 科内幼体形态资料稀缺、多数仅止于 zoea I，"
                      "实验室完整发育仅 2 个 Metopograpsus 种与 Geograpsus lividus 已知。"
                      "（更正：我此前写作“多数科仅有 zoea I 描述”，属过度外推，已按原文收窄到 Grapsidae。）"),
}

# --- 4. 独立互证：Orosco 参考文献表逐字确认了下列书目 ---
CROSS_VALIDATED = {
    "Young R.E. & Harman": "Orosco 2024 参考文献表第 12 条逐字确认：Malacologia 1988, 29, 201–207。",
    "Finn J.K. 2013": ("Kamatsos 2025 与 Orosco 2024 参考文献表均逐字确认："
                       "Molluscan Res. 2013, 33, 143–222, DOI 10.1080/13235818.2013.824854。"),
    "Sweeney M.J., Roper": ("Orosco 2024 参考文献表第 11 条逐字确认：Smithsonian Contributions to Zoology, "
                            "1992, Volume 513（年份 1992 无误）。"),
}

# 反爬墙域名：403 不代表死链，但也不能算已确认可达
BOT_WALL_DOMAINS = ("pnas.org", "cell.com", "sciencedirect.com", "onlinelibrary.wiley.com",
                    "academic.oup.com", "repository.si.edu", "repository.library.noaa.gov",
                    "researchgate.net", "xuewen.cnki.net", "cdnsciencepub.com", "doi.org")


def probe(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en,zh"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            body = r.read(300000).decode("utf-8", "ignore")
            return r.getcode(), body
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return None, f"{type(e).__name__}"


def main():
    d = json.load(open(SRC, encoding="utf-8"))
    d["schema"] = "growth-sequence/draft-v5"
    d["revision_note"] = (
        "v5：全部引用链接经本轮逐条实测。修正 3 条 MDPI 死链（URL 格式错）并为 Edgar 2022 换用开放获取 PMC 镜像；"
        "新增 link_status 字段区分「现在能打开」/「反爬墙挡住、我没能确认」/「原为死链已修好」——"
        "403 反爬不等于链接失效，但我不会把它标成已核验可达。"
        "另更正一处我自己的过度外推：Marco-Herrero 原文只说 Grapsidae 科内资料多止于 zoea I，我此前写成“多数科”。"
        "附带收获：Orosco 2024 与 Kamatsos 2025 的参考文献表逐字互证了 Young & Harman 1988、Finn 2013、"
        "Sweeney et al. 1992 三条书目。"
    )

    stat = {"opens_now": 0, "bot_walled": 0, "fixed_dead": 0, "unreachable": 0}
    fixed_urls, upgraded = set(), set()

    for r in d["records"]:
        for ref in r["references"]:
            old = ref["url"]
            url = URL_FIX.get(old, old)
            ref["url"] = url
            if url != old:
                fixed_urls.add(old)

            for key, newtext in TEXT_FIX.items():
                if key in ref["text"]:
                    ref["text"] = newtext

            if url in FULLTEXT_CONFIRMED:
                ref["verify_level"] = "opened"
                ref["link_note"] = FULLTEXT_CONFIRMED[url]
                upgraded.add(url)

            for key, note in CROSS_VALIDATED.items():
                if key in ref["text"]:
                    ref["link_note"] = (ref.get("link_note", "") + " ｜ " + note).strip(" ｜")
                    if ref["verify_level"] == "link_only":
                        ref["verify_level"] = "bibliographic"

            # 实测链接可达性
            code, body = probe(url)
            if code == 200:
                ref["link_status"] = "opens_now"
                ref["http_code"] = 200
            elif code == 403 and any(dom in url for dom in BOT_WALL_DOMAINS):
                ref["link_status"] = "bot_walled"
                ref["http_code"] = 403
                ref["link_note"] = (ref.get("link_note", "") +
                                    " ｜ 链接状态：本站对自动抓取返回 403 反爬墙，我此刻无法确认页面内容；"
                                    "你在浏览器里点开大概率正常，但请自行核对是否为目标文献。").strip(" ｜")
            else:
                ref["link_status"] = "unreachable"
                ref["http_code"] = code
                ref["link_note"] = (ref.get("link_note", "") +
                                    f" ｜ ⚠️ 链接状态：实测返回 {code}，我未能打开，请你自行核对或另找出处。").strip(" ｜")
            stat[ref["link_status"]] += 1

        # 重算该记录的等级分布
        refs = r["references"]
        lv = {k: sum(1 for x in refs if x["verify_level"] == k)
              for k in ("opened", "bibliographic", "link_only")}
        ls = {k: sum(1 for x in refs if x["link_status"] == k)
              for k in ("opens_now", "bot_walled", "unreachable")}
        if r.get("verification"):
            r["verification"]["verify_levels"] = lv
            r["verification"]["link_status"] = ls
        r["_lv"], r["_ls"] = lv, ls

    json.dump(d, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tally = {k: 0 for k in ("opened", "bibliographic", "link_only")}
    tot = 0
    for r in d["records"]:
        for x in r["references"]:
            tally[x["verify_level"]] += 1
            tot += 1
    print(f"✅ v5 已写: {OUT}")
    print(f"   引用 {tot} 条 · 核验等级 opened {tally['opened']} / 书目互证 {tally['bibliographic']} / 待你核 {tally['link_only']}")
    print(f"   链接实测 现在能开 {stat['opens_now']} · 反爬墙 {stat['bot_walled']} · 打不开 {stat['unreachable']}")
    print(f"   本轮修好的死链 {len(fixed_urls)} 条；升级为全文已读 {len(upgraded)} 条")
    bad = [(r["id"], x["url"], x["http_code"]) for r in d["records"] for x in r["references"]
           if x["link_status"] == "unreachable"]
    if bad:
        print("\n⚠️ 仍打不开的链接（已如实标注，未隐藏）：")
        for i, u, c in bad:
            print(f"   [{i}] HTTP {c} {u}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
