#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_assets.py — 浮游生物研究工作台 · 图像资产与派生指标生成

为什么需要这个脚本
------------------
既有 data.js 里的图片全部是 CDN 链接，带 auth_key 时效（2026-11-24 过期）。
研究工作台不能在 28 天后变成一片碎图，所以本脚本从外置盘原图重新生成一套
**本地**资产，日常使用不再依赖 CDN，也不依赖外置盘挂载。

产出
----
assets/thumb/<id>.jpg     400px 长边整图缩略（网格用，保留构图上下文）
assets/detail/<id>.jpg    主体裁剪 + 12% 留边，1200px 长边（检查器大图）
assets/derived.json       每图派生指标：原图尺寸、主体框、填充度、主色调、EXIF

安全边界
--------
* 只读外置盘，绝不写入 /Volumes/T7/
* 原图零改动；所有输出落在工作区项目目录内
* 无 PIL 则明确报错退出，不静默降级

依赖：系统 python3（自带 PIL）。不需要 numpy。
"""

import json
import os
import re
import sys
import glob
from collections import Counter

try:
    from PIL import Image, ImageOps
except ImportError:
    sys.exit("ERROR: 需要 PIL。请用系统 /usr/bin/python3 运行（自带 PIL 11.x）。")

# ---------------------------------------------------------------- 路径配置
SRC_DIR = "/Volumes/T7/Qwen_Homoplankton/PlanktonTest"
DATA_JS = ("/Users/jialingcai/Documents/qwen-agent/NZKKxizmz2/"
           "default/planktontest-v31-run108/assets/data.js")
WB_DIR = "/Users/jialingcai/Documents/qwen-agent/NZKKxizmz2/default/plankton-workbench"
THUMB_DIR = os.path.join(WB_DIR, "assets", "thumb")
DETAIL_DIR = os.path.join(WB_DIR, "assets", "detail")
OUT_JSON = os.path.join(WB_DIR, "assets", "derived.json")

THUMB_PX = 400        # 网格缩略图长边
DETAIL_PX = 1200      # 检查器大图长边
PAD_RATIO = 0.12      # 主体框外扩比例（框最小宽 20.9%，12% 留边不会吞掉邻体）

# ---- 色彩分析参数（见 color_profile 的实测依据说明）----
WATER_PCTL = 0.25     # 用主体框内亮度的第 25 百分位作「照亮水体」基线
T_MULT = 1.35         # 亮度 ≥ 水体基线×此系数 才算组织
T_FLOOR_ADD = 14      # 且至少高出基线这么多，避免基线≈0 时阈值过松
T_MIN = 16            # 绝对下限
PIG_SAT = 0.22        # 饱和度下限，低于此不算色素
PIG_WARM_LO = 32      # 暖色相区间：hue ≤ 32
PIG_WARM_HI = 330     #            或 hue ≥ 330
PIG_MIN_OF_ORG = 0.02 # 色素占组织比 < 2% → 判「未检出显著色素」，不硬给色值

# ---------------------------------------------------------------- 工具函数
def load_records():
    """从 data.js 提取记录（该文件是 window.PLAYGROUND_DATA={...} 形式）。"""
    raw = open(DATA_JS, encoding="utf-8").read()
    i = raw.index("[")
    j = raw.rindex("]") + 1
    return json.loads(raw[i:j])


def find_source(image_id):
    """id 与源文件 stem 108/108 完全对应，直接拼路径；找不到才模糊匹配。"""
    direct = os.path.join(SRC_DIR, image_id + ".jpg")
    if os.path.exists(direct):
        return direct
    cands = glob.glob(os.path.join(SRC_DIR, "*"))
    for f in cands:
        if re.sub(r"\.[A-Za-z0-9]+$", "", os.path.basename(f)) == image_id:
            return f
    return None


def fit(img, px):
    """等比缩放到长边 px，不放大。"""
    w, h = img.size
    s = px / max(w, h)
    if s < 1:
        img = img.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)
    return img


def subject_box_px(box, w, h):
    """归一化 box [x0,y0,x1,y1] → 外扩 PAD_RATIO 后的像素坐标，clamp 到画幅。"""
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    x0 = max(0.0, x0 - bw * PAD_RATIO)
    y0 = max(0.0, y0 - bh * PAD_RATIO)
    x1 = min(1.0, x1 + bw * PAD_RATIO)
    y1 = min(1.0, y1 + bh * PAD_RATIO)
    return (round(x0 * w), round(y0 * h), round(x1 * w), round(y1 * h))


def rgb2hsv(r, g, b):
    """RGB → (hue 0-360, sat 0-1, val 0-1)。手写实现，不依赖 colorsys/numpy。"""
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


def luma(p):
    return 0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2]


def is_warm(h):
    """暖色相 = 色素细胞的典型色相区间（橙、红、褐）。

    实测依据：黑水照片受闪光灯与水层影响，**水体与半透明组织的色相集中在
    190-225（蓝青）**。若按饱和度阈值判色素，会把蓝水误判成色素——初版就是这样，
    DSC_0933 被报为「色素 hue 216」。真色素（船蛸的橙红色素环）落在 hue 14-35。
    故这里只认暖色相。
    """
    return h <= PIG_WARM_LO or h >= PIG_WARM_HI


def mean_rgb(pxs):
    n = len(pxs)
    return (round(sum(x[0] for x in pxs) / n),
            round(sum(x[1] for x in pxs) / n),
            round(sum(x[2] for x in pxs) / n))


def color_profile(img, box_px):
    """
    把主体框内像素分为三类，而不是报一个「主色调」。

    为什么不是单一主色调
    --------------------
    初版实现（RGB 量化到 4096 桶取众数）经实测有两个致命问题：
      1. 直方图众数落在**水体暗尾**上：DSC_2999 框内 p25=70/p50=114 整体偏亮，
         却输出 rgb=[54,69,89]（亮度 67，属最暗四分之一），即把水当成了主体色；
         全库 105 张有框图中 16 张（15%）属此类污染。
      2. 桶过细导致 dominant_share 普遍只有 5-10%，「主色」基本是噪声。
    浮游动物是黑色水体上的小型半透明生物，单一主色无法表达。

    三分类模型
    ----------
    water  亮度 < T           照亮的水体（黑水摄影里主体周围的水也是亮的）
    tissue 亮度 ≥ T 且非暖色   半透明组织、几丁质、贝壳
    pigment 亮度 ≥ T 且暖色高饱和  色素细胞（分类学特征，如船蛸的橙红色素环）

    T 不用固定阈值，而取**主体框内**亮度第 25 百分位为水体基线再上浮。
    实测依据：用全图暗部众数做基线时，框外纯黑背景把基线压到 0，
    导致 T 全部塌到下限 18，108 张里 107 张「检出色素」（99%），毫无区分度。
    框内 p25 才是真正需要排除的「被闪光灯照亮的水」。

    色素占比不显著时返回 None 并标注「未检出显著色素」，不硬给色值——
    几个像素支撑的颜色值属于误导。这与鉴定「到置信层即停、不硬凑」同一原则。
    """
    crop = img.crop(box_px).convert("RGB")
    small = fit(crop, 200)
    px = list(small.getdata())
    total = len(px)
    if not total:
        return None

    lums = sorted(luma(p) for p in px)
    wbase = lums[min(total - 1, int(total * WATER_PCTL))]
    T = max(wbase * T_MULT, wbase + T_FLOOR_ADD, T_MIN)

    org = [p for p in px if luma(p) >= T]
    water_n = total - len(org)
    pig = [p for p in org if is_warm(rgb2hsv(*p)[0]) and rgb2hsv(*p)[1] >= PIG_SAT]

    out = {
        "water_threshold": round(T, 1),
        "water_baseline_p25": round(wbase, 1),
        "water_frac": round(water_n / total, 4),
        "tissue_frac": round(len(org) / total, 4),
        "pigment_frac": round(len(pig) / total, 4),
    }

    # 半透明组织均色
    out["tissue_rgb"] = mean_rgb(org) if org else None
    out["tissue_bright_p90"] = round(lums[min(total - 1, int(total * 0.90))], 1)

    # 色素：hue 15° 桶求众数（比 RGB 量化稳健），并检验占比是否显著
    if org and pig and len(pig) / len(org) >= PIG_MIN_OF_ORG:
        buckets = Counter(int(rgb2hsv(*p)[0] // 15) for p in pig)
        top_bucket = buckets.most_common(1)[0][0]
        mem = [p for p in pig if int(rgb2hsv(*p)[0] // 15) == top_bucket]
        hues = sorted(rgb2hsv(*p)[0] for p in pig)
        out["pigment"] = {
            "rgb": mean_rgb(mem),
            "hue_median": round(hues[len(hues) // 2]),
            "of_tissue": round(len(pig) / len(org), 4),
            "detected": True,
        }
    else:
        out["pigment"] = {
            "rgb": None, "hue_median": None,
            "of_tissue": round(len(pig) / len(org), 4) if org else 0.0,
            "detected": False,
            "note": ("色素占组织比 < 2%，不足以支撑一个色值，如实报未检出"
                     if org else "框内无组织像素"),
        }
    return out


EXIF_TAGS = {
    271: "Make", 272: "Model", 305: "Software", 306: "DateTime",
    315: "Artist", 33432: "Copyright", 36867: "DateTimeOriginal",
    36868: "DateTimeDigitized", 37378: "ApertureValue",
    33434: "ExposureTime", 34855: "ISOSpeedRatings",
    41989: "FocalLength35mm", 274: "Orientation", 316: "HostComputer",
}


def read_exif(img):
    """提取 EXIF。

    ⚠ 必须在 ImageOps.exif_transpose() **之前**调用。
    实测坑：exif_transpose() 返回的是通用 Image 对象，**没有 _getexif 方法**
    （该方法属 JpegImageFile 插件）。初版在 transpose 之后取 EXIF，
    108 张全部走 except 分支返回空 dict，导致 EXIF 覆盖率 0/108。

    已知 Lightroom 导出剥离了镜头/GPS/曝光，此处如实记录实际有什么，
    并对缺失字段显式标注，不静默跳过。
    """
    out = {}
    ex = {}
    try:
        ex = img._getexif() or {}
    except AttributeError:
        try:                                  # 回退：PIL 通用 getexif()
            ex = dict(img.getexif() or {})
        except Exception:
            ex = {}
    except Exception:
        ex = {}
    for k, name in EXIF_TAGS.items():
        if k in ex:
            v = ex[k]
            if isinstance(v, tuple) and name == "ExposureTime":
                v = f"{v[0]}/{v[1]}" if v[1] else str(v[0])
            if isinstance(v, bytes):
                v = "<binary>"
            out[name] = str(v)[:160]
    return out


def color_summary(col):
    """把三分类结果压成一句人类可读的显示标签，供网格与筛选器使用。"""
    if not col:
        return "无色彩数据"
    parts = []
    pig = col.get("pigment") or {}
    if pig.get("detected"):
        h = pig["hue_median"]
        if h is None:
            nm = "暖色素"
        elif h <= 20 or h >= 340:
            nm = "红"
        elif h <= 32:
            nm = "橙红"
        elif h >= 330:
            nm = "品红"
        else:
            nm = "暖色素"
        pct = round(pig["of_tissue"] * 100)
        parts.append(f"{nm}色素{pct}%")
    t = col.get("tissue_rgb")
    if t:
        v = luma(t) / 255.0
        s = rgb2hsv(*t)[1]
        if v > 0.80 and s < 0.14:
            parts.append("亮白组织")
        elif v > 0.45 and s < 0.14:
            parts.append("浅灰组织")
        elif v > 0.80:
            parts.append("亮彩组织")
        else:
            parts.append("暗组织")
    if not parts:
        parts.append("无明显主体")
    return " · ".join(parts)


# ---------------------------------------------------------------- 主流程
def main():
    if not os.path.isdir(SRC_DIR):
        sys.exit(f"ERROR: 外置盘未挂载或路径不存在：{SRC_DIR}")
    if not os.path.exists(DATA_JS):
        sys.exit(f"ERROR: 找不到 data.js：{DATA_JS}")

    for d in (THUMB_DIR, DETAIL_DIR):
        os.makedirs(d, exist_ok=True)

    recs = load_records()
    print(f"[1/3] 载入 {len(recs)} 条记录")

    derived = []
    stats = Counter()
    for idx, r in enumerate(recs, 1):
        iid = r["id"]
        src = find_source(iid)
        if not src:
            print(f"  !! 找不到源文件: {iid}")
            stats["missing_src"] += 1
            continue

        try:
            im = Image.open(src)
            exif = read_exif(im)                    # ⚠ 必须在 transpose 之前
            im = ImageOps.exif_transpose(im)        # 尊重拍摄方向
            W, H = im.size
            rgb = im.convert("RGB")

            # 缩略图：整图等比缩，保留构图
            th = fit(rgb.copy(), THUMB_PX)
            th.save(os.path.join(THUMB_DIR, iid + ".jpg"), quality=82, optimize=True)

            # 检查器大图：有 box 则裁主体，无 box 则整图缩放并如实标注
            box = r.get("box")
            if box:
                bp = subject_box_px(box, W, H)
                if bp[2] <= bp[0] or bp[3] <= bp[1]:
                    bp = None
            else:
                bp = None

            if bp:
                dt = fit(rgb.crop(bp), DETAIL_PX)
                crop_method = "subject_box"
                stats["cropped"] += 1
            else:
                dt = fit(rgb.copy(), DETAIL_PX)
                crop_method = "full_frame"          # 无主体框，不猜，如实标注
                bp = (0, 0, W, H)
                stats["full_frame"] += 1
            dt.save(os.path.join(DETAIL_DIR, iid + ".jpg"), quality=88, optimize=True)

            # 色彩三分类在**主体框**内做，避免框外纯黑背景干扰
            prof_box = r.get("box")
            if prof_box:
                pb = subject_box_px(prof_box, W, H)
                if pb[2] <= pb[0] or pb[3] <= pb[1]:
                    pb = (0, 0, W, H)
            else:
                pb = (0, 0, W, H)
            col = color_profile(rgb, pb)
            if col:
                if not (col.get("pigment") or {}).get("detected"):
                    stats["no_pigment"] += 1
            else:
                stats["no_color"] += 1

            derived.append({
                "id": iid,
                "source": {
                    "path": src,
                    "orig_w": W,
                    "orig_h": H,
                    "orig_bytes": os.path.getsize(src),
                    "aspect": round(W / H, 3),
                },
                "asset": {
                    "thumb": f"assets/thumb/{iid}.jpg",
                    "thumb_w": th.size[0], "thumb_h": th.size[1],
                    "detail": f"assets/detail/{iid}.jpg",
                    "detail_w": dt.size[0], "detail_h": dt.size[1],
                    "crop_method": crop_method,
                    "box_norm": prof_box,
                    "box_px": list(bp),
                },
                "color": col,
                "color_label": color_summary(col),
                "exif": exif,
            })
            im.close()
        except Exception as e:
            print(f"  !! 处理失败 {iid}: {type(e).__name__}: {e}")
            stats["error"] += 1

        if idx % 20 == 0:
            print(f"      …{idx}/{len(recs)}")

    print(f"[2/3] 生成完成 {len(derived)}/{len(recs)}")
    print(f"      裁剪方式: subject_box={stats['cropped']}  full_frame={stats['full_frame']}")
    if stats["no_pigment"]:
        print(f"      未检出显著色素: {stats['no_pigment']}（如实标注，不硬给色值）")
    if stats["no_color"]:
        print(f"      无色彩数据: {stats['no_color']}")
    if stats["error"]:
        print(f"      失败: {stats['error']}")

    payload = {
        "schema": "plankton-workbench/derived/v1",
        "source_dir": SRC_DIR,
        "thumb_px": THUMB_PX, "detail_px": DETAIL_PX,
        "pad_ratio": PAD_RATIO,
        "color_model": {
            "type": "three_way_split(water/tissue/pigment)",
            "water_pctl": WATER_PCTL, "t_mult": T_MULT,
            "t_floor_add": T_FLOOR_ADD, "t_min": T_MIN,
            "pigment_sat": PIG_SAT,
            "pigment_warm_hue": [PIG_WARM_LO, PIG_WARM_HI],
            "pigment_min_of_tissue": PIG_MIN_OF_ORG,
        },
        "note": ("从外置盘原图派生。data.js 的 CDN 链接 auth_key 于 2026-11-24 过期，"
                 "故工作台改用本地产物；重新生成本文件需要外置盘挂载，日常使用不需要。"),
        "records": derived,
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    tb = sum(os.path.getsize(p) for p in glob.glob(THUMB_DIR + "/*.jpg"))
    db = sum(os.path.getsize(p) for p in glob.glob(DETAIL_DIR + "/*.jpg"))
    print(f"[3/3] 写入 {OUT_JSON}")
    print(f"      thumb  {tb/1024/1024:.1f} MB   detail {db/1024/1024:.1f} MB"
          f"   合计 {(tb+db)/1024/1024:.1f} MB")


if __name__ == "__main__":
    main()
