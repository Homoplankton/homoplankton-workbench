#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ingest_feedback.py — 把用户在工作台里的裁决判决摄取回 claims，并沉淀进错题集/锚点库/准确率台账。

输入：data/decisions/*.json（工作台「保存」导出的 workbench_decisions.json 格式）
      每个文件含 overlay: { image_id: {verdict, taxonomy_path, stage_label, note, no_sequence, _at} }

产出（全部写入项目 data/，不触碰照片与原始图层）：
  1. claims.json      —— 用户判决覆盖 AI 草案：confirm→confirmed/human；correct→改写并留推翻记录；reject→refuted
  2. revision_log     —— 每条 correct/reject 生成一条「被推翻的判断」，含用户 note（漏看了什么）
  3. data/error_book.json    —— 错题集：我的草案 vs 用户纠正 vs 用户指出的漏看特征 + 失败模式归类
  4. data/anchors.json       —— 锚点库：已确认图按分类路径归档，未来批次强制先比对锚点
  5. data/accuracy_ledger.json —— 准确率台账：按批次/分类层级/失败模式统计，让提升可测量

设计纪律（与 larval-taxonomy 技能一致）：
  - 人工判决永远压过 AI 草案，且 AI 草案不得覆盖人工判决（status=confirmed/asserted_by=human）
  - 被推翻的旧值保留在 revision_log，不删改历史
  - 失败模式归类只做「建议」，标注 needs_human_review，不假装自动判定准确
"""
import json, os, glob, datetime, re, shutil, sys

WB = "/Users/jialingcai/Documents/qwen-agent/NZKKxizmz2/default/plankton-workbench"
DATA = os.path.join(WB, "data")
CJ = os.path.join(DATA, "claims.json")
DEC_DIR = os.path.join(DATA, "decisions")
ERROR_BOOK = os.path.join(DATA, "error_book.json")
ANCHORS = os.path.join(DATA, "anchors.json")
LEDGER = os.path.join(DATA, "accuracy_ledger.json")
NOW = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
TODAY = NOW[:10]

# 失败模式关键词启发（只作建议，标 needs_human_review）
FAILURE_MODE_HINTS = [
    ("误读结构归属", ["当成", "误读", "其实是", "把.*当", "看错", "错认"]),
    ("漏看特征", ["漏看", "没看到", "忽略了", "没注意", "应该看到", "本该", " missed", "missed"]),
    ("文献门未过", ["文献", "查一下", "没查", "引用", "来源", "literature", "reference"]),
    ("分期混淆", ["分期", "期", "stage", "zoea", "mysis", "veliger", "paralarva", "幼体期", "变态"]),
    ("趋同区未降档", ["趋同", "像.*但", "convergen", "混淆", "competence"]),
    ("过度自信/未停层", ["硬凑", "过度", "应该停", "不该判", "置信", "overclaim", "stop"]),
    ("色素/眼点误弃", ["色素", "眼点", "pigment", "eyespot", "当噪声"]),
    ("光学伪影误判", ["虹彩", "闪光", "眩光", "栉板", "iridescen", "artifact"]),
]
def classify_failure(note):
    """多标签：一条备注可能同时是多种失败模式（如"把背鳍当成皮瓣、漏看分节"
    既是误读结构归属又是漏看特征）。返回命中列表（可能为空）。
    关键词匹配只是**建议**，一律标 needs_human_review，不假装自动判定准确。"""
    if not note:
        return []
    hits = []
    for mode, kws in FAILURE_MODE_HINTS:
        for kw in kws:
            if re.search(kw, note, re.I):
                hits.append(mode)
                break
    return hits

def load(p, default):
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else default

def save(p, obj):
    json.dump(obj, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

def main():
    claims = load(CJ, None)
    if claims is None:
        print("claims.json 不存在"); sys.exit(1)
    by_id = {im["image_id"]: im for im in claims["images"]}

    error_book = load(ERROR_BOOK, {"schema": "plankton-workbench/error-book/v1", "cases": []})
    anchors = load(ANCHORS, {"schema": "plankton-workbench/anchors/v1", "by_taxon": {}, "confirmed_ids": []})
    ledger = load(LEDGER, {"schema": "plankton-workbench/accuracy-ledger/v1", "batches": []})

    # 收集所有待摄取的判决文件
    os.makedirs(DEC_DIR, exist_ok=True)
    files = sorted(glob.glob(os.path.join(DEC_DIR, "*.json")))
    if not files:
        print(f"无判决文件。请把工作台「保存」导出的 JSON 放进：{DEC_DIR}")
        return

    rev = claims.setdefault("revision_log", [])
    def next_cid():
        mx = 0
        for im in claims["images"]:
            for c in im["claims"]:
                try: mx = max(mx, int(c["claim_id"][1:]))
                except: pass
        return mx
    CID = next_cid()

    batch = {"batch_id": f"batch-{TODAY}-{len(ledger['batches'])+1}", "at": NOW,
             "source_files": [os.path.basename(f) for f in files],
             "n_confirm": 0, "n_correct": 0, "n_reject": 0, "n_unknown_img": 0,
             "by_rank": {}, "failure_modes": {}}
    ingested_ids = set()

    for fp in files:
        dec = load(fp, {})
        overlay = dec.get("overlay") or {}
        for iid, o in overlay.items():
            verdict = o.get("verdict")
            if not verdict:
                continue
            im = by_id.get(iid)
            if not im:
                batch["n_unknown_img"] += 1
                print(f"  ⚠ 判决指向未知图 {iid}（可能已被移除），跳过")
                continue
            ingested_ids.add(iid)
            tax = next((c for c in im["claims"] if c["predicate"] == "taxon_is"), None)
            stg = next((c for c in im["claims"] if c["predicate"] == "stage_is"), None)
            note = (o.get("note") or "").strip()
            my_path = (tax or {}).get("value", {}).get("path") if tax else None
            my_stage = (stg or {}).get("value", {}).get("discrete_label") if stg else None
            human_path = [s.strip() for s in (o.get("taxonomy_path") or "").split("/") if s.strip()] or None
            human_stage = (o.get("stage_label") or "").strip() or None

            if verdict == "confirm":
                batch["n_confirm"] += 1
                # 认可：把我的草案升格为人工确认（不改值，只改归属与状态）
                if tax:
                    tax["status"] = "confirmed"; tax["asserted_by"] = "human"
                    tax["reviewed_at"] = NOW
                    if note:
                        tax.setdefault("evidence", {}).setdefault("diagnostics", [])
                        tax["evidence"]["note"] = (tax["evidence"].get("note") or "") + f" ｜ 人工认可：{note}"
                if stg and stg.get("value"):
                    stg["status"] = "confirmed"; stg["asserted_by"] = "human"; stg["reviewed_at"] = NOW
                # 进锚点库
                if my_path:
                    key = " > ".join(my_path)
                    anchors["by_taxon"].setdefault(key, [])
                    if iid not in [a["image_id"] for a in anchors["by_taxon"][key]]:
                        anchors["by_taxon"][key].append({"image_id": iid, "stage": my_stage, "confirmed_at": NOW})
                    if iid not in anchors["confirmed_ids"]:
                        anchors["confirmed_ids"].append(iid)
                _rank_count(batch, my_path, "confirm")

            elif verdict == "correct":
                batch["n_correct"] += 1
                # ⚠ 先冻结我的原草案字符串，再覆盖——否则错题集会把我的人工纠正值误记成「我的草案」，
                #   失去「我错在哪」的意义（本 bug 在首次自查时抓到）。
                my_draft_path_str = " > ".join(my_path or []) if my_path else None
                # 修改：用人工值覆盖，留推翻记录
                if tax and human_path:
                    old = my_draft_path_str or "（空）"
                    new = " > ".join(human_path)
                    tax["value"] = {"path": human_path, "stop_reason": (tax.get("value") or {}).get("stop_reason")}
                    tax["status"] = "confirmed"; tax["asserted_by"] = "human"; tax["reviewed_at"] = NOW
                    if note:
                        tax.setdefault("evidence", {})["note"] = f"人工纠正：{note}"
                    rev.append({"rev": f"r{len(rev)+1}", "date": TODAY, "image_id": iid,
                        "predicate": "taxon_is", "superseded_value": old or "（空）",
                        "corrected_value": new, "corrected_by": "human",
                        "root_cause": note or "用户裁决纠正", "method_change": "用户判决覆盖 AI 草案；旧值留痕。"})
                    # 锚点库用纠正后的路径
                    key = new
                    anchors["by_taxon"].setdefault(key, [])
                    if iid not in [a["image_id"] for a in anchors["by_taxon"][key]]:
                        anchors["by_taxon"][key].append({"image_id": iid, "stage": human_stage or my_stage, "confirmed_at": NOW})
                    if iid not in anchors["confirmed_ids"]:
                        anchors["confirmed_ids"].append(iid)
                    my_path = human_path  # 后续台账按纠正后路径计
                if stg and human_stage:
                    stg["value"] = dict(stg.get("value") or {}, discrete_label=human_stage)
                    stg["status"] = "confirmed"; stg["asserted_by"] = "human"; stg["reviewed_at"] = NOW
                # 错题集
                fms = classify_failure(note)
                error_book["cases"].append({
                    "case_id": f"eb{len(error_book['cases'])+1:03d}", "image_id": iid, "at": NOW,
                    "my_draft_taxon": my_draft_path_str,
                    "my_draft_stage": my_stage,
                    "human_taxon": " > ".join(human_path) if human_path else None,
                    "human_stage": human_stage,
                    "human_note": note or None,
                    "missed_feature": note if note else None,
                    "failure_mode_suggested": fms,
                    "failure_mode_needs_human_review": True,
                    "verdict": "correct",
                })
                for fm in fms:
                    batch["failure_modes"][fm] = batch["failure_modes"].get(fm, 0) + 1
                _rank_count(batch, human_path, "correct")

            elif verdict == "reject":
                batch["n_reject"] += 1
                if tax:
                    tax["status"] = "refuted"; tax["asserted_by"] = "human"; tax["reviewed_at"] = NOW
                    rev.append({"rev": f"r{len(rev)+1}", "date": TODAY, "image_id": iid,
                        "predicate": "taxon_is", "superseded_value": " > ".join(my_path or []) or "（空）",
                        "corrected_value": "（否决，未给替代）", "corrected_by": "human",
                        "root_cause": note or "用户否决", "method_change": "用户否决 AI 草案。"})
                fms = classify_failure(note)
                error_book["cases"].append({
                    "case_id": f"eb{len(error_book['cases'])+1:03d}", "image_id": iid, "at": NOW,
                    "my_draft_taxon": " > ".join(my_path or []) if my_path else None,
                    "my_draft_stage": my_stage, "human_taxon": None, "human_stage": None,
                    "human_note": note or None, "missed_feature": note if note else None,
                    "failure_mode_suggested": fms, "failure_mode_needs_human_review": True,
                    "verdict": "reject",
                })
                for fm in fms:
                    batch["failure_modes"][fm] = batch["failure_modes"].get(fm, 0) + 1
                _rank_count(batch, my_path, "reject")

    # 台账
    total = batch["n_confirm"] + batch["n_correct"] + batch["n_reject"]
    batch["n_total"] = total
    batch["confirm_rate"] = round(batch["n_confirm"] / total, 3) if total else None
    ledger["batches"].append(batch)

    # 写回
    bak = CJ + f".bak-ingest-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(CJ, bak)
    claims["built_at"] = NOW
    claims.setdefault("counts", {})["human_confirmed"] = len(anchors["confirmed_ids"])
    save(CJ, claims)
    save(ERROR_BOOK, error_book)
    save(ANCHORS, anchors)
    save(LEDGER, ledger)

    # 摄取过的判决文件归档，避免重复摄取
    arch = os.path.join(DEC_DIR, "_ingested")
    os.makedirs(arch, exist_ok=True)
    for fp in files:
        shutil.move(fp, os.path.join(arch, os.path.basename(fp) + f".{datetime.datetime.now().strftime('%H%M%S')}"))

    print(f"备份: {bak}")
    print(f"摄取判决: {total} 条（confirm {batch['n_confirm']} / correct {batch['n_correct']} / reject {batch['n_reject']}）")
    print(f"未知图跳过: {batch['n_unknown_img']}")
    print(f"认可率: {batch['confirm_rate']}")
    print(f"错题集累计: {len(error_book['cases'])} 条")
    print(f"锚点库: {len(anchors['confirmed_ids'])} 张已确认，覆盖 {len(anchors['by_taxon'])} 个分类路径")
    print(f"失败模式分布: {batch['failure_modes']}")
    print("判决文件已归档到 data/decisions/_ingested/")

def _rank_count(batch, path, verdict):
    if not path: return
    # 按路径最深层级记一次（目级/科级/属级…粗分）
    depth = len(path)
    rank = {1: "门/纲级", 2: "目级", 3: "科级", 4: "属级", 5: "种级"}.get(depth, f"{depth}层")
    batch["by_rank"].setdefault(rank, {"confirm": 0, "correct": 0, "reject": 0})
    batch["by_rank"][rank][verdict] += 1

if __name__ == "__main__":
    main()
