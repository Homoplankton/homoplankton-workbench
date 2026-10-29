#!/usr/bin/env python3
"""apply_urls.py — 把 upload_asset.py 的输出（TSV）写回 data.js。

prep_assets.py 产出的 data.js 里 src/full 是暂存目录内的文件名；
上传后需要替换成公网 URL。此脚本按文件名匹配替换，并校验一一对应。

用法:
  python3 apply_urls.py <data.js> --display-urls disp.tsv --full-urls full.tsv [--out data.js]
  # 只用一层时省略另一个参数；两层相同（如轻量模式共用）时两个都传同一文件

TSV 格式（upload_asset.py 原样输出）: <文件路径>\\t<URL>
"""
import argparse
import json
import os
import re
import sys


def load_tsv(path):
    m = {}
    if not path:
        return m
    if not os.path.isfile(path):
        print(f"!! TSV 不存在: {path}", file=sys.stderr)
        sys.exit(2)
    for line in open(path, encoding="utf-8"):
        if "\t" not in line:
            continue
        p, u = line.rstrip("\n").split("\t", 1)
        m[os.path.basename(p.strip())] = u.strip()
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("--display-urls", default="")
    ap.add_argument("--full-urls", default="")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    raw = open(a.data, encoding="utf-8").read()
    m = re.search(r"window\.PLAYGROUND_DATA\s*=\s*(\{.*\})\s*;?\s*$", raw.strip(), re.S)
    if not m:
        print("!! 不是 PLAYGROUND_DATA 格式（旧版 BW_DATA 请手工处理）", file=sys.stderr)
        return 2
    payload = json.loads(m.group(1))
    recs = payload["records"]

    disp, full = load_tsv(a.display_urls), load_tsv(a.full_urls)
    if not disp and not full:
        print("!! 至少提供一个 URL 映射文件", file=sys.stderr)
        return 2

    miss_d = [r["id"] for r in recs if disp and r["src"] not in disp]
    miss_f = [r["id"] for r in recs if full and r["full"] not in full]
    if miss_d or miss_f:
        print(f"!! 映射缺失：显示层 {len(miss_d)} 条，灯箱层 {len(miss_f)} 条", file=sys.stderr)
        for x in (miss_d + miss_f)[:8]:
            print("   ", x, file=sys.stderr)
        return 3

    for r in recs:
        if disp:
            r["src"] = disp[r["src"]]
        if full:
            r["full"] = full[r["full"]]
        else:
            r["full"] = r["src"]

    urls = [r["src"] for r in recs] + [r["full"] for r in recs]
    if not all(u.startswith("http") for u in urls):
        print("!! 仍有非 http 的引用，检查 TSV 内容", file=sys.stderr)
        return 3
    if len(set(r["src"] for r in recs)) != len(recs):
        print("!! 显示层 URL 有重复", file=sys.stderr)
        return 3

    out = a.out or a.data
    open(out, "w", encoding="utf-8").write(
        "window.PLAYGROUND_DATA=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n")
    print(f"✅ 已写回 {out}：{len(recs)} 条记录，显示层与灯箱层 URL 均已替换且唯一")
    return 0


if __name__ == "__main__":
    sys.exit(main())
