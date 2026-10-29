#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inject_kinship.py — 把「分组数据 + 关联条带挂载层」干净注入站点（可重复执行）

为什么需要这个脚本（两个真实踩过的坑）
--------------------------------------
1. **双挂载并存**：早先的注入把挂载脚本放在 `</body>` 之前且**没有标记**，
   后来的注入器只会剥离「标记之间」的内容，于是 v3 与 v4 两份挂载同时存在、
   各建一条胶片条 —— 表现为 8 张 .kinfig（4+4）、src 混合（一份用整帧、一份用裁剪）。
   故本脚本按**内容特征**识别挂载块（而非注释标记）：凡 script 块里出现
   PlaygroundKin / __KIN_GROUPS__ / __KIN_CROPS__ / kinwrap 的，一律先移除，
   再追加唯一的新块。移除数会打印出来，>1 说明之前确有残留。

2. **分组数据不该硬编码进挂载层**：技能本体必须与具体项目解耦。
   分组由本脚本从 kinship.json 读出，写成 `window.__KIN_GROUPS__` 注入；
   挂载层只读这个全局变量。没有 kinship.json 时仍可只注入挂载层，
   挂载层检测到分组为空会整体静默关闭（站点退回纯漂浮长卷）。

用法
----
  python3 inject_kinship.py --mount assets/kinship_mount.js \\
      --groups <项目>/kinship.json --targets a.html b.html

  # 只注入挂载层（无分组，功能静默关闭）
  python3 inject_kinship.py --mount assets/kinship_mount.js --targets a.html
