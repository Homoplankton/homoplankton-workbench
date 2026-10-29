#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
find_kin.py — 跨时间「同一生物」候选对召回

诚实前提
--------
本脚本**不做**同一生物判定，只做候选召回。判定由人眼（AI 逐对目视）完成，
结果按置信度分级写入 kinship 断言。原因：
  * 无深度学习模型可用；PIL 只能算颜色直方图与形态统计量。
  * 物种级鉴定是本工具链实测最弱的一环（探针批 10 张 0 张能定到种）。
  * 把算法相似度直接当成「同一生物」，等于用低置信猜测冒充结论。

为什么连拍时间信号不够
----------------------
实测 108 张：同潜次内 ≤10 秒的连拍簇仅 6 个（13 张），95 簇是单帧，
覆盖率 12%。用户要的是跨时间、跨航次的同一生物，时间信号只能覆盖极小部分，
故与视觉信号并列，两种证据分开标注，不混算。

特征设计（按角度不变性排序，权重递减）
--------------------------------------
1. 色素色相直方图（12 bin）    色素细胞分布相对角度稳定，是分类学特征
2. 组织亮度直方图（8 bin）     半透明组织的明度分布
3. 色素/组织/水体三分类占比    已在 build_assets 验证过的口径
4. 形态统计量                  长宽比、伸展度、边缘方向直方图（8 bin）
   ↑ 角度变化会显著改变形态量，故权重最低，仅作辅助

