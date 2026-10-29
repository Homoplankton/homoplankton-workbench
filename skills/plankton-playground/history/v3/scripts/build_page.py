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
    ap.add_argument("--config", default="", help="JSON，覆盖 CFG 默认值（优先级高于预设）")
    ap.add_argument("--preset", default="",
                    help="预设 JSON 路径；缺省自动取模板同目录的 config.approved.json")
    ap.add_argument("--no-preset", action="store_true",
                    help="不套预设，仅用引擎默认值（复现 v23 基线、跑等价性校验时用）")
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

    # 配置注入：预设（config.approved.json）→ --config 覆盖 → 写入 PLAYGROUND_DATA.config
    # 为什么在构建期注入、而不改引擎 CFG 默认值：引擎默认必须与 v23 逐字一致，
    # 否则 check_equivalence.cjs 这道门会永久失效 —— 而正是它在本轮迭代抓出三个真实缺陷
    # （兜底计数恒真、手机端画布上限口径不一致、轨道半径 min(L,R) 致图块锁死）。
    # 预设把「用户认可的调优」与「引擎基线」解耦：基线仍可验，成品是验收过的样子。
    preset_path = args.preset
    if not args.no_preset and not preset_path:
        cand = os.path.join(os.path.dirname(os.path.abspath(args.template)), "config.approved.json")
        if os.path.isfile(cand):
            preset_path = cand
    merged = {}
    if preset_path:
        if not os.path.isfile(preset_path):
            print(f"!! 预设文件不存在: {preset_path}", file=sys.stderr)
            return 2
        try:
            merged.update(json.load(open(preset_path, encoding="utf-8")))
        except json.JSONDecodeError as e:
            print(f"!! 预设不是合法 JSON: {e}", file=sys.stderr)
            return 2
    if args.config.strip():
        try:
            merged.update(json.loads(args.config))
        except json.JSONDecodeError as e:
            print(f"!! --config 不是合法 JSON: {e}", file=sys.stderr)
            return 2
    if merged:
        m = re.search(r"window\.PLAYGROUND_DATA\s*=\s*(\{.*\})\s*;?\s*$", data_js.strip(), re.S)
        if m:
            payload = json.loads(m.group(1))
            payload.setdefault("config", {}).update(merged)
            data_js = "window.PLAYGROUND_DATA=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n"
        else:
            print("!! 旧格式 data.js 不支持配置注入，请改用 PLAYGROUND_DATA schema", file=sys.stderr)
            return 2
        src = f"预设 {os.path.basename(preset_path)}" if preset_path else ""
        if args.config.strip():
            src = (src + " + --config 覆盖") if src else "--config 覆盖"
        print(f"   已注入配置 {len(merged)} 项（{src}）")

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
