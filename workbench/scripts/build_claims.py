#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_claims.py — 浮游生物研究工作台 · claim-centric 数据层

为什么是「断言」而不是「图片的字段」
------------------------------------
归档工具的数据模型是「一张图 → 一堆字段」。研究工具必须是「一条断言 → 证据 → 状态」，
因为研究结论会被推翻，而**推翻这件事本身必须留痕**。

本项目实测支撑：在标注 108 张的过程中，AI 的四次判断被用户或文献推翻——
  1. DSC_0077 被误判为鱼类幼体，实为头足类（船蛸雌体）。根因：依据 560px 缩略图鉴定，
     壳肋与吸盘列等诊断特征在该分辨率下不可见。
  2. 曾给出一个从未在任何检索结果中出现过的 DOI（按 URL 规律推断而来），属编造，已废弃。
  3. Marco-Herrero 引用被过度外推：原文只说 Grapsidae 科内资料多止于 zoea I，
     曾写成「多数科」，已按原文收窄。
  4. 曾断定栉水母直接发育、无幼虫期故排除出序列；后被 Soto-Angel 2024 推翻
     （栉水母以 cydippid 形态孵化并渐变态），改判为 contested。
若这四次只存在于对话记忆里，等于没发生。本脚本把它们固化进 revision_log，
使 superseded_by 修正链成为可查询的数据，而非口述历史。

数据来源与优先级
----------------
exif        相机直读，最高可信（机器事实）
auto        本脚本/资产脚本派生，可复算，不含研究结论
ai          AI 推断，一律 draft，必须经人工确认才进 confirmed
human       人工确认/修改
literature  文献直接陈述（挂在 reference 上）