距离 = 加权余弦/欧氏混合，归一化到 0-1。越小越像。
"""

import json
import math
import os
import sys
from collections import defaultdict, Counter
import datetime as DT

try:
    from PIL import Image, ImageOps, ImageFilter
except ImportError:
    sys.exit("ERROR: 需要 PIL，请用系统 /usr/bin/python3 运行")

WB = "/Users/jialingcai/Documents/qwen-agent/NZKKxizmz2/default/plankton-workbench"
DETAIL_DIR = os.path.join(WB, "assets", "detail")
DERIVED = os.path.join(WB, "assets", "derived.json")
CLAIMS = os.path.join(WB, "data", "claims.json")
OUT_FEAT = os.path.join(WB, "data", "features.json")
OUT_CAND = os.path.join(WB, "data", "candidates.json")

HUE_BINS = 12
LUM_BINS = 8
EDGE_BINS = 8
SAMPLE_PX = 150          # 特征采样边长
W_HUE, W_LUM, W_MIX, W_SHAPE = 0.42, 0.22, 0.16, 0.20


def luma(p):
    return 0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2]


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


def l2(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def cosine(a, b):
    da = math.sqrt(sum(x * x for x in a)) or 1e-9
    db = math.sqrt(sum(x * x for x in b)) or 1e-9
    return sum(x * y for x, y in zip(a, b)) / (da * db)


def feats_for(path):
    """从主体裁切图提取特征向量。detail 图已按主体框+12%裁切，故直接整图分析。"""
    im = Image.open(path).convert("L")
    W, H = im.size
    s = SAMPLE_PX / max(W, H)
    if s < 1:
        im = im.resize((max(1, round(W * s)), max(1, round(H * s))), Image.LANCZOS)
    gray = im
    rgb = Image.open(path).convert("RGB")
    if s < 1:
        rgb = rgb.resize(gray.size, Image.LANCZOS)

    gpx = list(gray.getdata())
    rpx = list(rgb.getdata())
    gw, gh = gray.size

    # 用亮度阈值分离组织与水体（detail 图已裁主体，背景占比仍可能高）
    lums = sorted(gpx)
    n = len(lums)
    wbase = lums[min(n - 1, int(n * 0.25))]
    T = max(wbase * 1.35, wbase + 14, 16)

    hue_hist = [0.0] * HUE_BINS
    lum_hist = [0.0] * LUM_BINS
    n_org = n_pig = 0
    for (r, g, b), L in zip(rpx, gpx):
        if L < T:
            continue
        n_org += 1
        lum_hist[min(LUM_BINS - 1, int(L / 256 * LUM_BINS))] += 1
        h, sat, v = rgb2hsv(r, g, b)
        if sat >= 0.22:
            n_pig += 1
            hue_hist[min(HUE_BINS - 1, int(h / 360 * HUE_BINS))] += 1

    hue_hist = norm(hue_hist)
    lum_hist = norm(lum_hist)

    # 三分类占比
    mix = [n_org / n if n else 0.0, n_pig / n if n else 0.0,
           n_pig / n_org if n_org else 0.0]

    # 形态：二值前景的伸展度（用二阶矩近似，角度会变但同种有相关性）
    bw = gray.point(lambda x: 255 if x >= T else 0)
    coords = bw.load()
    xs = []; ys = []
    for y in range(0, gh, 2):
        for x in range(0, gw, 2):
            if coords[x, y]:
                xs.append(x); ys.append(y)
    if len(xs) > 4:
        mx_ = sum(xs) / len(xs); my_ = sum(ys) / len(ys)
        vx = sum((x - mx_) ** 2 for x in xs) / len(xs)
        vy = sum((y - my_) ** 2 for y in ys) / len(ys)
        cov = sum((xs[i] - mx_) * (ys[i] - my_) for i in range(len(xs))) / len(xs)
        tr = vx + vy
        det = vx * vy - cov * cov
        disc = max(0.0, tr * tr / 4 - det)
        l1 = tr / 2 + math.sqrt(disc)
        l2_ = max(1e-6, tr / 2 - math.sqrt(disc))
        elong = math.sqrt(l1 / l2_)            # 伸展度：细长=大
        fill = len(xs) / ((gw / 2) * (gh / 2))
    else:
        elong, fill = 1.0, 0.0

    # 边缘方向直方图（Sobel 近似）
    eg = gray.filter(ImageFilter.FIND_EDGES)
    epx = list(eg.getdata())
    edge_hist = [0.0] * EDGE_BINS
    # 用相邻像素梯度方向分箱（简化：按梯度强度分位分箱，保留纹理密度信息）
    es = sorted(epx); en = len(es)
    if en:
        for L in epx:
            if L < 12:
                continue
            edge_hist[min(EDGE_BINS - 1, int(L / 256 * EDGE_BINS))] += 1
    edge_hist = norm(edge_hist)

    return {
        "hue": [round(x, 5) for x in hue_hist],
        "lum": [round(x, 5) for x in lum_hist],
        "mix": [round(x, 5) for x in mix],
        "shape": [round(elong, 4), round(fill, 4), round(gw / gh, 4)],
        "edge": [round(x, 5) for x in edge_hist],
        "n_org": n_org, "n_px": n, "T": round(T, 1),
    }


def dist(a, b):
    """加权距离，0=完全相同，1=完全不同。"""
    d_hue = l2(a["hue"], b["hue"]) / math.sqrt(2)
    d_lum = l2(a["lum"], b["lum"]) / math.sqrt(2)
    d_mix = l2(a["mix"], b["mix"]) / math.sqrt(3)
    d_edge = l2(a["edge"], b["edge"]) / math.sqrt(2)
    # 形态量纲不同，先各自归一（elong 取对数压缩，fill/aspect 已在 0-1 附近）
    sa = [math.log(max(a["shape"][0], 1.0)), a["shape"][1], math.log(max(a["shape"][2], .1))]
    sb = [math.log(max(b["shape"][0], 1.0)), b["shape"][1], math.log(max(b["shape"][2], .1))]
    d_shape = l2(sa, sb) / 2.0
    d = (W_HUE * d_hue + W_LUM * d_lum + W_MIX * d_mix + W_SHAPE * d_shape)
    return round(min(1.0, d), 4), {
        "hue": round(d_hue, 4), "lum": round(d_lum, 4),
        "mix": round(d_mix, 4), "shape": round(d_shape, 4), "edge": round(d_edge, 4)}


def main():
    dv = json.load(open(DERIVED, encoding="utf-8"))
    db = json.load(open(CLAIMS, encoding="utf-8"))
    derived = {r["id"]: r for r in dv["records"]}

    def cap(im):
        for c in im["claims"]:
            if c["predicate"] == "capture_context":
                return c["value"].get("datetime_original")
        return None

    cap_of, dive_of = {}, {}
    for im in db["images"]:
        cap_of[im["image_id"]] = cap(im)
        dive_of[im["image_id"]] = im.get("dive_id")

    ids = sorted(derived)
    print(f"[1/4] 提取特征 {len(ids)} 张")
    feats = {}
    miss = []
    for iid in ids:
        p = os.path.join(DETAIL_DIR, iid + ".jpg")
        if not os.path.isfile(p):
            miss.append(iid); continue
        try:
            feats[iid] = feats_for(p)
        except Exception as e:
            print(f"  !! {iid}: {type(e).__name__}: {e}")
            miss.append(iid)
    if miss:
        print(f"      跳过 {len(miss)} 张: {miss[:5]}")
    os.makedirs(os.path.dirname(OUT_FEAT), exist_ok=True)
    json.dump({"schema": "plankton-workbench/features/v1",
               "weights": {"hue": W_HUE, "lum": W_LUM, "mix": W_MIX, "shape": W_SHAPE},
               "note": "候选召回特征，不含任何同一生物判定",
               "features": feats}, open(OUT_FEAT, "w", encoding="utf-8"),
              ensure_ascii=False)

    # 时间信号：连拍簇（同潜次内 ≤10 秒）
    print("[2/4] 时间信号：连拍簇")
    byd = defaultdict(list)
    for iid, t in cap_of.items():
        if t:
            try:
                byd[dive_of[iid]].append(
                    (DT.datetime.strptime(t, "%Y:%m:%d %H:%M:%S"), iid))
            except ValueError:
                pass
    bursts = []
    for dv_id, lst in byd.items():
        lst.sort()
        cur = [lst[0]]
        for prev, nxt in zip(lst, lst[1:]):
            if (nxt[0] - prev[0]).total_seconds() <= 10:
                cur.append(nxt)
            else:
                if len(cur) >= 2:
                    bursts.append([x[1] for x in cur])
                cur = [nxt]
        if len(cur) >= 2:
            bursts.append([x[1] for x in cur])
    burst_of = {}
    for bi, b in enumerate(bursts):
        for iid in b:
            burst_of[iid] = bi
    print(f"      {len(bursts)} 个连拍簇，覆盖 {len(burst_of)} 张")

    # 视觉候选对
    print("[3/4] 视觉两两距离")
    keys = [i for i in ids if i in feats]
    pairs = []
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = keys[i], keys[j]
            d, comp = dist(feats[a], feats[b])
            same_burst = (a in burst_of and burst_of[a] == burst_of.get(b, -1))
            pairs.append({"a": a, "b": b, "d": d, "comp": comp,
                          "same_burst": same_burst,
                          "same_dive": dive_of[a] == dive_of[b],
                          "cross_trip": (cap_of[a] or "")[:7] != (cap_of[b] or "")[:7]})
    pairs.sort(key=lambda x: x["d"])
    ds = [p["d"] for p in pairs]
    print(f"      共 {len(pairs)} 对；距离 min={ds[0]:.3f} "
          f"p1={ds[len(ds)//100]:.3f} 中位={ds[len(ds)//2]:.3f} max={ds[-1]:.3f}")

    # 每张图取 top-K 候选，且距离需显著低于中位（避免全是噪声对）
    K = 5
    med = ds[len(ds) // 2]
    thr = med * 0.62
    near = [p for p in pairs if p["d"] <= thr]
    print(f"      阈值 d≤{thr:.3f}（中位×0.62）→ {len(near)} 对进入候选")

    byimg = defaultdict(list)
    for p in near:
        byimg[p["a"]].append(p)
        byimg[p["b"]].append(p)
    # 每张图保留最近的 K 对
    cand = []
    seen = set()
    for iid, lst in byimg.items():
        lst.sort(key=lambda x: x["d"])
        for p in lst[:K]:
            key = tuple(sorted((p["a"], p["b"])))
            if key in seen:
                continue
            seen.add(key)
            cand.append(p)
    cand.sort(key=lambda x: x["d"])
    # 连拍簇内部对强制纳入（时间信号独立于视觉）
    for b in bursts:
        for i in range(len(b)):
            for j in range(i + 1, len(b)):
                key = tuple(sorted((b[i], b[j])))
                if key not in seen and b[i] in feats and b[j] in feats:
                    d, comp = dist(feats[b[i]], feats[b[j]])
                    seen.add(key)
                    cand.append({"a": b[i], "b": b[j], "d": d, "comp": comp,
                                 "same_burst": True,
                                 "same_dive": dive_of[b[i]] == dive_of[b[j]],
                                 "cross_trip": False})

    for p in cand:
        p["signals"] = []
        if p["same_burst"]:
            p["signals"].append("burst")
        if p["cross_trip"]:
            p["signals"].append("cross_trip")
        elif p["same_dive"]:
            p["signals"].append("same_dive")
        else:
            p["signals"].append("diff_dive")

    print(f"[4/4] 候选对 {len(cand)} 个，涉及 {len({x for p in cand for x in (p['a'],p['b'])})} 张")
    sc = Counter(tuple(p["signals"]) for p in cand)
    for k, v in sc.most_common():
        print(f"      {'+'.join(k)}: {v} 对")
    json.dump({"schema": "plankton-workbench/candidates/v1",
               "note": ("候选对=算法召回，非结论。status 一律 pending_review，"
                        "须经逐对目视确认后才可升级为 confirmed_same_individual / "
                        "same_species_likely / similar_uncertain / rejected"),
               "bursts": bursts,
               "distance_median": round(med, 4),
               "threshold": round(thr, 4),
               "candidates": cand},
              open(OUT_CAND, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"      → {OUT_FEAT}")
    print(f"      → {OUT_CAND}")


if __name__ == "__main__":
    main()
