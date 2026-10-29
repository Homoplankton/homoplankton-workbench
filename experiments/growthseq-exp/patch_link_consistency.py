#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_link_consistency.py — 修正 link_status 与 verify_level 的逻辑矛盾

矛盾是什么
----------
v5 标注中有 3 条引用同时满足：
    verify_level = "opened"        ← 声称我打开全文并核对过引用句
    link_status  = "unreachable"   ← 声称链接当前不可达
二者不能同真：链接若真的完全不可达，就不可能打开全文。

真相
----
这 3 条都是 MDPI 期刊（Taxonomy / Diversity）。我当轮确实用浏览器级抓取
打开了全文并逐字核对了引用句（note 字段里写着「本轮打开全文」+ 逐字命中内容），
verify_level=opened 是对的；而事后用 urllib 做批量可达性探测时，
MDPI 对自动请求返回 403 反爬，探测脚本把它归为 unreachable，这一步错了。
同批另外 15 条 403 都被正确归为 bot_walled（反爬墙挡住·未确认）。

修正
----
仅把这 3 条的 link_status 从 unreachable 改为 bot_walled，并在 link_note 追加
一句说明修正理由与依据（note 中已有的全文核对记录）。不改 verify_level，
不改 http_code（403 是实测事实，保留），不动其余任何条目。

保留但**不**修正的两条（它们是诚实标注，不是矛盾）：
  * 廖永岩等 2010（知网）   verify_level≠opened, code=None → 确实没打开，标不可达正确
  * Inoue 2004（PubMed）    verify_level≠opened, code=203  → 代理改写码，确实没打开

安全
----
修改前备份原文件；就地更新 v5（它是数据源头，下游 build_claims / make_review_page
都读它）。备份保留，可回溯。
"""

import json
import os
import shutil
import sys

EXP = "/Users/jialingcai/Documents/qwen-agent/NZKKxizmz2/default/growthseq-exp"
V5 = os.path.join(EXP, "draft_annotations_v5.json")
BAK = os.path.join(EXP, "draft_annotations_v5.pre-linkpatch.bak.json")

REASON = ("｜ ⚠️ 状态修正：verify_level=opened 与 link_status=unreachable 逻辑矛盾"
          "（不可达则无法打开全文）。本轮确实用浏览器级抓取打开过全文并逐字核对，"
          "403 来自 urllib 批量探测遭遇 MDPI 反爬，故改判 bot_walled，"
          "与同批另 15 条 403 同因。http_code 保留实测值 403。")


def main():
    if not os.path.exists(V5):
        sys.exit(f"ERROR: 找不到 {V5}")
    if not os.path.exists(BAK):
        shutil.copyfile(V5, BAK)
        print(f"[备份] → {os.path.basename(BAK)}")
    else:
        print(f"[备份] 已存在，跳过：{os.path.basename(BAK)}")

    d = json.load(open(V5, encoding="utf-8"))
    patched = []
    for rec in d["records"]:
        for x in (rec.get("references") or []):
            if x.get("verify_level") == "opened" and x.get("link_status") == "unreachable":
                x["link_status"] = "bot_walled"
                note = x.get("link_note") or ""
                if "状态修正" not in note:
                    x["link_note"] = (note + REASON).strip()
                patched.append((rec["id"], x["text"][:64]))

    if not patched:
        print("[结果] 未发现矛盾条目，文件未改动")
        return 0

    # 记录级 _ls 汇总同步重算，否则页面统计与逐条状态不一致
    for rec in d["records"]:
        ls = {"opens_now": 0, "bot_walled": 0, "unreachable": 0}
        for x in (rec.get("references") or []):
            k = x.get("link_status")
            if k in ls:
                ls[k] += 1
        if "_ls" in rec:
            rec["_ls"] = ls

    with open(V5, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)

    print(f"[修正] {len(patched)} 条 unreachable → bot_walled")
    for iid, t in patched:
        print(f"    {iid:<14} {t}")

    # 复核全库一致性
    allrefs = [x for r in d["records"] for x in r["references"]]
    bad = [x for x in allrefs
           if x.get("verify_level") == "opened" and x.get("link_status") == "unreachable"]
    from collections import Counter
    print(f"\n[复核] 引用出现 {len(allrefs)} 次，唯一书目 "
          f"{len({x.get('text') for x in allrefs})} 条")
    print(f"       verify_level {dict(Counter(x.get('verify_level') for x in allrefs))}")
    print(f"       link_status  {dict(Counter(x.get('link_status') for x in allrefs))}")
    print(f"       残留矛盾条目: {len(bad)}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
