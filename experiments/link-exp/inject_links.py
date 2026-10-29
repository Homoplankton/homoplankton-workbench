#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inject_links.py — 把单向链接层注入**实验副本**（L1：档案站 → 工作台）

安全边界（重要）
----------------
本脚本只接受显式传入的目标文件，且**默认拒绝**写入任何已交付的原始文件：
  * planktontest-v31-run108/blackwater-plankton-archive.html
  * 20261025-.../blackwater-plankton-archive (18).html
  * plankton-workbench/workbench.html
想改它们必须显式加 --allow-delivered。理由是用户明确要求
「实验不要动已建立的档案站」。

注入内容与顺序
--------------
档案站：`archive_link.js`（在既有 kinship 挂载之后追加，二者互不干扰）
工作台：`workbench_link.js`（追加在主脚本之后、`</body>` 之前，
        保证 select/IMG/setFilter 已就绪）

幂等：按内容特征（PlaygroundLink / WorkbenchLink）剥离旧块后再注入，
     避免重复注入导致双份 DOM（这是本项目踩过的真实坑，见 lessons #20）。
"""

import argparse
import hashlib
import os
import re
import sys

MARK_B = "<!--LINK_EXP_START-->"
MARK_E = "<!--LINK_EXP_END-->"
SCRIPT_RE = re.compile(r"<script\b[^>]*>(.*?)</script>", re.S)

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.dirname(HERE)          # .../default

# 受保护的已交付文件：按**解析后的绝对路径**匹配，不按文件名。
# 曾按 basename 匹配，结果把实验副本 link-exp/workbench.html 也一并拒绝——
# 文件名相同但路径不同，属于误伤。路径匹配才精确。
PROTECTED_PATHS = {
    os.path.realpath(os.path.join(DEFAULT_ROOT, p)) for p in (
        "planktontest-v31-run108/blackwater-plankton-archive.html",
        "20261025-010044-62e753ea-94bd-4a27-8e9e-58099f87a5b6/blackwater-plankton-archive (18).html",
        "plankton-workbench/workbench.html",
    )
}

ARCHIVE_SIG = re.compile(r"PlaygroundLink")
WB_SIG = re.compile(r"WorkbenchLink")


def strip_old(html, sig):
    """移除旧的实验链接块（按内容特征，不按标记）。"""
    removed = 0

    def repl(m):
        nonlocal removed
        if sig.search(m.group(1)):
            removed += 1
            return ""
        return m.group(0)

    html = SCRIPT_RE.sub(repl, html)
    for mark in (MARK_B, MARK_E):
        html = html.replace(mark, "")
    return html, removed


def inject(path, js, sig, label):
    html = open(path, encoding="utf-8").read()
    html, removed = strip_old(html, sig)

    html = html.rstrip()
    tail = ""
    if html.endswith("</html>"):
        html = html[: -len("</html>")].rstrip()
        if html.endswith("</body>"):
            html = html[: -len("</body>")].rstrip()
        tail = "</body>\n"

    block = MARK_B + "\n<script>\n" + js + "\n</script>\n" + MARK_E + "\n"
    out = html + "\n\n" + tail + block + "</html>\n"

    # 唯一性断言：链接层只应出现一次
    n = len([b for b in SCRIPT_RE.findall(out) if sig.search(b)])
    if n != 1:
        raise SystemExit(f"[FAIL] {os.path.basename(path)}: {label} 链接块数 = {n}（应为 1）")

    open(path, "w", encoding="utf-8").write(out)
    return os.path.getsize(path), removed


def guard(targets, allow):
    """拒绝写入已交付的原始文件。

    按解析后的绝对路径比对（realpath），不按 basename：实验副本可以叫
    workbench.html，只要它不在受保护路径上就应该放行。
    """
    bad = [t for t in targets if os.path.realpath(os.path.abspath(t)) in PROTECTED_PATHS]
    if bad and not allow:
        raise SystemExit(
            "[REFUSE] 目标含已交付的原始文件，实验不得改动它们：\n  "
            + "\n  ".join(bad)
            + "\n如确要修改，请显式传 --allow-delivered（并先确认这是用户的要求）。"
        )


def main():
    ap = argparse.ArgumentParser(description="注入 L1 单向链接层（仅实验副本）")
    ap.add_argument("--archive", required=True, help="档案站实验副本路径")
    ap.add_argument("--workbench", required=True, help="工作台实验副本路径")
    ap.add_argument("--allow-delivered", action="store_true",
                    help="允许写入已交付的原始文件（默认拒绝）")
    args = ap.parse_args()

    for p in (args.archive, args.workbench):
        if not os.path.exists(p):
            raise SystemExit(f"[FAIL] 文件不存在: {p}")
    guard([args.archive, args.workbench], args.allow_delivered)

    a_js_path = os.path.join(HERE, "archive_link.js")
    w_js_path = os.path.join(HERE, "workbench_link.js")
    for p in (a_js_path, w_js_path):
        if not os.path.exists(p):
            raise SystemExit(f"[FAIL] 缺少链接层脚本: {p}")
    a_js = open(a_js_path, encoding="utf-8").read()
    w_js = open(w_js_path, encoding="utf-8").read()

    if "PlaygroundLink" not in a_js:
        raise SystemExit("[FAIL] archive_link.js 缺少 PlaygroundLink 导出")
    if "WorkbenchLink" not in w_js:
        raise SystemExit("[FAIL] workbench_link.js 缺少 WorkbenchLink 导出")

    print(f"档案站链接层 {len(a_js)//1024}KB → {os.path.basename(args.archive)}")
    sz, rm = inject(args.archive, a_js, ARCHIVE_SIG, "档案站")
    print(f"  完成 {sz//1024}KB  移除旧块={rm}")

    print(f"工作台接收层 {len(w_js)//1024}KB → {os.path.basename(args.workbench)}")
    sz, rm = inject(args.workbench, w_js, WB_SIG, "工作台")
    print(f"  完成 {sz//1024}KB  移除旧块={rm}")

    print(f"\n  档案站 md5={hashlib.md5(open(args.archive,'rb').read()).hexdigest()[:12]}")
    print(f"  工作台 md5={hashlib.md5(open(args.workbench,'rb').read()).hexdigest()[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
