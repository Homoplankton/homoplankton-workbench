#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kin_features.py — 形态判别的视觉特征（v2）

为什么重做特征（v1 的失败）
--------------------------
v1 用「色素色相直方图 0.42 + 亮度 0.22 + 占比 0.16 + 形态 0.20」，
实测聚出的 C06 簇 maxd=0.096（全场最低之一），却把螺壳、水母钟、带棘幼体、
章鱼四种完全不同的生物归到一起。根因：黑水照片里所有胶质生物都是
「黑底上的半透明白蓝」，颜色直方图高度雷同，0.42 的颜色权重压倒了形态差异。

v2 的判别核心：**轮廓半径函数的频谱**
从主体质心出发，按 72 个角度（每 5°）向外射线，记录最远前景距离 r(θ)，
归一化后做 DFT 取幅值谱。这个特征直接编码「有几条腕 / 几道棘 / 是否圆形」：
  * 章鱼八腕     → f=8 附近有大峰
  * 水母钟形     → 低频集中、高频弱（接近圆）
  * 带棘幼体     → 高频能量强（多个尖锐小峰）
  * 螺壳螺旋     → 频谱平缓但质心偏移大
幅值谱天然旋转不变，均值归一化天然尺度不变——正好匹配「同一生物不同角度」。

辅以：
  * Hu 矩 7 个（平移/尺度/旋转不变的形状不变量）
  * 欧拉数（孔洞数：螺壳与水母的腔、多毛类的体节间隙）
  * 凸包实度 solidity（腕展开 vs 紧凑壳体）
颜色权重降到 0.12，仅作辅助（色素型仍有分类学意义，但不能主导）。

