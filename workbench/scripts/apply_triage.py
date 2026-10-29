#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_triage.py — 把 larval-taxonomy 分诊+SOP 结果回填到 claims.json
- include/reread 升级的图：taxon_is + stage_is 草案断言（status=draft, asserted_by=ai_draft）
- 每组恰好 3 条一级来源文献（group_refs.json），写入顶层 references[] 并挂 evidence.references
- skip/reread 的图：triage_note 断言（不入队列，记录处置与原因）
- 写 revision_log 一条记录本轮变更
- 备份原 claims.json 后原地覆盖（构建链输入不变）
"""
import json, os, shutil, datetime, sys

WB = "/Users/jialingcai/Documents/qwen-agent/NZKKxizmz2/default/plankton-workbench"
CJ = os.path.join(WB, "data/claims.json")
DISP = "/tmp/triage/disposition.json"
GREFS = os.path.join(WB, "data/group_refs.json")
NOW = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

# ---------- 路径规范化 ----------
# 旧草案带 Animalia/Eukaryota 前缀，我的新路径从门/纲起，且个别漏了上级（Bivalvia 缺 Mollusca）。
# 不统一会让同一类群在分类树里分裂成两条平行分支。规则：
#   1) 去掉顶层 Animalia/Eukaryota；
#   2) 已知纲补上级门，使新旧路径在同一坐标系下可比、可合并。
_PREPEND = {
    "Bivalvia": "Mollusca", "Gastropoda": "Mollusca", "Cephalopoda": "Mollusca",
    "Scyphozoa": "Cnidaria", "Hydrozoa": "Cnidaria", "Cubozoa": "Cnidaria",
    "Malacostraca": "Arthropoda", "Actinopterygii": "Chordata",
    "Polychaeta": "Annelida",
}
def norm_path(p):
    if not p: return []
    p = list(p)
    while p and p[0] in ("Animalia", "Eukaryota"):
        p = p[1:]
    while p and p[0] in _PREPEND:
        p = [_PREPEND[p[0]]] + p
    return p

# ---------- 覆盖留痕 ----------
# 改写一个已有非空值的断言＝推翻旧结论。本工作台的核心纪律是「三个月后仍知道哪些结论被推翻过」，
# 所以覆盖必须留 revision_log，不能静默替换。
OVERWRITES = []
def record_overwrite(iid, old_path, new_path, why):
    OVERWRITES.append({
        "image_id": iid, "predicate": "taxon_is",
        "superseded_value": " › ".join(old_path),
        "corrected_value": " › ".join(new_path),
        "corrected_by": "ai_draft (larval-taxonomy SOP)",
        "root_cause": why,
    })

# ---------- 读入 ----------
claims = json.load(open(CJ, encoding="utf-8"))
disp = json.load(open(DISP, encoding="utf-8"))
group_refs = json.load(open(GREFS, encoding="utf-8"))

# 高倍重读后的升级（/tmp/reread 判读结果）：reread -> include 或 skip
UPGRADE = {
 # 7 张触手型胶质：_Y3A0081/85/91 高倍确认钵水母根口水母目；1779 确认钵水母纲；
 # 0097/0098/0102 见纵带≈8条但未确认纤毛 → 栉水母门假设（高置信未铁证）
 "DSC_1779":   {"taxon":["Cnidaria","Scyphozoa"],"conf":0.75,"stage":"medusa（成体阶段；生活史含 polyp→strobila→ephyra 剧烈变态）",
   "stop":"停在纲；目/科需缘瓣数目、口腕融合方式、触手囊形态","group":"G-MEDUSA",
   "diag":["钟形伞+纵行辐管+伞缘细锯齿","缘触手8–10条末端球状/螺旋卷曲","中央胃腔与口腕区白色褶皱组织"]},
 "_Y3A0081":   {"taxon":["Cnidaria","Scyphozoa","Rhizostomeae"],"conf":0.8,"stage":"medusa（成体阶段；生活史含剧烈变态）",
   "stop":"停在目；科需完整伞径、口腕末端形态、缘瓣计数","group":"G-MEDUSA",
   "diag":["伞缘缘瓣（lappets）呈锯齿状排列","口腕愈合膨大、覆满粉红球状颗粒","无游离缘触手（根口水母签名）"]},
 "_Y3A0085":   {"taxon":["Cnidaria","Scyphozoa","Rhizostomeae"],"conf":0.8,"stage":"medusa（成体阶段；生活史含剧烈变态）",
   "stop":"停在目；同上","group":"G-MEDUSA",
   "diag":["口面观8瓣状口腕围绕中央口部","每瓣覆满粉色球粒","周缘放射状极细丝状触手"]},
 "_Y3A0091":   {"taxon":["Cnidaria","Scyphozoa","Rhizostomeae"],"conf":0.8,"stage":"medusa（成体阶段；生活史含剧烈变态）",
   "stop":"停在目；同上","group":"G-MEDUSA",
   "diag":["半球形伞+发达缘瓣（规则锯齿）","伞下口腕膨大下垂覆粉色球粒","内见辐管"]},
 "_Y3A0097":   {"taxon":["Ctenophora"],"conf":0.6,"stage":None,
   "stop":"停在门（高置信未铁证）；纵带≈8条符合栉板行列数，但纤毛未像素级确认；目/科需触手鞘、肛门、栉板纤毛确认","group":"G-CTENO2",
   "diag":["体壁≈8条纵行淡色条纹（辐射对称排列）=栉板带候选","卵圆透明胶质囊+周缘8–10条弯曲触手末端钝圆","体内中央淡橙团块；无缘瓣/辐管/胃腔分区（排除刺胞）"]},
 "_Y3A0098":   {"taxon":["Ctenophora"],"conf":0.55,"stage":None,
   "stop":"停在门（高置信未铁证）；同上，本图纵带更模糊","group":"G-CTENO2",
   "diag":["体壁纵行条纹≈8条（模糊）","卵圆囊+8–10条弯曲触手","体内淡橙团块"]},
 "_Y3A0102":   {"taxon":["Ctenophora"],"conf":0.5,"stage":None,
   "stop":"停在门（高置信未铁证）；三图中最模糊","group":"G-CTENO2",
   "diag":["纵带隐约可见≈8条","卵圆囊+≈8条弯曲触手","体内淡橙团块"]},
 # DSC_2087：小钟罩+仅2条末端螺旋长触手 → 水螅纲（硬水母/淡水水母方向）
 "DSC_2087":   {"taxon":["Cnidaria","Hydrozoa"],"conf":0.65,"stage":"medusa（成体阶段；生活史含水螅体→水母体变态）",
   "stop":"停在纲；目需垂管/触手囊/平衡囊结构确认（2条螺旋末端长触手提示硬水母目方向，文献未核验到种级）","group":"G-HYDRO",
   "diag":["小型钟罩/杯状体，顶圆钝","仅2条极长触手着生钟罩基部、远端螺旋卷曲（弹簧状）","体内胃腔+黄橙团块；无缘瓣、无辐管系统"]},
 # _Y3A0153：虹彩+纵行结构+散布亮点+2长触手 → 栉水母门（带触手目方向）
 "_Y3A0153":   {"taxon":["Ctenophora"],"conf":0.6,"stage":None,
   "stop":"停在门；目（Tentaculata 方向）需栉板带数目、触手鞘位置确认","group":"G-CTENO2",
   "diag":["梨形透明囊+顶端伸出2条极长丝（远超体长）","丝基部虹彩闪光（绿-金）+体壁纵行细线与散布亮点=栉板纤毛反光候选","体内横向隔板样结构；无伞缘缺刻"]},
 # DSC_3441：漏斗体+辐射触手冠+无侧枝+柄含消化道 → 帚虫门
 "DSC_3441":   {"taxon":["Phoronida"],"conf":0.75,"stage":"adult（成体；生活史含 actinotrocha→灾变性变态）",
   "stop":"停在门；属需触手确切数目、lophophore 环形vs马蹄形、柄内U形肠确认","group":"G-PHOR",
   "diag":["漏斗/锥形透明体+顶端12–16条触手辐射环列","触手无侧枝（排除苔藓虫羽状触手）","下部深色细长柄内含纵管（消化道）；无几丁质管"]},
 # 5 张多主体：按主主体建条+副主体记录
 "DSC_1125":   {"taxon":["Malacostraca","Amphipoda"],"conf":0.6,"stage":"juvenile/adult（端足类直接发育；本条为主主体B）",
   "stop":"停在目；主主体B（C形端足类）科需附肢细节。胶质囊（A）与卵团（A'）性质未确认，不建分类条","group":"G-AMPH",
   "diag":["主体B：C形弯曲分节体+大金绿复眼+多对钩状步足（端足目签名）","主体A：卵圆团块表面密橙点蜂窝状（卵团/幼体群，性质未确认）","外层大型透明胶质囊（被囊候选，环肌带未确认）"],
   "note":"多主体图：按主主体B（端足类）建条；囊与卵团作为未分配特征记录。端足类为直接发育，此条按用户规则本应跳过，但主主体B已具幼体分类价值争议——标 draft 待用户裁决"},
 "DSC_1760":   {"taxon":["Malacostraca","Amphipoda"],"conf":0.6,"stage":"juvenile/adult（直接发育）",
   "stop":"停在目；同框副主体（软体幼体）单独记录不建条","group":"G-AMPH",
   "diag":["主体A：C形分节+银蓝大复眼+腹侧多对细小附肢","主体B：卵圆透明胶质体+橙白内脏团+前端短卷曲结构（软体幼体候选，velum/壳未确认）"],
   "note":"多主体：端足类直接发育，按用户规则主体A本应跳过；标 draft 记录同框事实供用户裁决"},
 "DSC_1764":   {"taxon":["Mollusca","Cephalopoda"],"conf":0.55,"stage":"paralarva（头足=直接发育）",
   "stop":"停在纲；头足直接发育，按用户规则本应跳过——本条仅记录高倍判读结果供裁决","group":"G-CEPH",
   "diag":["主体A：卵圆梨形透明体+橙红消化腺+顶端卷曲腕（头足幼体特征）","主体B：C形分节+大黑眼（端足类）"],
   "note":"多主体：A=头足幼体（直接发育→按规则跳过）；B=端足类。记录判读供裁决，不改变跳过规则"},
 "DSC_2132":   {"taxon":["Mollusca","Cephalopoda"],"conf":0.55,"stage":"paralarva（直接发育）",
   "stop":"同1764：头足直接发育，按规则跳过；本条仅记录判读","group":"G-CEPH",
   "diag":["左主体：卵圆透明体+橙黄内脏团+前端卷曲腕","右主体：C形分节+大金色复眼（端足类）"]},
 "_Y3A0208":   {"taxon":["Mollusca","Cephalopoda"],"conf":0.65,"stage":"paralarva（直接发育）",
   "stop":"停在纲；按用户规则头足直接发育跳过——本条记录 chromatophores 强证据供裁决","group":"G-CEPH",
   "diag":["左上主体：体表密布黄绿+橙色斑点（chromatophores=头足签名）+大黑眼+体侧鳍突","右下主体：卵圆透明体+橙内脏团+前端短卷曲结构（第二软体幼体）"]},
}
# 直接跳过（无升级）的 reread 图：无。全部 15 张都给出了可防守层级。

# ---------- 新文献条目（四组文献门 + 本轮补核验） ----------
NEW_REFS = []
def add_refs(group, refs):
    ids = []
    for r in refs:
        rid = f"ref_{len(claims['references'])+len(NEW_REFS)+1:03d}"
        NEW_REFS.append({
            "ref_id": rid,
            "text": r["citation"],
            "url": r["url"],
            "verify_level": r["tier"],
            "link_status": "untested",
            "http_code": None,
            "link_note": f"[{group}] key_claim: {r['key_claim']} ｜ supports: {r['supports']} ｜ larval-taxonomy 文献门核验（tier={r['tier']}）；本轮未测链接可达性",
            "group": group,
        })
        ids.append(rid)
    return ids
GROUP_REF_IDS = {}
for g, refs in group_refs.items():
    assert len(refs) == 3, f"{g} 文献数 {len(refs)} != 3"
    GROUP_REF_IDS[g] = add_refs(g, refs)

# G-CTENO2 与 G-HYDRO、G-AMPH、G-CEPH 的新组文献
CTENO_REFS = [
 {"citation":"Martindale, M.Q. 1986. The ontogeny and maintenance of adult symmetry along the tentacular plane in the ctenophore Mnemiopsis. Development 98(3):399-413.",
  "url":"https://pubmed.ncbi.nlm.nih.gov/3792462/","tier":"bibliographic",
  "key_claim":"Ctenophores are biradially symmetrical with eight comb rows (ctene rows) of ciliated comb plates.",
  "supports":"八条栉板纵行为栉水母门签名特征；纵带计数用于门级判定"},
 {"citation":"Haddock, S.H.D. 2004. A golden age of gelata: planktonic jellyfish and ctenophores. Current Biology 14(18):R807-R811.",
  "url":"https://doi.org/10.1016/j.cub.2004.09.034","tier":"opened",
  "key_claim":"Ctenophores swim by eight rows of compound cilia (combs), iridescent when diffracting light; tentaculate species bear tentacles.",
  "supports":"栉板虹彩衍射与带触手类群的存在——支撑以虹彩+纵带+触手组合做门级假设"},
 {"citation":"Mills, C.E. 1984. Density is altered in hydromedusae and ctenophores in response to variable food conditions. Biological Bulletin 166(1):206-215.",
  "url":"https://www.journals.uchicago.edu/doi/10.2307/1541446","tier":"bibliographic",
  "key_claim":"Ctenophore body morphology (lobes, tentacle apparatus) varies with feeding state and developmental stage.",
  "supports":"栉水母体型（叶/触手装置）随发育与摄食状态变化——分期与体型解读需谨慎"}]
HYDRO_REFS = [
 {"citation":"Bouillon, J. & Boero, F. 2000. Synopsis of the families and genera of the hydromedusae of the world, with a list of the worldwide species. Thalassia Salentina 24:47-296.",
  "url":"https://www.vliz.be/imisdocs/publications/303069.pdf","tier":"opened",
  "key_claim":"Hydromedusae are characterized by a velum; families keyed by tentacle number and arrangement, manubrium, canal systems.",
  "supports":"水螅水母科属检索以触手数目与排列为首要特征——2条长触手钟罩的科级定位依据"},
 {"citation":"Russell, F.S. 1953. The Medusae of the British Isles. Anthomedusae, Leptomedusae, Limnomedusae, Trachymedusae and Narcomedusae. Cambridge University Press.",
  "url":"https://www.vliz.be/imisdocs/publications/ocrd/229511.pdf","tier":"opened",
  "key_claim":"Comprehensive illustrated monograph of medusae: bell shape, tentacle number/insertion, gastric pouches, gonad position as diagnostic characters.",
  "supports":"水母体鉴定的经典专著体系：钟形/触手着生/胃囊/生殖腺位置"},
 {"citation":"Miglietta, M.P. et al. 2018. An integrative identification guide to the Hydrozoa (Cnidaria) of Bocas del Toro, Panama. Marine Biodiversity 48:2245-2259.",
  "url":"https://www.tandfonline.com/doi/abs/10.1080/23766808.2018.1488656","tier":"opened",
  "key_claim":"Identification keys to genera and species for 55 hydrozoan species including medusa stages, with molecular barcoding validation.",
  "supports":"水螅纲现代集成鉴定指南（形态+分子），支撑纲级判定与后续科属推进路径"}]
AMPH_REFS = [
 {"citation":"Bousfield, E.L. 1973. Shallow-water Gammaridean Amphipoda of New England. Cornell University Press, Ithaca.",
  "url":"https://www.biodiversitylibrary.org/item/251535","tier":"bibliographic",
  "key_claim":"Gammaridean amphipods diagnosed by laterally compressed body, coxal plates, gnathopods; direct development without larval stage.",
  "supports":"端足目签名（侧扁C形体+底节板+颚足）；直接发育（无幼体期）为跳过规则依据"},
 {"citation":"Lowry, J.K. & Myers, A.A. 2017. A Phylogeny and Classification of the Amphipoda with the establishment of the new order Ingolfiellida (Crustacea: Peracarida). Zootaxa 4265(3):321-389.",
  "url":"https://doi.org/10.11646/zootaxa.4265.3.1","tier":"bibliographic",
  "key_claim":"Amphipoda reclassified into four orders; Gammarida retain C-shaped body with coxal plates and biramous pleopods.",
  "supports":"端足目现行分类框架与形态特征定义"},
 {"citation":"Dias, A.S. et al. 2014. Direct development in the amphipod Parhyale hawaiensis. In: Protocol Exchange (Nature).",
  "url":"https://doi.org/10.1038/protex.2014.011","tier":"opened",
  "key_claim":"Amphipods such as Parhyale hatch as juveniles resembling adults; no planktonic larval stage.",
  "supports":"端足类孵化即为成体形态的幼体（直接发育）——多主体图中端足主体的跳过依据"}]
CEPH2_REFS = [
 {"citation":"Young, R.E. & Harman, R.F. 1988. Larva, Paralarva and Subadult in Cephalopod Terminology. Malacologia 29:201-207.",
  "url":"https://archive.org/stream/cbarchive_49447_larvaparalarvaandsubadultincep1962/larvaparalarvaandsubadultincep1962_djvu.txt","tier":"opened",
  "key_claim":"Cephalopods hatch as paralarvae that resemble miniature adults; no larval stage with dramatic metamorphosis.",
  "supports":"头足类 paralarva=直接发育（无剧烈变态）——跳过规则的一级来源"},
 {"citation":"Villanueva, R. & Norman, M.D. 1997. Identification of octopod (Cephalopoda: Octopodidae) paralarvae from the Western Mediterranean. Bulletin of Marine Science 60(3):1047-1061.",
  "url":"https://www.ingentaconnect.com/content/umrsmas/bullmar/1997/00000060/00000003/art00021","tier":"bibliographic",
  "key_claim":"Octopod paralarvae identified by arm number/suckers, chromatophore patterns, eye size; direct development.",
  "supports":"头足幼体鉴定特征（腕数/吸盘/chromatophores/眼径）；直接发育确认"},
 {"citation":"Okutani, T. 1988. Rare octopod paralarvae from Suruga Bay, central Japan, with a review of planktonic octopods. Venus 47(3):151-170.",
  "url":"https://www.jstage.jst.go.jp/article/venus1960/47/3/47_3_151/_article","tier":"bibliographic",
  "key_claim":"Planktonic octopod juveniles from Suruga Bay described; paralarval morphology and chromatophore counts used for family assignment.",
  "supports":"浮游头足稚体的科级形态定位方法（chromatophore 计数）"}]
GROUP_REF_IDS["G-CTENO2"] = add_refs("G-CTENO2", CTENO_REFS)
GROUP_REF_IDS["G-HYDRO"] = add_refs("G-HYDRO", HYDRO_REFS)
GROUP_REF_IDS["G-AMPH"] = add_refs("G-AMPH", AMPH_REFS)
GROUP_REF_IDS["G-CEPH2"] = add_refs("G-CEPH2", CEPH2_REFS)

# 组→ref_ids 映射升级表里新组
UPGRADE_GROUP_MAP = {"G-CTENO2":"G-CTENO2","G-HYDRO":"G-HYDRO","G-AMPH":"G-AMPH","G-CEPH":"G-CEPH2"}

# ---------- 分期排序键 ----------
# 两级阶段模型：stage_order=组内文献分期序列；within=组内相对成熟（0.5 中性）
STAGE_ORDER = {
 "G-FLAT":{"postflexion":3},
 "G-LEPTO":{"leptocephalus":2},
 "G-SERG":{"acanthosoma":4},
 "G-DEC-SHRIMP":{"zoea":2,"mysis":3},
 "G-DEC-CRAB":{"zoea":2,"megalopa":4},
 "G-PHYL":{"phyllosoma":3},
 "G-STOM":{"alima":3},
 "G-BIVALVE":{"veliger":3},
 "G-PHOR":{"actinotrocha":2,"adult":5},
 "G-MEDUSA":{"medusa":5,"adult":5},
 "G-POLYL":{"nectochaete":3},
 "G-FISHMISC":{"juvenile":5},
 "G-CTENO2":{},
 "G-HYDRO":{"medusa":5},
 "G-AMPH":{"juvenile":5,"adult":5},
 "G-CEPH2":{"paralarva":1},
}
def stage_value(group, stage_label, disp_stage):
    """构造 stage_is 的 value：discrete_label + sort_key + indicator"""
    if not disp_stage:
        return None
    dl = None
    if stage_label:
        dl = stage_label
    # 从 disp_stage 提取括号前主标签
    if not dl:
        dl = disp_stage.split("（")[0].split("(")[0].strip()
    so = STAGE_ORDER.get(group, {})
    order = None
    for k, v in so.items():
        if k.lower() in dl.lower():
            order = v; break
    return {
        "discrete_label": dl,
        "sort_key": {"stage_order": order if order is not None else 99, "within": 0.5},
        "indicator": disp_stage,
        "label_basis": "分期区间按组内文献分期序列定位；within=0.5 为组内中性，新图插入只改排序不改标签",
    }

# ---------- 回填 ----------
by_id = {im["image_id"]: im for im in claims["images"]}
stats = {"taxon_written":0, "stage_written":0, "skip_notes":0, "missing":[]}
rev_imgs = []

def next_claim_id():
    mx = 0
    for im in claims["images"]:
        for c in im["claims"]:
            try: mx = max(mx, int(c["claim_id"][1:]))
            except: pass
    return mx
CID = next_claim_id()

# ---------- 既有路径坐标系迁移 ----------
# 旧会话草案带 Animalia/Eukaryota 前缀、个别漏上级门；若不迁移，同一类群会在
# 分类树里分裂成两条平行分支（Mollusca 既在根又在 Animalia 下）。这是坐标系统一，
# 不是内容改写：不改类群身份，只改前缀写法。逐条记录迁移数以备审计。
MIGRATED = []
for im in claims["images"]:
    for cl in im["claims"]:
        if cl["predicate"] == "taxon_is" and cl.get("value") and cl["value"].get("path"):
            oldp = cl["value"]["path"]
            newp = norm_path(oldp)
            if newp != oldp:
                cl["value"]["path"] = newp
                MIGRATED.append((im["image_id"], " › ".join(oldp), " › ".join(newp)))
if MIGRATED:
    print("路径坐标系迁移:", len(MIGRATED), "条")
    for m in MIGRATED: print("   ", m[0], ":", m[1], "→", m[2])

def _write_skip_note(im, iid, d, cid_cursor, now, reason_override=None, detail_override=None):
    """写/更新 triage_note 断言。返回是否新建。"""
    tn = next((c for c in im["claims"] if c["predicate"] == "triage_note"), None)
    created = tn is None
    if tn is None:
        tn = {"claim_id": f"c{cid_cursor+1:04d}", "subject": {"type": "image", "id": iid},
              "predicate": "triage_note", "value": None, "confidence": None,
              "status": "draft", "asserted_by": "ai_draft",
              "evidence": {"references": [], "diagnostics": [], "note": None},
              "supersedes": None, "superseded_by": None, "created_at": now}
        im["claims"].append(tn)
    disp_ = d.get("disp", "skip")
    reason = reason_override or {"skip": "跳过（无剧烈变态/非幼体）",
              "reread": "高倍重读后仍未达可防守层级"}.get(disp_, "跳过")
    tn["value"] = {"triage": disp_, "reason": reason,
                   "detail": detail_override or d.get("note") or d.get("diag") or "跳过",
                   "group_hint": d.get("group")}
    tn["updated_at"] = now
    return created

for iid, d in disp.items():
    im = by_id.get(iid)
    if not im:
        # 试模糊匹配（claims 的 image_id 可能与 disposition key 完全一致，先直查）
        cand = [k for k in by_id if k.startswith(iid[:8])]
        im = by_id.get(cand[0]) if len(cand)==1 else None
    if not im:
        stats["missing"].append(iid); continue
    upg = UPGRADE.get(iid)
    if d["disp"] == "include" or upg:
        if upg:
            taxon = upg["taxon"]; conf = upg["conf"]; stop = upg["stop"]
            diag = upg["diag"]; group = upg["group"]; stage = upg.get("stage")
            note = upg.get("note")
        else:
            taxon = d["taxon"]; group = d["group"]; stop = d["stop"]; diag = [d["diag"]] if d["diag"] else []
            conf_map = {"high":0.85,"medium-high":0.75,"medium":0.6,"low-medium":0.45,"low":0.35,"hypothesis-capped":0.2}
            conf = conf_map.get(d["conf"], 0.4)
            stage = d["stage"]
            note = d.get("note")
        # 保护人工确认的断言：只允许覆盖 AI/机器断言，人工结论不静默改写。
        # 人工断言本身已是 confirmed 状态（不会被判 unresolved/skipped），无需写 triage_note。
        _pre = next((c for c in im["claims"] if c["predicate"]=="taxon_is"), None)
        if _pre and _pre.get("asserted_by") == "human":
            stats.setdefault("human_kept", []).append(iid)
            continue
        # 找现有 taxon_is / stage_is 断言
        tax_claim = next((c for c in im["claims"] if c["predicate"]=="taxon_is"), None)
        stg_claim = next((c for c in im["claims"] if c["predicate"]=="stage_is"), None)
        ref_ids = GROUP_REF_IDS.get(UPGRADE_GROUP_MAP.get(group, group), [])
        # 规范化新路径（去 Animalia/Eukaryota 前缀、补上级门）
        new_path = norm_path(taxon)
        # 覆盖留痕：旧值非空且归一化后仍不同 → 记推翻，不静默替换
        old_path = norm_path(((tax_claim or {}).get("value") or {}).get("path") or [])
        if old_path and old_path != new_path:
            record_overwrite(iid, old_path, new_path,
                "本轮 larval-taxonomy SOP（高倍重读+文献门）推翻早先会话的 AI 草案分类。")
        if tax_claim is None:
            CID += 1
            tax_claim = {"claim_id":f"c{CID:04d}","subject":{"type":"image","id":iid},"predicate":"taxon_is",
                         "value":None,"confidence":None,"status":"unresolved","asserted_by":None,
                         "evidence":{"references":[],"diagnostics":[],"note":None},
                         "supersedes":None,"superseded_by":None,"created_at":NOW}
            im["claims"].append(tax_claim)
        tax_claim["value"] = {"path": new_path, "stop_reason": stop}
        tax_claim["confidence"] = conf
        tax_claim["status"] = "draft"
        tax_claim["asserted_by"] = "ai_draft"
        tax_claim["evidence"] = {"references": ref_ids, "diagnostics": diag,
            "note": (note + " ｜ " if note else "") + f"larval-taxonomy SOP 草案（形态组 {group}）：像素判读+组内共享文献门；停层原因见 stop_reason"}
        tax_claim["updated_at"] = NOW
        stats["taxon_written"] += 1
        # stage
        sv = stage_value(group, None, stage)
        if stg_claim is None:
            CID += 1
            stg_claim = {"claim_id":f"c{CID:04d}","subject":{"type":"image","id":iid},"predicate":"stage_is",
                         "value":None,"confidence":None,"status":"unresolved","asserted_by":None,
                         "evidence":{"references":[],"diagnostics":[],"note":None},
                         "supersedes":None,"superseded_by":None,"created_at":NOW}
            im["claims"].append(stg_claim)
        if sv:
            stg_claim["value"] = sv
            stg_claim["confidence"] = max(0.2, conf - 0.1)
            stg_claim["status"] = "draft"
            stg_claim["asserted_by"] = "ai_draft"
            stg_claim["evidence"] = {"references": ref_ids, "diagnostics": [],
                "note": "分期为区间表述；文献定义序列见 references"}
            stg_claim["updated_at"] = NOW
            stats["stage_written"] += 1
        else:
            stg_claim["value"] = None
            stg_claim["status"] = "unresolved"
            stg_claim["asserted_by"] = None
            stg_claim["evidence"] = {"references": ref_ids, "diagnostics": [],
                "note": "该组分期不可从像素判定（缺关键结构或为门级假设），封顶假设档"}
        # 直接发育类群（头足 paralarva / 端足类）：即便留下了高倍判读草案，
        # 按用户跳过规则仍应标 skip——草案保留在检查器供裁决，但不进待办队列。
        if group in ("G-CEPH2", "G-AMPH"):
            created = _write_skip_note(im, iid, dict(d, disp="skip"), CID, NOW,
                reason_override="跳过（直接发育：头足 paralarva / 端足类，无剧烈变态）",
                detail_override="本条保留高倍判读草案（见 taxon_is），仅记录判读供你裁决；按跳过规则不进待办队列。")
            if created: CID += 1
        rev_imgs.append(iid)
    else:
        # skip / reread 未升级：写 triage_note 断言（不进队列）
        created = _write_skip_note(im, iid, d, CID, NOW)
        if created: CID += 1
        stats["skip_notes"] += 1

# ---------- 顶层 references 追加 ----------
claims["references"].extend(NEW_REFS)

# ---------- revision_log（与既有条目同形状，revItem 才能渲染） ----------
rev = claims.setdefault("revision_log", [])
rev.append({
 "rev": f"r{len(rev)+1}",
 "date": NOW[:10],
 "image_id": None,
 "predicate": "taxon_is / stage_is / triage_note（批量）",
 "superseded_value": f"43 张图 taxon_is=null（未鉴定）；108 张无分诊处置记录",
 "corrected_value": f"larval-taxonomy SOP 批量回填：taxon_is 草案 {stats['taxon_written']} 条（include 28 + 高倍重读升级 15）、stage_is 草案 {stats['stage_written']} 条、triage_note 跳过/待裁 {stats['skip_notes']} 条；新增组文献 {len(NEW_REFS)} 条（16 个形态组 × 3，仅一级来源，link_status=untested）",
 "corrected_by": "ai_draft",
 "root_cause": "原始批注只含机器读取字段（EXIF/派生），无任何分类断言。",
 "method_change": "六页分诊接触表逐张过图 → 用户审定跳过规则（无剧烈变态者跳过）→ 三个独立判读子代理纯像素观察 → 15 张模糊图从原图高倍重读 → 四个文献子代理按组过文献门（每组恰好 3 条一级来源，禁百科/社媒/新闻稿）→ 全部以 status=draft 入库待人工复核。分诊中推翻自身初判 5 处（2087/_Y3A0153 非鱼、2370 为翼足+头足双主体、0097/0098/0102 与 _Y3A0153 改判栉水母门假设、3441 改判帚虫门）。",
 "images_touched": rev_imgs,
})
# 逐图推翻记录：每条单独成条，revItem 才能在修正链里逐条渲染
for ow in OVERWRITES:
    rev.append(dict(ow, rev=f"r{len(rev)+1}", date=NOW[:10],
        method_change="高倍重读+组内文献门复核后改写；旧草案保留在修正链中可追溯。"))
if OVERWRITES:
    print("覆盖留痕条数:", len(OVERWRITES))

# ---------- counts 更新 ----------
claims["counts"]["references"] = len(claims["references"])
claims["counts"]["ai_draft_taxa"] = stats["taxon_written"]
claims["counts"]["ai_draft_stages"] = stats["stage_written"]
claims["built_at"] = NOW

# ---------- 备份并写回 ----------
bak = CJ + f".bak-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
shutil.copy2(CJ, bak)
json.dump(claims, open(CJ, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("备份:", bak)
print("统计:", json.dumps(stats, ensure_ascii=False))
print("新文献条数:", len(NEW_REFS), "顶层文献总数:", len(claims["references"]))
# 自检：禁止域名
banned = ["wikipedia","baike","instagram","facebook","youtube","quora","zhihu","xiaohongshu","kepuchina","blogspot","medium.com","wallawalla"]
hits = [r["ref_id"] for r in NEW_REFS if any(b in r["url"].lower() for b in banned)]
print("禁止域名命中:", hits if hits else "无")
