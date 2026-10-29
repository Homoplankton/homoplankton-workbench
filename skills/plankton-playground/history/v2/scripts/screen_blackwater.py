#!/usr/bin/env python3
"""screen_blackwater.py — S1.0 黑水背景筛选（可选前置阶段）。

把图片分三类：明确黑水 / 明确非黑水 / 灰带（必须人工逐张判定）。
只输出分类与清单，不移动、不删除任何文件。

用法:
  python3 screen_blackwater.py <文件夹> [--out screen.json] [--grid-dir <拼图目录>]
                                [--tile 300] [--cols 6]

判据（源自 2044 张真实黑水库的标定）:
  edge_dark ≥ 0.85                          → 黑水（四周近黑）
  sat_lit ≥ 0.15 且 whole_dark < 0.30        → 非黑水（大面积彩色：礁石/珊瑚/蓝绿水体）
  lit ≥ 0.80 且 edge_dark < 0.30            → 非黑水（整体亮：浅水/船面/沙地）
  其余                                       → 灰带（人工判定）
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
IMG_EXT = (".jpg", ".jpeg", ".png")
EDGE = 0.08
WORK = 700


def features(path):
    with Image.open(path) as im:
        im.draft("RGB", (WORK, WORK))
        im = im.convert("RGB")
        im.thumbnail((WORK, WORK), Image.BILINEAR)
        a = np.asarray(im, dtype=np.float32)
    h, w, _ = a.shape
    eh, ew = max(1, int(h * EDGE)), max(1, int(w * EDGE))
    band = np.concatenate([a[:eh].reshape(-1, 3), a[-eh:].reshape(-1, 3),
                           a[:, :ew].reshape(-1, 3), a[:, -ew:].reshape(-1, 3)], axis=0)
    L = 0.299 * band[..., 0] + 0.587 * band[..., 1] + 0.114 * band[..., 2]
    edge_dark = float((L < 25).mean())
    edge_med = float(np.median(L))
    fl = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    whole_dark = float((fl < 25).mean())
    mx, mn = a.max(2), a.min(2)
    S = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    lit = fl > 70
    sat_lit = float((lit & (S > 0.45)).mean())
    lit_frac = float(lit.mean())
    dark = fl < 25
    dm = dark | ((fl >= 25) & (fl < 60))
    dark_blue = 0.0
    if dm.any():
        rr, bb = float(a[..., 0][dm].mean()), float(a[..., 2][dm].mean())
        dark_blue = bb / max(rr, 1e-3)
    return dict(edge_dark=edge_dark, edge_med=edge_med, whole_dark=whole_dark,
                sat_lit=sat_lit, lit=lit_frac, dark_blue=dark_blue)


def classify(f):
    if f["sat_lit"] >= 0.15 and f["whole_dark"] < 0.30:
        return "drop", "大面积彩色背景（礁石/珊瑚/蓝绿水体）"
    if f["lit"] >= 0.80 and f["edge_dark"] < 0.30:
        return "drop", "整体亮背景（浅水/船面/沙地）"
    if f["edge_dark"] >= 0.85:
        return "keep", "四周近黑"
    if f["edge_dark"] < 0.15 and f["whole_dark"] < 0.15:
        return "drop", "画面几乎无黑区"
    return "review", "灰带：需人工判定"


def make_grid(items, folder, out_path, tile, cols, tag):
    if not items:
        return
    n = len(items)
    rows = (n + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tile, rows * tile), (40, 40, 40))
    from PIL import ImageDraw
    for k, it in enumerate(items):
        p = os.path.join(folder, it["file"])
        try:
            im = Image.open(p).convert("RGB")
            im.thumbnail((tile - 6, tile - 34))
        except Exception:
            continue
        x, y = (k % cols) * tile, (k // cols) * tile
        sheet.paste(im, (x + 3, y + 33))
        d = ImageDraw.Draw(sheet)
        d.text((x + 3, y + 3), f"{tag}{k} {it['file'][:24]}", fill=(255, 255, 0))
        d.text((x + 3, y + 14), f"ed={it['f']['edge_dark']:.2f} sat={it['f']['sat_lit']:.2f} lit={it['f']['lit']:.2f}",
               fill=(120, 255, 120))
        d.text((x + 3, y + 24), it["reason"][:30], fill=(255, 200, 160))
    sheet.save(out_path, quality=86)
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--out", default="screen_result.json")
    ap.add_argument("--grid-dir", default="")
    ap.add_argument("--tile", type=int, default=300)
    ap.add_argument("--cols", type=int, default=6)
    ap.add_argument("--limit-grid", type=int, default=180, help="灰带拼图最多画多少张")
    a = ap.parse_args()

    if not os.path.isdir(a.folder):
        print("!! 文件夹不存在: " + a.folder, file=sys.stderr)
        return 2
    files = sorted(n for n in os.listdir(a.folder)
                   if not n.startswith("._") and n.lower().endswith(IMG_EXT)
                   and os.path.isfile(os.path.join(a.folder, n)))
    if not files:
        print("!! 没有图片", file=sys.stderr)
        return 2
    print(f"扫描 {len(files)} 张…")

    keep, drop, review = [], [], []
    for i, n in enumerate(files, 1):
        try:
            f = features(os.path.join(a.folder, n))
        except Exception as e:
            print(f"  跳过（无法解码）{n}: {e}")
            continue
        cat, reason = classify(f)
        rec = {"file": n, "cat": cat, "reason": reason, "f": {k: round(v, 4) for k, v in f.items()}}
        (keep if cat == "keep" else drop if cat == "drop" else review).append(rec)
        if i % 200 == 0:
            print(f"  {i}/{len(files)}", flush=True)

    total = len(keep) + len(drop) + len(review)
    print(f"\n明确黑水 {len(keep)} ({len(keep)/total*100:.0f}%) | "
          f"明确非黑水 {len(drop)} ({len(drop)/total*100:.0f}%) | "
          f"灰带待判 {len(review)} ({len(review)/total*100:.0f}%)")

    result = {"folder": a.folder, "total": total,
              "counts": {"keep": len(keep), "drop": len(drop), "review": len(review)},
              "keep": keep, "drop": drop, "review": review}

    if a.grid_dir:
        os.makedirs(a.grid_dir, exist_ok=True)
        # 灰带必须人工判定 → 出拼图
        if review:
            chunk = a.limit_grid
            for gi in range(0, len(review), chunk):
                part = review[gi:gi + chunk]
                gp = os.path.join(a.grid_dir, f"review_{gi//chunk+1}.jpg")
                make_grid(part, a.folder, gp, a.tile, a.cols, "R")
                print(f"  灰带拼图: {gp} ({len(part)} 张)")
        if drop:
            gp = os.path.join(a.grid_dir, "drop_sample.jpg")
            make_grid(drop[:a.limit_grid], a.folder, gp, a.tile, a.cols, "D")
            print(f"  剔除样本拼图: {gp}")
        print("\n⚠️ 灰带只能靠肉眼判定：白天打光压暗背景的微距照（红蛙鱼/红珊瑚/管子鱼洞穴）"
              "像素上极像黑水，纯算法无法区分。请用 Read 工具查看拼图后逐张定夺。")

    json.dump(result, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n清单已写: {a.out}")
    print("下一步：把 keep + 人工确认的 review 项作为 prep_assets.py 的输入；drop 清单交用户过目，不静默丢弃。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