⚠ 本脚本只产出特征与候选对，**不产出任何「同一生物」结论**。
结论由逐簇目视核验后写入 kinship.json。
"""

import json
import math
import os
import sys
from collections import defaultdict, deque

try:
    from PIL import Image
except ImportError:
    sys.exit("ERROR: 需要 PIL（/usr/bin/python3 通常自带）")

import argparse

SHAPE_PX = 128          # 形状分析采样边长（够用且快）
N_ANG = 72              # 半径函数采样角数（每 5°）
N_FREQ = 14             # 保留的频谱低频个数
W_RAD, W_HU, W_EULER, W_COLOR = 0.52, 0.22, 0.14, 0.12
IMG_EXT = (".jpg", ".jpeg", ".png")


# ---------------------------------------------------------------- 基础
def luma(r, g, b):
    return 0.299 * r + 0.587 * g + 0.114 * b


def rgb2hsv(r, g, b):
    mx, mn = max(r, g, b), min(r, g, b)
    v = mx / 255.0
    s = 0.0 if mx == 0 else (mx - mn) / mx
    if mx == mn:
        return 0.0, s, v
    dd = mx - mn
    if mx == r:
        h = ((g - b) / dd) % 6
    elif mx == g:
        h = (b - r) / dd + 2
    else:
        h = (r - g) / dd + 4
    return h * 60.0, s, v


def norm(v):
    s = sum(v)
    return [x / s for x in v] if s > 0 else [0.0] * len(v)


def largest_component(mask, w, h):
    """BFS 取最大连通分量，返回像素坐标集合。纯 Python，128×128 足够快。"""
    seen = [[False] * w for _ in range(h)]
    best = []
    for sy in range(h):
        for sx in range(w):
            if not mask[sy * w + sx] or seen[sy][sx]:
                continue
            comp = []
            q = deque([(sx, sy)])
            seen[sy][sx] = True
            while q:
                x, y = q.popleft()
                comp.append((x, y))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1),
                               (1, 1), (1, -1), (-1, 1), (-1, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and not seen[ny][nx] \
                            and mask[ny * w + nx]:
                        seen[ny][nx] = True
                        q.append((nx, ny))
            if len(comp) > len(best):
                best = comp
    return best


def radius_signature(pts, w, h):
    """半径函数 r(θ) → 归一化 → DFT 幅值谱。旋转/尺度不变。"""
    if len(pts) < 20:
        return [0.0] * N_FREQ, 0.0
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    pset = set(pts)
    # 边界点：4 邻域内有非前景的
    bnd = [(x, y) for (x, y) in pts
           if any((x + dx, y + dy) not in pset
                  for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))] or pts
    r_of = []
    for k in range(N_ANG):
        th = 2 * math.pi * k / N_ANG
        ct, st = math.cos(th), math.sin(th)
        best = 0.0
        # 沿射线找最远边界点投影
        for (x, y) in bnd:
            dx, dy = x - cx, y - cy
            proj = dx * ct + dy * st
            if proj > best:
                perp = abs(-dx * st + dy * ct)
                if perp < max(3.0, 0.10 * max(w, h)):
                    best = proj
        r_of.append(max(best, 1e-6))
    mean = sum(r_of) / len(r_of)
    rn = [r / mean for r in r_of]          # 尺度不变
    # DFT 幅值谱（低频 N_FREQ 个），旋转不变
    spec = []
    for f in range(1, N_FREQ + 1):
        re = sum(rn[t] * math.cos(2 * math.pi * f * t / N_ANG) for t in range(N_ANG))
        im = -sum(rn[t] * math.sin(2 * math.pi * f * t / N_ANG) for t in range(N_ANG))
        spec.append(math.hypot(re, im) / N_ANG)
    mx = max(spec) or 1.0
    spec = [s / mx for s in spec]          # 幅值归一，消除整体复杂度差异
    return [round(s, 5) for s in spec], round(max(w, h) and mean / max(w, h), 4)


def hu_moments(pts, w, h):
    """Hu 7 矩。经典形状不变量，对旋转/尺度/镜像稳定。"""
    n = len(pts)
    if n < 10:
        return [0.0] * 7
    cx = sum(p[0] for p in pts) / n
    cy = sum(p[1] for p in pts) / n
    m = defaultdict(float)
    for x, y in pts:
        dx, dy = x - cx, y - cy
        for p_ in range(4):
            for q_ in range(4):
                if p_ + q_ <= 3:
                    m[(p_, q_)] += (dx ** p_) * (dy ** q_)
    for k in m:
        m[k] /= n
    n00 = m[(0, 0)] or 1.0
    n20 = m[(2, 0)] / n00; n02 = m[(0, 2)] / n00; n11 = m[(1, 1)] / n00
    n30 = m[(3, 0)] / n00; n03 = m[(0, 3)] / n00
    n21 = m[(2, 1)] / n00; n12 = m[(1, 2)] / n00
    h1 = n20 + n02
    h2 = (n20 - n02) ** 2 + 4 * n11 ** 2
    h3 = (n30 - 3 * n12) ** 2 + (3 * n21 - n03) ** 2
    h4 = (n30 + n12) ** 2 + (n21 + n03) ** 2
    h5 = ((n30 - 3 * n12) * (n30 + n12) *
          ((n30 + n12) ** 2 - 3 * (n21 + n03) ** 2) +
          (3 * n21 - n03) * (n21 + n03) *
          (3 * (n30 + n12) ** 2 - (n21 + n03) ** 2))
    h6 = ((n20 - n02) * ((n30 + n12) ** 2 - (n21 + n03) ** 2) +
          4 * n11 * (n30 + n12) * (n21 + n03))
    h7 = ((3 * n21 - n03) * (n30 + n12) *
          ((n30 + n12) ** 2 - 3 * (n21 + n03) ** 2) -
          (n30 - 3 * n12) * (n21 + n03) *
          (3 * (n30 + n12) ** 2 - (n21 + n03) ** 2))
    hu = [h1, h2, h3, h4, h5, h6, h7]
    # 对数压缩，避免量级悬殊
    out = []
    for v in hu:
        a = abs(v)
        out.append(round(math.copysign(math.log10(a + 1e-30), v), 4))
    return out


def euler_and_hull(pts, w, h):
    """孔洞数与凸包实度。

    ⚠ 只保留**旋转不变**的量。v2 初版把包围盒长宽比 (bw/bh, bw, bh) 也放进来，
    但包围盒对旋转敏感：同一只栉水母转 45° 后包围盒长宽比改变，
    导致 topo 距离 1.60，把地面真值对拖垮（实测 burst 召回仅 38%）。
    孔洞数与实度（前景/凸包或前景/bbox 面积比里取实度）才是旋转不变的。
    """
    n = len(pts)
    if n < 10:
        return 0.0, 0.0
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    if bw * bh < 16:
        return 0.0, 1.0
    pset = set(pts)
    seen = set()
    holes = 0
    for sy in range(y0, y1 + 1):
        for sx in range(x0, x1 + 1):
            if (sx, sy) in pset or (sx, sy) in seen:
                continue
            comp = []
            q = deque([(sx, sy)])
            seen.add((sx, sy))
            touch = False
            while q:
                x, y = q.popleft()
                comp.append((x, y))
                if x in (x0, x1) or y in (y0, y1):
                    touch = True
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if x0 <= nx <= x1 and y0 <= ny <= y1 and (nx, ny) not in seen \
                            and (nx, ny) not in pset:
                        seen.add((nx, ny))
                        q.append((nx, ny))
            if not touch and len(comp) >= 4:
                holes += 1
    # 实度：前景面积 / 包围盒面积（旋转敏感弱于长宽比，且能区分展开腕 vs 紧凑壳）
    solidity = n / (bw * bh) if bw * bh else 0.0
    return float(holes), round(min(1.0, solidity), 4)


def color_hist(rgb_small):
    """颜色仅作辅助：色素色相 8 bin + 组织亮度 6 bin。"""
    hue = [0.0] * 8
    lum = [0.0] * 6
    px = list(rgb_small.getdata())
    lums = sorted(luma(*p) for p in px)
    n = len(lums)
    if not n:
        return [0.0] * 14
    wbase = lums[min(n - 1, int(n * 0.25))]
    T = max(wbase * 1.35, wbase + 14, 16)
    for (r, g, b) in px:
        L = luma(r, g, b)
        if L < T:
            continue
        lum[min(5, int(L / 256 * 6))] += 1
        hh, s, v = rgb2hsv(r, g, b)
        if s >= 0.22:
            hue[min(7, int(hh / 360 * 8))] += 1
    return [round(x, 5) for x in norm(hue) + norm(lum)]


def feats_for(path):
    im = Image.open(path).convert("RGB")
    W, H = im.size
    s = SHAPE_PX / max(W, H)
    if s < 1:
        im = im.resize((max(1, round(W * s)), max(1, round(H * s))), Image.LANCZOS)
    w, h = im.size
    rgb = list(im.getdata())
    gray = im.convert("L")
    gpx = list(gray.getdata())
    lums = sorted(gpx)
    n = len(lums)
    wbase = lums[min(n - 1, int(n * 0.25))]
    T = max(wbase * 1.35, wbase + 14, 16)
    mask = [L >= T for L in gpx]
    fg_n = sum(mask)
    if fg_n < 30:
        return None
    pts = largest_component(mask, w, h)
    spec, rel_r = radius_signature(pts, w, h)
    hu = hu_moments(pts, w, h)
    holes, sol = euler_and_hull(pts, w, h)
    col = color_hist(im)
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    bw = (max(xs) - min(xs) + 1) / w
    bh = (max(ys) - min(ys) + 1) / h
    return {
        "spec": spec,
        "hu": hu,
        # topo 只含旋转不变量：孔洞数、实度、（归一化相对尺寸）
        "topo": [holes, sol, round(fg_n / n, 4)],
        "color": col,
        "bbox_frac": [round(bw, 4), round(bh, 4)],   # 仅记录，不参与距离
        "fg_frac": round(fg_n / n, 4),
        "T": round(T, 1), "w": w, "h": h,
    }


# ---------------------------------------------------------------- 距离
def l2(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def standardize_hu(feats):
    """对 Hu 矩做逐分量数据集标准化（z-score 后压缩到 ±1）。

    为什么必须做
    ------------
    v2 初版直接 min(d_hu, 1.5) 钳位，实测大量对的 d_hu 顶到钳位上限，
    恒定贡献 0.22×1.5=0.33 的**噪声距离**，把真正有判别力的项淹掉。
    决定性案例 B02（同一只栉水母旋转约 45°）：spec=0.05、col=0.06 都极好，
    却因 hu=1.50 饱和被判 d=0.591（排名 19%）。钳位不是归一化，是截断信息。

    标准化后各分量同量纲，饱和消失，且对离群值用 tanh 压缩而非硬截断。
    """
    keys = sorted(feats)
    if len(keys) < 3:
        return
    n_hu = len(feats[keys[0]]["hu"])
    for j in range(n_hu):
        vals = [feats[k]["hu"][j] for k in keys]
        mu = sum(vals) / len(vals)
        sd = math.sqrt(sum((v - mu) ** 2 for v in vals) / len(vals)) or 1.0
        for k in keys:
            feats[k]["hu"][j] = round(math.tanh((feats[k]["hu"][j] - mu) / sd), 4)


def dist(a, b):
    d_spec = l2(a["spec"], b["spec"]) / math.sqrt(2)
    d_hu = l2(a["hu"], b["hu"]) / math.sqrt(2 * len(a["hu"]))
    d_top = l2(a["topo"], b["topo"]) / math.sqrt(2 * len(a["topo"]))
    d_col = l2(a["color"], b["color"]) / math.sqrt(2)
    d = (W_RAD * d_spec + W_HU * d_hu + W_EULER * d_top + W_COLOR * d_col)
    return round(min(1.0, d), 4), {
        "spec": round(d_spec, 4), "hu": round(d_hu, 4),
        "topo": round(d_top, 4), "color": round(d_col, 4)}


def main():
    ap = argparse.ArgumentParser(
        description="提取形态特征 + 候选对召回（只召回，不下同一生物结论）")
    ap.add_argument("img_dir",
                    help="含主体居中裁剪图的文件夹（每张一图，文件名 stem 即 id）")
    ap.add_argument("--out", required=True, help="输出 kin_features.json 路径")
    ap.add_argument("--limit", type=int, default=0,
                    help="只处理前 N 张（0=全部）；大图库先小规模试跑")
    args = ap.parse_args()

    if not os.path.isdir(args.img_dir):
        sys.exit(f"ERROR: 图片目录不存在: {args.img_dir}")

    files = sorted(
        f for f in os.listdir(args.img_dir)
        if f.lower().endswith(IMG_EXT))
    if args.limit:
        files = files[: args.limit]
    ids = [os.path.splitext(f)[0] for f in files]
    print(f"[1/3] 提取形态特征 {len(ids)} 张（源 {args.img_dir}）")

    feats, skipped = {}, []
    for i, (iid, fn) in enumerate(zip(ids, files), 1):
        p = os.path.join(args.img_dir, fn)
        try:
            f = feats_for(p)
            if f is None:
                skipped.append((iid, "前景像素不足"))
            else:
                feats[iid] = f
        except Exception as e:
            skipped.append((iid, f"{type(e).__name__}: {e}"))
        if i % 30 == 0:
            print(f"      …{i}/{len(ids)}")
    print(f"      成功 {len(feats)}，跳过 {len(skipped)}")
    for iid, why in skipped[:6]:
        print(f"        {iid}: {why}")
    if len(feats) < 2:
        sys.exit("ERROR: 有效特征不足 2 张，无法做两两召回")

    print("[2/3] 两两距离")
    standardize_hu(feats)          # 先标准化，再算距离
    keys = sorted(feats)
    pairs = []
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = keys[i], keys[j]
            d, comp = dist(feats[a], feats[b])
            pairs.append({"a": a, "b": b, "d": d, "comp": comp})
    pairs.sort(key=lambda x: x["d"])
    ds = [p["d"] for p in pairs]
    q = lambda f: ds[min(len(ds) - 1, int(len(ds) * f))]
    print(f"      {len(pairs)} 对：min={ds[0]:.3f} p1={q(.01):.3f} "
          f"p5={q(.05):.3f} 中位={q(.5):.3f} max={ds[-1]:.3f}")

    print("[3/3] 写入特征与候选对")
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    json.dump({"schema": "plankton-playground/kin-features/v2",
               "weights": {"spec": W_RAD, "hu": W_HU, "topo": W_EULER, "color": W_COLOR},
               "n_ang": N_ANG, "n_freq": N_FREQ, "shape_px": SHAPE_PX,
               "note": ("v2 判别核心为轮廓半径函数频谱（旋转/尺度不变），"
                        "颜色权重从 v1 的 0.42 降到 0.12。v1 因颜色主导，"
                        "把螺壳/水母/带棘幼体/章鱼归为一簇（maxd=0.096）。"
                        "本文件只是特征与候选，不含同一生物结论。"),
               "quantiles": {"min": ds[0], "p1": q(.01), "p5": q(.05),
                             "p10": q(.10), "median": q(.5)},
               "skipped": [{"id": i, "why": w} for i, w in skipped],
               "features": feats,
               "pairs": pairs},
              open(args.out, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"      → {args.out}  ({os.path.getsize(args.out)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
