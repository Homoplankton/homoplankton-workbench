#!/usr/bin/env python3
"""check_urls.py — 并发校验 data.js 里的图片外链是否真实可取。

为什么要有这个脚本：交付前的「链接可访问性」校验若用串行 curl 逐个请求，
104 张约 10 秒、上千张则要数分钟；实测 8 路并发可降到约 1 秒（10x）。
本脚本只用标准库（urllib + ThreadPoolExecutor），不依赖宿主注入的 SDK，
因此可独立运行，也能被 verify 流程直接调用。

用法:
  python3 check_urls.py <data.js> [--layer both|src|full] [--workers 8] [--timeout 20]

退出码: 0 = 全部可取；1 = 有异常链接（逐条打印）；2 = 用法/解析错误。
"""
import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request, urlopen

MIN_BYTES = 1000          # 小于此值视为错误响应（图床出错常回几百字节的错误页）


def load_records(data_path):
    r"""解析 data.js 或「已内联数据的入口 HTML」。

    用 raw_decode 从标记处增量解析，而不是正则匹配整个对象：
    内联进 HTML 后数据后面还跟着引擎代码，`(\{.*\})\s*;?\s*$` 这类锚定行尾的
    正则会匹配失败（实测退出码 2，等于根本没校验），而交付物恰恰是内联单文件版。
    """
    raw = open(data_path, encoding="utf-8").read()
    dec = json.JSONDecoder()
    for marker in ("window.PLAYGROUND_DATA", "window.BW_DATA"):
        idx = raw.find(marker)
        if idx < 0:
            continue
        eq = raw.find("=", idx + len(marker))
        if eq < 0:
            continue
        try:
            payload, _ = dec.raw_decode(raw[eq + 1:].lstrip())
        except json.JSONDecodeError as e:
            print(f"!! {marker} 解析失败: {e}", file=sys.stderr)
            sys.exit(2)
        if marker.endswith("BW_DATA"):          # 旧 schema：数组 + u/fu 字段
            return [{"src": r.get("u"), "full": r.get("fu")} for r in payload]
        return payload["records"]
    print("!! 无法解析（既非 PLAYGROUND_DATA 也非 BW_DATA）", file=sys.stderr)
    sys.exit(2)


def check(url, timeout):
    """返回 (url, ok, bytes, err)。用 HEAD，取不到体积时退化为 Range GET 首字节。"""
    try:
        req = Request(url, method="HEAD", headers={"User-Agent": "plankton-check/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            cl = resp.headers.get("Content-Length")
            n = int(cl) if cl and cl.isdigit() else -1
            if n >= 0:
                return url, n >= MIN_BYTES, n, None if n >= MIN_BYTES else "体积过小"
        # HEAD 未给体积：拉首 4KB 确认是图片而非错误页
        req2 = Request(url, headers={"User-Agent": "plankton-check/1.0", "Range": "bytes=0-4095"})
        with urlopen(req2, timeout=timeout) as resp:
            head = resp.read(4096)
            return url, len(head) > 0 and head[:3] != b"<!D" and head[:1] != b"<", len(head), None
    except Exception as e:                                     # noqa: BLE001
        return url, False, 0, f"{type(e).__name__}: {str(e)[:60]}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("--layer", choices=("both", "src", "full"), default="both")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--timeout", type=float, default=20.0)
    a = ap.parse_args()

    if not os.path.isfile(a.data):
        print(f"!! data.js 不存在: {a.data}", file=sys.stderr)
        return 2
    recs = load_records(a.data)

    tasks = []                                                 # (label, url)
    for i, r in enumerate(recs):
        if a.layer in ("both", "src") and r.get("src", "").startswith("http"):
            tasks.append((f"#{i} src", r["src"]))
        if a.layer in ("both", "full") and r.get("full", "").startswith("http"):
            tasks.append((f"#{i} full", r["full"]))
    if not tasks:
        print("!! 未发现 http(s) 外链（可能仍是本地文件名，需先 apply_urls.py 回填）", file=sys.stderr)
        return 2

    # 同一 URL 可能两层共用，去重以减少请求
    uniq = {}
    for label, url in tasks:
        uniq.setdefault(url, label)
    urls = list(uniq.keys())
    print(f"记录 {len(recs)} 条 → 待验唯一 URL {len(urls)} 个（{a.workers} 路并发）")

    bad = []
    total = 0
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(check, u, a.timeout) for u in urls]
        for f in futs:
            url, ok, n, err = f.result()
            total += max(n, 0)
            if not ok:
                bad.append((uniq[url], url, err))

    print(f"可访问: {len(urls) - len(bad)} / {len(urls)}    合计 {total/1024/1024:.1f} MB")
    if bad:
        print("异常链接：")
        for label, url, err in bad[:20]:
            print(f"  [{label}] {err}  {url[:100]}")
        if len(bad) > 20:
            print(f"  …另有 {len(bad) - 20} 条")
        return 1
    print("==> 全部链接可访问")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
