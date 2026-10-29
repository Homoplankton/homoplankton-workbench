#!/usr/bin/env python3
"""prep_assets.py — S1 素材准备：盘点 → 去重 → 抽样 → 双层素材 → 主体框 → 元数据 → data.js

用法:
  python3 prep_assets.py <图片文件夹> --stage <暂存目录> --out <项目>/assets/data.js \
      [--min-mb 1.0] [--display-long 900] [--dedupe] [--sample N] [--title "…"] \
      [--sidecar <csv|json>] [--report report.json]

铁律：只读源文件夹，一切产物写入 --stage；永不修改用户原图。
规模闸门：>200 张且 --min-mb>0 时，先打印预估上传体积并要求 --force-big 才继续。
"""
import argparse
import csv
import io
import json
import os
import re
import shutil
import statistics
import sys
from collections import defaultdict

from PIL import Image

Image.MAX_IMAGE_PIXELS = None
IMG_EXT = (".jpg", ".jpeg", ".png")


def _estimate_display_mb(sample_paths, long_side, n=8):
    """按目标长边真实试编码若干张，取中位体积（MB）。

    用试编码而非源图体积估算：黑水照片大面积纯黑，压缩率极高，
    源图 3–7MB 缩到长边 1500px 后常仅 70–80KB，两者相差近 40 倍。
    """
    sizes = []
    for p in sample_paths[:n]:
        try:
            with Image.open(p) as im:
                im.draft("RGB", (long_side, long_side))
                im = im.convert("RGB")
                w0, h0 = im.size
                sc = min(1.0, long_side / max(w0, h0))
                if sc < 1:
                    im = im.resize((max(1, int(w0 * sc)), max(1, int(h0 * sc))), Image.LANCZOS)
                bio = io.BytesIO()
                im.save(bio, "JPEG", quality=86, optimize=True, progressive=True)
                sizes.append(bio.tell())
        except Exception:                                        # noqa: BLE001
            continue
    if not sizes:
        return 0.3                                               # 无法估计时给保守小值，不误拦
    return statistics.median(sizes) / 1e6


# ---------- 盘点 ----------
def inventory(folder):
    files = []
    for root, _dirs, names in os.walk(folder):
        for n in names:
            if n.startswith("._") or n.startswith("."):
                continue
            if n.lower().endswith(IMG_EXT):
                files.append(os.path.join(root, n))
    return sorted(files)


# ---------- 去重 ----------
def canon_stem(path):
    s = os.path.splitext(os.path.basename(path))[0]
    s = re.sub(r"[- .]+(enhanced[- .]?nr|edit\d*|copy|nr)\d*[- .]*\d*$", "", s, flags=re.I)
    s = re.sub(r"[- .]+\d+$", "", s)
    return s.lower()


def seq_of(path):
    m = re.search(r"(\d{3,5})", os.path.splitext(os.path.basename(path))[0])
    return int(m.group(1)) if m else None


def ym_of(path, root):
    rel = os.path.relpath(os.path.dirname(path), root).split(os.sep)
    y = mo = "?"
    for part in rel:
        m = re.search(r"(19|20)\d{2}", part)
        if m and y == "?":
            y = m.group(0)
        for name in ("January", "February", "March", "April", "May", "June", "July",
                     "August", "September", "October", "November", "December",
                     "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"):
            if part.lower().startswith(name.lower()):
                mo = name[:3]
                break
    return (y, mo)


def taxon_of(path, root):
    """从目录名推断类目（浮游生物常见类群关键词）"""
    KNOWN = ("Cephalopoda", "Cnidaria", "Crustacea", "Ctenophora", "Ctenophoda", "Fish",
             "Gastropoda", "Polychaeta", "Thaliacea", "Mollusca", "Chordata", "Sipuncula",
             "Bryozoa", "Echinodermata", "Rotifera", "Tardigrada", "Amphipoda", "Chaetognatha",
             "Radiolaria", "Foraminifera", "Unidentified")
    for part in reversed(os.path.relpath(os.path.dirname(path), root).split(os.sep)):
        for k in KNOWN:
            if part.lower() == k.lower():
                return k
    return ""


