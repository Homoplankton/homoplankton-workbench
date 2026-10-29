#!/usr/bin/env python3
"""build_page.py — 模板 + 数据 → 入口 HTML。

只做注入，不触碰引擎算法。

用法:
  python3 build_page.py --template assets/playground.html --data data.js \
      --out blackwater-plankton-archive.html --title "Homoplankton" \
      [--data-src assets/data.js] [--config '{"voidRatio":1.35}'] [--version v23]

--data-src 缺省为 assets/data.js（相对入口的引用路径）；
若传入 http(s) URL，则写成远程 script src。
"""
import argparse
import json
import os
import re
import shutil
import sys

TPL_DATA = "__DATA_SRC__"
TPL_TITLE = "__TITLE__"
TPL_VER = "__VERSION__"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", required=True)
    ap.add_argument("--data", required=True, help="data.js 源文件路径")
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="Plankton Playground")
    ap.add_argument("--data-src", default="assets/data.js", help="入口中引用 data 的路径或URL")
    ap.add_argument("--config", default="", help="JSON，覆盖 CFG 默认值")
    ap.add_argument("--version", default="v23-baseline")
    ap.add_argument("--inline-data", action="store_true", help="把 data.js 内容内联进入口（单文件交付）")
    args = ap.parse_args()

    for p in (args.template, args.data):
        if not os.path.isfile(p):
            print(f"!! 文件不存在: {p}", file=sys.stderr)
            return 2

    html = open(args.template, encoding="utf-8").read()
    for token in (TPL_DATA, TPL_TITLE, TPL_VER):
        if token not in html:
            print(f"!! 模板缺少占位符 {token}", file=sys.stderr)
            return 2

    data_js = open(args.data, encoding="utf-8").read()
    if not re.search(r"window\.(PLAYGROUND_DATA|BW_DATA)\s*=", data_js):
        print("!! data.js 未定义 window.PLAYGROUND_DATA（或旧版 BW_DATA）", file=sys.stderr)
        return 2

    # config 覆盖：写入 PLAYGROUND_DATA.config
    if args.config.strip():
        try:
            cfg = json.loads(args.config)
        except json.JSONDecodeError as e:
            print(f"!! --config 不是合法 JSON: {e}", file=sys.stderr)
            return 2
        m = re.search(r"window\.PLAYGROUND_DATA\s*=\s*(\{.*\})\s*;?\s*$", data_js.strip(), re.S)
        if m:
            payload = json.loads(m.group(1))
            payload.setdefault("config", {}).update(cfg)
            data_js = "window.PLAYGROUND_DATA=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n"
        else:
            print("!! 旧格式 data.js 不支持 --config，请改用 PLAYGROUND_DATA schema", file=sys.stderr)
            return 2

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)

    if args.inline_data:
        html = html.replace(f'<script src="{TPL_DATA}"></script>',
                            "<script>\n" + data_js + "</script>")
        data_src_note = "（已内联）"
    else:
        html = html.replace(TPL_DATA, args.data_src)
        # 数据文件需与入口同目录结构
        if not args.data_src.startswith("http"):
            dst = os.path.join(os.path.dirname(os.path.abspath(args.out)), args.data_src)
            os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
            if os.path.abspath(dst) != os.path.abspath(args.data):
                shutil.copy2(args.data, dst)
        data_src_note = args.data_src

    html = html.replace(TPL_TITLE, args.title).replace(TPL_VER, args.version)

    # 记录数（供报告）
    m = re.search(r'"records"\s*:\s*\[', data_js)
    n = data_js.count('"id":') if m else -1

    open(args.out, "w", encoding="utf-8").write(html)
    print(f"✅ 入口已生成: {args.out}")
    print(f"   标题: {args.title} | 数据: {data_src_note} | 记录: {n} | 版本标记: {args.version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
