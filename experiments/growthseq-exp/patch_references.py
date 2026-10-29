#!/usr/bin/env python3
"""patch_references.py — 把本轮真实检索到的文献写入草稿标注。

为什么用补丁脚本而不是手改 JSON：引用字符串长、易抄错；集中在一处便于核对与复现。
原则：只写本轮检索中确实出现的文献（作者/年份/出处可在检索结果中核对），不编造；
      通俗科普类来源显式标注层级，不与同行评议文献混为一谈。

本次检索带来两处实质结论变更（不只是补装饰）：
  · s09 栉水母：原判「直接发育→无序列」过于简化。Edgar 2022 与 Soto-Angel 2024 结论相反，
    能否进序列取决于类群（lobate 以 cydippid 孵化并渐变变态）。故撤销排除建议，改为待判。
  · s01/s07 头足类：Young & Harman 1988 给出 paralarva 术语定义 → discrete_label 由 null 升级为可引用标签。
  · s03 多毛类：nectochaeta 有文献定义 → discrete_label 由 null 升级为「nectochaeta 或更晚期」。
"""
import json
import os

EXP = "/Users/jialingcai/Documents/qwen-agent/NZKKxizmz2/default/growthseq-exp"
DRAFT = os.path.join(EXP, "draft_annotations_v1.json")
OUT = os.path.join(EXP, "draft_annotations_v2.json")