def dedupe(paths, root):
    """变体合并 + 连拍归组（并查集，同(年,月)且序号差≤4）"""
    by_stem = defaultdict(list)
    for p in paths:
        by_stem[canon_stem(p)].append(p)
    reps = []
    for _stem, group in by_stem.items():
        reps.append(max(group, key=lambda p: os.path.getsize(p)))
    n_variant = len(paths) - len(reps)

    parent = list(range(len(reps)))
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
    by_ym = defaultdict(list)
    for i, p in enumerate(reps):
        s = seq_of(p)
        if s is not None:
            by_ym[ym_of(p, root)].append((s, i))
    for lst in by_ym.values():
        lst.sort()
        for (s1, i1), (s2, i2) in zip(lst, lst[1:]):
            if s2 - s1 <= 4:
                union(i1, i2)
    groups = defaultdict(list)
    for i, p in enumerate(reps):
        groups[find(i)].append(p)
    out = [max(g, key=lambda p: os.path.getsize(p)) for g in groups.values()]
    return out, n_variant, len(reps) - len(out)


# ---------- 色彩与抽样 ----------
def hue_bucket(path):
    import numpy as np
    with Image.open(path) as im:
        im.draft("RGB", (200, 200))
        im = im.convert("HSV")
        im.thumbnail((110, 110))
        a = np.asarray(im)
        L, S = a[..., 2].astype(float), a[..., 1].astype(float)
        m = (L > 60) & (S > 70)
        if m.sum() < 40:
            return "clear"
        h = float(np.median(a[..., 0][m].astype(float)) * (360 / 255))
    for hi, name in ((20, "red"), (45, "orange"), (75, "yellow"), (110, "green"),
                     (175, "cyan"), (255, "blue")):
        if h < hi:
            return name
    return "pink"


def balanced_sample(paths, root, n):
    """类目 × 色彩 双层轮转抽样"""
    import random
    rng = random.Random(42)
    pools = defaultdict(list)
    for p in paths:
        pools[(taxon_of(p, root) or "Unknown", hue_bucket(p))].append(p)
    for v in pools.values():
        rng.shuffle(v)
    keys = sorted(pools, key=lambda k: -len(pools[k]))
    chosen, i = [], 0
    while len(chosen) < n and keys:
        progressed = False
        for k in list(keys):
            if pools[k] and len(chosen) < n:
                chosen.append(pools[k].pop())
                progressed = True
        if not progressed:
            break
        i += 1
    if len(chosen) < n:
        rest = [p for p in paths if p not in chosen]
        rng.shuffle(rest)
        chosen += rest[:n - len(chosen)]
    return chosen[:n]


# ---------- 主体框 ----------
def subject_box(path):
    import numpy as np
    with Image.open(path) as im:
        im.draft("L", (900, 900))
        g = im.convert("L")
        g.thumbnail((900, 900))
        a = np.asarray(g).astype(np.float32)
    h, w = a.shape
    t = max(14, a.mean() + 3 * a.std())
    m = a > t
    if m.sum() < a.size * 0.001:
        return None
    ys, xs = np.nonzero(m)
    x0, x1 = np.percentile(xs, 0.3), np.percentile(xs, 99.7)
    y0, y1 = np.percentile(ys, 0.3), np.percentile(ys, 99.7)
    bw, bh = x1 - x0, y1 - y0
    px, py = bw * 0.06, bh * 0.06
    return [round(max(0, x0 - px) / w, 4), round(max(0, y0 - py) / h, 4),
            round(min(w - 1, x1 + px) / w, 4), round(min(h - 1, y1 + py) / h, 4)]


# ---------- 素材生成 ----------
def make_display(src, dst, min_bytes, long_side):
    """生成显示层：长边封顶 long_side，返回 (w,h,bytes,used_original)。

    历史 bug：旧 LADDER 为凑 min_bytes 而逐级「缩小」长边（2000→1200），
    但缩小只会让文件更小，故高压缩率素材（大面积纯黑的黑水照片）五档必败，
    最终 shutil.copy2 塞入原图 —— 一张 7000px/3MB 原图被拿去渲染 200px 图块，
    导致整页负载爆炸、首屏长时间纯黑。
    正解：长边像素是主控变量，min_bytes 只是「不要放大凑数」的护栏。
    达不到下限时保留最大档成品，绝不回退原图。
    """
    # 质量阶梯：同一长边封顶下逐级提质量，达标即停（用于让低压缩素材更清晰）
    quals = (78, 84, 88, 92)
    best = None
    for q in quals:
        with Image.open(src) as im:
            im.draft("RGB", (long_side, long_side))
            im = im.convert("RGB")
            w0, h0 = im.size
            sc = min(1.0, long_side / max(w0, h0))          # 只缩不放
            if sc < 1:
                im = im.resize((max(1, int(w0 * sc)), max(1, int(h0 * sc))), Image.LANCZOS)
            im.save(dst, "JPEG", quality=q, optimize=True, progressive=True)
        best = (im.size[0], im.size[1], os.path.getsize(dst))
        if best[2] >= min_bytes:                             # 达标即停，不做无谓重编码
            return best[0], best[1], best[2], False
    # 走完阶梯仍不足 min_bytes：这是素材本身压缩率高，保留最高质量档成品。
    # 不再回退原图（used_original=False），避免整页负载失控。
    return best[0], best[1], best[2], False


