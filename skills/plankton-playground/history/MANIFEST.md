# Plankton Playground — 技能版本台账

| 版本 | 日期 | 变更摘要 | 等价性 | 备注 |
|---|---|---|---|---|
| v1 | 2026-10-25 | 首版定型：引擎（分级加载 + 单张淡入）、双层素材管线（长边 1500 封顶、不回退原图）、并发外链校验、四视口验证门、v23 等价门 | 1440×900 逐帧 0.0000px | 快照见 `history/v1/`；测试跑成果见项目 `planktontest-playground/history/` |
| v1+exp | 2026-10-25 | 实验性扩展（默认关闭或显式开启）：`spacingFactor`/`speedFactor` 相对倍率；`fixScreensCap`/`fixFallbackScan`/`fixOrbitRadius` 缺陷修复开关；`weakRatio` 逐块速度下限；`FALLBACK_N` 真实计数；速度断言替换振幅断言并改为逐块最差值 | 开关全关时四视口 0.0000px | 开启 fix* 开关后等价性失败属预期；验收改用"相对 v1 实测对比" |
| **v2** | 2026-10-25 | **定版**（用户认可）。含 v1+exp 全部能力并写入正式文档：SKILL.md 断言清单补入弱动/静止两条（逐块最差值，非中位数）、参数速查表补全 8 个新参数、纠正「voidRatio 是密度主杠杆」的错误结论、登记手机视口兜底豁免与 iPhone 16 Pro Max(440×956) 覆盖 | 开关全关时四视口 0.0000px | 快照见 `history/v2/`（15 文件 / 220K，引擎 637 行）；引擎较 v1 增 139 行 |
| **v3** | 2026-10-26 | **定版**（用户认可）。折叠「刷新随机尺寸」机制：`randomSize`/`sizeSpread`/`sizeJumpMin` 三参数 + localStorage 尺寸记忆 + 强制跳变（≥18%）+ 无尖峰区间映射；新增 `reload_chain.cjs`（接力刷新验证）与 `rsize_concentration.cjs`（堆积诊断）；文档同步（params 制约④、SOP 第④道门、lessons #18） | 默认路径（randomSize=0）四视口 0.0000px | 快照见 `history/v3/`；接力验证：桌面 12 刷 0 违规/0 越界/0 乒乓，单图每变 ≥19.8%；手机窄带自动退化为带内随机 |
| **v3.1** | 2026-10-26 | **把验收调优固化为默认**（用户主动发现遗漏）。v3 只入了机制、12 个参数默认仍是保守 v2 值，照默认跑会产出老样子。新增 `assets/config.approved.json`（spacingFactor 0.45 / speedFactor 1.38 / weakRatio 0.72 / randomSize 1 / sizeSpread 2.6 / sizeJumpMin 0.18 / 四个 fix* 全开），`build_page.py` 构建期自动注入；另加 `--no-preset` 复现基线、`--config` 单项覆盖、`--preset` 换预设。文档同步（SOP S2 预设说明 + config 取值陷阱、lessons #19） | 引擎 CFG 默认仍与 v23 逐字一致：四视口 0.0000px（等价门继续有效） | 快照 `history/v3/` 已重建为 18 文件 / 264K（含预设）。三路径实测：默认注入 12 项且逐项匹配预设、`--no-preset` config 为空、`--config` 只覆盖指定键 |
| **v4** | 2026-10-27 | **新增 S6 关联条带**（同一生物多角度）。挂载层 `assets/kinship_mount.js`（kin-4.1）经 `lightbox:open/close` 钩子挂载，**核心引擎零改动**：横向胶片条、触控板/滚轮滑动平移 + 抬手吸附、点邻图只平移不重建、焦点纯 transform scale 1.22、居中锁定、保留错落、完全不显示 image ID、关闭延迟 460ms 清理避免闪烁；内建指认纠正机制（P/◎：声明同组、移出分组、localStorage 持久化、导出 corrections JSON）。新增管线 `kin_features.py`（轮廓半径频谱特征，spec .52/hu .22/topo .14/color .12）→ `kin_sheets.py`（接触表）→ 人工核验 → `kinship.json` → `inject_kinship.py`（按内容特征幂等注入 + status 词表归一化）→ `test_kinship.mjs`（26 项 CDP 实测）。文档：SKILL.md 铁律 8/9/10 + S6 阶段；新增 `references/kinship.md`；lessons #20–24 | 未触碰引擎，等价门继续有效；morph 实测默认 0 | 快照见 `history/v4/`（24 文件 / 376K）。实测 26/26 通过（退出码 0）；无分组时静默降级 12/12 通过（不建 DOM、引擎完好）。地面真值：连拍簇 8 对，紧阈值召回 50%、宽网 88%，但**任意阈值同簇率恒 2/8** → 确立铁律 9（算法只召回、人眼判定）。已否决并记录：640px 主体裁剪（过裁失真被用户否决，见 lessons #22）、焦点全分辨率升级（`r.full` 是整帧非裁剪）、聚类自动判定（见 #23） |

## v1 已知缺陷（v23 自带，v1 继承）

- 画布屏数上限固定（真 v23 为 8 屏；模板曾误写 9，已在当前版修回 8）→ 手机/窄屏视口上限绑定时走延底垫放，桌面 2–3 张、手机 10–13 张堆在画布底部。
- 兜底/自愈扫描步长过粗（≈0.35×图块尺寸），会跳过仍然够用的窄缝，加剧垫底。
- 轨道半径用 `min(L,R)` 而非 `(L+R)/2`，任一侧为 0 时图块完全静止（用户肉眼可见"锁住"）。
- 三者分别由 `fixScreensCap` / `fixFallbackScan` / `fixOrbitRadius` 开关修复，默认关闭以保持逐帧等价。

## 实验结论（密度 +20% / 速度 +20%，2026-10-25 终版）

胜出组合：`spacingFactor=0.45, voidRatio=1.5, speedFactor=1.38, fixScreensCap=true, fixFallbackScan=true, fixOrbitRadius=true, weakRatio=0.72, speedFloorCap=6`
- 桌面：每屏 12.8→16.3 张（+27.5%），首屏 +20.8%，实测速度 3.37→4.23 px/s（+25.3%），最慢块 1.11→4.00 px/s，兜底 2→0，零相交 0.0px
- 手机：密度 +26.9%，速度 +29.0%，兜底 11→3（手机基线本有 3–4，系 390px 容量极限）
- 机制两条：① 密度与**振幅**零和、但与**速度**不零和——零相交只取决于半径，提频可安全提速；② 高密度下必然出现被四面包夹的弱动块，搬迁无效（整带都包夹），**逐块提频**（`weakRatio`）是唯一解。
- 校准记录：`weakRatio` 0.60/0.72/0.85 三档实测，0.72 为平衡点（提速 26 张/页、最慢 4.0px/s）；0.85 会提速 38 张、频率周期逼近 7.7s，动感趋同，不取。