# 本轮真实检索到的文献（可在检索结果中逐条核对出处）
REFS = {
    "cephalopod_manual": 'Sweeney M.J., Roper C.F.E., Mangold K.M., Clarke M.R. & Boletzky S.v. (eds) 1992. "Larval" and Juvenile Cephalopods: A Manual for Their Identification. Smithsonian Contributions to Zoology 513, 282pp.',
    "ceph_term": "Young R.E. & Harman R.F. 1988. \u201cLarva\u201d, \u201cParalarva\u201d and \u201cSubadult\u201d in Cephalopod Terminology. Malacologia 29:201\u2013207.",
    "argo_finn": "Finn J.K. 2013. Taxonomy and Biology of the Argonauts (Cephalopoda: Argonautidae). Molluscan Research 33:143\u2013222.",
    "argo_kamatsos": "Kamatsos E. et al. 2025. Rare Observation of a Female Argonauta argo in the Northeastern Aegean Sea. Diversity 17(5):361.",
    "argo_orosco": "Orosco X. et al. 2024. Species Delimitation of Argonauta Paralarvae Reveals Extensive Morphological Variability. Diversity 16(6):320.",
    "cteno_edgar": "Edgar A. et al. 2022. Ctenophores are direct developers that reproduce continuously beginning very early after hatching. PNAS 119(24):e2122052119.",
    "cteno_soto": "Soto-Angel J.J. et al. 2024. Reverse development in the ctenophore Mnemiopsis leidyi. (PMC11551415) — 记载 lobate 类以 cydippid 孵化、触手重吸收并渐变变态。",
    "cteno_schnitzler": "Schnitzler C.E. et al. 2014. Sox gene expression through embryonic development of Mnemiopsis leidyi. (PMC4021642) — \u201cNearly all ctenophores display direct development\u201d.",
    "cteno_pang": "Pang K. et al. 2008. Ctenophores. Current Biology 18(14):R619 — \u201cNearly all ctenophores are direct developing, holopelagic, self-fertile hermaphrodites\u201d.",
    "scyp_complex": "Comparative muscle development of scyphozoan jellyfish with simple and complex life cycles. (PMC4415277) — \u201cSimple life cycles arise from complex life cycles when one or more developmental stages are lost\u201d.",
    "lep_noaa": "NOAA Technical Report: Guide to the Leptocephali (Elopiformes, Anguilliformes, and Notacanthiformes). repository.library.noaa.gov/view/noaa/4540",
    "lep_miller": "Miller M.J. 2009. An Introduction to Leptocephali: Biology and Identification.",
    "lep_myo": "Leptocephalus overview, ScienceDirect Topics — \u201cseparated from one another primarily by the number of myomeres, e.g. 103\u2013111 for the American eel and 112\u2013119 for the European eel\u201d.",
    "lep_chen": "Chen J.N. et al. 2014. Phylogeny of the Elopomorpha (Teleostei). Mol. Phylogenet. Evol. — leptocephalus 定义为背腹极度压缩的柳叶状透明幼体。",
    "lep_inoue": "Inoue J.G. et al. 2004. Mitogenomic evidence for the monophyly of elopomorph fishes. (PubMed 15186813) — leptocephalus 为 Elopomorpha 共有衍征。",
    "dec_weiss": "Weiss H.M. Decapod Crustacean Larvae (Connecticut Sea Grant 专著 PDF) — \u201ccrabs usually go through several zoeal larval stages before metamorphosing into a megalopa\u201d.",
    "dec_wear": "Wear R.G. Larvae of the Brachyura (Crustacea: Decapoda) I — 检索表（VLIZ 全文 PDF，被引 110）；含 \u201cpleopod buds in all zoea stages\u201d 等分期字符。",
    "dec_li2022": "Li J. et al. 2022. Morphology of the complete embryonic and larval development — 六期：zoea I\u2013V + megalopa。",
    "dec_marco": "Marco-Herrero E. et al. 2026. The Megalopa Stage in Grapsidae Crabs (Decapoda). MDPI 6(1):15 — 指出多数科仅有 zoea I 描述、完整发育资料稀缺。",
    "dec_pleopod": "micro-CT 研究（ResearchGate fig.2, 2018）— \u201cpleopod anlagen emerge as small buds in the Zoea II and become fully functional in the Megalopa\u201d.",
    "dec_charybdis": "廖永岩、黄惠良、王能钦 2010. 室内锈斑蟳幼体发育的形态观察. 热带海洋学报 — zoea I\u2013VI 第1颚足外肢羽状刚毛数 4/6/8/9\u201310/13\u201314/15\u201316（分期量化字符）。",
    "pol_nectochaeta": "Traits: Nectochaeta, Coastal Wiki — \u201cA polychaete larval stage where the first set of chaetal bundles and parapodia develop\u201d（定义层来源，非同行评议）。",
    "pol_azmi": "Azmi S.S. et al. 2021. Epitokous metamorphosis, reproductive swimming and early development of Neanthes glandicincta (Nereididae). ZooKeys (PMC7835201) — 以 3 刚节 nectochaeta 晚期转入底栖幼体。",
    "pol_sabellaria": "Larval development and metamorphosis of Sabellaria cementarium. Can. J. Zool. (z85-156) — 时序：feeding trochophore → metatrochophore → metatrochophore with tentacle buds → nectochaeta。",
    "pol_blake": "Blake J.A. 2017. Larval development of Polychaeta from the northern California coast. J. Mar. Biol. Assoc. UK.",
    "rad_zettler": "Zettler L.A. et al. 1997. A molecular perspective on Haeckel\u2019s Radiolaria. (PMC23483) — axopodia 与 central capsule 为 Acantharea 与 Polycystinea 共有特征。",
    "rad_celestite": "Nguyen A. Molecular Identification of an Acantharian (USF Digital Commons) — \u201cAcantharia are heterotrophic marine protists within the phylum Radiolaria\u2026 endoskeletons composed of celestite crystals\u201d.",
    "rad_decelle": "Decelle J. et al. 2012. An original mode of symbiosis in open ocean plankton. PNAS 109(45) — 棘射虫与共生微藻关系（被引 191）。",
    "rad_acantharia": "About the Acantharia, photosymbiosis.com — \u201cunicellular eukaryotes that measure 20 to 800 micrometers\u2026 skeleton of 10 or 20 spicules\u201d（科普/项目页层级）。",
    "gas_nutzel": "N\u00fctzel A. 2014. Larval ecology and morphology in fossil gastropods. Palaeontology — \u201cIn planktotrophic species\u2026 the number of protoconch whorls is greater than two to three\u201d（原壳螺层数为分期字符）。",
    "gas_howes": "Howes E.L. et al. 2014. A status review of thecosome pteropod culture techniques (AWI PDF) — veliger 壳特性与培养。",
    "gas_vidal": "Vidal-Miralles J. et al. 2024. A global phylogeny of pelagic pteropod molluscs. Mol. Phylogenet. Evol.",
    "salp_fender": "Fender C.K. et al. 2023. Prey size spectra and predator to prey size ratios of salps — 按 solitary / aggregate 生活阶段分选。",
    "salp_morph": "Salp Morphology fig.1: \u201cSolitary form (oozooid) and Aggregate form (blastozooid) of Thalia democratica\u201d (ResearchGate) — 樽海鞘世代交替两型。",
    "clione_popsci": "科普中国：冰海天使 — \u201c幼年期为有壳无翼，成熟过程中外壳退化、足部特化成翼\u201d（科普层级，仅作线索不作依据）。",
}