# ---------- 元数据 ----------
def load_sidecar(path):
    if not path:
        return {}
    if not os.path.isfile(path):
        print(f"!! sidecar 不存在: {path}", file=sys.stderr)
        return {}
    if path.lower().endswith(".json"):
        d = json.load(open(path, encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    if path.lower().endswith(".csv"):
        rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
        key = None
        for cand in ("file", "filename", "name", "id"):
            if rows and cand in rows[0]:
                key = cand
                break
        out = {}
        for r in rows:
            if key:
                out[os.path.splitext(r[key])[0]] = {k: v for k, v in r.items() if k != key and v}
        return out
    return {}


def exif_of(path):
    try:
        with Image.open(path) as im:
            ex = im.getexif()
        if not ex:
            return {}
        out = {}
        TAGS = {306: "DateTime", 271: "Make", 272: "Model", 37386: "FocalLength"}
        for k, name in TAGS.items():
            if k in ex and ex[k]:
                out[name] = str(ex[k])[:40]
        return out
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--stage", required=True, help="产物暂存目录（display/ 与 full/）")
    ap.add_argument("--out", required=True, help="data.js 输出路径")
    ap.add_argument("--min-mb", type=float, default=0.0,
                    help="显示层「质量护栏」：单张不足此值时逐级提 JPEG 质量，"
                         "但绝不放大、绝不回退原图。0=不做护栏（默认，最快）")
    ap.add_argument("--display-long", type=int, default=1500,
                    help="显示层长边封顶像素（主控参数）。屏幕图块仅 162–206px，"
                         "1500 已远超需求且与 v23 观感一致；再高只增负载不增清晰度")
    ap.add_argument("--dedupe", action="store_true")
    ap.add_argument("--sample", type=int, default=0, help="抽样张数，0=全用")
    ap.add_argument("--title", default="Plankton Playground")
    ap.add_argument("--sidecar", default="")
    ap.add_argument("--report", default="")
    ap.add_argument("--force-big", action="store_true")
    ap.add_argument("--full-mode", choices=("source", "copy"), default="source",
                    help="灯箱层策略：source=直接上传源原图（默认，省一倍磁盘）；"
                         "copy=先复制副本到 stage/full 再上传（源目录只读或需固定命名时用）")
    a = ap.parse_args()

    if not os.path.isdir(a.folder):
        print("!! 文件夹不存在: " + a.folder, file=sys.stderr)
        return 2
    root = a.folder
    paths = inventory(root)
    if not paths:
        print("!! 文件夹内没有图片", file=sys.stderr)
        return 2
    print(f"盘点: {len(paths)} 张")

    n_var = n_burst = 0
    if a.dedupe:
        paths, n_var, n_burst = dedupe(paths, root)
        print(f"去重: 变体合并 {n_var} 张，连拍归组 {n_burst} 张 → 剩 {len(paths)}")
    if a.sample and a.sample < len(paths):
        paths = balanced_sample(paths, root, a.sample)
        print(f"抽样: → {len(paths)} 张（类目×色彩均衡）")

    # 规模闸门：按「显示层实际体积」估算上传量，而非源图体积或字节下限。
    # 源图常有 3–7MB，但显示层封顶长边后通常仅数十 KB，用源图估算会严重高估并误拦。
    if len(paths) > 200 and not a.force_big:
        est = _estimate_display_mb(paths[:40], a.display_long) * len(paths) / 1000
        print(f"\n⛔ 规模闸门：{len(paths)} 张 × 长边 {a.display_long}px ≈ {est:.1f} GB 上传量。")
        print("   千张级上传耗时较长，且首屏并发加载会拖垮低端机器。")
        print("   请二选一后重跑：")
        print(f"     · 降长边：--display-long 900（估算 ≈ {est * (900 / a.display_long) ** 2:.1f} GB）")
        print("     · 维持当前档位：加 --force-big（已知代价）")
        return 3

    disp_dir = os.path.join(a.stage, "display")
    os.makedirs(disp_dir, exist_ok=True)
    full_dir = ""
    if a.full_mode == "copy":
        full_dir = os.path.join(a.stage, "full")
        os.makedirs(full_dir, exist_ok=True)
    side = load_sidecar(a.sidecar)

    # source 模式下 full 用原文件名；不同目录可能出现同名，必须提前拦截
    # （否则上传后 URL 映射会串，且无法察觉）
    if a.full_mode == "source":
        seen = defaultdict(list)
        for p in paths:
            seen[os.path.basename(p)].append(p)
        dup = {k: v for k, v in seen.items() if len(v) > 1}
        if dup:
            print(f"!! source 模式下有 {len(dup)} 个同名原文件，无法一一对应上传：", file=sys.stderr)
            for k, v in list(dup.items())[:5]:
                print(f"   {k}: {len(v)} 份", file=sys.stderr)
            print("   请改用 --full-mode copy（用 f0001.jpg 等唯一名）", file=sys.stderr)
            return 3

    records = []
    sizes_d, sizes_f = [], []
    n_orig = 0
    for i, src in enumerate(paths, 1):
        stem = os.path.splitext(os.path.basename(src))[0]
        rid = re.sub(r"[^\w.-]", "_", stem)[:60]
        dname = f"p{i:04d}.jpg"
        w, h, db, used_orig = make_display(src, os.path.join(disp_dir, dname),
                                          int(a.min_mb * 1024 * 1024), a.display_long)
        n_orig += used_orig
        if a.full_mode == "copy":
            fname = f"f{i:04d}.jpg"
            shutil.copy2(src, os.path.join(full_dir, fname))   # 逐字节，不重编码
            fb = os.path.getsize(os.path.join(full_dir, fname))
        else:
            fname = os.path.basename(src)                        # 直接上传源原图，零复制
            fb = os.path.getsize(src)
        sizes_d.append(db)
        sizes_f.append(fb)
        attrs = {}
        tax = taxon_of(src, root)
        if tax:
            attrs["taxon"] = tax
        y, mo = ym_of(src, root)
        if y != "?":
            attrs["year"] = y
        if mo != "?":
            attrs["month"] = mo
        attrs.update(exif_of(src))
        sc = side.get(stem) or side.get(rid)
        if isinstance(sc, dict):
            attrs.update(sc)
        records.append({
            "id": rid, "src": dname, "full": fname,
            "w": w, "h": h, "box": subject_box(src),
            "attrs": attrs,
            "_srcfile": os.path.basename(src), "_disp_bytes": db, "_full_bytes": fb,
        })
        if i % 50 == 0:
            print(f"  {i}/{len(paths)}", flush=True)

    payload = {"schema": "plankton-playground/v1", "title": a.title,
               "config": {}, "records": [
                   {k: v for k, v in r.items() if not k.startswith("_")} for r in records]}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    open(a.out, "w", encoding="utf-8").write(
        "window.PLAYGROUND_DATA=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n")

    fills = [r["box"] for r in records if r["box"]]
    report = {
        "source_folder": root, "count": len(records),
        "variant_merged": n_var, "burst_grouped": n_burst,
        "display_total_mb": round(sum(sizes_d) / 1e6, 1),
        "display_median_kb": round(statistics.median(sizes_d) / 1024),
        "display_used_original": n_orig,
        "full_total_mb": round(sum(sizes_f) / 1e6, 1),
        "box_detected": len(fills), "box_null": len(records) - len(fills),
        "taxa": dict(sorted({t: sum(1 for r in records if r["attrs"].get("taxon") == t)
                             for t in {r["attrs"].get("taxon") for r in records} if t}.items(),
                            key=lambda kv: -kv[1])) or "(无类目信息：源目录名未含类群关键词)",
        "with_taxon": sum(1 for r in records if r["attrs"].get("taxon")),
        "with_exif_date": sum(1 for r in records if r["attrs"].get("DateTime")),
        "stage_display": disp_dir, "stage_full": full_dir, "data_js": a.out,
    }
    if a.report:
        json.dump(report, open(a.report, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # 上传清单：每行一个待上传文件路径，供 upload_asset.py 使用
    man_dir = os.path.dirname(os.path.abspath(a.out)) or "."
    man_d = os.path.join(man_dir, "upload_display.txt")
    man_f = os.path.join(man_dir, "upload_full.txt")
    with open(man_d, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(os.path.join(disp_dir, r["src"]) + "\n")
    with open(man_f, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write((os.path.join(full_dir, r["full"]) if a.full_mode == "copy"
                      else os.path.join(root, r["full"])) + "\n")

    print("\n=== 素材报告 ===")
    for k, v in report.items():
        print(f"  {k}: {v}")
    print(f"\n待上传清单已写: {man_d} / {man_f}")
    print("下一步：upload_asset.py 上传两份清单 → apply_urls.py 把 URL 写回 data.js。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
