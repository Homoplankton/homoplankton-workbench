#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inject_mount.py — 把关联图挂载层干净地注入站点（可重复执行）

为什么需要这个脚本（踩过的坑）
------------------------------
早先的注入把挂载脚本放在 `</body>` 之前且**没有标记**，后来的注入器只会剥离
「标记之间」的内容，导致 v3 与 v4 两份挂载同时存在并各自建了一条胶片条：
表现为 8 张 .kinfig（4+4）、src 混合（v3 用整帧 CDN、v4 用主体裁剪）。

因此本脚本按**内容特征**识别挂载脚本块，而不是按注释标记：
凡是 script 块里出现 PlaygroundKin / __KIN_CROPS__ / kinwrap 的，一律先移除，
再在 </body> 之后追加唯一的、带标记的新块。
"""
import hashlib
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT = "/Users/jialingcai/Documents/qwen-agent/NZKKxizmz2/default"

TARGETS = [
    os.path.join(DEFAULT, "planktontest-v31-run108", "blackwater-plankton-archive.html"),
    os.path.join(
        DEFAULT,
        "20261025-010044-62e753ea-94bd-4a27-8e9e-58099f87a5b6",
        "blackwater-plankton-archive (18).html",
    ),
]

MARK_B = "<!--KINSHIP_MOUNT_START-->"
MARK_E = "<!--KINSHIP_MOUNT_END-->"
# 挂载层的内容特征：命中任一即认定该 script 块属于挂载层
SIG = re.compile(r"PlaygroundKin|__KIN_CROPS__|kinwrap")

SCRIPT_RE = re.compile(r"<script\b[^>]*>(.*?)</script>", re.S)


def strip_mounts(html):
    """移除所有属于挂载层的 script 块，以及遗留的挂载标记注释。"""
    removed = 0

    def repl(m):
        nonlocal removed
        body = m.group(1)
        if SIG.search(body):
            removed += 1
            return ""
        return m.group(0)

    html = SCRIPT_RE.sub(repl, html)
    # 清掉可能残留的标记注释（旧版注入留下的）
    for mark in (MARK_B, MARK_E):
        html = html.replace(mark, "")
    return html, removed


def build_block(js):
    return (
        MARK_B
        + "\n<script>\n"
        + js
        + "\n</script>\n"
        + MARK_E
        + "\n"
    )


def inject(path, js):
    html = open(path, encoding="utf-8").read()
    html, removed = strip_mounts(html)

    # 归一化结尾：确保 </body></html> 结构完整，再把挂载块放在 </body> 之后
    html = html.rstrip()
    if html.endswith("</html>"):
        html = html[: -len("</html>")].rstrip()
        if html.endswith("</body>"):
            html = html[: -len("</body>")].rstrip()
        tail = "</body>\n"
    else:
        tail = ""

    out = html + "\n\n" + tail + build_block(js) + "</html>\n"

    # 断言：整份文件里挂载特征只应出现在一个 script 块中（v4.1 起不再内嵌裁剪数据）
    blocks = [b for b in SCRIPT_RE.findall(out) if SIG.search(b)]
    if len(blocks) != 1:
        raise SystemExit(
            f"[FAIL] {os.path.basename(path)}: 挂载相关 script 块数 = {len(blocks)}（应为 1：挂载层）"
        )
    if out.count("PlaygroundKin = {") != 1:
        raise SystemExit(f"[FAIL] {os.path.basename(path)}: PlaygroundKin 定义数 != 1")

    open(path, "w", encoding="utf-8").write(out)
    return os.path.getsize(path), removed, blocks


def main():
    js_path = os.path.join(ROOT, "scripts", "kinship_mount.js")
    js = open(js_path, encoding="utf-8").read()

    if "PlaygroundKin" not in js:
        raise SystemExit("[FAIL] kinship_mount.js 缺少 PlaygroundKin 导出")

    ver = re.search(r'version:\s*"([^"]+)"', js)
    print(f"挂载层版本: {ver.group(1) if ver else '?'}  JS {len(js)//1024}KB（不再内嵌裁剪数据）")

    hashes = []
    for p in TARGETS:
        if not os.path.exists(p):
            raise SystemExit(f"[FAIL] 目标不存在: {p}")
        size, removed, blocks = inject(p, js)
        hashes.append(hashlib.md5(open(p, "rb").read()).hexdigest())
        print(f"  {os.path.basename(p)}: {size//1024}KB  移除旧挂载块={removed}  新块={len(blocks)}")

    same = len(set(hashes)) == 1
    print(f"两份字节一致: {same}  md5={hashes[0]}")
    if not same:
        raise SystemExit("[FAIL] 两份站点文件不一致")


if __name__ == "__main__":
    main()
