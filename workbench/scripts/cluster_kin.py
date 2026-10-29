#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cluster_kin.py — 把候选对聚成簇并生成接触表，供逐簇目视核验

为什么聚簇而不是逐对核验
------------------------
293 个候选对逐对目视不现实，且 UI 的真实需求是「点开一张 → 看到一组」，
所以核验单位应该是**簇**而非**对**。单链接聚类后检查簇内最大距离，
过大则说明链接过度（chaining），需要收紧阈值。

⚠ 本脚本只产出「待核验的簇 + 接触表」，不产出任何同一生物结论。
结论由目视核验后写入 kinship.json，且按证据分级。
"""

import json
import os
import sys
from collections import defaultdict

try:
    from PIL import Image, ImageDraw
except ImportError:
    sys.exit("ERROR: 需要 PIL，请用系统 /usr/bin/python3 运行")

WB = "/Users/jialingcai/Documents/qwen-agent/NZKKxizmz2/default/plankton-workbench"
DETAIL = os.path.join(WB, "assets", "detail")
CAND = os.path.join(WB, "data", "candidates.json")
SHEET_DIR = os.path.join(WB, "data", "sheets")

THRESH = 0.18          # 全链接阈值。实测扫描：0.16-0.18 为拐点（30 簇、最大簇 4），
                       # 0.20 起开始过度合并。连拍对 d=0.053-0.189 全部落入。
MAX_INTRA = 0.18       # 全链接保证簇内每对 ≤ THRESH，此值仅用于报告异常
CELL = 190             # 接触表每格边长
PAD = 10


def load():
    return json.load(open(CAND, encoding="utf-8"))


def cluster(cands, thr):
    """全链接聚类（complete-linkage）：保证簇内**每一对**距离都 ≤ thr。

    为什么不用单链接
    ----------------
    实测单链接在 thr=0.13 时产出 55 张巨簇且簇内最大距离 1.0：
    A像B、B像C 就把 A-C 连进来，一路链式膨胀。对「点开一张图弹出关联图」的
    真实用途，55 张互不相干的图毫无意义。全链接以「最远那一对」为准，
    天然阻止链式膨胀。

    实现：按距离升序贪心合并，合并前检查两簇间所有跨簇对是否都 ≤ thr。
    """
    dmap = {tuple(sorted((p["a"], p["b"]))): p["d"] for p in cands}
    nodes = sorted({x for p in cands for x in (p["a"], p["b"])})
    parent = {x: x for x in nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    members = {x: [x] for x in nodes}
    for p in sorted(cands, key=lambda x: x["d"]):
        if p["d"] > thr:
            break                       # 升序遍历，超过阈值即可停
        ra, rb = find(p["a"]), find(p["b"])
        if ra == rb:
            continue
        ma, mb = members[ra], members[rb]
        # 全链接判据：两簇之间所有跨簇对都必须 ≤ thr
        ok = all(dmap.get(tuple(sorted((x, y))), 1.0) <= thr
                 for x in ma for y in mb)
        if not ok:
            continue
        parent[ra] = rb
        members[rb] = mb + ma
        members.pop(ra, None)
    groups = defaultdict(list)
    for x in nodes:
        groups[find(x)].append(x)
    return [sorted(v) for v in groups.values() if len(v) >= 2]


def intra_max(members, dmap):
    m = 0.0
    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            k = tuple(sorted((members[i], members[j])))
            m = max(m, dmap.get(k, 1.0))
    return round(m, 4)


def contact_sheet(clusters, dmap, out_path, title):
    """一簇一行；每行左侧写簇号/规模/簇内最大距离，右侧平铺成员图。"""
    rows = []
    for ci, mem in enumerate(clusters, 1):
        imgs = []
        for iid in mem:
            p = os.path.join(DETAIL, iid + ".jpg")
            if not os.path.isfile(p):
                continue
            im = Image.open(p).convert("RGB")
            im.thumbnail((CELL, CELL), Image.LANCZOS)
            imgs.append((iid, im))
        if imgs:
            rows.append((ci, mem, imgs))
    if not rows:
        return 0
    label_w = 150
    maxn = max(len(r[2]) for r in rows)
    W = label_w + maxn * (CELL + PAD) + PAD
    rowh = CELL + 26
    H = 34 + len(rows) * rowh + PAD
    sheet = Image.new("RGB", (W, H), (8, 8, 10))
    dr = ImageDraw.Draw(sheet)
    dr.text((PAD, 8), title, fill=(200, 205, 212))
    y = 34
    for ci, mem, imgs in rows:
        im_max = intra_max(mem, dmap)
        dr.text((PAD, y + 4), f"C{ci:02d}  n={len(mem)}", fill=(230, 232, 236))
        dr.text((PAD, y + 20), f"maxd={im_max:.3f}", fill=(150, 190, 230))
        x = label_w
        for iid, im in imgs:
            sheet.paste(im, (x, y))
            nm = iid if len(iid) <= 22 else iid[:20] + ".."
            dr.text((x + 3, y + im.size[1] + 4), nm, fill=(170, 175, 182))
            x += CELL + PAD
        y += rowh
    sheet.save(out_path, quality=88)
    return len(rows)


def main():
    c = load()
    cands = c["candidates"]
    dmap = {tuple(sorted((p["a"], p["b"]))): p["d"] for p in cands}
    sig = {tuple(sorted((p["a"], p["b"]))): p["signals"] for p in cands}

    clusters = cluster(cands, THRESH)
    clusters.sort(key=lambda m: -len(m))
    print(f"[1/3] 阈值 d≤{THRESH} 聚出 {len(clusters)} 簇，"
          f"覆盖 {sum(len(m) for m in clusters)} 张")
    from collections import Counter
    print(f"      规模分布: {dict(sorted(Counter(len(m) for m in clusters).items()))}")

    over = [(i, m, intra_max(m, dmap)) for i, m in enumerate(clusters, 1)
            if intra_max(m, dmap) > MAX_INTRA]
    print(f"      链接过度（簇内最大距离 > {MAX_INTRA}）: {len(over)} 簇")
    for i, m, d in over[:6]:
        print(f"        C{i:02d} n={len(m)} maxd={d}  {m[:5]}")

    # 时间信号统计：簇内有几对是连拍/同潜次/跨航次
    print("\n[2/3] 每簇的信号构成")
    stats = []
    for ci, m in enumerate(clusters, 1):
        n_burst = n_cross = n_diff = n_same = 0
        for i in range(len(m)):
            for j in range(i + 1, len(m)):
                s = sig.get(tuple(sorted((m[i], m[j]))), [])
                if "burst" in s:
                    n_burst += 1
                if "cross_trip" in s:
                    n_cross += 1
                elif "diff_dive" in s:
                    n_diff += 1
                elif "same_dive" in s:
                    n_same += 1
        stats.append({"cluster": f"C{ci:02d}", "n": len(m), "members": m,
                      "max_intra": intra_max(m, dmap),
                      "burst_pairs": n_burst, "cross_trip_pairs": n_cross,
                      "diff_dive_pairs": n_diff, "same_dive_pairs": n_same})
        if ci <= 14:
            print(f"  C{ci:02d} n={len(m):<2} maxd={intra_max(m,dmap):.3f} "
                  f"burst={n_burst} cross_trip={n_cross} diff_dive={n_diff} "
                  f"same_dive={n_same}")

    os.makedirs(SHEET_DIR, exist_ok=True)
    print("\n[3/3] 生成接触表")
    # 分批，每批最多 14 簇，避免单图过大
    per = 14
    paths = []
    for b in range(0, len(clusters), per):
        chunk = clusters[b:b + per]
        p = os.path.join(SHEET_DIR, f"sheet_{b//per+1:02d}.jpg")
        n = contact_sheet(chunk, dmap, p,
                          f"Kinship clusters {b+1}-{b+len(chunk)} "
                          f"(thresh d<={THRESH}) — pending visual review")
        if n:
            paths.append((p, n, os.path.getsize(p)))
            print(f"  {os.path.basename(p)}: {n} 簇, "
                  f"{os.path.getsize(p)/1024:.0f} KB")

    json.dump({"schema": "plankton-workbench/kin-clusters/v1",
               "threshold": THRESH, "max_intra_limit": MAX_INTRA,
               "note": ("待核验簇，非结论。每簇需目视判定：coherent(同种/同型) / "
                        "mixed(需拆分) / rejected(不像)。判定结果写入 kinship.json"),
               "clusters": stats,
               "sheets": [p for p, _, _ in paths]},
              open(os.path.join(WB, "data", "kin_clusters.json"), "w",
                   encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"      → data/kin_clusters.json")


if __name__ == "__main__":
    main()