PATCH = {
    "DSC_0361": {
        "refs": ["ceph_term", "cephalopod_manual"],
        "discrete_label": "paralarva",
        "label_basis": "Young & Harman 1988 定义：头足类孵化后营浮游、形态与成体同型者称 paralarva（非 larva）。本个体无壳、腕吸盘成形、无鳍 → 八腕目 paralarva。",
        "stage_conf": 0.6,
        "lit_note": "Sweeney et al. 1992 (SCtZ 513) 为头足类幼体鉴定权威手册，但科级鉴定需齿舌/腕式等本图不可见特征，故分类止于目。",
    },
    "DSC_1062": {
        "refs": ["dec_weiss", "dec_wear", "dec_pleopod", "dec_charybdis", "dec_marco"],
        "discrete_label": None,
        "label_basis": "文献分期字符（第1颚足外肢羽状刚毛数、腹肢芽期次、尾节刚毛式）均需显微观察；照片分辨率与角度不足以数刚毛，故不赋 discrete_label，只给相对成熟度。",
        "stage_conf": 0.45,
        "lit_note": "腹肢原基自 zoea II 出现、至 megalopa 具功能（micro-CT 研究）；锈斑蟳 zoea I–VI 刚毛数 4/6/8/9–10/13–14/15–16 为量化分期字符。本个体螯足发达、尾扇完整、腹部已分节 → 晚期 zoea 或 decapodid/mysis 期，但科不明则分期方案不可套用（Marco-Herrero 2026 指出多数科仅有 zoea I 描述）。",
    },
    "_Y3A0257": {
        "refs": ["pol_nectochaeta", "pol_azmi", "pol_sabellaria", "pol_blake"],
        "discrete_label": "nectochaeta（或更晚期）",
        "label_basis": "nectochaeta 定义：首批刚毛束与疣足已发育（Coastal Wiki 定义层）。本个体每节疣足叶分明、长刚毛成束伸出体外、体节多 → 达 nectochaeta 或其后的幼体后阶段。",
        "stage_conf": 0.6,
        "lit_note": "Sabellaria 时序可作参照：feeding trochophore → metatrochophore → 具触手原基 → nectochaeta；Azmi 2021 记载以 3 刚节 nectochaeta 晚期转底栖。目/科级需头部附肢与刚毛微结构，本图不可辨。",
    },
    "_Y3A0153": {
        "refs": ["cteno_soto", "cteno_edgar", "scyp_complex"],
        "discrete_label": None,
        "label_basis": None,
        "stage_conf": 0.0,
        "lit_note": "门未定故不给阶段。若为栉水母：Edgar 2022 主张直接发育（cydippid 非真幼体），Soto-Angel 2024 记载 lobate 类以 cydippid 孵化并渐变变态 → 术语本身在争议中。若为水螅水母：PMC4415277 记载简单生活史由复杂生活史丢失阶段而来，即存在阶段有无之别。两条路径都要求先定门。",
    },
    "DSC_0933": {
        "refs": ["rad_zettler", "rad_celestite", "rad_decelle", "rad_acantharia"],
        "discrete_label": None,
        "label_basis": None,
        "stage_conf": 0.0,
        "lit_note": "Acantharia 为放射虫门内的单细胞异养原生生物（Nguyen, USF），具 axopodia 与 central capsule（Zettler 1997），内骨骼为天青石（celestite, SrSO4）而非硅质 —— 但矿物成分无法从照片验证，故属级判定置信仅 0.5。单细胞生物无后生动物发育序列，排除依据充分；其金色小球疑为共生微藻（Decelle 2012 PNAS）。",
    },
    "DSC_2430": {
        "refs": ["lep_chen", "lep_inoue", "lep_myo", "lep_noaa", "lep_miller"],
        "discrete_label": "leptocephalus",
        "label_basis": "leptocephalus 为 Elopomorpha 共有衍征（Inoue 2004），定义为背腹极度压缩、柳叶状、高度透明的幼体型（Chen 2014）。本个体符合。",
        "stage_conf": 0.7,
        "lit_note": "科级鉴定主要依据肌节数（myomere count），如美洲鳗 103–111、欧洲鳗 112–119（ScienceDirect overview）；本图无法可靠计数，故止于总目。NOAA《Guide to the Leptocephali》与 Miller 2009 为鉴定入口。变态序列为 leptocephalus → glass eel → elver（色素时相 I–VI 可分期）。",
    },
    "DSC_26982020": {
        "refs": ["ceph_term", "cephalopod_manual"],
        "discrete_label": "paralarva",
        "label_basis": "同 DSC_0361 依据（Young & Harman 1988）。本个体腕吸盘更大且两列分明、外套膜更圆 → 在连续谱上较 DSC_0361 成熟，故 within=2。",
        "stage_conf": 0.6,
        "lit_note": "Sweeney et al. 1992 (SCtZ 513) 提供八腕目 paralarva 鉴定字符；科级仍需不可见特征。",
    },
    "DSC_25802020": {
        "refs": ["argo_finn", "argo_kamatsos", "argo_orosco"],
        "discrete_label": None,
        "label_basis": "船蛸无文献定义的离散分期：Kamatsos 2025 明确记载壳分泌自孵化后数日开始、持续至性成熟，为连续过程；且 juvenile female（即使已交配）尚无可见壳。故本个体「有壳未抱卵」只能定位为连续谱上的亚成体至成体雌，不给离散标签。",
        "stage_conf": 0.6,
        "lit_note": "Finn 2013 为船蛸科分类与生物学专著（壳形可塑性大，不能用于分种）；Orosco 2024 以 COI 证明 A.argo 与 A.nouryi 幼体色素型高度重叠、形态学不可分种 → 种级判定需分子数据。",
    },
    "DSC_3058": {
        "refs": ["cteno_edgar", "cteno_soto", "cteno_pang", "cteno_schnitzler"],
        "discrete_label": None,
        "label_basis": None,
        "stage_conf": 0.2,
        "no_sequence": None,
        "lit_note": "撤销先前「直接发育→排除序列」的判断：文献结论冲突。Edgar 2022 / Pang 2008 / Schnitzler 2014 支持直接发育（cydippid 不算真幼体）；但 Soto-Angel 2024 记载 lobate 类以 cydippid 孵化、触手重吸收并发育新结构，属渐变变态，学界正争论是否废除 larva/metamorphosis 术语。→ 能否进序列取决于本个体所属类群（cydippid / lobate / cestid），而目级未定，故标为待判而非排除。",
    },
    "DSC_2999": {
        "refs": ["gas_nutzel", "gas_howes", "gas_vidal", "salp_fender", "salp_morph", "clione_popsci"],
        "discrete_label": None,
        "label_basis": None,
        "stage_conf": 0.0,
        "lit_note": "两条假说各有文献支撑，故不取舍：①翼足类 veliger —— Nützel 2014 给出原壳螺层数（protoconch whorls）作为浮游营养型幼体分期字符，Howes 2014 述 veliger 壳特性，Vidal-Miralles 2024 为翼足类系统发育；裸海蝶类（Clione）幼体有壳无翼、成熟时壳退化（科普中国，仅线索）。②樽海鞘 —— 存在 solitary(oozooid) / aggregate(blastozooid) 世代交替两型（Fender 2023；Thalia democratica 形态图），聚合体可解释「双卵圆结构」。图中两枚镜像卵圆体各含白色螺旋壳样物与橙色团，倾向①，但底部两足样附器相接无法解释，需你判断。",
    },
}


