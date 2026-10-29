#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kin_sheets.py — 生成人工核验用的接触表（宽网候选，按连通分量分批）

为什么用宽网 + 人工核验，而不是让算法聚类下结论
----------------------------------------------
实测（6 个连拍簇 = 地面真值，≤10 秒内拍摄，几乎必然同一个体）：
  * 紧阈值下地面真值召回 50%；宽网（每图取前 20 近邻）召回 88%
  * 但**任何阈值**下，地面真值「同簇」率恒为 2/8（0.20→0.40 都是）
    → 放宽阈值只是把垃圾并成大簇，并不解决判别力
结论：算法适合**召回**，不适合**判定**。判定必须由人眼完成。

为什么 v1 的颜色主导特征是错的
------------------------------
v1 把螺壳、水母钟、带棘幼体、章鱼聚成一簇且 maxd=0.096（全场最低）。
根因：黑水照片里所有胶质生物都是「黑底上的半透明白蓝」，颜色直方图雷同。
v2 改以轮廓半径函数频谱为主（0.52），颜色降到 0.12，该簇已被拆开（maxd→0.898）。

v2 已修的两个自身 bug
---------------------
  1. 把**包围盒长宽比**放进 topo 特征——它对旋转敏感，同一只栉水母转 45°
     就判为不同（实测 topo 距离 1.60）。已移除，只留旋转不变量。
  2. Hu 矩用 min(d,1.5) 硬钳位，大量对顶到上限，恒定贡献 0.33 的**噪声距离**，
     淹没有判别力的项。已改为数据集标准化 + tanh 压缩。
    修复后地面真值召回 38% → 50%。

已知的真局限（不是 bug，修不了）
--------------------------------
三维姿态剧变会让轮廓投影完全不同：八腕幼体三帧 spec=0.44~0.72；
樽海鞘两帧因变焦不同 spec=0.76（连拍地面真值中唯一漏网的一对）。
人靠「八条腕＋橙色色素环」认得出，纯几何认不出。
→ 故最终结论必须人工核验，算法只负责把候选送到眼前。
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
FEAT = os.path.join(WB, "data", "kin_features.json")
CAND = os.path.join(WB, "data", "candidates.json")
OUT_DIR = os.path.join(WB, "data", "review_sheets")

K_NEIGHBORS = 8          # 每图展示的邻居数（宽网召回，判定靠人）
WIDE_THR = 0.42          # 连通分量的宽阈值：只求把可能相关的图放同一张表里看
PER_SHEET = 6            # 每张表放几个「主图+邻居」组
CELL = 172
PAD = 7


def build_index(pairs):
    by = defaultdict(list)
    for p in pairs:
        by[p["a"]].append((p["d"], p["b"], p["comp"]))
        by[p["b"]].append((p["d"], p["a"], p["comp"]))
    for k in by:
        by[k].sort(key=lambda x: x[0])
    return by


def components(nodes, by, thr):
    """宽阈值连通分量，只为分批看图，不作为任何结论。"""
    parent = {x: x for x in nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, lst in by.items():
        for d, b, _ in lst:
            if d > thr:
                break
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb
    g = defaultdict(list)
    for x in nodes:
        g[find(x)].append(x)
    return sorted(g.values(), key=lambda m: -len(m))


def thumb(iid, cell):
    p = os.path.join(DETAIL, iid + ".jpg")
    if not os.path.isfile(p):
        return None
    im = Image.open(p).convert("RGB")
    im.thumbnail((cell, cell), Image.LANCZOS)
    return im


def draw_group(canvas, dr, x, y, main, neighbors, cell):
    """一组：上行=主图，下行=其近邻（带距离）。返回占用高度。"""
    mi = thumb(main, cell)
    if mi is None:
        return 0
    dr.rectangle([x - 2, y - 2, x + mi.size[0] + 2, y + mi.size[1] + 2],
                 outline=(240, 200, 120), width=2)
    canvas.paste(mi, (x, y))
    dr.text((x + 2, y + mi.size[1] + 4), "★" + main[:19], fill=(255, 214, 130))
    xx = x + cell + PAD
    for d, nb, comp in neighbors:
        ni = thumb(nb, cell)
        if ni is None:
            continue
        canvas.paste(ni, (xx, y))
        dr.text((xx + 2, y + ni.size[1] + 4), f"{d:.3f} {nb[:15]}", fill=(170, 176, 184))
        # 标出主要差异来源，便于判断是姿态还是本质不同
        key = max(comp, key=lambda k: comp[k]) if comp else None
        if key:
            dr.text((xx + 2, y + ni.size[1] + 15), f"Δ{key}", fill=(120, 150, 190))
        xx += cell + PAD
    return cell + 26


def main():
    d = json.load(open(FEAT, encoding="utf-8"))
    feats = d["features"]
    pairs = d["pairs"]
    by = build_index(pairs)
    nodes = sorted(feats)

    comps = components(nodes, by, WIDE_THR)
    print(f"[1/3] 宽网连通分量（thr≤{WIDE_THR}）：{len(comps)} 组，"
          f"覆盖 {sum(len(c) for c in comps)} 张")
    print(f"      规模分布 top: {[len(c) for c in comps[:8]]}")

    # 每个分量内的图各成一组（主图 + 其前 K 近邻）
    groups = []
    for comp in comps:
        for iid in comp:
            nb = [(dd, o, c) for dd, o, c in by[iid][:K_NEIGHBORS]]
            groups.append((iid, nb, comp))
    print(f"[2/3] 待核验组 {len(groups)} 个（每组=1主图+至多{K_NEIGHBORS}近邻）")

    os.makedirs(OUT_DIR, exist_ok=True)
    # 清掉旧表，避免混批误读
    for f in os.listdir(OUT_DIR):
        if f.endswith(".jpg"):
            os.remove(os.path.join(OUT_DIR, f))

    W = PAD + (K_NEIGHBORS + 1) * (CELL + PAD)
    rowh = CELL + 34
    paths = []
    for si in range(0, len(groups), PER_SHEET):
        chunk = groups[si:si + PER_SHEET]
        H = 30 + len(chunk) * rowh + PAD
        sheet = Image.new("RGB", (W, H), (8, 8, 10))
        dr = ImageDraw.Draw(sheet)
        dr.text((PAD, 8),
                f"KINSHIP REVIEW {si+1}-{si+len(chunk)}  ★=main, row=its {K_NEIGHBORS} nearest  "
                f"(label=distance, Δ=dominant differing feature)  — PENDING HUMAN VERDICT",
                fill=(205, 210, 218))
        y = 30
        for main_id, nb, comp in chunk:
            h = draw_group(sheet, dr, PAD, y, main_id, nb, CELL)
            if h:
                y += rowh
        p = os.path.join(OUT_DIR, f"review_{si//PER_SHEET+1:02d}.jpg")
        sheet.save(p, quality=88)
        paths.append(p)
    print(f"[3/3] 接触表 {len(paths)} 张 → {OUT_DIR}")
    for p in paths[:6]:
        print(f"      {os.path.basename(p)}  {os.path.getsize(p)/1024:.0f} KB")

    json.dump({"schema": "plankton-workbench/review-groups/v1",
               "wide_thr": WIDE_THR, "k_neighbors": K_NEIGHBORS,
               "note": ("每张表：★为主图，其后为该图的最近邻及距离；Δ标出主要差异特征。"
                        "这些是候选，不是结论；结论由人工核验写入 kinship.json。"),
               "components": [{"n": len(c), "members": c} for c in comps],
               "sheets": [os.path.basename(p) for p in paths]},
              open(os.path.join(WB, "data", "review_groups.json"), "w",
                   encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
