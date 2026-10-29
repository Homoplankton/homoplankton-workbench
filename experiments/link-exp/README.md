# L1 连接实验：档案站 → 工作台（单向深链）

**状态：实验成功，37/37 断言通过（退出码 0），未并入任何已交付文件。**

## 验证了什么

| # | 问题 | 结果 |
|---|---|---|
| 1 | `file://` → `file://` 跳转 + fragment 传参是否被浏览器放行 | **可行**。Chrome 同目录相对跳转正常，`#img=DSC_0214&mode=verify` 完整到达并被解析（探针 a.html/b.html） |
| 2 | 档案站点开生物后能否生成正确链接 | 可行。入口是 `#wbLink` 锚点，灯箱打开时才出现，href = `workbench.html#img=<id>&from=archive` |
| 3 | 点击后工作台能否自动定位同一张图 | 可行。接收层解析 hash → `setFilter('all','all')` → `select(id)` → 网格高亮 + 检查器展开 + 来源提示条 |
| 4 | 是否破坏档案站沉浸感 | 未破坏。入口平时 `display:none`；文案是动作不是 ID；不含任何 image ID 字样 |
| 5 | 是否与 kinship 挂载冲突 | 不冲突。三层（引擎 v3.1 + kinship 4.1 + link 0.2）共存，条带 5 张正常 |
| 6 | 未知 id / 无 hash 进入是否安全 | 显式提示「找不到这张图」，不静默失败，不改当前选中 |
| 7 | 工作台核心功能是否被接收层破坏 | 未破坏。待办队列、争议筛选（2 张）、全量 108 张均正常 |

## 三个实测发现（改动前必读）

1. **`window.open` 无用户手势会被拦**（返回 null，CDP 捕获 `Page.windowOpen gesture=false`）。
   真实鼠标手势下成功（`gesture=true`）。故入口改为**原生锚点导航**
   （`<a target="_blank">`），不依赖手势判定，还顺带支持中键/⌘点击/右键打开/复制链接。
   **测试必须用 CDP `Input.dispatchMouseEvent` 真实手势**，合成 `.click()` 会得到假失败。
2. **`<a>` 必须有 `target="_blank"`**。缺了它原生导航会**替换当前标签**，
   档案站的漂浮状态（滚动位置、随机尺寸、已加载图）全丢。
3. **护栏按 basename 匹配会误伤**。实验副本也叫 `workbench.html`，
   第一版护栏把它当成已交付文件拒绝了。改为 `os.path.realpath` 比对受保护路径。

## 为什么用 URL fragment 而不是 localStorage / postMessage

- 无状态、跨标签页、不依赖同源存储（`file://` 下 localStorage 按目录分区，两文件不同名共享不可靠）
- 链接本身就是完整状态，刷新可复现，也可以直接发给别人
- postMessage 在 `file://` 下需要两个窗口同时活着，做不到「发个链接给人」

## 安全边界（实验纪律）

- `inject_links.py` **默认拒绝**写入已交付文件（三个受保护路径，realpath 比对），
  必须显式 `--allow-delivered` 才放行。已实测拒绝路径退出码 = 1。
- 实验全程只改 `link-exp/` 内的副本。已交付文件 md5 六次核对未变：
  - 工作区档案站 `aca451a0…`
  - 工作台 `67aa3339…`
  - 外置盘存档 `aca451a0…`
- 注入幂等：按内容特征（`PlaygroundLink`/`WorkbenchLink`）剥离旧块，重复注入不累积。

## 文件清单

| 文件 | 作用 |
|---|---|
| `probe/a.html`, `probe/b.html` | file:// 跳转可行性探针（已验，可删） |
| `archive.html`, `workbench.html` | 两个已交付文件的**实验副本**（已注入链接层） |
| `archive_link.js` | 档案站侧入口（link-0.2，原生锚点） |
| `workbench_link.js` | 工作台侧接收层（link-0.1，含反向 URL 生成预留） |
| `inject_links.py` | 带护栏的注入器（默认拒写已交付文件） |
| `test_link.mjs` | 37 项端到端断言（真实鼠标手势；直接取 node 退出码） |
| `check_*.png` | 两侧页面截图（视觉核对用） |

## 尚未做（下一步候选）

- **反向**（工作台 → 档案站）：`WorkbenchLink.backUrl()` 已预留生成逻辑，未接线未测。
- **L2 查询链接**（把工作台筛选结果送到档案站渲染）：未做。需要 `Playground.relayout/setTargets` 或逐块改样式，是另一轮实验。
- **L3 共享数据层**（消除 kinship 分组双份存储）：等分组核对做完再收。

## 并入正式交付的前提

用户明确要求并入时，把两个链接层脚本与 `inject_links.py` 的调用
（带 `--allow-delivered`，且须确认是用户的要求）作用于真实文件，
并把 `test_link.mjs` 的 MATCH/路径参数化后纳入回归。在此之前**保持隔离**。