def main():
    d = json.load(open(DRAFT, encoding="utf-8"))
    d["schema"] = "growth-sequence/draft-v2"
    d["revision_note"] = ("v2：为全部 10 条补入本轮真实检索的文献；并因文献检索产生三处实质结论变更："
                          "(1) s09 栉水母撤销「直接发育→排除序列」判断，改为待判（Edgar 2022 与 Soto-Angel 2024 结论冲突）；"
                          "(2) s01/s07 头足类 discrete_label 由 null 升级为 paralarva（Young & Harman 1988 术语定义）；"
                          "(3) s03 多毛类 discrete_label 升级为 nectochaeta 或更晚期（文献定义 + 刚毛/疣足已发育）。")
    d["policy"]["references"] = ("仅填本轮真实检索到的文献，并区分层级：同行评议 > 专著/技术报告 > 定义层（Coastal Wiki/WoRMS）"
                                 "> 科普（显式标注，仅作线索）。检索改变结论时必须写 lit_note 说明。")
    n_ref = 0
    n_changed = 0
    for r in d["records"]:
        p = PATCH.get(r["id"])
        if not p:
            continue
        refs = [REFS[k] for k in p["refs"]]
        r["references"] = refs
        n_ref += len(refs)
        old_label = r["stage"].get("discrete_label")
        if p.get("discrete_label") is not None and p["discrete_label"] != old_label:
            r["stage"]["discrete_label"] = p["discrete_label"]
            n_changed += 1
        if p.get("label_basis"):
            r["stage"]["label_basis"] = p["label_basis"]
        if p.get("stage_conf") is not None:
            r["stage"]["confidence"] = p["stage_conf"]
        if p.get("lit_note"):
            r["stage"]["literature_note"] = p["lit_note"]
        if r["id"] == "DSC_3058":
            # 撤销排除建议：改为待判
            r["stage"]["continuum_note"] = ("能否进序列待判：文献结论冲突（见 literature_note），取决于所属类群。"
                                            "不再默认排除。")
            r["reviewer_note"] = ("需你判断：(a) 是否为栉水母；(b) 若是，属 cydippid / lobate / cestid 哪一类——"
                                  "这决定它有没有发育序列可排。")
            r["status"] = "draft"
    json.dump(d, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"✅ v2 草稿已写: {OUT}")
    print(f"   记录数: {len(d['records'])}   新增引用条目: {n_ref}   discrete_label 升级: {n_changed} 张")
    pend = sum(1 for r in d["records"] if any(x == "pending" for x in r["references"]))
    print(f"   仍含 pending 的记录: {pend} 张（应为 0）")
    uniq = len({x for r in d["records"] for x in r["references"]})
    print(f"   唯一文献数: {uniq}")


if __name__ == "__main__":
    main()
