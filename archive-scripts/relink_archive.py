#!/usr/bin/env python3
"""
把档案站 HTML 里的 216 条 CDN 外链改写为仓库内相对路径。

采用**文本级 URL 替换**，不重新序列化 PLAYGROUND_DATA：
除被替换的 URL 字符串本身，页面其余字节与定版逐字节一致，
避免 JSON 重排键序/浮点格式化引入任何观感漂移。

外链带 auth_key 签名、2026-11-24 过期；改写后页面只依赖仓库内素材，永不过期。

校验（任一不通过即非零退出，不产出文件）：
  1. 替换计数必须恰好等于记录数 × 2
  2. 改写后不得残留任何 workspace-cdn 字样
  3. PLAYGROUND_DATA 仍可被 json.loads 解析
  4. 每条记录的 src/full 都指向实际存在的本地文件
"""
import argparse
import json
import re
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", required=True, help="档案站 HTML（只读，不修改）")
    ap.add_argument("--site-root", required=True, help="站点根目录（素材所在处）")
    ap.add_argument("--out", required=True, help="改写后 HTML 的输出路径")
    args = ap.parse_args()

    src_html = Path(args.html)
    root = Path(args.site_root)
    out = Path(args.out)

    text = src_html.read_text(encoding="utf-8")
    m = re.search(r"window\.PLAYGROUND_DATA=(\{.*?\});\n", text, re.S)
    if not m:
        print("❌ 未找到 PLAYGROUND_DATA", file=sys.stderr)
        return 1
    data = json.loads(m.group(1))
    recs = data["records"]

    new = text
    replaced = 0
    missing = []

    for r in recs:
        rid = r["id"]
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", rid)
        for key, layer in (("src", "display"), ("full", "full")):
            url = r.get(key)
            if not url:
                print(f"❌ {rid} 缺少 {key}", file=sys.stderr)
                return 1
            local = f"assets/{layer}/{safe}.jpg"
            if not (root / local).is_file():
                missing.append(local)
                continue
            # 逐个替换，计数确认每个 URL 只出现一次
            before = new
            new = new.replace(url, local, 1)
            if new == before:
                print(f"❌ URL 未在页面中找到：{url[:80]}", file=sys.stderr)
                return 1
            replaced += 1

    if missing:
        print(f"❌ 本地素材缺失 {len(missing)} 个：{missing[:6]}", file=sys.stderr)
        return 1

    expected = len(recs) * 2
    if replaced != expected:
        print(f"❌ 替换数 {replaced} ≠ 预期 {expected}", file=sys.stderr)
        return 1

    if "workspace-cdn" in new:
        n = new.count("workspace-cdn")
        print(f"❌ 改写后仍残留 {n} 处 workspace-cdn", file=sys.stderr)
        return 1

    # 重新解析改写后的数据块，确认 JSON 结构未破坏
    m2 = re.search(r"window\.PLAYGROUND_DATA=(\{.*?\});\n", new, re.S)
    if not m2:
        print("❌ 改写后 PLAYGROUND_DATA 无法定位", file=sys.stderr)
        return 1
    d2 = json.loads(m2.group(1))
    r2 = d2["records"]
    if len(r2) != len(recs):
        print(f"❌ 记录数变化 {len(recs)} → {len(r2)}", file=sys.stderr)
        return 1
    for r in r2:
        for key in ("src", "full"):
            if not r[key].startswith("assets/"):
                print(f"❌ {r['id']}.{key} 未指向本地：{r[key][:60]}", file=sys.stderr)
                return 1

    # 结构等价性：除 src/full 外所有字段必须与原版完全一致
    for a, b in zip(recs, r2):
        for k in a:
            if k in ("src", "full"):
                continue
            if a[k] != b[k]:
                print(f"❌ {a['id']} 字段 {k} 被意外改动", file=sys.stderr)
                return 1
    # config 与 title 必须逐字节一致
    if data.get("config") != d2.get("config") or data.get("title") != d2.get("title"):
        print("❌ config/title 发生变化", file=sys.stderr)
        return 1

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(new, encoding="utf-8")

    print(f"✅ 替换 {replaced} 条 URL（{len(recs)} 图 × 2 层）")
    print(f"✅ 无外链残留，JSON 可解析，非 URL 字段与定版逐项一致")
    print(f"✅ 写出 {out} ({out.stat().st_size / 1024:.0f}KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
