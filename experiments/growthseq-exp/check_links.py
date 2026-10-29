#!/usr/bin/env python3
"""check_links.py — 逐条实测每个引用链接能否打开，并核对标题是否吻合。

为什么必须做这一步：上一轮我口述过一个凭 URL 规律推测的 DOI（Howes 2014），
那属于臆造。这次要给 38 条链接，绝不能再交付「看起来合理但可能打不开」的引用。
判定分三档：
  OK        HTTP 2xx 且页面里能找到预期关键词（作者/标题片段）
  NOKEYWORD HTTP 2xx 但没匹配到关键词 → 链接通，但内容对不上，需人工看
  FAIL      4xx/5xx/超时/被拦 → 必须替换或标注不可达
"""
import json
import re
import sys
import urllib.request

SRC = "/Users/jialingcai/Documents/qwen-agent/NZKKxizmz2/default/growthseq-exp/draft_annotations_v4.json"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def keywords_for(text):
    """从引用文本里挑几个应该出现在目标页面的关键词（作者姓、年份）。"""
    kw = []
    m = re.findall(r"\b([A-ZÀ-Ý][a-zà-ÿ'’\-]{2,})\b", text)
    if m:
        kw.append(m[0])
    y = re.findall(r"\b(19|20)\d{2}\b", text)
    if y:
        kw.append(y[0] + text[text.index(y[0]):text.index(y[0]) + 4])
    return kw[:2]


def check(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en,zh"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            code = r.getcode()
            body = r.read(400000).decode("utf-8", "ignore")
            return code, body, None
    except Exception as e:
        return None, "", f"{type(e).__name__}: {e}"


def main():
    d = json.load(open(SRC, encoding="utf-8"))
    results = []
    for r in d["records"]:
        for ref in r["references"]:
            url, text = ref["url"], ref["text"]
            code, body, err = check(url)
            if err:
                status, detail = "FAIL", err[:110]
            else:
                low = body.lower()
                kws = keywords_for(text)
                hit = [k for k in kws if k.lower() in low]
                if kws and not hit:
                    status, detail = "NOKEYWORD", f"HTTP {code}, 未匹配 {kws}"
                else:
                    status, detail = "OK", f"HTTP {code}, 命中 {hit}"
            results.append((status, r["id"], ref["verify_level"], url, detail, text[:55]))
            print(f"[{status:9}] {r['id']:18} {url[:78]}")
            print(f"            {detail}")

    n = {s: sum(1 for x in results if x[0] == s) for s in ("OK", "NOKEYWORD", "FAIL")}
    print(f"\n总计 {len(results)} 条：OK {n['OK']} · NOKEYWORD {n['NOKEYWORD']} · FAIL {n['FAIL']}")

    json.dump([{"status": s, "id": i, "verify_level": v, "url": u, "detail": det, "text": t}
               for s, i, v, u, det, t in results],
              open("/Users/jialingcai/Documents/qwen-agent/NZKKxizmz2/default/growthseq-exp/link_check.json", "w"),
              ensure_ascii=False, indent=1)
    print("明细已写 link_check.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