"""

import argparse
import hashlib
import json
import os
import re
import sys

MARK_B = "<!--KINSHIP_MOUNT_START-->"
MARK_E = "<!--KINSHIP_MOUNT_END-->"
# 挂载层的内容特征：命中任一即认定该 script 块属于挂载层（含历史遗留的裁剪数据块）
SIG = re.compile(r"PlaygroundKin|__KIN_GROUPS__|__KIN_CROPS__|kinwrap")
SCRIPT_RE = re.compile(r"<script\b[^>]*>(.*?)</script>", re.S)

# 挂载层读取的分组字段（其余字段如 evidence/note/likely_members 留在 kinship.json 备查）
# ⚠ id 字段名与 status 词表都要归一化，见 load_groups 的说明
STATUS_MAP = {
    # kinship.json 的完整语义名 → 挂载层 BADGE 表的键
    "confirmed_by_visual": "visual",
    "confirmed_by_visual_and_time": "visual+burst",
    "confirmed_by_taxonomy_and_visual": "visual+taxonomy",
    "confirmed_by_time": "burst",
    "similar_uncertain": "uncertain",
    "user_pin": "user",
    # 已是挂载层键名的，原样保留
    "visual": "visual", "visual+burst": "visual+burst",
    "visual+taxonomy": "visual+taxonomy", "burst": "burst",
    "uncertain": "uncertain", "user": "user",
}


def load_groups(path):
    """从 kinship.json 提取并归一化挂载层需要的最小分组结构。

    两处必须归一化（都是实测踩到的）：
      1. **id 字段名**：kinship.json 写 `group_id`，挂载层读 `id`。
         不归一化 → 注入校验直接拦下（好），或更糟：静默注入缺 id 的组。
      2. **status 词表**：kinship.json 用完整语义名 `confirmed_by_visual`，
         挂载层 BADGE 表用短键 `visual`。挂载层对未知 status 会 fallback 到
         `uncertain`（显示「相似·待你确认」）—— 于是**每组都被标成存疑**，
         把人工确认过的结论降级成待核，这是会误导用户判断的静默错误。
    """
    if not path:
        return None
    if not os.path.exists(path):
        raise SystemExit(f"[FAIL] 找不到分组文件: {path}")
    d = json.load(open(path, encoding="utf-8"))
    raw = d.get("groups") if isinstance(d, dict) else d
    if not isinstance(raw, list):
        raise SystemExit(f"[FAIL] {path} 缺少 groups 数组")

    groups, unknown_status, skipped = [], [], []
    for g in raw:
        mem = g.get("members") or []
        if len(mem) < 2:
            skipped.append(g.get("group_id") or g.get("id") or "?")
            continue
        gid = g.get("id") or g.get("group_id")
        if not gid:
            raise SystemExit(f"[FAIL] 分组缺 id/group_id: {list(g.keys())}")
        st = g.get("status") or "uncertain"
        if st not in STATUS_MAP:
            unknown_status.append((gid, st))
        groups.append({
            "id": gid,
            "label": g.get("label") or gid,
            "status": STATUS_MAP.get(st, "uncertain"),
            "members": list(mem),
        })

    if unknown_status:
        raise SystemExit(
            "[FAIL] 出现未知 status 取值（会被降级显示为「相似·待你确认」，属误导）：\n"
            + "\n".join(f"    {gid}: {st!r}" for gid, st in unknown_status)
            + f"\n  请在 STATUS_MAP 中登记，或改用已支持的取值：{sorted(set(STATUS_MAP))}")

    if not groups:
        raise SystemExit(f"[FAIL] {path} 里没有 ≥2 张成员的有效分组（跳过: {skipped}）")
    if skipped:
        print(f"  ℹ 跳过 {len(skipped)} 个单成员组: {skipped[:5]}")
    return groups


def groups_js(groups):
    """生成 window.__KIN_GROUPS__ 赋值（单行 JSON，转义 </ 防提前闭合 script）。"""
    payload = {"schema": "plankton-playground/kin-groups/v1", "groups": groups}
    s = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    s = s.replace("</", "<\\/")
    s = s.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return "window.__KIN_GROUPS__ = " + s + ";"


def strip_mounts(html):
    """移除所有属于挂载层的 script 块与遗留标记注释。"""
    removed = 0

    def repl(m):
        nonlocal removed
        if SIG.search(m.group(1)):
            removed += 1
            return ""
        return m.group(0)

    html = SCRIPT_RE.sub(repl, html)
    for mark in (MARK_B, MARK_E):
        html = html.replace(mark, "")
    return html, removed


def build_block(js, gjs):
    parts = [MARK_B]
    if gjs:
        parts.append("\n<script>\n" + gjs + "\n</script>")
    parts.append("\n<script>\n" + js + "\n</script>\n" + MARK_E + "\n")
    return "".join(parts)


def inject(path, js, gjs):
    html = open(path, encoding="utf-8").read()
    html, removed = strip_mounts(html)

    # 归一化结尾，把挂载块放在 </body> 之后（避免被后续脚本顺序影响）
    html = html.rstrip()
    tail = ""
    if html.endswith("</html>"):
        html = html[: -len("</html>")].rstrip()
        if html.endswith("</body>"):
            html = html[: -len("</body>")].rstrip()
        tail = "</body>\n"

    out = html + "\n\n" + tail + build_block(js, gjs) + "</html>\n"

    # 断言 1：挂载特征只应落在预期的块数里（有分组=2 块：数据+挂载；无分组=1 块）
    want = 2 if gjs else 1
    blocks = [b for b in SCRIPT_RE.findall(out) if SIG.search(b)]
    if len(blocks) != want:
        raise SystemExit(
            f"[FAIL] {os.path.basename(path)}: 挂载相关 script 块数 = {len(blocks)}（应为 {want}）")

    # 断言 2：PlaygroundKin 定义数必须与挂载层源码里的定义数一致。
    # 不能写死为 1：挂载层有两处定义（无分组时的降级守卫 + 正常导出），
    # 源码改了这里会自动跟随，不会因为「看起来该是 1」而误判。
    want_kin = js.count("window.PlaygroundKin = {")
    got_kin = out.count("PlaygroundKin = {")
    if got_kin != want_kin:
        raise SystemExit(
            f"[FAIL] {os.path.basename(path)}: PlaygroundKin 定义数 {got_kin} != 挂载层源码 {want_kin}")

    open(path, "w", encoding="utf-8").write(out)
    return os.path.getsize(path), removed, len(blocks)


def main():
    ap = argparse.ArgumentParser(description="把分组数据与关联条带挂载层注入站点")
    ap.add_argument("--mount", required=True, help="kinship_mount.js 路径")
    ap.add_argument("--groups", help="kinship.json 路径（省略则只注入挂载层，功能静默关闭）")
    ap.add_argument("--targets", nargs="+", required=True, help="待注入的站点 HTML（可多个）")
    args = ap.parse_args()

    if not os.path.exists(args.mount):
        raise SystemExit(f"[FAIL] 找不到挂载层: {args.mount}")
    js = open(args.mount, encoding="utf-8").read()
    if "PlaygroundKin" not in js:
        raise SystemExit("[FAIL] 挂载层缺少 PlaygroundKin 导出")

    # ⚠ 注入前必做语法预检：JS 不支持 Python 式相邻字符串拼接，
    #   写错会让整个 <script> 块静默失效、页面毫无反应（本项目踩过两次）。
    #   node --check <mount.js> 必须先过。

    groups = load_groups(args.groups)
    gjs = groups_js(groups) if groups else None
    n_img = len({m for g in (groups or []) for m in g["members"]}) if groups else 0

    ver = re.search(r'version:\s*"([^"]+)"', js)
    print(f"挂载层版本: {ver.group(1) if ver else '?'}  JS {len(js)//1024}KB")
    if groups:
        print(f"分组: {len(groups)} 组 / 覆盖 {n_img} 张")
    else:
        print("分组: 未提供（挂载层将静默关闭，站点退回纯漂浮长卷）")

    hashes = []
    for p in args.targets:
        if not os.path.exists(p):
            raise SystemExit(f"[FAIL] 目标不存在: {p}")
        size, removed, nb = inject(p, js, gjs)
        hashes.append(hashlib.md5(open(p, "rb").read()).hexdigest())
        print(f"  {os.path.basename(p)}: {size//1024}KB  移除旧挂载块={removed}  新块={nb}")

    if len(set(hashes)) != 1:
        print(f"  ⚠ 多目标内容不一致: {sorted(set(hashes))}")
    else:
        print(f"  多目标字节一致 ✓  md5={hashes[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