产出 data/claims.json —— 工作台唯一数据源（前端不直接读 derived.json / v5 标注）。
"""

import json
import os
import re
import sys
import datetime as DT
from collections import defaultdict, Counter

WB = "/Users/jialingcai/Documents/qwen-agent/NZKKxizmz2/default/plankton-workbench"
DERIVED = os.path.join(WB, "assets", "derived.json")
V5 = ("/Users/jialingcai/Documents/qwen-agent/NZKKxizmz2/"
      "default/growthseq-exp/draft_annotations_v5.json")
OUT = os.path.join(WB, "data", "claims.json")

# 同一日内拍摄间隔 > 此分钟数 → 视为不同潜次（时段）
DIVE_GAP_MIN = 40

# ---------------------------------------------------------------- 争议登记
# 为什么是显式登记，而不是关键词自动判定
# --------------------------------------
# 曾用关键词扫描（冲突/争议/待判/排除…）自动找争议，命中 3 张，但其中
# DSC_0933 是**假阳性**：它的 continuum_note 命中「排除」一词，原文却是
# 「单细胞生物，无后生动物发育序列；排除依据充分」——这是确定结论，不是争议。
# 关键词匹配会把确定结论误标成争议，反而稀释争议板的可信度。
# 故改为逐条显式登记，每条写明依据原文与冲突的两造文献。
#
# 每条：image_id → (是否争议, 序列资格, 理由, 依据的 ref 文本关键词)
DISPUTED = {
    "DSC_3058": {
        "contested": True,
        "eligible": None,           # 未定：不是 true 也不是 false
        "reason": ("撤销先前「直接发育→排除序列」的判断。Edgar 2022 / Pang 2008 / "
                   "Schnitzler 2014 支持直接发育（cydippid 不算真幼体）；但 Soto-Angel 2024 "
                   "记载 lobate 类以 cydippid 孵化、触手重吸收并发育新结构，属渐变变态，"
                   "学界正争论是否废除 larva / metamorphosis 术语。能否进序列取决于本个体"
                   "所属类群（cydippid / lobate / cestid），而目级未定。"),
        "needs": "定目级（cydippid / lobate / cestid）后方可判断",
        "refs": ["Edgar", "Soto-Angel", "Pang", "Schnitzler"],
    },
    "_Y3A0153": {
        "contested": True,
        "eligible": None,
        "reason": ("门未定，阶段判断无意义。若为栉水母：Edgar 2022 主张直接发育，"
                   "Soto-Angel 2024 记载 lobate 渐变变态 → 术语本身在争议中。"
                   "若为水螅水母：PMC4415277 记载简单生活史由复杂生活史丢失阶段而来，"
                   "即存在阶段有无之别。两条路径都要求先定门。"),
        "needs": "定门（栉水母 vs 水螅水母）",
        "refs": ["Edgar", "Soto-Angel", "scyphozoan"],
    },
    "DSC_0933": {
        "contested": False,          # 确定结论，非争议
        "eligible": False,
        "reason": ("单细胞生物（Acantharia，放射虫门内异养原生生物），无后生动物发育序列，"
                   "排除依据充分。内骨骼为天青石而非硅质，但矿物成分无法从照片验证，"
                   "故属级判定置信仅 0.5 —— 置信低不等于有争议。"),
        "needs": None,
        "refs": ["Acantharia", "Zettler", "Decelle"],
    },
}


def now_iso():
    return DT.datetime.now(DT.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- claim 构造
_cid = [0]


def new_claim(subject, predicate, value, *, asserted_by, status,
              confidence=None, evidence=None, note=None, created_at=None,
              supersedes=None, superseded_by=None):
    """构造一条断言。字段语义见模块 docstring。"""
    _cid[0] += 1
    return {
        "claim_id": f"c{_cid[0]:04d}",
        "subject": subject,
        "predicate": predicate,
        "value": value,
        "confidence": confidence,
        "status": status,          # machine_read|draft|confirmed|contested|refuted|unresolved
        "asserted_by": asserted_by,  # exif|auto|ai|human|literature
        "evidence": evidence or {"references": [], "diagnostics": [], "note": None},
        "supersedes": supersedes,
        "superseded_by": superseded_by,
        "created_at": created_at or now_iso(),
        "reviewed_at": None,
        "note": note,
    }


# ---------------------------------------------------------------- 潜次推断
def infer_dives(images):
    """
    由 DateTimeOriginal 推断潜次分组。

    实测依据（108 张）：
      * 拍摄日 28 个，Lightroom 导出批次只有 5 个 —— 导出会把多个航次合并，
        故潜次必须由拍摄时间而非导出时间推断。
      * 导出批次与航次的对应关系清晰：2023:10:04 批次含 2017-03 与 2019-01~03 的片子，
        2023:10:13 + 2023:12:10 含 2019-12~2020-01，2023:07:17 含 2023-03，
        2024:03:19 含 2024-01。导出批次保留为 trip 线索，但不作为潜次边界。
      * 同日内存在 >40min 断点的有 19 天，说明单日可能含多潜。

    分组键 = (拍摄日期, 同日内的时段序号)。这是**推断值**，asserted_by=auto、
    status=machine_read，用户可在潜次面板改判（改判后生成 human 断言覆盖）。
    """
    by_day = defaultdict(list)
    for im in images:
        d = (im["exif"].get("DateTimeOriginal") or "")[:10]
        by_day[d].append(im)

    groups = {}
    for day, ims in by_day.items():
        if not day or day == "?":
            continue
        parsed = []
        for im in ims:
            t = im["exif"]["DateTimeOriginal"][11:19]
            try:
                parsed.append((DT.datetime.strptime(t, "%H:%M:%S"), im))
            except ValueError:
                parsed.append((None, im))
        parsed.sort(key=lambda x: (x[0] is None, x[0]))
        seg = 0
        prev = None
        for ts, im in parsed:
            if ts is not None and prev is not None:
                if (ts - prev).total_seconds() / 60 > DIVE_GAP_MIN:
                    seg += 1
            if ts is not None:
                prev = ts
            gid = f"{day}#{seg + 1}"
            groups[gid] = groups.get(gid, [])
            groups[gid].append(im["id"])

    # 航次：按拍摄年月聚类（导出批次另存为线索）
    trips = defaultdict(set)
    for gid, ids in groups.items():
        ym = gid[:7]
        trips[ym].update(ids)
    trip_of = {}
    for ym, ids in trips.items():
        for i in ids:
            trip_of[i] = ym

    dive_of = {}
    for gid, ids in groups.items():
        for i in ids:
            dive_of[i] = gid
    return dive_of, {k: sorted(v) for k, v in groups.items()}, trip_of


# ---------------------------------------------------------------- v5 转换
def convert_v5(rec, ref_index):
    """
    把 draft_annotations_v5.json 的一条 record 转成断言列表。
    保留全部原始信息，不做二次判断。所有 ai 断言 status=draft，等用户确认。
    """
    iid = rec["id"]
    subj = {"type": "image", "id": iid}
    claims = []
    tax = rec.get("taxonomy") or {}
    stage = rec.get("stage") or {}
    diag = rec.get("diagnostics") or []
    ref_ids = [ref_index[r["text"]] for r in (rec.get("references") or [])
               if r["text"] in ref_index]

    if tax.get("path"):
        claims.append(new_claim(
            subj, "taxon_is",
            {"path": tax["path"], "stop_reason": tax.get("stop_reason")},
            asserted_by="ai", status="draft",
            confidence=tax.get("confidence"),
            evidence={"references": ref_ids, "diagnostics": list(diag),
                      "note": stage.get("literature_note")},
            note="AI 鉴定，止于置信度最高层级；待人工确认",
        ))

    label = stage.get("discrete_label")
    # 争议登记优先于 record 级 status：栉水母类群的分期结论在文献层面就未定，
    # 若照搬 draft 会让「争议板」永远为空，而争议恰恰是研究工具最该暴露的东西。
    disp = DISPUTED.get(iid)
    stage_status = "contested" if (disp and disp["contested"]) else "draft"
    claims.append(new_claim(
        subj, "stage_is",
        {"discrete_label": label,
         "sort_key": stage.get("sort_key"),
         "indicator": stage.get("indicator"),
         "maturity_basis": stage.get("maturity_basis"),
         "continuum_note": stage.get("continuum_note"),
         "label_basis": stage.get("label_basis")},
        asserted_by="ai", status=stage_status,
        confidence=stage.get("confidence"),
        evidence={"references": ref_ids, "diagnostics": list(diag), "note": None},
        note=("文献离散分期 + 期内相对成熟度；显示序号由排序计算，插入新图只需改 sort_key，"
              "不需重标已有条目" if stage_status == "draft" else
              "分期结论在文献层面存在冲突，状态标 contested 而非 draft；"
              "正反两造证据见 sequence_eligible 断言"),
    ))

    # 序列资格断言：能否进入生长发育序列。显式登记，含正反证据与解决条件。
    if disp:
        elig_refs = []
        for kw in disp.get("refs", []):
            for text, rid in ref_index.items():
                if kw.lower() in text.lower() and rid not in elig_refs:
                    elig_refs.append(rid)
        claims.append(new_claim(
            subj, "sequence_eligible",
            {"eligible": disp["eligible"],
             "reason": disp["reason"],
             "needs": disp.get("needs"),
             "disputed": disp["contested"]},
            asserted_by="literature",
            status="contested" if disp["contested"] else "confirmed",
            confidence=None,
            evidence={"references": elig_refs, "diagnostics": [],
                      "note": ("eligible=None 表示未定：既不肯定也不否定。"
                               "解决条件见 needs 字段。")},
            note=("争议保留而非删改：相反证据并列，供你裁决"
                  if disp["contested"] else "确定结论：单细胞生物无后生动物发育序列"),
        ))

    if rec.get("series_hypothesis"):
        claims.append(new_claim(
            subj, "series_member_of",
            {"hypothesis": rec["series_hypothesis"], "confirmed": False},
            asserted_by="ai", status="unresolved",
            confidence=None,
            evidence={"references": [], "diagnostics": [], "note": None},
            note="同系假说，同种性未经确认；不得据此装配序列",
        ))

    if rec.get("reviewer_note"):
        claims.append(new_claim(
            subj, "reviewer_note",
            {"text": rec["reviewer_note"]},
            asserted_by="human", status="confirmed",
            evidence={"references": [], "diagnostics": [], "note": None},
        ))
    return claims


# ---------------------------------------------------------------- 主流程
def main():
    for p, why in ((DERIVED, "派生指标"), (V5, "v5 标注")):
        if not os.path.exists(p):
            sys.exit(f"ERROR: 找不到{why}：{p}")

    dv = json.load(open(DERIVED, encoding="utf-8"))
    v5 = json.load(open(V5, encoding="utf-8"))
    derived = {r["id"]: r for r in dv["records"]}
    print(f"[1/5] 载入派生指标 {len(derived)} 张；v5 标注 {len(v5['records'])} 条")

    # ---- 参考文献去重建档（38 条唯一）----
    ref_index, references = {}, []
    for rec in v5["records"]:
        for r in (rec.get("references") or []):
            t = r["text"]
            if t in ref_index:
                continue
            rid = f"ref_{len(references) + 1:03d}"
            ref_index[t] = rid
            references.append({
                "ref_id": rid,
                "text": t,
                "url": r.get("url"),
                "verify_level": r.get("verify_level"),   # opened|bibliographic|link_only
                "link_status": r.get("link_status"),     # opens_now|bot_walled|unreachable
                "http_code": r.get("http_code"),
                "link_note": r.get("link_note"),
            })
    print(f"[2/5] 参考文献建档 {len(references)} 条（去重后）")
    vl = Counter(r["verify_level"] for r in references)
    ls = Counter(r["link_status"] for r in references)
    print(f"      核验层级 {dict(vl)}")
    print(f"      链接状态 {dict(ls)}")

    # ---- 潜次推断 ----
    img_list = [{"id": i, "exif": r["exif"]} for i, r in derived.items()]
    dive_of, dive_groups, trip_of = infer_dives(img_list)
    print(f"[3/5] 潜次推断：{len(dive_groups)} 个潜次，"
          f"{len(set(trip_of.values()))} 个航次")

    # ---- 逐图建断言 ----
    v5_by_id = {r["id"]: r for r in v5["records"]}
    images = []
    n_unresolved_taxon = 0
    for iid, d in sorted(derived.items()):
        ex = d["exif"]
        col = d["color"] or {}
        subj = {"type": "image", "id": iid}
        claims = []

        # exif 断言：机器事实，直接 machine_read
        claims.append(new_claim(
            subj, "capture_context",
            {"make": ex.get("Make"), "model": ex.get("Model"),
             "software": ex.get("Software"),
             "datetime_original": ex.get("DateTimeOriginal"),
             "datetime_edit": ex.get("DateTime"),
             "exposure": ex.get("ExposureTime"),
             "aperture_av": ex.get("ApertureValue"),
             "iso": ex.get("ISOSpeedRatings"),
             "focal_35mm": ex.get("FocalLength35mm"),
             "artist": ex.get("Artist"), "copyright": ex.get("Copyright")},
            asserted_by="exif", status="machine_read",
            note=("DateTimeOriginal 为真实拍摄时间（108/108 覆盖）；DateTime 是 "
                  "Lightroom 导出时间，二者不可混用。曾误报「拍摄时间不可恢复」，"
                  "错因是 exif_transpose() 返回的对象无 _getexif 方法，已修。"),
        ))

        # auto 断言：可复算派生，不含研究结论
        claims.append(new_claim(
            subj, "auto_derived",
            {"orig_w": d["source"]["orig_w"], "orig_h": d["source"]["orig_h"],
             "aspect": d["source"]["aspect"],
             "subject_box": d["asset"]["box_norm"],
             "crop_method": d["asset"]["crop_method"],
             "water_frac": col.get("water_frac"),
             "tissue_frac": col.get("tissue_frac"),
             "pigment_frac": col.get("pigment_frac"),
             "pigment_detected": (col.get("pigment") or {}).get("detected"),
             "pigment_rgb": (col.get("pigment") or {}).get("rgb"),
             "pigment_hue_median": (col.get("pigment") or {}).get("hue_median"),
             "tissue_rgb": col.get("tissue_rgb")},
            asserted_by="auto", status="machine_read",
            note=("色素细胞颜色具分类学意义（如船蛸的橙红色素环）。"
                  "三分类模型见 build_assets.py；占比不显著时如实报未检出，不硬给色值。"),
        ))

        # 潜次断言（推断值，可被人工覆盖）
        if iid in dive_of:
            claims.append(new_claim(
                subj, "dive_is",
                {"dive_id": dive_of[iid], "trip": trip_of.get(iid),
                 "depth_m": None, "water_temp_c": None, "location": None},
                asserted_by="auto", status="machine_read",
                note=("由 DateTimeOriginal 推断（同日内 >40min 断点切分）。"
                      "深度/水温/地点为人工字段，支持按潜次批量填。"),
            ))

        # 分类断言：有 v5 标注则转换，否则显式记为未鉴定
        if iid in v5_by_id:
            claims.extend(convert_v5(v5_by_id[iid], ref_index))
        else:
            n_unresolved_taxon += 1
            claims.append(new_claim(
                subj, "taxon_is", None,
                asserted_by=None, status="unresolved",
                note="尚未鉴定。缺口检测据此统计。",
            ))
            claims.append(new_claim(
                subj, "stage_is", None,
                asserted_by=None, status="unresolved",
                note="尚未分期。",
            ))

        images.append({
            "image_id": iid,
            "asset": {"thumb": d["asset"]["thumb"], "detail": d["asset"]["detail"],
                      "detail_w": d["asset"]["detail_w"],
                      "detail_h": d["asset"]["detail_h"],
                      "thumb_w": d["asset"]["thumb_w"],
                      "thumb_h": d["asset"]["thumb_h"],
                      # v2 新增：检查器改用整帧层（用户要求完整展示，不要主体裁剪）。
                      # full/full_w/full_h 在 derived.json 存在时才携带；aspect 供
                      # 前端校验「整帧未裁」（比例应等于原图比例）。
                      "full": d["asset"].get("full"),
                      "full_w": d["asset"].get("full_w"),
                      "full_h": d["asset"].get("full_h"),
                      "aspect": d["source"].get("aspect"),
                      # 主体框（归一化）：检查器在整帧图上叠虚线框，
                      # 此前漏传导致叠加层永不渲染。
                      "box_norm": d["asset"].get("box_norm")},
            "source_path": d["source"]["path"],
            "color_label": d.get("color_label"),
            "dive_id": dive_of.get(iid),
            "trip": trip_of.get(iid),
            "annotated": iid in v5_by_id,
            "claims": claims,
        })

    print(f"[4/5] 建图 {len(images)} 张；其中已标注 {len(v5_by_id)} 张，"
          f"未鉴定 {n_unresolved_taxon} 张")

    # ---- 修正链：固化四次被推翻的判断 ----
    revision_log = [
        {
            "rev": "r1", "date": "2026-10-26",
            "image_id": "DSC_0077",
            "predicate": "taxon_is",
            "superseded_value": "鱼类幼体（fish larva）",
            "corrected_value": "头足纲 八腕目（船蛸 Argonauta 雌体）",
            "corrected_by": "human",
            "root_cause": ("依据 560px 缩略图鉴定；壳肋、吸盘列等诊断特征在该分辨率下不可见。"),
            "method_change": ("改为从原图（最大 5504×3668）按主体框裁剪后鉴定，"
                              "禁止使用展示层或缩略图做分类判断。"),
        },
        {
            "rev": "r2", "date": "2026-10-26",
            "image_id": None,
            "predicate": "reference",
            "superseded_value": "Howes 2014 DOI 10.1093/plankt/fbt124",
            "corrected_value": "撤回该 DOI，仅保留实际检索到的 URL",
            "corrected_by": "human",
            "root_cause": ("该 DOI 从未出现在任何检索结果中，系按 URL 规律推断而成，属编造。"),
            "method_change": ("建立三级核验层级 opened / bibliographic / link_only，"
                              "区分「我确实打开读过」与「仅确认书目存在」。"),
        },
        {
            "rev": "r3", "date": "2026-10-26",
            "image_id": "DSC_2999",
            "predicate": "reference_claim",
            "superseded_value": "「多数科仅有 zoea I 描述」（归于 Marco-Herrero）",
            "corrected_value": "「Grapsidae 科内资料多止于 zoea I」",
            "corrected_by": "literature",
            "root_cause": "过度外推，把单一科的情况写成多数科；并漏写期刊名（Taxonomy）。",
            "method_change": "引用陈述必须逐字对齐原文范围限定，不得扩大适用域。",
        },
        {
            "rev": "r4", "date": "2026-10-26",
            "image_id": None,
            "predicate": "sequence_eligibility",
            "superseded_value": "栉水母直接发育、无幼虫期 → 排除出发育序列",
            "corrected_value": "能否进序列待判，取决于所属类群（status=contested）",
            "corrected_by": "literature",
            "root_cause": ("仅依据 Edgar 2022 (PNAS) 支持直接发育即下结论；"
                           "未检索到 Soto-Angel 2024 记录叶栉水母以 cydippid 孵化并渐变态"
                           "（触手吸收、新结构发育），学界正在争论是否废除 larva/metamorphosis 术语。"),
            "method_change": ("单一来源不足以支撑排除性结论；结论相反的证据必须并列保留，"
                              "断言状态标 contested 而非直接删改。"),
        },
        {
            "rev": "r5", "date": "2026-10-27",
            "image_id": None,
            "predicate": "exif_availability",
            "superseded_value": "镜头/GPS/曝光/DateTimeOriginal 均为 0/108，拍摄时间不可恢复",
            "corrected_value": ("DateTimeOriginal、曝光、光圈、ISO 均 108/108；"
                                "等效焦距 88/108；仍缺镜头型号与 GPS"),
            "corrected_by": "auto",
            "root_cause": ("读取代码在 ImageOps.exif_transpose() 之后调用 _getexif()，"
                           "而该方法属 JpegImageFile 插件、transpose 后的通用 Image 对象没有它，"
                           "108 张全部走异常分支返回空字典。"),
            "method_change": ("「工具读不到」不得报为「数据不存在」；"
                              "字段缺失必须先用第二种方法交叉验证。"),
        },
        {
            "rev": "r6", "date": "2026-10-27",
            "image_id": None,
            "predicate": "auto_derived.color",
            "superseded_value": "单一 dominant_rgb 主色调（59/108 判为「蓝」，15% 实为照亮的水体）",
            "corrected_value": "三分类 water/tissue/pigment，色素只认暖色相且需占比显著",
            "corrected_by": "auto",
            "root_cause": ("① 直方图众数落在水体暗尾上：DSC_2999 框内 p25=70/p50=114 整体偏亮，"
                           "却输出亮度 67 的暗蓝。② RGB 量化到 4096 桶过细，"
                           "dominant_share 普遍仅 5-10%，「主色」基本是噪声。"
                           "③ 用全图暗部众数做水体阈值时，框外纯黑把基线压到 0，"
                           "阈值塌到下限，107/108 张「检出色素」，毫无区分度。"),
            "method_change": ("水体阈值改取主体框内亮度 p25 再上浮；"
                              "色素占组织比 <2% 时报「未检出显著色素」而非硬给色值。"),
        },
    ]

    payload = {
        "schema": "plankton-workbench/claims/v1",
        "built_at": now_iso(),
        "policy": dict(v5.get("policy") or {}),
        "model_note": (
            "claim-centric：一行一条断言，而非一图一堆字段。每条断言带 "
            "asserted_by（谁说的）、status（可信到什么程度）、evidence（凭什么）、"
            "superseded_by（被谁推翻）。研究工具的价值在于三个月后仍能判断哪些结论可信、"
            "哪些被推翻过。"),
        "counts": {
            "images": len(images),
            "annotated": len(v5_by_id),
            "unresolved_taxon": n_unresolved_taxon,
            "references": len(references),
            "dives": len(dive_groups),
            "trips": len(set(trip_of.values())),
            "revisions": len(revision_log),
        },
        "dive_groups": {k: v for k, v in sorted(dive_groups.items())},
        "references": references,
        "revision_log": revision_log,
        "source_notes": {
            "v5_revision_note": v5.get("revision_note"),
            "v5_verification_note": v5.get("verification_note"),
        },
        "images": images,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    nc = sum(len(i["claims"]) for i in images)
    sc = Counter(c["status"] for i in images for c in i["claims"])
    pc = Counter(c["predicate"] for i in images for c in i["claims"])
    print(f"[5/5] 写入 {OUT}")
    print(f"      断言总数 {nc} 条")
    print(f"      按状态 {dict(sc)}")
    print(f"      按谓词 {dict(pc)}")
    print(f"      修正链 {len(revision_log)} 条")
    sz = os.path.getsize(OUT)
    print(f"      文件大小 {sz / 1024:.0f} KB")


if __name__ == "__main__":
    main()
