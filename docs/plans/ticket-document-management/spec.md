# AragonTeam 工单文档管理（Ticket Document Management）Spec

- **文档版本**: **v2**（v1 由 Subtask #0 · Solution Architect 产出；v2 由 Subtask #1 · Design Reviewer 评审并就地修复 P0/P1）
- **Feature slug**: `ticket-document-management`
- **轮次**: 第 12 轮迭代（建立在 `scale-and-project-scope` 之上，最新 commit **`d3e21a0`**）
- **本轮需求**: 「需求和 BUG 跟踪流程中缺少文档上传 / 查看 / 编辑 / 绑定环节，应在全流程各环节支持文档管理；界面美观优雅，功能完善稳健可靠。」
- **技术栈（沿用，零新增运行时依赖）**: Next.js 14 App Router + React 18 + TypeScript + Tailwind + @dnd-kit + SWR ｜ Flask 3.0.3 + SQLAlchemy 2.0.31 + SQLite + flask-jwt-extended + Flask-CORS + Werkzeug 3.0.3。
- **目标读者**: 下游实施工程师（须可据此逐行实现，无需再做架构决策）。
- **主题一句话**: **「需求和 BUG 从新建到关闭的每一个环节，都要能上传、查看、编辑、绑定它的文档；
  文档是可复用的一等资源，不是某张单的私有附件；每一次文档动作都进时间线。」**

---

## 评审记录（Review Notes）

> 评审人：Subtask #1 · Design Reviewer（Anthropic Engineering）｜ 评审基线：spec v1 + 现网 `d3e21a0`
> 四维：**可行性 / 完备性 / 一致性 / 尺度**。P0/P1 **已在正文就地修复**（下表「已修复」列给出落点）；P2 记录备查，其中低成本者亦已顺手改掉。
> 评审方法：**逐节复核 + 三支只读代码审计**（后端服务契约、后端路由与工具契约、前端契约），全部基于现网源码逐行核对，未采信任何未经核实的断言。

**总体判断**：v1 的**架构主干是正确且克制的**——三表分离（Document / DocumentVersion / DocumentLink）
对「一份 PRD 服务多张单」这一真实约束给出了唯一正确的答案；内容寻址存储让路径穿越成为
**结构性不可能**而非「靠清洗函数守住」；门禁默认关闭 + Agent 路径永久豁免这一取舍，
准确复用了 `reliability-hardening` 轮学到的教训。评审员逐条核对了它引用的 **17 处现网事实**
（`can_manage_ticket` 位置、`want_str` 枚举不变量、`allowed` 键分流约定、`_ticket_humans`、
`short_text`、`expose_headers` 已含 `X-Total-Count`、`schema_sync` 对新表无需登记、
`paginate` 的裸数组契约、侧边栏恰 8 项、`signalUnauthorizedIfNeeded` 名称、
`PRAGMA foreign_keys=ON` 生效、pytest 基线 371……），**绝大多数属实**，这在同类文档里是少见的。

问题集中在**「从设计到可运行代码的最后一公里」**：v1 描述了「读前 12 字节嗅探魔数」，
也描述了「把 `file.stream` 交给 `digest_and_persist`」，但**从未把这两句话放在一起想**——
按字面实现，**每一个上传的文件都会丢掉开头 12 字节**，而 §7.2 罗列的 23 条必过用例
**没有任何一条会变红**。这是本次评审最重要的一条发现，定级 P0。其余 11 条 P1 分布在
「新代码亲手带回一个 500」「前端预览路径绕开了 §8 R-2 三道防线中的两道」「计数字段会静默过期」
「引用了不存在的前端类型」等处，均已就地修复。

| # | 维度 | 严重度 | 问题 | 已修复（落点） |
|---|---|---|---|---|
| **R1** | **可行性（致命实现缺口）** | **P0** | **按 v1 字面实现，100% 的上传文件都会被截掉开头 12 字节，且现有测试全绿。** §2.3 闸 4「读前 12 字节与 `_SIGNATURES` 比对」会把 `FileStorage.stream` 的游标推进到 12；§2.9 时序 A 紧接着 `storage.digest_and_persist(file.stream)` **从当前位置**开始读。落盘内容 = 原文件 `[12:]`，摘要基于残缺内容计算，因此**去重、完整性校验、下载全部"自洽地正确"**——`test_upload_creates_document_and_version`（查文件存在）、`test_identical_uploads_share_one_blob`（查副本数）、`test_download_sets_nosniff_and_disposition`（查响应头）**无一会失败**。这是一条**静默的、全量的数据损坏**，且会在实施完成、测试全绿、上线之后才由用户发现「下载下来的 PNG 打不开」 | §2.3 闸 4 补**流位置契约**（嗅探必须 `seek(0)` 复位，`_validate_upload` 出口不变量为「游标恒在 0」）；§2.2 `digest_and_persist` 补入口断言；§2.9 时序 A 显式标出复位步；§7.2 新增 **`test_downloaded_bytes_match_uploaded_bytes`**（字节级往返相等）与 `test_sniffing_does_not_consume_stream` 两条用例——**这两条是本轮唯一能捕获该缺陷的护栏** |
| **R2** | **一致性（与"神圣"的状态机冲突）/ 完备性** | **P1** | **v1 全篇按「需求 6 态」设计，现网需求是 7 态。** 现网 `services/workflow.py:12-20` 的 `REQUIREMENT_TRANSITIONS` 含第 7 个状态 **`bug_fixing`（修复中）**，可由 `testing` 与 `reviewing` 双向进出。v1 的 §0 环节表、§2.4 `STAGE_DOC_EXPECTATIONS`、§7.3-1「全程六个状态」**均遗漏它**，落地后该列的阶段清单会渲染成空白，验收清单也会漏测整整一列。此外 v1 未定义**回退迁移**（`done→reviewing`、`closed→verifying`、`testing→in_development`、`bug_fixing→*`）下门禁的行为——按字面实现，用户想把一张错误 `done` 的单**退回返工**时会被"缺测试报告"挡住，而退回的原因恰恰是材料不合格 | §0 环节表补 `bug_fixing` 行；§2.4 `STAGE_DOC_EXPECTATIONS` 补 `("requirement","bug_fixing")` 与 `stage_label` 全量映射；§2.4 新增**铁律 4「门禁只作用于前进迁移」**（回退与同列不校验）并给出判定式；§7.3-1 改为七个状态；§7.2 新增 `test_gate_never_blocks_backward_move` |
| **R3** | **一致性（CLAUDE.md / 上一轮硬门槛）** | **P1** | **新端点会亲手带回一个 500。** `documents.project_id` 是**真外键**（§5.1），且现网 `extensions.py:_set_sqlite_pragma` 对每条连接执行 `PRAGMA foreign_keys=ON`，外键**在 DB 层真实生效**。v1 的 `POST /api/documents` 接受用户提供的 `project_id` 却**无任何前置校验** → 不存在的 id 触发 `IntegrityError` → 被 `errors.py:46` 兜底处理器渲染成 **500**。同理 `POST …/:id/documents` 的 `json{document_id}` 分支未定义 document 不存在时的响应。这直接违反 `services/lifecycle.py:8-13` 的既定契约（「引用完整性一律前置检查，绝不依赖数据库外键异常兜底」）与上一轮自设的「坏输入零 500」硬门槛 | §2.3 新增**闸 0 · 引用前置校验**，直接复用现网 `routes/requirements.py::_validate_project`（已导出、bugs 蓝图已在用）；§4.1 / §4.2 失败列补 400 / 404；§7.2 新增 `test_bad_project_id_returns_400_not_500` 与 `test_bind_unknown_document_returns_404` |
| **R4** | **完备性（并发正确性）/ 可行性** | **P1** | **内容寻址 + 去重 + 即时回收三者组合存在一个会丢用户文件的竞态，且 GC 工具会删掉正在上传的文件。** ①「commit 后 `delete_blob`」的窗口内，另一个请求可能**去重命中**同一摘要（命中时不写盘）→ 随后 `delete_blob` 删除该文件 → 新版本永久指向空气（用户看到 410）。v1 §2.2 只论证了"先删文件 vs 先提交"的顺序，未意识到去重把这个窗口变成了**真实的丢数据路径**。②§4.4 的 GC 判据是「磁盘上有、`document_versions` 里无人引用」，而 `UPLOAD_DIR/.tmp/*.part` 恰好满足该判据 → `--apply` 会**删除其他进程正在写入的临时文件** | §2.2 重写回收小节：新增 `.tmp/` 排除、**去重命中必须 `os.utime` 触碰**、**宽限窗口 `BLOB_GRACE_SECONDS`（默认 3600）**三条，并把在线删除降级为「只做引用判定、物理删除统一交给 GC」；§4.4 GC 判据补两条排除；§5.3 新增配置项；§7.2 新增 `test_gc_skips_tmp_and_recent_blobs` 与 `test_dedup_touches_blob_mtime` |
| **R5** | **完备性（静默数据销毁）** | **P1** | **两条路径会让用户"编辑一下"就永久毁掉文件内容。** ① §4.1 的 `/content` 响应带 `truncated` 字段，§2.6 的 `is_text_editable` 判据是 `size <= 512KB`，但 v1 **从未把 `read_text` 的 `max_bytes` 与这个 512KB 关联起来**——若 `max_bytes < 512KB`，用户会拿到被截断的正文、编辑、保存，**截断即成为新版本的全部内容**。② `read_text` 规定「UTF-8 失败抛 `NotTextual`」，但本项目面向中文团队，Windows 工具产出的 `.log` / `.csv` 大量是 GBK——若未来放宽为 `errors="replace"` 预览，用户编辑后保存会把每个不可解码字节写成 U+FFFD，**原文件不可逆损毁** | §2.6 重写「编辑」小节：钉死不变量 **`DOC_TEXT_PREVIEW_MAX_BYTES(1MB) > DOC_TEXT_EDIT_MAX_BYTES(512KB)`**、**`truncated == true` ⇒ `editable == false`（前后端各判一次）**、**非 UTF-8 可预览但恒不可编辑**（`encoding_confident: false`）；§4.1 `/content` 响应补 `encoding_confident`；§5.3 补两项配置；§7.2 新增 3 条用例 |
| **R6** | **一致性（安全，自身风险表被绕开）** | **P1** | **§8 R-2 声明的三道 XSS 防线，有两道在 v1 自己的前端预览路径上完全失效。** 三道防线是「扩展名白名单 / `Content-Disposition: attachment` / `nosniff`」，后两道都是**响应头**；而 §2.6 明确要求前端「带 auth 头取 blob → `objectURL`」渲染——`blob:` URL 的 MIME **取自前端 `new Blob(..., {type})` 的入参，与任何响应头无关**，且 `blob:` 文档运行在**前端源**（JWT 就存在该源的 `localStorage["aragon_token"]`，现网 `lib/api.ts:7`）。即三道防线只剩第一道在起作用，而 v1 的风险表把它记成了「三重防线」，会让实施者误以为余量充足 | §2.6 预览小节新增**前端硬规则**：Blob 的 `type` **只能**取自后端 `mime_type` 且**必须**先经 `INLINE_SAFE_MIMES` 白名单过滤，落选一律 `application/octet-stream` 并走下载；PDF 只在 `<iframe sandbox>` 内渲染；**禁止**把 `objectURL` 交给 `window.open` / 顶层导航。§8 R-2 补第 4 道防线并如实改写余量描述；§7.3 新增验收 10 |
| **R7** | **完备性（静默说谎的 UI）** | **P1** | **`document_count` 会立刻过期。** §4.3 把 `document_count` 加到 `GET /requirements`、`GET /bugs`、`GET /board/*`、`GET /{entity}/:id` 四类响应上，§3.5 又让看板卡片据此渲染回形针徽章；但 §2.9 时序 A 的前端收尾**只失效了两个键**（`/requirements/42/documents` 与 `…/feed`）。用户上传文档后，**看板与列表上的徽章仍显示旧数字**，直到下一次整页刷新——这正是上一轮通篇在消灭的「静默说谎的 UI」 | §2.9 时序 A 收尾改为调用 `invalidateTicketViews(mutate)`（现网 `lib/swr-keys.ts:33`，其 `TICKET_VIEW_PREFIXES` 已覆盖 `/requirements`、`/bugs`、`/board/`）；§3.5 澄清 `invalidateDocumentViews` **只负责 `/documents` 前缀**，不重复既有覆盖面（避免制造第二个真相源）；§7.3 新增验收 11 |
| **R8** | **可行性（落点写错 + N+1 无落地方案）** | **P1** | **`document_count` 的实现落点在现网不成立。** ①§3.2 把看板计数记到 `backend/routes/board.py`，但现网 `board.py` 只是 32 行 shim，序列化在 `services/board_page.py:27-55`。②更关键：看板与列表**都只调 `r.to_dict()`**（`models/requirement.py:39` / `models/bug.py:39` 两份独立字面量 dict），`to_dict` **拿不到批量计数**，因此「一次 group-by」在 v1 描述的位置**无法实现**；照字面写只能退化成每行一次子查询，即 §2.1 自己点名要避免的 N+1。③现网 `to_dict` 上**不存在任何 `*_count` 字段**，没有先例可抄；最接近的批量聚合惯用法是 `routes/stats.py:24-33` 的 `func.count + group_by`。④看板一次返回 7 列，"恰好 1 次查询"必须是**整块看板 1 次**而非每列 1 次 | §3.2 落点改为 `backend/services/board_page.py`（并保留 `routes/board.py` **不变**）；§4.3 新增「实现约束」小节：新建 `services/documents/counts.py::link_counts(entity, ids) -> dict[int,int]`，在**序列化站点**以 `{**r.to_dict(), "document_count": counts.get(r.id, 0)}` 富化，**不改任何 `to_dict`**；§7.2 的 `test_document_count_is_single_query` 断言改为「整块看板（7 列）恰好 1 次计数查询」 |
| **R9** | **完备性（现网 a11y 事实冲突）** | **P1** | **抽屉内再开模态，Esc 会同时关掉两层；模态关闭还会解锁抽屉的滚动锁。** 现网 `TicketDrawer.tsx:91-94` 的 Esc 处理器挂在 **`window`** 上，`:96/:99` 又对 `document.body.style.overflow` 做 set/restore。§6.4 要求预览 / 编辑模态「复用抽屉已验证的 a11y 模式」，照做即：按 Esc → 模态与抽屉一起消失（用户丢失上下文，编辑器的二次确认也被绕过）；模态卸载时把 `overflow` 恢复成 `""` → **抽屉仍开着，但页面已能滚动**。v1 对此毫无察觉 | §6.4 a11y 小节重写：新增**层叠契约**——引入 `lib/overlay-stack.ts` 单一层栈，Esc 只交给**栈顶**层处理，滚动锁按**引用计数**加解；抽屉现有的 `window` 监听须改为经该栈判定后才响应；§7.3-7 补「抽屉内开模态按 Esc 只关模态、抽屉仍开、页面仍锁滚」的显式验收 |
| **R10** | **完备性 / 一致性（时间线文案）** | **P1** | **四种新 Activity 在时间线上会渲染成裸英文，且 Agent 提示会刷屏。** ①现网 `lib/constants.ts` 有 `ACTION_LABELS` + `actionLabel()` 兜底映射（`:93/:106`），v1 的 §3.5 列了 `lib/constants.ts` 的三项改动却**漏掉了 `ACTION_LABELS`**——落地后 `doc_attached` / `doc_detached` / `doc_revised` 会在「协作时间线」里以兜底样式出现，而"文档动作进时间线"正是本轮的核心卖点。②§2.4 铁律 2 引入的 `doc_missing_hint` **不在 §2.5 的 Activity 表里**，语义、触发条件、去重策略全未定义；而 Agent 侧 `tick` / `autorun-all` 是**循环调用**（`routes/agents.py:147-240`），照字面实现会**每一次 tick 写一条**，几轮之后时间线被提示淹没。③v1 未说明该提示是否受 `DOC_STAGE_GATE` 约束——若不受约束，默认配置下所有项目立刻开始刷提示 | §2.5 Activity 表补 `doc_missing_hint` 行（含中文模板、不发通知）；§2.4 铁律 2 补三条限定：**仅 `DOC_STAGE_GATE=true` 时写**、**同一 (工单, 目标状态) 只写一次**（写前查最近一条同类 Activity）、**落点唯一**为 `services/agent_runner.py::advance_one`；§3.5 `lib/constants.ts` 明确追加 `ACTION_LABELS` 四项；§7.2 新增 `test_doc_missing_hint_is_deduped` |
| **R11** | **尺度 / 可行性（写锁窗口）** | **P1** | **一次编辑可能引发无界扇出，且全部发生在 SQLite 写锁窗口内。** §2.9 时序 B 规定「对该文档的**每一个** `DocumentLink` 各写一条 `doc_revised` Activity + 通知」。文档复用正是本轮的立身之本，`link_count` 天然可以很大；一份绑了 60 张单的接口契约改一版 = 60 条 Activity + 最多 120 条 Notification，在**同一个事务**里写完。这与 §8 R-7 自己的主张（「把慢操作挪出写锁窗口」）直接矛盾，且 v1 未设任何上限 | §2.5 / §2.9 时序 B 补**扇出上限 `DOC_FANOUT_MAX_LINKS`（默认 20）**：按 `link.id` 升序取前 N 张单写 Activity + 通知，超出部分**只在文档自身写一条汇总 Activity**并在响应体回传 `fanout_truncated: true`（如实告知，不假装全发了）；§5.3 补配置项；§7.2 新增 `test_revise_fanout_is_capped` |
| **R12** | **可行性（前端 typecheck 会直接红）** | **P1** | **§5.4 的三个 interface 引用了不存在的类型。** `Principal` 在现网 `frontend/lib/types.ts`（343 行）中**不存在**——`Principal` 这个标识符全仓库只出现在本 spec 的 §5.4。现网对应形状是 `AssigneeSummary`（`types.ts:25-35`）与 `AuthorSummary`（`types.ts:124-130`）。照抄 §5.4 会让 `npm run typecheck`（§7.1 的硬质量闸之一）**立即失败** | §5.4 三处 `Principal` 全部改为 `AuthorSummary`（文档的 uploader / created_by 语义与「时间线作者」一致，且已含 `type: "user"\|"agent"\|"system"`），并补一句现网出处 |
| R13 | 完备性（Windows 特有） | P2 | §2.2 步骤 4 的 `os.replace(tmp, target)`：两个并发请求首次上传**相同新内容**时会双双未命中去重、双双 replace 同一目标；Windows 下若目标已被另一进程打开读取，`os.replace` 抛 `PermissionError`。CLAUDE.md 明确本项目跑在 Windows | §2.2 步骤 4 补 `try/except (PermissionError, FileExistsError)` → 目标已存在即视为去重命中（内容寻址下二者等价） |
| R14 | 健壮性（启动期） | P2 | §3.2 让 `app.py` 在启动期 `os.makedirs(UPLOAD_DIR)`。只读挂载 / 权限不足时会**让整个应用起不来**——包括与文档毫无关系的登录、看板、Agent。现网 `extensions.py` 处理 WAL 不可用时的取向是「降级但不阻断」 | §3.2 改为「`makedirs` 失败只记 `log.warning` 不阻断启动」；§2.2 补 `StorageUnavailable` → 上传/下载端点返 **503**（其余功能不受影响） |
| R15 | 一致性（分页铁律） | P2 | §4.2 的 `GET …/:id/documents` 返回裸数组 + `X-Total-Count`，却**无 `limit` / `offset`**。上一轮的主题恰是"数据一多翻得到"，新增一个无分页列表是逆行 | §4.2 明确该端点走现网 `services/pagination.py::paginate(q, default_limit=MAX_LIMIT)`（与 `requirements.py:594` 的活动时间线同款） |
| R16 | 一致性（HTTP 语义） | P2 | §4.1 `GET /documents/:id/content` 对非文本返 **409**。409 在本仓库是「状态冲突」的专用码，且前端以「有无 `allowed`」分流 409；此处语义应为 **415 Unsupported Media Type** | §4.1 改为 415；并补 `410`（blob 缺失，与 `/download` 对齐）与 `DELETE` 缺失的 `404` |
| R17 | 完备性（配置细节） | P2 | §3.2 说 CORS「`expose_headers` 追加 `Content-Disposition`」，但未写出现网原值 `["X-Total-Count", "X-Request-Id"]`（`app.py:49-55`）——"追加"若被实现成"替换"，会**打掉全站分页**（前端 `listFetcher` 读 `X-Total-Count`，`lib/api.ts:185`） | §3.2 直接钉死三元素完整列表 |
| R18 | 完备性（测试基线） | P2 | §7.1 的括号「索引记录为 371」措辞像是转述索引而非实测。评审员实测 `python -m pytest --collect-only` = **371**（27 个文件），与之一致；但 CLAUDE.md 写的是「380+」，属**陈旧**。实施者若以 CLAUDE.md 为准会误判基线下降 | §7.1 改为写死"评审实测 371"并注明 CLAUDE.md 的 380+ 已陈旧、以实测为准 |
| R19 | 完备性（DoD 不可达） | P2 | §7.4 要求「`git status` 中无遗留的 `backend/var/uploads` 内容（`.gitignore` 已排除）」，但现网 `.gitignore` **无任何 `var/` 或 uploads 条目**，且 §3.2 的改动清单里**没有 `.gitignore`** → 该 DoD 项按 v1 无法达成 | §3.2 新增 `.gitignore` 一行改动 |
| R20 | 可行性（模型注册细节） | P2 | §3.2 说 `models/__init__.py`「导出三个新模型」，但现网该文件同时维护 `from .x import Y` 与显式 `__all__`（`:6-15` / `:17-28`），**两处都要加**，漏一处则表不进 metadata / 名字导不出 | §3.2 该行补「import 行与 `__all__` 两处均需登记」 |
| R21 | 完备性（派生面澄清） | P2 | 追加 `NOTIFICATION_TYPES` 会牵动 `services/notification_prefs.py:16`、`routes/me.py:177-181`、`NotificationPrefsCard.tsx:10` 三处，v1 只列了最后一处，实施者会怀疑前两处是否漏改 | §3.2 补一句：前两处**由 `NOTIFICATION_TYPES` 派生，无需改动**；只有前端镜像需手改 |
| R22 | 尺度（Non-Goal 缺项） | P2 | §10 未声明**病毒 / 恶意内容扫描**不在范围内。这是文件上传功能最常被追问的一条，不写清楚会在评审与验收里反复被提 | §10 补第 7 条 Non-Goal，并说明缓解取向 |

**P0 / P1 残留**：**0 条**。R1–R12 已全部在正文就地修复；R13–R22 十条 P2 亦已顺手改掉（均为一两句话的成本）。

**评审复核过、确认 v1 正确的关键断言**（记录于此，避免下一轮把它们当成新缺陷重查）：
`can_manage_ticket` 在 `services/auth_helpers.py:58` ✓；`want_str` 的「非必填枚举必须传 `default`」不变量真实存在且写在 docstring 里 ✓；
状态机 409 的 `allowed` 在**响应体顶层**、非 `detail` 内，前端 `ApiError.allowed`（`lib/api.ts:30`）据此分流 ✓；
`_ticket_humans` / `short_text` 名称与语义 ✓；`NOTIFICATION_TYPES` 确在 `models/notification.py` 而非 `services/notifications.py` ✓；
`expose_headers` 已含 `X-Total-Count` ✓；`schema_sync` 对**新增表**无需任何条目（只有新增列才要登记）✓；
`paginate` 的裸数组 + `X-Total-Count` 契约 ✓；侧边栏现恰 8 项，文档页为第 9 项 ✓；
`signalUnauthorizedIfNeeded` 名称与 401 全局登出语义 ✓；`ProgressBar` / `formatBytes` 确不存在、需新建 ✓；
门禁插桩点「`can_transition` 判 True 之后、`req.status = to` 之前」对应现网 `routes/requirements.py:376→378` ✓。

---

## 0. 立场：为什么本轮是「文档」

把前十轮的成果摆在一起看，AragonTeam 今天已经能把**状态**流转得很好：邻接表状态机、
人/Agent 混合推进、看板拖拽、通知扇出、项目作用域、分页检索、生命周期治理、真实 LLM 执行。
但一个真实研发团队跑一张需求单时，流转的从来不只是状态，还有**交付物**：

| 环节（需求） | 现实中必然产生的文档 | 今天系统里的落点 |
|---|---|---|
| new / assigned | 需求说明书、原型图、竞品截图 | **无**（只能贴进 description 或评论正文） |
| in_development | 技术方案、接口契约、DB 设计 | **无** |
| testing | 测试用例、测试计划 | **无** |
| bug_fixing | 缺陷清单、修复说明 | **无** |
| reviewing / done | 测试报告、验收单、发布说明 | **无** |
| BUG open / assigned | 复现录屏、崩溃日志、堆栈截图 | **无** |
| BUG verifying / closed | 回归验证报告 | **无** |

结论很直接：**这套系统目前无法承载研发协作里体量最大的那一类信息**。用户只有两条退路——
把内容硬塞进 `description`（Text 列，无版本、无格式、无法下载），或者贴一个外部网盘链接
（链接会失效、权限对不上、离开系统就断了审计）。两条都不是「文档管理」，只是绕开它。

再往下看一层，缺的不是「附件上传」这一个功能点，而是**四个彼此独立的能力**，缺一个整条链就断：

| 能力 | 缺失时的真实后果 |
|---|---|
| **上传** | 交付物进不了系统 |
| **查看**（预览 / 下载 / 版本history） | 传进来了也看不了，等于只是个黑盒二进制 |
| **编辑** | 方案改一版就要重新传一个「xx_final_v2_真的最终版.md」，版本关系全靠文件名猜 |
| **绑定** | 一份 PRD 明明服务 5 张需求单，却要传 5 份；改一次要改 5 处；删单时不知道能不能删文件 |

本轮把这四条一次补齐，并且**贯穿全流程**：文档不是详情页角落里的一个附件列表，而是
①在**每一个状态**上都能被添加、②被添加时**记录当时所处的环节**、③每一次动作都写进
**协作时间线**、④每个环节都有一份**阶段文档清单**告诉用户「这一步通常应该有什么」。

本轮的四个缺陷类：

| 类 | 级别 | 一句话 |
|---|---|---|
| **A** | P0 | 系统无任何文件存储能力：需求 / BUG 的交付物完全无处安放 |
| **B** | P0 | 无「文档」这一实体：无法查看、无法编辑、无版本、无审计 |
| **C** | P1 | 无绑定关系：文档天然多对多复用，塞进工单的附件字段就永远复用不了 |
| **D** | P1 | 流程无文档感知：状态推进时没有任何「这一步该有什么材料」的提示与留痕 |

---

## 1. Overview（概述）

本轮为 AragonTeam 引入**文档（Document）**这一新的一等领域实体，以及围绕它的完整生命周期：
上传 → 预览 / 下载 → 在线编辑（产生新版本）→ 绑定到需求 / BUG → 解除绑定 → 删除。
文档独立于工单存在于「文档库」中，通过**绑定关系（DocumentLink）**与任意数量的需求、BUG
建立多对多关联。这一刀切在这里，是因为现实里文档与工单本就不是从属关系：一份 PRD 服务一簇
需求，一份回归测试报告同时关掉三个 BUG，一份接口契约被需求和 BUG 双向引用。把文档做成工单的
私有附件，等于在第一天就把复用能力焊死。

在存储上，本轮采用**本地内容寻址存储（content-addressed storage）**：文件按 SHA-256 摘要
落盘到 `UPLOAD_DIR/<ab>/<cd>/<digest>`，元数据（原始文件名、MIME、大小、上传人、版本号、备注）
全部进数据库。这样做同时拿下三件事：**去重**（同一份文件被不同人传 10 次只占一份磁盘）、
**防路径穿越**（落盘路径由摘要推导，与用户提供的文件名完全无关）、**可校验**（摘要即完整性签名）。
本轮**不引入任何第三方依赖**——不上 boto3、不上 python-magic、不上 Alembic——与项目既有的
「LLM 层只用 stdlib urllib」同一条价值观：能用标准库解决的边界，不为它增加供应链与许可证风险。

在流程贯通上，本轮做三件事。其一，**绑定时快照当时的工单状态**（`document_links.stage`），
于是「这份测试报告是在测试中阶段交的，还是在验收后补的」这一问题永远有答案。其二，
**每一次文档动作写 Activity**，直接流进既有的合并 feed，抽屉时间线因此天然覆盖文档事件，
无需前端做任何合并逻辑。其三，引入 **`services/doc_policy.py` 阶段文档清单**：为每个
（实体, 状态）声明「这一步通常应该有哪几类文档」，前端在看板与抽屉里渲染为**建议性清单**，
默认**绝不阻断**任何流转；仅当运维显式打开 `DOC_STAGE_GATE=true` 时，人类推进才会在材料
不齐时收到 409。这条默认关闭的开关是刻意的：一个默认强制的门禁会让存量数据全线卡死，
而 Agent 自动流水线会**静默死锁**在一个没人看得见的地方。

一条硬约束贯穿全篇：**状态机是神圣的**。本轮不给 `services/workflow.py` 增加任何一行——
文档门禁是在 `can_transition` 判定为合法**之后、写入之前**的一次独立前置检查，它只会让
一次合法迁移被拒绝，永远不会让一次非法迁移被放行。同样地，本轮**不修改任何既有表的任何列**，
只新增三张全新表，因此 `services/schema_sync.py::ADDITIVE_COLUMNS` 无需登记任何条目
（与 `notifications`、`seed_records` 两轮的处理逐字一致）。

---

## 2. 技术设计（Technical Design）

### 2.1 领域模型：三分而非一表

```
Document (文档，逻辑实体)          DocumentVersion (版本，物理实体)
  id, title, kind, description       id, document_id, version_no
  project_id, uploader_id            original_filename, mime_type
  current_version_id  ────────────►  size_bytes, sha256, note
  created_at, updated_at             uploader_id, created_at
        │
        │  1 : N
        ▼
DocumentLink (绑定关系)
  id, document_id, entity_type(requirement|bug), entity_id
  label, stage(绑定时的工单状态快照), created_by_id, created_at
  UNIQUE(document_id, entity_type, entity_id)
```

**为什么必须三张表而不是一张 `attachments`：**

- 一张表意味着「同一份文件绑 5 张单」要存 5 行、5 份磁盘副本，改名要改 5 处——这正是
  需要被消灭的问题本身。
- 「编辑」如果不产生新版本行，就只能覆盖原文件，历史直接消失；而研发文档的价值有一半
  在版本对比上。
- `current_version_id` 冗余在 `Document` 上，是为了让列表页「一次查询拿到当前版本」，
  避免每行一次子查询（列表页 50 行 = 50 次往返，正是 `_next_position` 那一类问题）。
  它由 `service.add_version()` 单点维护，不允许任何其他代码路径写。

**多态照旧不建 DB 外键**：`document_links.(entity_type, entity_id)` 与既有
`comments` / `activities` / `notifications` 同策略——SQLite 无法为多态引用建约束，
且真外键会让「删掉一张需求单」这一合法操作被外键挡住。引用完整性由应用层前置检查保证
（`services/lifecycle.py` 的既定契约）。`document_versions.document_id` 与
`documents.project_id` / `uploader_id` **建真外键**（单态，且语义上确实不允许悬挂）。

### 2.2 存储层：内容寻址 + 去重 + 后提交回收

`services/documents/storage.py` 是唯一接触文件系统的模块，对外只暴露六个函数：

```python
def digest_and_persist(stream) -> BlobInfo          # 落盘并返回 (sha256, size_bytes, deduped)
def blob_path(sha256: str) -> Path                  # 摘要 → 绝对路径
def open_blob(sha256: str) -> BinaryIO              # 读；缺失抛 BlobMissing
def read_text(sha256: str, max_bytes: int) -> TextRead  # 见 §2.6：带 truncated / encoding_confident
def delete_blob(sha256: str) -> bool                # 物理删除，幂等（不存在返回 False）
def is_reapable(path: Path, now: float) -> bool     # 【评审 R4】GC 可回收性判定，见下
```

模块内所有函数在 `UPLOAD_DIR` 不可写时抛 `StorageUnavailable`；路由层把它映射为 **503**
（`{"error": "document storage is unavailable"}`），**而不是 500**——这是运维问题，不是代码缺陷，
用户与告警系统都应该看到二者的区别。【评审 R14】

**落盘算法**（`digest_and_persist`，实现要点逐条）：

0. **【评审 R1 · P0】入口契约**：本函数**假定 `stream` 的游标在 0**，并在入口以
   `assert stream.tell() == 0`（或等价的显式检查）**断言**之。理由见 §2.3 闸 4——
   上游的魔数嗅探会推进游标，一旦它忘记复位，本函数会静默地把文件开头若干字节丢掉，
   而摘要、去重、下载**全部自洽地正确**，没有任何一条既有断言会失败。
   这个断言是该缺陷唯一的运行期护栏，**不得以「理论上不会发生」为由省略**。
1. 先写到 `UPLOAD_DIR/.tmp/<uuid4>.part`，边写边用 `hashlib.sha256` 增量更新，边累加字节数。
   分块大小 `64 * 1024`。**绝不 `stream.read()` 一次读进内存**——20 MB 上限乘以并发就是 OOM。
2. 写满后计算最终摘要，目标路径 `UPLOAD_DIR/<d[0:2]>/<d[2:4]>/<d>`。
3. 目标已存在（**去重命中**）→ `os.remove(tmp)`；**必须先 `os.utime(target, None)` 触碰
   目标的 mtime**，再返回 `BlobInfo(sha256, size, deduped=True)`。
   【评审 R4】这一次 `utime` 不是可有可无的整洁动作，它是下面宽限窗口判据的**唯一输入**：
   去重命中时不写盘，若不触碰 mtime，一个"很久以前落盘、刚刚被复用"的 blob 在 GC 眼里
   与"很久以前落盘、早已无人引用"完全一样。
4. 不存在 → `os.makedirs(parent, exist_ok=True)` + `os.replace(tmp, target)`。`os.replace`
   在同一文件系统内是原子的，因此**永远不存在半个文件被别的请求读到**的窗口。
   **【评审 R13】该调用必须包在 `try/except (PermissionError, FileExistsError)` 内**：
   两个并发请求首次上传相同内容时会双双走到这一步，而 Windows 下若目标此刻正被另一进程
   打开读取，`os.replace` 会抛 `PermissionError`。捕获后**按去重命中处理**（内容寻址下
   "目标已存在"与"我刚写成功"在语义上完全等价），并清理自己的 `.part`。
5. 任何异常路径都在 `finally` 里清理 `.part` 临时文件。

**回收（GC）：在线路径只做判定，物理删除统一交给宽限窗口**【评审 R4 · P1 重写】

v1 的原方案是「commit 之后调 `delete_blob()`」。这个顺序本身是对的（先删文件再回滚 →
数据库留下指向空气的版本记录；先提交再删文件失败 → 只留一个孤儿文件，可离线回收；
**在两种失败模式之间永远选可修复的那个**），但它**漏掉了去重带来的第三种失败模式**：

> 请求 A 删除了引用摘要 `X` 的最后一个版本 → commit → 正准备 `delete_blob(X)`；
> 此刻请求 B 上传了内容恰好为 `X` 的文件 → **去重命中，不写盘**，只插一行版本记录 →
> 请求 A 的 `delete_blob(X)` 执行 → **请求 B 的文件从此指向空气**，用户永远得到 410。

这不是理论窗口：文档复用正是本轮的立身之本，同一份文件被不同人重复上传是**预期高频行为**。
因此在线删除路径**不再直接删文件**，改为：

1. 事务内算出「本次删除后 `document_versions` 中不再有任何行引用的摘要集合」；
2. `db.session.commit()`；
3. 对每个摘要调用 `storage.delete_blob(sha256)`，而 `delete_blob` **内部先做可回收性判定
   `is_reapable`**，不满足则直接返回 `False`（留给离线 GC 下一轮处理）。

`is_reapable(path, now)` 的三条判据（**在线删除与 `tools/gc_orphan_blobs.py` 共用同一个函数，
不允许两处各写一份**）：

- 路径**不在** `UPLOAD_DIR/.tmp/` 下 —— `.part` 是别的进程**正在写**的临时文件，
  它天然满足"磁盘上有、`document_versions` 里无人引用"，按 v1 的判据会被 `--apply` **直接删掉**，
  表现为并发上传随机失败。
- 路径**符合** `<2 hex>/<2 hex>/<64 hex>` 的内容寻址形状 —— 形状不符的一律不碰
  （运维手工放进去的文件、备份、`README`，都不该被工具删）。
- `now - path.stat().st_mtime >= BLOB_GRACE_SECONDS`（默认 3600）—— 这一条与步骤 3 的
  `os.utime` 配对，把上面那个竞态窗口从"毫秒级不可控"变成"一小时级且可配"。

`delete_blob` 的失败（含判定不通过）**只记 `log.warning`，绝不向上抛**——文件系统的临时故障
不该让一次已经成功提交的删除对用户显示为失败；漏删的代价只是磁盘多占几 MB，且下一轮 GC 会收走。

### 2.3 上传边界：五道闸，全部在边界一次性完成

`services/documents/service.py::create_document()` 与 `add_version()` 共用
`_validate_upload(file_storage) -> UploadCandidate`，各闸依次执行，任一不过即
`ValidationError`（→ 全局 400，绝不 500）。

**`_validate_upload` 的出口不变量（【评审 R1 · P0】）**：函数返回时，
**`file_storage.stream` 的游标必须恒为 0**。闸 4 会读走开头若干字节，因此闸 4 结束时
**必须** `file_storage.stream.seek(0)`；该复位写在 `finally` 里，异常路径同样成立。
这条不变量与 `storage.digest_and_persist` 的入口断言（§2.2 步骤 0）**互为对照**，
二者缺一，本轮就会以"测试全绿 + 每个文件都损坏"的形式上线。

**闸 0 · 引用前置校验（【评审 R3 · P1】新增）**：请求里所有指向既有行的 id，
在**进入任何写入之前**逐个校验存在性，**绝不依赖数据库外键异常兜底**：

- `project_id`（`POST /api/documents` 的表单字段）→ 直接复用现网
  `routes/requirements.py::_validate_project`（已被 `routes/bugs.py` 跨蓝图导入使用），
  不存在返 **400** `{"error": "project not found"}`。
- `document_id`（`POST /api/{entity}/:id/documents` 的 JSON 绑定分支）→ 不存在返 **404**
  `{"error": "document not found"}`。
- `version_id`（`?version_id=` 查询串）→ 不属于本文档或不存在返 **404**。

这一闸不是防御性冗余，而是硬性契约：`documents.project_id` / `document_versions.document_id`
是**真外键**（§5.1），且现网 `extensions.py::_set_sqlite_pragma` 对**每一条** SQLite 连接执行
`PRAGMA foreign_keys=ON` —— 外键在 DB 层真实生效。少了这一闸，一个不存在的 `project_id`
会触发 `IntegrityError`，被 `errors.py` 的兜底处理器渲染成 **500**，直接违反
`services/lifecycle.py` 开篇的既定契约与上一轮自设的「坏输入零 500」硬门槛。

1. **存在性**：`request.files.get("file")` 为空 / `filename` 为空 → 400
   `{"error": "file is required", "detail": {"field": "file"}}`。
2. **文件名清洗**：`werkzeug.utils.secure_filename` 取基名；结果为空（如全中文名被清成空串）
   → 回退为 `upload`。**清洗结果只用于展示**（`original_filename`），落盘路径不使用它，
   所以路径穿越在本设计里是**结构性不可能**，而不是靠清洗函数守住的。
   `original_filename` 保留用户原始文件名（含中文），仅截断到 255 字符。
3. **扩展名白名单**：取 `filename.rsplit(".", 1)[-1].lower()`，必须 ∈ `ALLOWED_EXTENSIONS`
   （配置项，默认见 §5.3）。不在名单 → 400，`detail.allowed` 回传名单，前端直接提示。
   **`Content-Type` 请求头一律不信任**：MIME 由扩展名经 `_MIME_BY_EXT` 表推导。
4. **魔数嗅探**：读前 12 字节与 `_SIGNATURES` 表比对，**读完立即 `stream.seek(0)`**（见上方
   出口不变量；复位写在 `finally` 里）。仅对**在 `_SIGNATURES` 表中登记了**扩展名的类型校验
   （PNG `\x89PNG`、JPEG `\xff\xd8\xff`、GIF `GIF8`、PDF `%PDF-`、WEBP `RIFF….WEBP`、
   zip 系 `PK\x03\x04`——docx/xlsx/pptx/zip 共用）。
   **未登记的扩展名一律放行**，这是明确的兜底规则而非疏漏：纯文本类（md/txt/log/csv/json/yaml）
   本就无签名，强行猜只会误伤；`doc/xls/ppt` 是 OLE2 复合文档（`\xd0\xcf\x11\xe0`），
   与更早的其他格式共用同一签名，判定价值低于误伤成本，故**同样不登记、一律放行**。
   零字节文件（读不满 12 字节）视为无签名，放行。
   签名与扩展名冲突 → 400 `{"error": "file content does not match its extension"}`。
   **这一闸的目的不是防杀毒**，而是防「把 .html 改名成 .png 上传，再骗浏览器 inline 渲染」。

**大小上限**由 Flask 的 `MAX_CONTENT_LENGTH` 在**进入路由之前**拦截，因此超大文件不会
被读进进程。代价是 werkzeug 抛 `RequestEntityTooLarge`，被既有 `HTTPException` 处理器渲染成
`{"error": "Request Entity Too Large", ...}`——文案对用户毫无意义。故 `errors.py` **必须**
新增一个专门的处理器（§3 表），回传 `{"error": "file too large", "detail": {"max_mb": N}}`，
状态码 413。

### 2.4 全流程贯通：stage 快照 + 阶段清单 + 可选门禁

**stage 快照**：`POST /api/{entity}/:id/documents` 落 `DocumentLink` 时，把
`ticket.status` 原样写进 `link.stage`。它是**历史事实的快照**，工单后续流转**绝不回写**它。
于是时间线可以说出「这份测试报告是在 `testing` 阶段交的」，而不只是「有个文件」。

**阶段清单**（`services/doc_policy.py`）：

```python
# 【评审 R2】键必须覆盖 workflow.py 的全部状态。现网需求是 **7 态**（含 bug_fixing），
# 不是 6 态；此表按 services/workflow.py:12-20 / :34-40 逐字对齐，落一个状态，
# 前端该列的阶段清单就会渲染成空白。
STAGE_DOC_EXPECTATIONS: dict[tuple[str, str], tuple[str, ...]] = {
    ("requirement", "new"):            (),                                # 刚建单，不期望材料
    ("requirement", "assigned"):       ("requirement_spec",),
    ("requirement", "in_development"): ("requirement_spec", "design"),
    ("requirement", "testing"):        ("test_plan",),
    ("requirement", "bug_fixing"):     ("bug_evidence",),                 # 【评审 R2】v1 遗漏
    ("requirement", "reviewing"):      ("test_report",),
    ("requirement", "done"):           ("test_report",),
    ("bug", "open"):                   (),
    ("bug", "assigned"):               ("bug_evidence",),
    ("bug", "fixing"):                 ("bug_evidence",),
    ("bug", "verifying"):              ("test_report",),
    ("bug", "closed"):                 ("test_report",),
}
```

`stage_label`（§4.2 响应字段）**不另建映射**，直接取现网 `workflow.REQUIREMENT_COLUMNS` /
`BUG_COLUMNS` 的中文标题（`新建 / 已指派 / 开发中 / 测试中 / 修复中 / 审批中 / 已完成`、
`新建 / 已指派 / 修复中 / 验证中 / 已关闭`）——两处各写一份中文名，迟早会漂移。

`checklist(entity, ticket) -> dict` 的判定口径是**该工单当前绑定的全部文档的 kind 集合**，
而不是「在这个阶段绑定的文档」。理由：一份在 `assigned` 阶段交的需求说明书，到了
`in_development` 依然满足要求；按阶段切分会逼用户为每个阶段重传同一份文件，把设计的初衷
（复用）亲手废掉。

**门禁**（`gate_transition(entity, ticket, to_status) -> tuple | None`）四条铁律：

1. 只在 `current_app.config["DOC_STAGE_GATE"]` 为真时生效；默认 `False`，
   因此**默认行为与本轮之前逐字节相同**，存量库、存量测试零影响。
2. 只作用于**人类主动推进**（`PATCH /move`）。`agent-advance` / `autorun` / `tick` /
   `claim-next` **一律不受门禁约束**——Agent 是后台循环，被门禁挡住会表现为「自动流水线
   莫名其妙不动了」，而没有任何一个人会收到这个 409。Agent 路径改为写一条
   **建议性 Activity**（`action="doc_missing_hint"`），把缺口留在时间线上给人看。
   **该提示受三条限定（【评审 R10 · P1】）**，否则它自己会变成新的噪音源：
   - **仅当 `DOC_STAGE_GATE=true` 时才写**。开关关闭时阶段清单是纯建议性的，
     没有任何理由往每一张单的时间线里塞一条"你少了个文件"。
   - **同一 (工单, 目标状态) 只写一次**：写入前查该工单最近一条 `doc_missing_hint`，
     若其 `detail` 中的目标状态相同则跳过。现网 `tick` / `autorun-all`
     （`routes/agents.py:147-240`）是**循环调用**，不去重就会每一轮写一条，几分钟内淹没时间线。
   - **落点唯一**为 `services/agent_runner.py::advance_one`（现网唯一一处为 Agent 改写
     `ticket.status` 的代码，`agent_runner.py:115-116`）。v1 写的"在 `advance_one` 外层"
     是歧义的——其外层有 `_advance_with_handoff` / `do_agent_advance` / `_agent_run_all` /
     `agent_autopilot.autorun` 四层，写在哪一层会得到完全不同的触发频率。
3. 返回体是 409 且**不带 `allowed` 键**——前端看板拖拽以 `err.allowed` 是否存在区分
   「状态机非法」与「其他冲突」，带上会被误分流（`services/lifecycle.py` 开篇的同一条约定）。
   经评审核实：现网状态机 409 把 `allowed` 放在**响应体顶层**（`routes/requirements.py:371-376`），
   前端 `ApiError.allowed`（`lib/api.ts:30`）据此分流，本条约定成立。
4. **只作用于「前进」迁移（【评审 R2 · P1】新增）**。判定式：
   `to_status` 在该实体的 `column_keys()` 顺序中**严格靠后于** `ticket.status`，
   否则 `gate_transition` 直接返回 `None`。
   理由是行为性的：现网状态机允许 `done → reviewing`、`closed → verifying`、
   `reviewing → bug_fixing`、`testing → in_development` 等**回退**迁移，而用户按下回退键的
   原因**恰恰是材料不合格**。若门禁在回退时也生效，就会出现「因为缺测试报告，所以你不能把
   这张误标为已完成的单退回去补测试报告」这种死结。同理，`frm == to` 的同列拖拽
   （现网 `routes/requirements.py:358-368` 的早返回分支）在门禁之前就已返回，天然不受影响。

调用点在 `routes/requirements.py::move_requirement` 与 `routes/bugs.py::move_bug` 中
（**两处都要挂**，`bugs.py` 只复用 `check_concurrency` 等助手，`move` 的主体是各自独立的），
位置**严格**是：`can_transition` 判 True 之后、`req.status = to` 之前
（现网对应 `routes/requirements.py:376` 与 `:378` 之间）。这保证门禁只能否决合法迁移，
永远无法放行非法迁移——状态机仍是唯一的迁移仲裁者。

### 2.5 时间线与通知接入

| 动作 | Activity.action | message 模板 | 通知 |
|---|---|---|---|
| 上传并绑定 | `doc_attached` | `在「{stage中文名}」阶段上传文档「{title}」` | `document_added` |
| 绑定已有 | `doc_attached` | `绑定了文档「{title}」` | `document_added` |
| 解除绑定 | `doc_detached` | `解除了文档「{title}」的绑定` | 不发 |
| 新版本 | `doc_revised` | `将文档「{title}」更新到 v{n}` | `document_added` |
| 阶段材料缺口提示 | `doc_missing_hint` | `推进到「{stage中文名}」通常需要：{缺失类型中文名列表}` | 不发 |

**【评审 R10 · P1】** 上表第 5 行由 §2.4 铁律 2 引入，v1 遗漏，此处补齐：它由 Agent 路径写入、
不发通知（Agent 的自言自语不该变成人的未读红点），且受铁律 2 的三条限定约束。

**四个新 action 必须同时登记进前端 `lib/constants.ts::ACTION_LABELS`**
（现网 `:93`，配 `actionLabel()` 兜底访问器 `:106`）。漏登记不会报错——`actionLabel()` 会静默
回退到兜底文案——于是「文档动作进时间线」这个本轮的核心卖点，会以一串裸英文 action 名
呈现给用户。v1 的 §3.5 列了 `lib/constants.ts` 的三项改动却恰好漏了这一项。

**扇出上限（【评审 R11 · P1】新增）**：`doc_revised` 需要为**该文档的每一个 `DocumentLink`**
写 Activity 与通知。文档复用正是本轮的立身之本，`link_count` 天然可以很大——一份绑了 60 张单的
接口契约改一版，就是 60 条 Activity + 最多 120 条 Notification **写在同一个事务里**，
而 SQLite 是单写者，这与 §8 R-7 自己的主张（把慢操作挪出写锁窗口）直接矛盾。故：

- 按 `link.id` 升序取前 **`DOC_FANOUT_MAX_LINKS`**（配置项，默认 20）张单写 Activity + 通知；
- 超出部分**不静默丢弃**：在文档自身写一条汇总 Activity，并在 201 响应体回传
  `{"fanout_truncated": true, "fanout_written": 20, "link_count": 60}`。
  如实告知是这个产品一贯的态度——假装 60 条都发了，比只发 20 条更糟。

`Activity.log` 已自带 255 截断，标题另经 `notifications.short_text()` 收到 40 字，
双保险与既有写法一致。通知走新的 `notifications.notify_document(ticket, entity, doc, actor)`，
收件人 = `_ticket_humans(ticket)`（reporter + 人类 assignee），复用既有的「不给自己发 /
不给 Agent 发 / 停用用户不落库 / 偏好闸」四条跳过条件——**一行都不用重写**。

`NOTIFICATION_TYPES`（现网在 `backend/models/notification.py:11-18`，**不在** `services/notifications.py`）
追加 `"document_added"`。因 `NotificationPreference` 采用「无行 = 开启」，
存量用户**零回填**即自动收到该类通知，这与该表设计时的初衷一致。

**【评审 R21】该常量的下游派生面**（写在这里，免得实施者逐个去猜要不要改）：
`services/notification_prefs.py:16` 与 `routes/me.py:177-181` 都是**从 `NOTIFICATION_TYPES`
派生**的（前者算有效偏好映射，后者做校验），**无需任何改动**；
唯一需要手改的是前端镜像 `components/settings/NotificationPrefsCard.tsx:10`——它按**顺序**
硬编码了一份列表，新类型不加进去就不会出现在设置页的开关列表里。

**解除绑定刻意不发通知**：它是一次收敛性操作（东西变少了），给所有人推一条通知只会制造噪音；
时间线上有留痕，需要追责时查得到，这个强度是合适的。

### 2.6 在线查看与编辑

**查看**分三层，按代价递增：

1. **元数据层**：列表 / 抽屉里直接渲染 kind 徽章、文件名、大小、版本号、上传人、时间——零额外请求。
2. **预览层**：图片 / PDF 经 `GET /documents/:id/download`（带 auth 头，取 blob → `objectURL`）
   在模态里渲染；文本 / Markdown 经 `GET /documents/:id/content` 取文本，以等宽
   `<pre>` 渲染并保留空白。**不引入 Markdown 渲染库**——前端目前零 Markdown 依赖，为一个
   预览功能引入一整套渲染 + XSS 消毒链，收益与风险不成比例（§8 R-6）。
3. **下载层**：任何类型都可下载原文件。

> **【评审 R6 · P1】预览层的前端硬规则——`objectURL` 会绕开 §8 R-2 的两道防线**
>
> §8 R-2 声明了三道 XSS 防线：扩展名白名单、`Content-Disposition` 默认 `attachment`、
> `X-Content-Type-Options: nosniff`。**后两道都是响应头，而 `blob:` URL 与响应头无关**：
> `blob:` 文档的 MIME **完全取自前端 `new Blob(bytes, {type})` 的入参**，且它运行在
> **前端源**——JWT 就存放在该源的 `localStorage["aragon_token"]`（现网 `lib/api.ts:7`）。
> 换句话说，在本设计选定的预览方式下，三道防线**只剩第一道真正在起作用**。
> 因此以下四条是**实施硬约束**，不是建议：
>
> 1. 构造 Blob 的 `type` **只能**来自后端返回的 `mime_type`（数据库字段，非用户可控），
>    **绝不**取自 `Content-Type` 响应头、文件扩展名或用户输入。
> 2. 该 `mime_type` **必须**先经 `INLINE_SAFE_MIMES` 白名单过滤；落选的一律以
>    `application/octet-stream` 构造并**只用于下载**，不进预览容器。
> 3. PDF 只在 **`<iframe sandbox>`**（不含 `allow-same-origin` / `allow-scripts`）内渲染；
>    图片只进 `<img>`；文本只进 `<pre>` 的 `textContent`（**不用** `innerHTML`）。
> 4. **禁止**把 `objectURL` 交给 `window.open()` 或任何顶层导航——那正是把 blob 文档
>    提升为同源顶级文档的唯一路径。每个 `objectURL` 在模态卸载时 `URL.revokeObjectURL`。

**编辑**分两类，界限清晰：

- **元数据编辑**（title / kind / description）：`PATCH /api/documents/:id`，
  带 `expected_updated_at` 乐观并发守卫——**直接复用现网
  `routes/requirements.py::check_concurrency(obj, data)`**（它只依赖 `obj.updated_at`，
  与模型无关，`bugs.py` 已在跨蓝图复用），不另写一份。
- **正文编辑**（仅文本类）：`POST /api/documents/:id/versions`，`Content-Type: application/json`
  且体为 `{content, note, expected_version_id}`。服务端把 `content.encode("utf-8")` 当作
  一次上传走完全相同的落盘链路，产出 `version_no + 1` 的新版本。
  `expected_version_id` 与 `document.current_version_id` 不符 → 409
  `{"error": "document was revised by someone else", "detail": {"current_version_id": N}}`。
  **二进制文档不可在线编辑**——前端据此隐藏「编辑」按钮，后端独立复核（前端隐藏只是收敛，不是权限）。

**【评审 R5 · P1】`editable` 的完整判据——两条会静默销毁用户数据的路径**

v1 把 `is_text_editable` 定义为 `ext ∈ TEXT_EXTENSIONS and size <= 512KB`，同时让 `/content`
响应带一个 `truncated` 字段、让 `read_text` 接受 `max_bytes` 并「UTF-8 失败抛 `NotTextual`」。
这三处**各自都合理，组合起来有两条数据销毁路径**：

1. **截断后保存**：若 `max_bytes < 512KB`，一个 400KB 的文件会被判定为 `editable=true`，
   却只把前 `max_bytes` 字节交给编辑器；用户改一个字保存，**截断即成为新版本的全部内容**，
   原文尾部永久消失（旧版本虽在，但没有任何提示告诉用户发生过什么）。
2. **非 UTF-8 后保存**：本项目面向中文团队，Windows 工具产出的 `.log` / `.csv` 大量是 GBK。
   若为了"能预览"把解码放宽成 `errors="replace"`，用户保存时每个不可解码字节都会被写成
   U+FFFD，**原文件不可逆损毁**。

故钉死如下不变量，三处各判一次（存储层、API 层、UI 层）：

- **`DOC_TEXT_PREVIEW_MAX_BYTES`（默认 1 MB）> `DOC_TEXT_EDIT_MAX_BYTES`（默认 512 KB）**
  —— 编辑阈值以下的文件**在结构上不可能**被截断。二者都是配置项（§5.3），
  且 `doc_policy` 启动期断言前者严格大于后者，改配置改错了立刻起不来。
- `read_text` 返回 `TextRead(content, truncated: bool, encoding_confident: bool)`：
  先尝试严格 UTF-8；失败则以 `errors="replace"` 解码并置 `encoding_confident=False`
  （**可预览**，因为看不到内容对用户毫无价值）。
- **`editable == (ext ∈ TEXT_EXTENSIONS) and (size <= DOC_TEXT_EDIT_MAX_BYTES)
  and (not truncated) and encoding_confident`** —— 四个条件缺一不可。
- **后端在 `POST /versions` 的 JSON 分支里独立复核**：若目标文档的当前版本
  `editable == False`，直接 **409** `{"error": "this document is not editable as text",
  "detail": {"reason": "truncated" | "encoding" | "binary" | "too_large"}}`。
  前端隐藏按钮只是收敛，不是防线。
- 前端编辑器在 `encoding_confident=false` 时显示只读的「该文件不是 UTF-8 编码，可预览、不可在线编辑」
  横幅，并给出下载入口——如实说明原因，而不是让「编辑」按钮神秘消失。

同一个 `POST /versions` 端点吃两种 `Content-Type`（`multipart/form-data` 传新文件、
`application/json` 传新正文），是刻意的：两者产出的东西**完全相同**（一个新版本行 + 一个 blob），
拆成两个端点会得到两份几乎一样的编排代码，正是本仓库反复消灭的那类重复。

### 2.7 RBAC 与可见性

| 动作 | 门禁 | 实现 |
|---|---|---|
| 列表 / 详情 / 下载 / 正文 | 任意已认证用户 | `@jwt_required()` |
| 上传到文档库 | 任意已认证用户 | `@jwt_required()` |
| 编辑元数据 / 新版本 / 删除 | 上传者 或 pm/admin | `can_manage_document()` |
| 绑定 / 解绑到某工单 | `can_manage_ticket(user, ticket)` | 复用既有函数 |

读权限对所有已认证用户开放，是与既有 `GET /api/requirements/:id`（仅 `@jwt_required()`）
**对齐**的结果：工单正文本就人人可读，如果文档比工单更严，用户会立刻发现「我看得到这张单，
却看不到它的附件」，那是更糟的体验不一致。要收紧就该连工单一起收紧，那是另一轮的题目。

`can_manage_document(user, doc)` 新增于 `services/auth_helpers.py`，与 `can_manage_ticket`
并列；前端 `lib/permissions.ts` 加一份镜像 `canManageDocument`（沿用既有「前端镜像后端判据、
后端仍是权威」的模式）。

### 2.8 级联与生命周期

**删工单**（`lifecycle.delete_ticket_cascade`）：新增一步——删除该工单的全部 `DocumentLink`，
返回值追加 `"document_links": N`。经评审核实，现网返回值恰为 3 个键
（`comments` / `notifications` / `activities`，`lifecycle.py:147-151`），本轮**只追加不改动**，
且该函数**不 commit、不 delete ticket 本身**的既有契约不变。
**文档本体绝不删除**：文档可能绑在别的单上；即使没有，它也是用户真实上传的数据，
删掉一张单就静默销毁一份 PRD 是不可接受的。文档随后仍完整躺在文档库里可被检索与重新绑定。
这与 CLAUDE.md「`comments` / `activities` / `notifications` 永不按数量清理」是同一条价值观：
**对用户真实数据的推定必须是保留**。抽屉里的删除确认文案必须如实说明这一点（§6.4）。

**删文档**：若仍有绑定 → 409 `{"error": "document is still linked", "detail": {"links": N,
"hint": "unbind it from the tickets first"}}`（无 `allowed` 键）。pm/admin 可带 `?force=1`
强制删除，此时连同其绑定关系一并删除，并为每个受影响的工单写一条 `doc_detached` 审计。
物理 blob 按 §2.2 的后提交回收。

**删用户 / 删项目**：`documents.uploader_id`、`documents.project_id` 是真外键，
`tools/purge_demo_data.py::_user_references` 需把 `documents` 计入引用计数，
否则一个上传过文档的用户会被判定为可删，然后撞上外键错误 → 被兜底处理器变成 500
（正是该模块开篇声明要避免的失败模式）。

### 2.9 关键调用时序

**时序 A：在「测试中」阶段上传并绑定一份测试报告**

```
前端 DocumentUploadZone (drop file)
  └─► POST /api/requirements/42/documents   multipart{file, title?, kind, label?}
        ├─ _get_entity_or_404 → Requirement#42
        ├─ can_manage_ticket(user, req)                  否 → 403
        ├─ service._validate_upload(file)                闸 0~4，任一不过 → 400/404
        │    └─ 闸 4 嗅探 12 字节后 **file.stream.seek(0)**  ← 【评审 R1】漏此步则文件损坏
        ├─ storage.digest_and_persist(file.stream)       → (sha256, size, deduped)
        │    └─ 入口 assert stream.tell() == 0            ← 【评审 R1】该缺陷的运行期护栏
        ├─ Document(title, kind, project_id=req.project_id, uploader_id=user.id)
        ├─ db.session.flush()                            → doc.id
        ├─ DocumentVersion(document_id=doc.id, version_no=1, sha256=…)
        ├─ db.session.flush(); doc.current_version_id = ver.id
        ├─ DocumentLink(doc.id, "requirement", 42, stage=req.status="testing")
        ├─ Activity.log("requirement", 42, "doc_attached", …)
        ├─ notifications.notify_document(req, "requirement", doc, actor)
        └─ db.session.commit() → 201 {document: {...}, link: {...}}
前端收尾 —— 【评审 R7】**不能只失效那两个键**：
  ├─ mutate(`/requirements/42/documents`)      本抽屉的文档列表
  ├─ mutate(`/requirements/42/feed`)           本抽屉的时间线
  ├─ mutate(`/requirements/42/document-checklist`)  阶段清单的 satisfied 会变
  └─ invalidateTicketViews(mutate)             ← 关键：看板/列表上的 document_count 徽章
```

**为什么最后一行不可省**：§4.3 把 `document_count` 加到了 `GET /requirements`、`GET /bugs`、
`GET /board/*`、`GET /{entity}/:id` 四类响应上，§3.5 又让看板卡片据此渲染回形针徽章。
只失效抽屉自己的两个键，意味着用户上传完文档、关掉抽屉，**看板上的徽章仍是旧数字**，
直到整页刷新——这正是上一轮通篇在消灭的「静默说谎的 UI」。
现网 `lib/swr-keys.ts:33` 的 `invalidateTicketViews` 已覆盖
`/requirements`、`/bugs`、`/board/`、`/stats`、`/me/work`、`/notifications`、`/search`
七个前缀，**直接调用即可，不必新造轮子**。解绑（`doc_detached`）与删除文档同理。

**时序 B：在线编辑一份 Markdown 方案并产生 v3**

```
GET  /api/documents/7/content
     → {content, version_no: 2, version_id: 19,
        truncated: false, encoding_confident: true, editable: true}
（用户在 DocumentTextEditorModal 中编辑）
POST /api/documents/7/versions           json{content, note:"补充降级方案", expected_version_id: 19}
  ├─ can_manage_document(user, doc)               否 → 403
  ├─ 当前版本 editable 复核                        否 → 409 detail.reason   ← 【评审 R5】
  ├─ doc.current_version_id != 19                 → 409（不带 allowed）
  ├─ storage.digest_and_persist(BytesIO(utf8))    → 去重命中则不落新盘（并 utime 触碰）
  ├─ DocumentVersion(version_no=3, …); doc.current_version_id = new.id
  ├─ 取前 DOC_FANOUT_MAX_LINKS 个 DocumentLink 写 doc_revised Activity + 通知  ← 【评审 R11】
  │    超出部分只在文档自身写一条汇总 Activity，响应体带 fanout_truncated
  └─ commit → 201 {document, version, fanout_truncated, fanout_written, link_count}
前端收尾：mutate(文档详情 / 版本历史) + invalidateTicketViews(mutate)   ← 【评审 R7】
```

**时序 C：开启门禁时把需求从 reviewing 拖到 done 但缺测试报告**

```
PATCH /api/requirements/42/move  {status:"done", position:0, expected_updated_at:"…"}
  ├─ can_manage_ticket                             否 → 403
  ├─ want_str/status 合法性                        否 → 400
  ├─ check_concurrency                             不符 → 409(current_updated_at)
  ├─ workflow.can_transition("requirement","reviewing","done")  否 → 409(带 allowed)
  ├─ doc_policy.gate_transition(...)   ← 仅 DOC_STAGE_GATE=true 时
  │     缺 test_report → 409 {"error":"required documents are missing",
  │                            "detail":{"stage":"done","missing":["test_report"],
  │                                      "hint":"attach a test report first"}}   无 allowed
  └─ 通过 → 既有逻辑逐字不变（改状态 / 重编号 / 审计 / 通知 / commit）
```

---

## 3. 文件 / 模块变更计划

### 3.1 后端 · 新建

| 文件 | 意图（一句话） |
|---|---|
| `backend/models/document.py` | `Document` / `DocumentVersion` 模型 + `DOCUMENT_KINDS` 枚举 + `to_dict` |
| `backend/models/document_link.py` | `DocumentLink` 多态绑定模型（含 `stage` 快照与唯一约束） |
| `backend/services/documents/__init__.py` | 门面：re-export `service` 与 `storage` 的公开函数，路由只 import 这里 |
| `backend/services/documents/storage.py` | 唯一接触文件系统的模块：摘要落盘 / 读取 / 文本读 / 物理删除 |
| `backend/services/documents/service.py` | 编排：上传校验、建文档、加版本、绑定、解绑、删除 |
| `backend/services/documents/counts.py` | **【评审 R8】** `link_counts(entity, ids) -> dict[int,int]`：一次 `func.count + group_by + in_()` 批量计数，是 `document_count` 的**唯一**来源 |
| `backend/services/doc_policy.py` | 阶段文档期望表 + `checklist()` + `gate_transition()`（默认关闭）+ 启动期断言预览/编辑阈值大小关系 |
| `backend/routes/documents.py` | 文档库蓝图 `/api/documents`（CRUD / 版本 / 下载 / 正文） |
| `backend/routes/ticket_documents.py` | 工单文档蓝图：`/api/{requirements,bugs}/:id/documents` 与 `/document-checklist` |
| `backend/tools/gc_orphan_blobs.py` | 离线孤儿 blob 回收 CLI（dry-run 默认，`--apply`，退出码同 purge 约定） |

### 3.2 后端 · 修改

| 文件 | 意图（一句话） |
|---|---|
| `backend/models/__init__.py` | 导出三个新模型与 `DOCUMENT_KINDS`。**【评审 R20】`from .x import Y` 行与显式 `__all__` 两处都要登记**（现网 `:6-15` / `:17-28`）：漏前者表不进 metadata，漏后者名字导不出 |
| `backend/models/notification.py` | `NOTIFICATION_TYPES` 追加 `"document_added"`（**注意常量在 models 层，不在 `services/notifications.py`**；下游 `notification_prefs.py` / `routes/me.py` 由其派生，**无需改动**） |
| `backend/config.py` | 新增 `UPLOAD_DIR` / `MAX_UPLOAD_MB` / `MAX_CONTENT_LENGTH` / `DOC_ALLOWED_EXTENSIONS` / `DOC_STAGE_GATE` / `BLOB_GRACE_SECONDS` / `DOC_TEXT_PREVIEW_MAX_BYTES` / `DOC_TEXT_EDIT_MAX_BYTES` / `DOC_FANOUT_MAX_LINKS`（见 §5.3）；`TestConfig` 覆盖为 1 MB 上限。沿用现网 `_env_int` / `_env_bool` 两个既有助手 |
| `backend/app.py` | CORS `expose_headers` **【评审 R17】完整值钉死为 `["X-Total-Count", "X-Request-Id", "Content-Disposition"]`**——现网原值是前两项（`app.py:49-55`），若"追加"被实现成"替换"，前端 `listFetcher`（`lib/api.ts:185`）读不到 `X-Total-Count`，**全站分页当场失效**。启动期 `os.makedirs(UPLOAD_DIR, exist_ok=True)`，**【评审 R14】失败只记 `log.warning` 不阻断启动**（与 `extensions.py` 处理 WAL 不可用时"降级但不阻断"的取向一致）——只读挂载不该让登录、看板、Agent 一起起不来 |
| `backend/errors.py` | 新增 `RequestEntityTooLarge` 处理器 → 413 `{"error":"file too large","detail":{"max_mb":N}}`；新增 `StorageUnavailable` → 503。**注**：现网已有 `HTTPException` catch-all（`errors.py:23-25`），413 今天就会被渲染成 `{"error":"Request Entity Too Large"}`——新增处理器是为了把 `e.name` 换成稳定的领域文案，Flask 会优先匹配更具体的处理器 |
| `backend/routes/__init__.py` | 在顶部 import 并在 `register_blueprints(app)` 内注册 `documents_bp` 与 `ticket_documents_bp`（现网 `:16-30`，app.py 不直接注册蓝图） |
| `backend/routes/requirements.py` | `move` 中插入 `doc_policy.gate_transition`（位置见 §2.4）；列表 / 详情序列化站点富化 `document_count` |
| `backend/routes/bugs.py` | 同上。**`move_bug` 的主体是独立的**（`bugs.py` 只跨蓝图复用 `check_concurrency` 等助手），门禁必须**单独挂一次** |
| `backend/services/board_page.py` | **【评审 R8】** 每列卡片附 `document_count`。**落点是这里，不是 `routes/board.py`**——现网 `board.py` 只是 32 行 shim，序列化在 `board_page.py:27-55`。实现约束见 §4.3 |
| `backend/routes/board.py` | **不变**（此行显式写出，以免实施者按 v1 的错误落点去改这个 shim） |
| `.gitignore` | **【评审 R19】** 新增 `backend/var/`——否则 §7.4 的 DoD「`git status` 中无遗留的上传内容」按 v1 **不可达**（现网 `.gitignore` 无任何 `var/` 或 uploads 条目） |
| `backend/services/lifecycle.py` | `delete_ticket_cascade` 增删链接一步，返回值追加 `"document_links"` |
| `backend/services/notifications.py` | 新增 `notify_document(ticket, entity, doc, actor)` |
| `backend/services/auth_helpers.py` | 新增 `can_manage_document(user, doc)` |
| `backend/tools/purge_demo_data.py` | `_user_references` 计入 `documents`；报告的「未触碰」段落列出文档三表；清理因删单而孤儿的 link |
| `backend/requirements.txt` | **不变**（零新增依赖，此处显式声明以免实施者顺手加包） |
| `backend/seed.py` | **不变**：seed 维持 8 行一类一行，不新增文档种子行（§8 R-5） |
| `backend/services/schema_sync.py` | **不变**：本轮只新增表、不改既有表的列（此条写进 spec 是为了让实施者不必猜） |

### 3.3 后端 · 测试新建

| 文件 | 覆盖 |
|---|---|
| `backend/tests/test_document_storage.py` | **字节级往返相等（R1）**、嗅探不消费流（R1）、摘要一致性、去重、去重触碰 mtime（R4）、原子替换、并发 replace 退化为去重（R13）、临时文件清理、缺失 blob、非 UTF-8 文本 |
| `backend/tests/test_documents.py` | 上传 / 闸 0~4 的 400 与 404（含 **坏 `project_id` → 400 非 500**，R3）/ 413 / 列表分页 / 详情 / PATCH 并发 409 / 删除 409 与 force |
| `backend/tests/test_document_versions.py` | 多版本递增、`current_version_id` 维护、JSON 正文编辑、`expected_version_id` 409、**截断/非 UTF-8 不可编辑（R5）**、**扇出上限（R11）**、下载头 |
| `backend/tests/test_document_links.py` | 绑定 / 重复绑定 / 绑定不存在的文档 → 404（R3）/ 解绑幂等 / stage 快照 / RBAC / 删单级联 / `document_count` 单查询（R8） |
| `backend/tests/test_doc_policy.py` | 清单判定、**七态全覆盖含 `bug_fixing`（R2）**、门禁默认关闭、开启后 409 形状、**回退迁移永不被挡（R2）**、Agent 路径永不被挡、**`doc_missing_hint` 去重（R10）** |
| `backend/tests/test_document_gc.py` | 孤儿 blob 识别、**跳过 `.tmp/` 与宽限窗口内的 blob（R4）**、dry-run 不删、`--apply` 删、退出码 |

### 3.4 前端 · 新建

| 文件 | 意图 |
|---|---|
| `frontend/app/(app)/documents/page.tsx` | 文档库页：筛选（关键词 / 类型 / 项目）+ 分页 50 + 上传入口 |
| `frontend/components/documents/DocumentPanel.tsx` | 抽屉内「文档」区块：清单 + 列表 + 上传区 + 绑定入口 |
| `frontend/components/documents/DocumentUploadZone.tsx` | 拖放 / 点击上传 + 进度条 + 多文件队列 + 去重提示 |
| `frontend/components/documents/DocumentRow.tsx` | 单行：类型徽章、名称、版本、大小、上传人、操作菜单 |
| `frontend/components/documents/DocumentBindModal.tsx` | 从文档库搜索并绑定已有文档（含防重复绑定提示） |
| `frontend/components/documents/DocumentPreviewModal.tsx` | 图片 / PDF / 文本预览 + 下载 + 版本切换 |
| `frontend/components/documents/DocumentTextEditorModal.tsx` | 文本正文在线编辑 → 提交为新版本（带备注） |
| `frontend/components/documents/DocumentVersionTimeline.tsx` | 版本历史（版本号、备注、上传人、时间、下载） |
| `frontend/components/documents/StageChecklist.tsx` | 当前阶段文档清单（已满足 / 缺失，缺失项一键上传） |
| `frontend/components/ui/ProgressBar.tsx` | UI 原语：确定进度条（上传进度复用）。经核实现网 `components/ui/` 无此文件，确需新建 |
| `frontend/lib/overlay-stack.ts` | **【评审 R9】** 全局层栈：`pushLayer/popLayer/isTopLayer(id)` + 滚动锁引用计数。抽屉与所有模态共用，Esc 只由栈顶层消费 |
| `frontend/hooks/useTicketDocuments.ts` | 工单文档列表 + 上传 / 绑定 / 解绑 + 清单，成功后失效 feed |
| `frontend/hooks/useDocumentLibrary.ts` | 文档库分页 / 筛选 / 上传 / 删除 |
| `frontend/hooks/useDocumentContent.ts` | 文本正文读取 + 保存新版本 |

### 3.5 前端 · 修改

| 文件 | 意图 |
|---|---|
| `frontend/lib/api.ts` | 新增 `uploadWithProgress()`（XHR，带 JWT，不手设 `Content-Type`）、`downloadBlob()`、`DOCUMENTS_KEY`；导出 `signalUnauthorizedIfNeeded` 供 XHR 路径复用 |
| `frontend/lib/types.ts` | `DocumentKind` / `DocumentSummary` / `DocumentVersion` / `DocumentLink` / `TicketDocument` / `StageChecklist` |
| `frontend/lib/constants.ts` | `DOCUMENT_KIND_STYLES`（沿用现网 `BadgeStyle {label,bg,fg}` 内联十六进制色的既有写法，**不引入 Tailwind class 体系**）、`documentIcon()`、`formatBytes()`、`NOTIFICATION_LABELS`/`NOTIFICATION_ICONS` 追加 `document_added`、**【评审 R10】`ACTION_LABELS` 追加 `doc_attached` / `doc_detached` / `doc_revised` / `doc_missing_hint` 四项**——漏登记不会报错，只会让时间线显示裸英文 |
| `frontend/lib/swr-keys.ts` | `invalidateDocumentViews(mutate)` **只负责 `/documents` 一个前缀**。**【评审 R7】工单维度的键（`/requirements`、`/bugs`、`/board/`）已被既有 `TICKET_VIEW_PREFIXES` 覆盖**，文档动作后应直接调 `invalidateTicketViews`；再写一份重叠的前缀表就是第二个真相源，正是本文件头部注释警告的事 |
| `frontend/lib/permissions.ts` | `canManageDocument(user, doc)` 镜像后端判据（与既有 `canManageTicket` 并列，沿用「前端镜像、后端权威」模式） |
| `frontend/components/TicketDrawer.tsx` | 嵌入 `StageChecklist` + `DocumentPanel`（置于「协作时间线」之上）；删除确认文案说明「解绑不删文档」；**【评审 R9】现有 `window` 级 Esc 监听（`:91-94`）与 `body.overflow` 锁（`:96/:99`）改为经 `lib/overlay-stack.ts` 判定** |
| `frontend/components/kanban/KanbanCard.tsx` | `document_count > 0` 时显示回形针徽章 |
| `frontend/app/(app)/requirements/page.tsx` · `bugs/page.tsx` | 列表新增文档数列 |
| `frontend/components/layout/Sidebar.tsx` | 导航第 9 项「文档」→ `/documents` |
| `frontend/components/settings/NotificationPrefsCard.tsx` | 新增 `document_added` 开关 |

---

## 4. 接口设计（REST）

统一前提：全部 `@jwt_required()`；错误体恒为 `{error, detail?}`；列表端点响应体为**裸数组**，
总数走 `X-Total-Count`（既有契约，不得为文档破例）。

### 4.1 文档库 `/api/documents`

| 方法 | 路径 | 请求 | 成功 | 失败 |
|---|---|---|---|---|
| POST | `/api/documents` | `multipart`: `file`(必), `title`, `kind`, `description`, `project_id` | 201 `Document` | 400 缺文件/坏扩展/魔数不符/**`project_id` 不存在** · 413 超限 · 503 存储不可用 |
| GET | `/api/documents` | `?q&kind&project_id&uploader_id&limit&offset` | 200 `Document[]` + `X-Total-Count` | 400 坏查询参数 |
| GET | `/api/documents/:id` | — | 200 `DocumentDetail`（含 `versions[]` 与 `links[]`） | 404 |
| PATCH | `/api/documents/:id` | `{title?, kind?, description?, expected_updated_at?}` | 200 `Document` | 400 · 403 · 404 · 409 并发 |
| DELETE | `/api/documents/:id` | `?force=1`（仅 pm/admin） | 204 | 403 · **404** · 409 仍有绑定 |
| POST | `/api/documents/:id/versions` | `multipart{file, note, expected_version_id?}` 或 `json{content, note, expected_version_id}` | 201 `{document, version, fanout_truncated, fanout_written, link_count}` | 400 · 403 · 404 · 409 版本冲突 / **不可编辑** · 413 · 503 |
| GET | `/api/documents/:id/download` | `?version_id=`（缺省取当前版本） | 200 二进制流 | 404（文档/版本不存在）· 410 blob 缺失 |
| GET | `/api/documents/:id/content` | `?version_id=` | 200 `{content, version_id, version_no, truncated, encoding_confident, editable}` | 404 · 410 blob 缺失 · **415 非文本类型** |

**【评审 R16】** `/content` 对非文本返回 **415 Unsupported Media Type**（v1 写的是 409）。
409 在本仓库是「系统状态冲突」的专用码，且前端以「有无 `allowed`」分流 409；
「这个文件根本不是文本」是**请求与资源类型不匹配**，不是状态冲突，混用会污染既有分流逻辑。
`/download` 与 `/content` 在 blob 物理缺失时**统一返 410 Gone**（§8 R-9），二者不得不一致。

**【评审 R5】** `POST /versions` 的 `multipart` 分支同样接受 `expected_version_id`（可选），
语义与 JSON 分支完全一致——同一个端点对两种 `Content-Type` 给出两套并发语义，
是最容易被实施者猜错的地方，故此处显式对齐。

**`Document` 响应形状**（列表与详情共用的基础块）：

```json
{
  "id": 7,
  "title": "支付网关技术方案",
  "kind": "design",
  "description": "含降级方案与灰度计划",
  "project_id": 1,
  "uploader": {"type": "user", "id": 3, "name": "李工"},
  "current_version": {
    "id": 19, "version_no": 2, "original_filename": "payment-design.md",
    "mime_type": "text/markdown", "size_bytes": 8421, "sha256": "9f2c…",
    "note": "补充降级方案", "created_at": "2026-07-20T03:11:02.481Z"
  },
  "link_count": 3,
  "editable": true,
  "created_at": "...", "updated_at": "..."
}
```

**下载响应头**（三条缺一不可）：
`Content-Type` 取自 `mime_type`；`X-Content-Type-Options: nosniff`；
`Content-Disposition` —— MIME ∈ `INLINE_SAFE_MIMES`（`image/png|jpeg|gif|webp`、
`application/pdf`、`text/plain`、`text/markdown`）时为 `inline`，**其余一律 `attachment`**。
`text/html` 与 `image/svg+xml` **不在白名单也不在扩展名白名单**——它们能在同源下执行脚本，
inline 渲染等于给自己开一个存储型 XSS（§8 R-2）。文件名以
`filename*=UTF-8''<percent-encoded>` 形式给出，中文名才不会被截断成乱码。

### 4.2 工单文档 `/api/{requirements|bugs}/:id/documents`

| 方法 | 路径 | 请求 | 成功 | 失败 |
|---|---|---|---|---|
| GET | `…/:id/documents` | `?limit&offset` | 200 `TicketDocument[]` + `X-Total-Count` | 400 坏分页参数 · 404 |
| POST | `…/:id/documents` | `multipart{file,…}`（上传并绑定）或 `json{document_id, label}`（绑定已有） | 201 `{document, link}` | 400 · 403 · 404（工单或 `document_id` 不存在）· 409 已绑定 · 413 · 503 |
| DELETE | `…/:id/documents/:document_id` | — | 204（幂等：未绑定也返回 204） | 403 · 404 工单不存在 |
| GET | `…/:id/document-checklist` | — | 200 `StageChecklist` | 404 |

**【评审 R15】** `GET …/:id/documents` **必须走现网 `services/pagination.py::paginate(q,
default_limit=MAX_LIMIT)`**（与活动时间线 `routes/requirements.py:594` 同款）。
v1 给了 `X-Total-Count` 却没有 `limit`/`offset`，是一个无上限列表——上一轮的主题恰是
「数据一多翻得到」，新增一个无分页端点是逆行。`paginate` 已自带 `limit` 钳位与 `offset` 负值 400，
不必自己写校验。

`TicketDocument` = `Document` + `{"link": {"id": …, "label": "验收报告", "stage": "testing",
"created_by": {...}, "created_at": "..."}}`。

`StageChecklist`：

```json
{
  "entity": "requirement", "entity_id": 42, "stage": "testing",
  "stage_label": "测试中", "enforced": false, "satisfied": false,
  "items": [
    {"kind": "test_plan", "label": "测试计划", "satisfied": false, "document_ids": []},
    {"kind": "requirement_spec", "label": "需求说明", "satisfied": true, "document_ids": [7]}
  ]
}
```

`enforced` 直接把 `DOC_STAGE_GATE` 的真实值告诉前端，UI 据此决定文案是「建议补充」
还是「必须补充，否则无法推进」。**前端绝不自己猜这个开关**。

### 4.3 受影响的既有端点（全部为 additive）

- `GET /api/requirements`、`GET /api/bugs`、`GET /api/board/*`、
  `GET /api/{entity}/:id` → 每个工单对象追加 `"document_count": N`。
- `PATCH /api/{entity}/:id/move` → 门禁开启时可能新增一种 409（`detail.missing`，无 `allowed`），
  且**仅对前进迁移**（§2.4 铁律 4）。
- `DELETE /api/{entity}/:id` → 行为不变，内部多删一批 link。

**`document_count` 的实现约束（【评审 R8 · P1】，v1 未给出可落地方案）**

现网的事实是：看板与两个列表页**都只调 `r.to_dict()`**
（`models/requirement.py:39-54` 与 `models/bug.py:39-55` 是两份独立的字面量 dict，
没有共享序列化器，`to_dict` 上也不存在任何 `*_count` 先例）。`to_dict` 是模型实例方法，
**拿不到批量预取的结果**——因此 v1 说的「一次 group-by 计数」在 v1 指定的位置**无法实现**，
照字面写只能退化成每行一次子查询，即 §2.1 自己点名要消灭的 N+1。落地方式钉死为：

1. `services/documents/counts.py::link_counts(entity: str, ids: list[int]) -> dict[int, int]`
   —— 一次 `db.session.query(DocumentLink.entity_id, func.count(DocumentLink.id))
   .filter(DocumentLink.entity_type == entity, DocumentLink.entity_id.in_(ids))
   .group_by(DocumentLink.entity_id)`。惯用法照抄现网 `routes/stats.py:24-33`。
2. **在序列化站点富化，不改任何 `to_dict`**：
   `counts = link_counts(entity, [r.id for r in rows])`，
   然后 `{**r.to_dict(), "document_count": counts.get(r.id, 0)}`。
   两个 `to_dict` 一行不动，既有 21 个调用方零风险。
3. **看板必须整块一次**：`services/board_page.py` 一次返回 7 列，
   计数要在**收集完全部列的 rows 之后**调一次 `link_counts`，
   **不是每列调一次**。`ids` 只含实际返回的行（该模块有 `column_limit` 截断）。
4. `ids` 为空时直接返回 `{}`，不发查询（SQLite 对空 `IN ()` 的行为不必去赌）。

### 4.4 CLI

```
python backend/tools/gc_orphan_blobs.py [--apply] [--json] [--database-url URL] [--upload-dir DIR]
```
默认 dry-run，只报告可回收文件数与总字节；`--apply` 才真删。
退出码沿用 `purge_demo_data` 约定：`0` 成功 / `1` 前置条件不满足 / `2` 跳过。

**【评审 R4 · P1】回收判据不是「磁盘上有、`document_versions` 里无人引用」这一条。**
按 v1 的字面判据，`UPLOAD_DIR/.tmp/<uuid>.part`——**其他进程正在写入的临时文件**——
恰好满足它，于是 `--apply` 会在并发上传时随机删掉别人写到一半的文件。
本工具与在线删除路径**共用同一个 `storage.is_reapable(path, now)`**（§2.2），三条判据缺一不可：
不在 `.tmp/` 下、路径符合 `<2hex>/<2hex>/<64hex>` 的内容寻址形状、
`mtime` 早于 `now - BLOB_GRACE_SECONDS`。报告中须分别列出
「无人引用但在宽限期内（本轮跳过）」与「本轮实际回收」两个数字——
一个只说自己删了多少、不说自己跳过了多少的清理工具，会让人误以为已经清干净了。

---

## 5. 数据模型

### 5.1 DDL（SQLite 方言；由 `db.create_all()` 建，无需迁移）

```sql
CREATE TABLE documents (
    id                 INTEGER PRIMARY KEY,
    title              VARCHAR(200) NOT NULL,
    kind               VARCHAR(32)  NOT NULL DEFAULT 'other',
    description        TEXT,
    project_id         INTEGER REFERENCES projects(id),
    uploader_id        INTEGER REFERENCES users(id),
    current_version_id INTEGER,                 -- 无 FK：与 document_versions 互相引用会成环
    created_at         DATETIME NOT NULL,
    updated_at         DATETIME NOT NULL
);
CREATE INDEX ix_documents_project ON documents (project_id);
CREATE INDEX ix_documents_kind    ON documents (kind);

CREATE TABLE document_versions (
    id                INTEGER PRIMARY KEY,
    document_id       INTEGER NOT NULL REFERENCES documents(id),
    version_no        INTEGER NOT NULL,
    original_filename VARCHAR(255) NOT NULL,
    mime_type         VARCHAR(128) NOT NULL,
    size_bytes        INTEGER NOT NULL,
    sha256            CHAR(64)     NOT NULL,
    note              VARCHAR(255),
    uploader_id       INTEGER REFERENCES users(id),
    created_at        DATETIME NOT NULL
);
CREATE UNIQUE INDEX uq_docver_doc_no ON document_versions (document_id, version_no);
CREATE INDEX ix_docver_sha           ON document_versions (sha256);   -- 去重与 GC 的唯一依据

CREATE TABLE document_links (
    id            INTEGER PRIMARY KEY,
    document_id   INTEGER NOT NULL REFERENCES documents(id),
    entity_type   VARCHAR(16) NOT NULL,          -- requirement | bug（多态，无 FK）
    entity_id     INTEGER NOT NULL,
    label         VARCHAR(64),
    stage         VARCHAR(24),                   -- 绑定当时的工单状态快照，永不回写
    created_by_id INTEGER REFERENCES users(id),
    created_at    DATETIME NOT NULL
);
CREATE UNIQUE INDEX uq_doclink_doc_entity ON document_links (document_id, entity_type, entity_id);
CREATE INDEX ix_doclink_entity            ON document_links (entity_type, entity_id);
```

`documents.current_version_id` **刻意不建外键**：`documents ↔ document_versions` 双向外键
在 SQLite 下会让「先插文档再插版本」这一必经顺序无法满足（插文档时版本还不存在）。
它由 `service.add_version()` 单点维护，并有测试守卫其始终指向本文档的最大版本号。

`ix_doclink_entity` 是 `document_count` 批量计数与工单文档列表的支撑索引；
`ix_docver_sha` 是去重查询与 GC 扫描的支撑索引——没有它，GC 会退化成全表扫描。

### 5.2 枚举

```python
DOCUMENT_KINDS = (
    "requirement_spec",  # 需求说明
    "design",            # 技术方案
    "test_plan",         # 测试计划
    "test_report",       # 测试 / 验收报告
    "bug_evidence",      # 复现材料（录屏 / 日志 / 截图）
    "release_note",      # 发布说明
    "reference",         # 参考资料
    "other",             # 其他
)
DOCUMENT_LINK_ENTITY_TYPES = ("requirement", "bug")
```

`kind` 走 `want_str(..., choices=DOCUMENT_KINDS, default="other")`。
注意 `services/validation.py::want_str` 的既有不变量：**非必填 + 带 choices 的调用方必须
同时传 `default` 且 `default ∈ choices`**，否则归一后的空串会回退成非法的 `""`。

### 5.3 配置项

| 配置 | 环境变量 | 默认 | 说明 |
|---|---|---|---|
| `UPLOAD_DIR` | `UPLOAD_DIR` | `backend/var/uploads` | blob 根目录；随 `.gitignore` 排除 |
| `MAX_UPLOAD_MB` | `MAX_UPLOAD_MB` | `20` | 单请求体上限 |
| `MAX_CONTENT_LENGTH` | —（派生） | `MAX_UPLOAD_MB × 1024²` | Flask 原生闸，路由前生效 |
| `DOC_ALLOWED_EXTENSIONS` | 同名（逗号分隔） | `md,txt,log,csv,json,yaml,yml,pdf,png,jpg,jpeg,gif,webp,doc,docx,xls,xlsx,ppt,pptx,zip` | 白名单；**不含 html/htm/svg/js** |
| `DOC_STAGE_GATE` | 同名 | `false` | 阶段文档门禁，默认建议不阻断 |
| `BLOB_GRACE_SECONDS` | 同名 | `3600` | **【R4】** blob 回收宽限窗口；与去重时的 `os.utime` 配对，关闭「删除↔去重」竞态 |
| `DOC_TEXT_PREVIEW_MAX_BYTES` | 同名 | `1048576`（1 MB） | **【R5】** `/content` 预览上限；超出则 `truncated=true` |
| `DOC_TEXT_EDIT_MAX_BYTES` | 同名 | `524288`（512 KB） | **【R5】** 在线编辑上限。**启动期断言必须严格小于预览上限**，否则可编辑文件会被截断保存 |
| `DOC_FANOUT_MAX_LINKS` | 同名 | `20` | **【R11】** 单次改版最多向多少张单扇出 Activity + 通知；超出只写汇总 |

配置读取沿用现网 `config.py` 已有的 `_env_int` / `_env_bool` 两个助手（含非法值静默回落），
不新造解析逻辑。

`TestConfig` 覆盖：`MAX_UPLOAD_MB = 1`（让 413 用例只需造 1 MB 数据）。
**`UPLOAD_DIR` 不在 `TestConfig` 上写死**——`TestConfig` 是**类级常量**，全套用例共享一份，
写死就等于所有用例共用一个目录。正确做法是在 conftest 的 app fixture 里，
于 `create_app(TestConfig)` **之后**用 `app.config["UPLOAD_DIR"] = str(tmp_path / "uploads")`
逐用例注入，并在 teardown 删除。**测试绝不允许写进真实的 `backend/var/uploads`**。
`MAX_UPLOAD_MB=1` 会派生出 1 MB 的全局 `MAX_CONTENT_LENGTH`，作用于**全部 371 条既有用例**；
§8 R-12 的断言即为守住这一点。

### 5.4 内存形状（前端）

**【评审 R12 · P1】** v1 的三个 interface 引用了 `Principal` 类型，而它在现网
`frontend/lib/types.ts`（343 行）中**不存在**——`Principal` 这个标识符全仓库只出现在本文档里。
照抄会让 `npm run typecheck`（§7.1 的硬质量闸之一）**立即失败**。现网对应形状是
`AuthorSummary`（`types.ts:124-130`，`{type: "user"|"agent"|"system", id?, name, avatar_color?, kind?}`）
与 `AssigneeSummary`（`types.ts:25-35`）。此处统一采用 **`AuthorSummary`**：文档的
uploader / created_by 语义与「时间线作者」一致，且它已含区分人/Agent/系统所需的 `type` 字段。

```ts
import type { AuthorSummary } from "./types";   // 现网既有类型，勿新造 Principal

export interface DocumentVersion {
  id: number; version_no: number; original_filename: string;
  mime_type: string; size_bytes: number; sha256: string;
  note: string | null; created_at: string;
  uploader: AuthorSummary | null;
}
export interface DocumentSummary {
  id: number; title: string; kind: DocumentKind; description: string | null;
  project_id: number | null; uploader: AuthorSummary | null;
  current_version: DocumentVersion | null;
  link_count: number; editable: boolean;
  created_at: string; updated_at: string;
}
export interface TicketDocument extends DocumentSummary {
  link: { id: number; label: string | null; stage: string | null;
          created_by: AuthorSummary | null; created_at: string };
}
export interface DocumentContent {
  content: string; version_id: number; version_no: number;
  truncated: boolean; encoding_confident: boolean; editable: boolean;   // 【R5】
}
```

---

## 6. 前端设计（信息架构与交互）

### 6.1 三个触点，各司其职

1. **工单抽屉**（主战场）：在「协作时间线」**之上**新增「文档」区块——顺序是刻意的，
   文档是流转的输入，时间线是流转的结果，用户的阅读动线应当先看材料再看过程。
2. **文档库页** `/documents`：跨工单的检索、批量管理、复用来源。侧边栏第 9 项。
3. **看板 / 列表的轻量指示**：回形针 + 数字。**只读**，点击不做任何事（打开工单才是唯一入口），
   避免在看板卡片上堆第二种点击语义。

### 6.2 抽屉内「文档」区块的结构

```
┌ 文档 (3)                                        [＋ 上传]  [🔗 绑定已有] ┐
│ ┌ 本阶段清单 · 测试中 ────────────────────────────────────────────────┐ │
│ │  ✓ 需求说明        ○ 测试计划  ← 缺失项本身即为一个上传按钮          │ │
│ └────────────────────────────────────────────────────────────────────┘ │
│  [设计] payment-design.md          v2 · 8.2 KB · 李工 · 07-18   ⋯      │
│  [证据] repro.png                  v1 · 240 KB · 王工 · 07-19   ⋯      │
│  ── 拖放文件到此处上传，或点击选择 ──                                    │
└────────────────────────────────────────────────────────────────────────┘
```

- **清单区**：`satisfied` 项为柔和的成功色对勾 + 类型名（不喧宾夺主）；缺失项为虚线描边的
  可点击 chip，点击直接打开上传对话框并**预选好该 kind**——把「知道缺什么」与「补上它」
  压缩成一次点击，这是本设计里交互密度最高、也最值得的一处。
- `enforced=false` 时清单标题为「本阶段建议材料」；`true` 时为「本阶段必需材料」并在缺失时
  给出「未补齐将无法推进到下一步」的说明。**同一套组件，两种文案，由后端字段驱动。**
- **行操作菜单**（⋯）：预览 / 下载 / 新版本 / 在线编辑（仅 `editable`）/ 版本历史 / 解除绑定。
  破坏性项（解除绑定）置于分隔线之下并用危险色——与既有 `ConfirmDialog` 的分区惯例一致。

### 6.3 上传交互

- 拖放区在**整个抽屉面板**上监听 `dragover`/`drop`（不只是那条虚线框），拖进来时面板整体
  浮起一层 `clay/8` 的蒙版与提示——用户拖着文件时的目标是「这张单」，不是「那个小方框」。
- 多文件并发上限 3，其余排队；每个文件一行，含 `ProgressBar` + 取消按钮。
- 进度依赖 `XMLHttpRequest.upload.onprogress`（`fetch` 无上传进度事件）。这是
  `lib/api.ts` 需要一个 XHR 分支的**唯一**理由，其余请求继续走 `fetch`。
  该分支必须复用 `signalUnauthorizedIfNeeded`，否则上传路径的 401 不会触发全局登出，
  用户会看到一个永远失败的进度条而不知道自己已经掉线。
- **去重命中**（后端 `deduped=true`）时 toast 文案为「该文件已在库中，已直接绑定」，
  而不是假装上传了一份——如实告知是这个产品一贯的态度。
- 失败态：行内红字 + 「重试」按钮，**不自动重试**（用户的文件、用户的带宽，由用户决定）。

### 6.4 视觉与 a11y 规范

- 全部复用既有设计令牌：`bg` / `surface` / `border` / `ink` / `ink-muted` / `clay`，
  圆角 `rounded-lg`，阴影 `shadow-lift`。**不引入新配色体系**。
- 类型徽章复用 `Badge` 原语，`DOCUMENT_KIND_STYLES` 给 8 个 kind 各配一组低饱和底色 + 深色字，
  对比度 ≥ 4.5:1。
- 预览 / 编辑模态复用抽屉已验证的 a11y 模式：`role="dialog"` + `aria-modal` +
  焦点进入 / 归还。编辑器有未保存内容时，Esc 与遮罩点击**必须**先弹二次确认。

> **【评审 R9 · P1】层叠契约——照 v1 字面实现会同时关掉两层，并解锁抽屉的滚动锁**
>
> 现网 `TicketDrawer.tsx` 的 Esc 处理器挂在 **`window`** 上（`:91-94`），
> 又对 `document.body.style.overflow` 做 set/restore（`:96` / `:99`）。
> 本轮所有模态都开在抽屉**之内**，若各自照抄这套模式，会得到两个必现缺陷：
> ① 按 Esc → 模态与抽屉**一起消失**，用户丢失整个工单上下文，编辑器的未保存二次确认也被绕过；
> ② 模态卸载时把 `overflow` 恢复成 `""` → **抽屉还开着，背景却已经能滚动**。
>
> 故引入 `lib/overlay-stack.ts` 作为**单一层栈**，抽屉与全部模态共用：
> - 层挂载时 `pushLayer(id)`，卸载时 `popLayer(id)`；
> - **Esc 只由 `isTopLayer(id)` 为真的那一层消费**，其余层的监听直接 return；
>   `TicketDrawer` 现有的 `window` 监听须改为先过这道判定（这是本轮**唯一**必须改动的既有 a11y 代码）；
> - **滚动锁按引用计数**：栈从空变非空时加锁，从非空变空时解锁，中间的 push/pop 不动 `body.style`；
> - 焦点归还沿用现网的 `restoreRef` 模式，层各自持有自己的 `restoreRef`，天然正确。
>
> 现网抽屉**没有**焦点陷阱（只有初始聚焦 + 归还 + Esc），本轮**不为文档功能补建焦点陷阱**——
> 那是一次独立的全站 a11y 改造，范围远超本轮（记入 §10 Non-Goals）。
- 上传区可键盘操作：`tabIndex=0` + `role="button"` + Enter/Space 触发文件选择；
  `<input type="file">` 视觉隐藏但保持可聚焦（不用 `display:none`）。
- 进度条带 `role="progressbar"` 与 `aria-valuenow`；上传完成 / 失败经既有 toast 播报。
- 空 / 骨架 / 错误三态齐全，复用 `EmptyState` / `Skeleton` / `ErrorState`。
- 删除工单的确认文案更新为：
  > 将永久删除「{title}」，连同它的 N 条评论与全部协作时间线，且不可恢复。
  > **其绑定的 M 份文档不会被删除**，将保留在文档库中。

---

## 7. 测试与验收标准

### 7.1 质量闸

- 后端：`cd backend` → `python -m pytest -q`。判据**相对化**：完工后要求**零失败**且
  **用例总数不低于基线**。**基线 = 371 条**（27 个测试文件），由评审员在 `d3e21a0` 上
  实测 `python -m pytest --collect-only` 得到。
  **注意 `CLAUDE.md` 里写的「380+」是陈旧数字**，以本行的实测值为准；
  实施者若照 CLAUDE.md 判定会误以为基线下降了。本轮预计新增 60–75 条用例。
- 前端：`npm run typecheck` 与 `npm run build` 均须零错误。

### 7.2 后端必过用例（节选，每条对应一个真实失败模式）

> **【评审 R1】以下前两条是本轮最重要的两条用例。** v1 列出的 23 条用例
> **没有任何一条**能捕获「嗅探消费了流 → 每个文件丢开头 12 字节」这个 P0——
> 因为落盘、去重、下载全都基于残缺内容自洽。**唯一的判据是字节级往返相等。**

| 用例 | 断言 |
|---|---|
| **`test_downloaded_bytes_match_uploaded_bytes`** | **上传一个含已知魔数头的真实 PNG（≥ 64 KB），下载回来 `assert downloaded == original`（逐字节）。对 md / pdf / zip 各再跑一遍**（R1） |
| **`test_sniffing_does_not_consume_stream`** | 直接单测 `_validate_upload`：调用后 `file_storage.stream.tell() == 0`；异常路径（扩展名不合法）下同样为 0（R1） |
| `test_upload_creates_document_and_version` | 201；`version_no == 1`；`current_version_id` 指向它；磁盘上存在该摘要文件 |
| `test_identical_uploads_share_one_blob` | 两次上传同内容 → 两个 Document、两个 Version、**一个**磁盘文件 |
| `test_rejects_disallowed_extension` | `evil.html` → 400，`detail.allowed` 含白名单 |
| `test_rejects_content_extension_mismatch` | HTML 内容伪装成 `.png` → 400 |
| `test_rejects_oversize_upload` | 超 `MAX_UPLOAD_MB` → **413** 且响应体是 JSON 契约，不是 HTML |
| `test_missing_file_field_returns_400` | 空 multipart → 400，不 500 |
| `test_download_sets_nosniff_and_disposition` | 三条响应头齐全；非白名单 MIME 恒 `attachment` |
| `test_download_of_missing_blob_returns_410` | 手工删掉磁盘文件 → 410，不 500 |
| `test_text_edit_creates_new_version` | JSON 正文提交 → `version_no == 2`；旧版本仍可下载 |
| `test_stale_expected_version_id_conflicts` | 409 且 `detail.current_version_id` 正确 |
| `test_bind_records_stage_snapshot` | 在 `testing` 绑定 → `link.stage == "testing"`；工单后续流转后该值**不变** |
| `test_duplicate_bind_returns_409` | 同一文档二次绑同一单 → 409 |
| `test_unbind_is_idempotent` | 未绑定时 DELETE → 204，不写审计、不发通知 |
| `test_bind_requires_can_manage_ticket` | 无关 member → 403 |
| `test_delete_ticket_unbinds_but_keeps_documents` | 删单后 link 为 0、**Document 行仍在**、磁盘文件仍在 |
| `test_delete_linked_document_conflicts` | 409，`detail.links` 为真实计数，**响应体无 `allowed` 键** |
| `test_document_count_is_single_query` | 用 `sqlalchemy` event 计数：列表 50 行 → 计数查询恰 1 次；**整块看板（7 列）也恰 1 次**（R8） |
| `test_checklist_reflects_bound_kinds` | 绑定 test_plan 后该项 `satisfied` 翻真 |
| `test_checklist_covers_every_workflow_status` | 遍历 `workflow.column_keys()` 两个实体的**全部 12 个状态**，每个都能取到非 500 的清单；`bug_fixing` 有非空期望（R2） |
| `test_gate_disabled_by_default` | 不设 `DOC_STAGE_GATE` → 缺材料照样能 move 到 done |
| `test_gate_blocks_human_move_when_enabled` | 409，`detail.missing == ["test_report"]`，**无 `allowed`** |
| `test_gate_never_blocks_backward_move` | 门禁开启 + 缺材料 → `done→reviewing`、`reviewing→bug_fixing`、`closed→verifying` 全部 200（R2） |
| `test_gate_never_blocks_agent_advance` | 开启门禁 + 缺材料 → `agent-advance` 仍 200 |
| `test_doc_missing_hint_is_deduped` | 门禁开启下连续 3 次 `tick` → 该工单只多出 **1** 条 `doc_missing_hint`；门禁关闭时 **0** 条（R10） |
| `test_illegal_transition_still_wins_over_gate` | 非法迁移在门禁开启时仍返回**带 `allowed`** 的状态机 409 |
| `test_bad_project_id_returns_400_not_500` | `POST /api/documents` 带不存在的 `project_id` → **400**；断言响应体不是 `{"error":"internal server error"}`（R3） |
| `test_bind_unknown_document_returns_404` | `POST …/documents` 的 JSON 分支带不存在的 `document_id` → 404，非 500（R3） |
| `test_truncated_text_is_never_editable` | 造一个介于编辑阈值与预览阈值之间的文本 → `editable=false`；强行 `POST /versions` → 409 `detail.reason=="truncated"`（R5） |
| `test_non_utf8_text_previewable_not_editable` | GBK 编码的 `.csv` → 200 且 `encoding_confident=false`、`editable=false`；强行提交 → 409（R5） |
| `test_revise_fanout_is_capped` | 把一份文档绑到 `DOC_FANOUT_MAX_LINKS + 5` 张单后改版 → Activity 数恰为上限值，响应体 `fanout_truncated == true`（R11） |
| `test_dedup_touches_blob_mtime` | 去重命中后目标 blob 的 `st_mtime` 被刷新（R4） |
| `test_gc_skips_tmp_and_recent_blobs` | `.tmp/x.part` 与刚落盘的孤儿 blob 在 `--apply` 后**仍在**；把 mtime 调老到宽限期外后才被回收（R4） |
| `test_purge_never_deletes_real_documents` | `--apply` 后用户上传的文档一行不少 |
| `test_existing_endpoints_unaffected_by_max_content_length` | 普通 JSON 写端点（建单 / 评论 / PATCH）在 `MAX_CONTENT_LENGTH` 生效下行为逐字不变（R-12） |

### 7.3 前端 / 端到端验收清单

1. 需求 **七个**状态 `new / assigned / in_development / testing / bug_fixing / reviewing / done`
   （**含 v1 遗漏的 `bug_fixing`**，见评审 R2），每一个状态下抽屉都能上传、预览、下载、绑定、解绑，
   且清单文案随状态变化、`bug_fixing` 列不得渲染成空白。
2. BUG 五个状态同上。
3. 上传 15 MB 文件有可见进度；上传 25 MB 文件得到「文件过大（上限 20 MB）」而非白屏或 500。
4. 同一份 PRD 绑定到 3 张需求单：文档库显示 `link_count = 3`；改标题后三张单同步显示新标题。
5. 在线编辑 Markdown 保存后，版本历史出现 v2，v1 仍可下载，时间线出现 `doc_revised` 条目。
6. 删除一张已绑定 2 份文档的需求：确认框如实说明文档不会被删除；删除后文档库仍有这 2 份。
7. 键盘全流程可达：Tab 到上传区 → Enter 选文件 → 上传 → Tab 到行操作 → Enter 预览 → Esc 关闭，
   焦点正确归还。
8. 断网时上传失败给出可重试的行内错误，不产生半截文档记录。
9. 移动端（375px）抽屉内文档区不横向溢出，操作菜单可点。
10. **【评审 R6】** 上传一个内容为 `<script>alert(document.cookie)</script>`、扩展名为 `.txt` 的文件，
    点击预览：内容以纯文本原样显示（`<pre>` 的 `textContent`），**不弹窗**；
    浏览器 DevTools 中确认预览用的 `blob:` URL 其 MIME 为 `text/plain` 而非 `text/html`，
    且页面中不存在指向该 `blob:` 的顶层导航。上传 `.html` / `.svg` 直接被拒（400）。
11. **【评审 R7】** 看板页打开一张单的抽屉 → 上传一份文档 → 关闭抽屉，
    **看板卡片上的回形针数字立即 +1**（不刷新整页）；解绑后立即 −1。列表页同验。
12. **【评审 R9】** 在抽屉内打开预览模态 → 按 **Esc**：**只有模态关闭**，抽屉仍开、
    背景**仍**锁滚动；再按 Esc 抽屉才关闭，焦点回到原触发元素。
    在编辑器里改动内容后按 Esc → 先弹未保存二次确认。
13. **【评审 R5】** 上传一个 600 KB 的 `.md`：可预览、**「编辑」按钮不出现**；
    上传一个 GBK 编码的 `.csv`：可预览、显示「非 UTF-8，不可在线编辑」横幅且能下载。

### 7.4 Definition of Done

- 上述质量闸全绿；§7.2 全部用例通过；§7.3 **十三条**人工验收全部签字。
- `git status` 中无遗留的 `backend/var/` 内容（`.gitignore` 已在 §3.2 登记该条目）。
- README 增补「文档管理」一节与新增环境变量表，并写明 **R-11 的多机部署约束**
  （`UPLOAD_DIR` 必须共享）。
- **评审记录（本文档头部）中的 R1–R12 逐条落地**，其中 R1 以
  `test_downloaded_bytes_match_uploaded_bytes` 变绿为唯一判据。

---

## 8. 风险与缓解

| ID | 风险 | 级别 | 缓解 |
|---|---|---|---|
| **R-1** | **误用 `schema_sync` 或忘记登记列** | 高 | 本轮**只新增表、不改既有列**，故 `ADDITIVE_COLUMNS` 无需任何条目。若实施中确实要给既有表加列（如给工单加 `document_count` 物化列——**不推荐**），必须同步登记，否则存量库全线 500。物化计数已被本设计明确否决：计数由 group-by 现算 |
| **R-2** | **存储型 XSS**：上传 HTML/SVG 后 inline 渲染，窃取前端源 `localStorage` 里的 JWT | 高 | **四道防线，且必须清楚哪几道在预览路径上真正生效**（【评审 R6】v1 记为"三重防线"，实际其中两道对本设计选定的预览方式**完全无效**）：① **扩展名白名单不含 `html/htm/svg/js`** —— 这是预览路径上**唯一**真正起作用的一道，因此白名单的收紧是硬性的，任何后续放宽都必须重做本项风险评估；② `Content-Disposition` 默认 `attachment`、inline 白名单只含图片/PDF/纯文本；③ 恒发 `X-Content-Type-Options: nosniff` —— ②③ 只对**直接导航到 API URL** 的场景有效，而该端点需要 `Authorization` 头，浏览器直接导航根本取不到内容，故二者在实际用户路径上近乎摆设；④ **【新增，真正的第二道】前端 `objectURL` 硬规则**（§2.6）：Blob 的 `type` 只能取自数据库 `mime_type` 且必须经 `INLINE_SAFE_MIMES` 过滤，PDF 只进 `<iframe sandbox>`，文本只进 `textContent`，禁止 `window.open`/顶层导航 —— 因为 `blob:` URL 的 MIME 由前端入参决定、与任何响应头无关，且 `blob:` 文档运行在**前端源**（JWT 所在源） |
| **R-3** | **路径穿越 / 文件名注入** | 高 | 落盘路径**只由 SHA-256 推导**，与用户文件名结构性无关；原始文件名仅作为数据库字段与响应头出现，且以 RFC 5987 百分号编码 |
| **R-4** | **磁盘被占满**：无配额，恶意用户可无限上传 | 中 | 单文件 20 MB 硬上限；`ix_docver_sha` 支撑的去重让重复内容零成本；`gc_orphan_blobs.py` 回收孤儿。**每用户 / 每项目配额不在本轮范围**——它需要一套用量统计与告警，属于独立议题，此处显式记为已知缺口 |
| **R-5** | **seed 契约被破坏**：顺手加一行示例文档 | 中 | 明确**不加**。CLAUDE.md 规定 seed 恰 8 行且每行登记进 `seed_records`；加一行文档就得同时改 `SEED_ENTITY_TYPES`、`purge_demo_data` 与 `test_seed_minimal`，收益（演示效果）远小于成本 |
| **R-6** | **为预览引入 Markdown 渲染链** | 中 | 明确**不引入**。文本一律以 `<pre>` 保留空白渲染。渲染 Markdown 意味着 HTML 输出，意味着必须配一套消毒库，意味着两个新依赖与一类新漏洞 |
| **R-7** | **文件写入与 SQLite 写锁互相拖累** | 中 | 落盘（慢，无锁）在 `db.session` 的任何写入**之前**完成，事务内只做元数据写入。与 `agent_prompts` 把 LLM 调用挪出写锁窗口是同一手法 |
| **R-8** | **门禁把 Agent 流水线卡死** | 高 | 门禁仅作用于人类 `move`；Agent 全部路径豁免，改写建议性 Activity。且总开关默认关闭 |
| **R-9** | **blob 与 DB 不一致**（文件在库无记录，或记录在文件已丢） | 中 | 记录在文件丢 → 下载与 `/content` 均返 **410 Gone**（语义准确且可被前端友好提示），不 500；文件在库无记录 → GC 工具识别并回收。回收恒在 commit 之后 |
| **R-13** | **【评审 R4 新增】「删除↔去重」竞态吃掉用户刚上传的文件** | 高 | 删除最后一个引用后、物理删除前的窗口内，另一请求可能去重命中同一摘要（**命中时不写盘**），随后文件被删 → 新版本永久 410。这不是理论窗口：文档复用是本轮的立身之本，重复内容是**预期高频**。缓解见 §2.2：去重命中必须 `os.utime` 触碰 + 回收须过 `BLOB_GRACE_SECONDS` 宽限窗口 + 在线路径只判定不硬删。三者共同把窗口从毫秒级不可控变为小时级且可配 |
| **R-14** | **【评审 R4 新增】GC 删掉正在写入的 `.part` 临时文件** | 中 | v1 的 GC 判据「磁盘上有、`document_versions` 无引用」把 `.tmp/*.part` 也算作孤儿。缓解：`is_reapable` 三条判据（排除 `.tmp/`、路径形状必须是 `<2hex>/<2hex>/<64hex>`、过宽限窗口），且**在线删除与离线 GC 共用同一个函数**，不允许两处各写一份 |
| **R-10** | **`delete_ticket_cascade` 返回值变形打破既有调用方** | 低 | 只**追加**键 `"document_links"`，既有键名与语义逐字不变；`routes/*` 与 `purge_demo_data` 均按键名读取。仍需跑一遍 `test_lifecycle.py` / `test_purge_demo_data.py` 确认无按长度断言的用例 |
| **R-11** | **多 worker 部署下的 `UPLOAD_DIR`** | 中 | 内容寻址天然幂等，多进程同时写同一摘要靠 `os.replace` 原子收敛。但**多机部署必须共享该目录**（NFS / 对象存储），否则一台机上传的文件另一台读不到。README 需显式写明；这也是未来切换到对象存储时唯一需要替换的模块（`storage.py`，五个函数的窄接口即为此准备） |
| **R-12** | **`MAX_CONTENT_LENGTH` 是全局的**，会同时限制普通 JSON 请求体 | 低 | 20 MB 远大于任何 JSON 体，无实际影响。但需在 `test_validation.py` 补一条断言，确保普通写端点行为不变 |

---

## 9. 建议实施顺序（每步都可独立提交且全绿）

1. **地基**：`config.py` 配置项（含 §5.3 四个新增项与阈值断言）+ `errors.py` 413/503 +
   `storage.py`（**含 §2.2 步骤 0 的入口断言、去重 `os.utime`、`is_reapable`**）+
   `test_document_storage.py`。此步不触碰任何路由，风险最低，且后续全部依赖它。
   **本步的出门条件是 `test_downloaded_bytes_match_uploaded_bytes` 变绿**——
   R1 是本轮唯一一个"测试全绿仍会全量损坏数据"的缺陷，必须在地基层就钉死。
2. **模型与库**：三张表 + `models/__init__.py`（**import 行与 `__all__` 两处**）+ 建表冒烟。
   确认 `create_all` 建全、`schema_sync` 仍返回 `[]`。
3. **文档库端点**：`routes/documents.py` + `service.py`（**含闸 0 引用校验与闸 4 的 `seek(0)`**）
   + `test_documents.py` / `test_document_versions.py`。
   此时后端已可用 curl 完成上传/下载/编辑全链路。
4. **绑定与流程**：`routes/ticket_documents.py` + `counts.py` + `lifecycle` 级联 +
   `notifications`（**含扇出上限**）+ `board_page.py` / 两个列表页的 `document_count` 富化 +
   `test_document_links.py`。
5. **阶段策略**：`doc_policy.py`（**七态全覆盖 + 前进迁移判定**）+ `move` 在
   requirements 与 bugs **两处**挂钩 + `agent_runner.advance_one` 的去重提示 +
   `test_doc_policy.py`（默认关闭，零行为变更）。
6. **前端基础**：`lib/overlay-stack.ts`（**先落地并把 `TicketDrawer` 接过去，
   否则第 7 步的模态一开就会带出 R9 的两个缺陷**）+ `api.ts` 上传/下载能力 +
   types（用 `AuthorSummary`）+ constants（**含 `ACTION_LABELS` 四项**）+ `useTicketDocuments`。
7. **前端主界面**：`DocumentPanel` / `UploadZone` / `PreviewModal`（**含 §2.6 的 objectURL 硬规则**）
   / `TextEditorModal` / `StageChecklist` 接入抽屉。
8. **前端外围**：文档库页 + 侧边栏第 9 项 + 看板/列表徽章 + 通知偏好项 +
   **文档动作后调 `invalidateTicketViews`**。
9. **收尾**：`gc_orphan_blobs.py` + `purge_demo_data` 增补 + `.gitignore` + README + 全量回归。

---

## 10. 明确不做（Non-Goals）

以下每一项都被认真考虑过并**有意排除**，写在这里是为了让实施者不必反复权衡，也让下一轮
的作者知道这些缺口是已知的、而非被遗忘的：

- **对象存储 / 云盘对接**：`storage.py` 的五函数窄接口已为此预留，但本轮落地本地磁盘。
- **在线协同编辑（多人同时编辑同一文档）**：需要 OT/CRDT 与 WebSocket，量级远超本轮。
  本轮以 `expected_version_id` 的乐观锁给出**冲突可检测**的下限。
- **全文检索文档正文**：`GET /api/search` 本轮仍只搜工单与文档**标题**，不进正文。
- **文档级权限（私有 / 指定人可见）**：本轮读权限与工单对齐（已认证即可读），见 §2.7 的理由。
- **每用户 / 每项目存储配额与用量看板**：见 R-4。
- **文档预览的服务端转码**（如 docx → PDF）：需要重型依赖，本轮 office 文档一律下载查看。
- **病毒 / 恶意内容扫描**（【评审 R22】补）：不引入 ClamAV 或任何云查杀。本轮的取向是
  **「不执行、不渲染、不解压」**——文件只被摘要、存盘、原样回吐，服务端从不解析其内容，
  因此恶意载荷缺少触发面。真正的查杀属于部署侧议题（对象存储的扫描钩子 / 邮件网关同款方案），
  引入进应用层只会得到一个既拖慢上传又给不出可靠结论的中间态。
- **全站焦点陷阱（focus trap）**（【评审 R9】补）：现网 `TicketDrawer` 只有初始聚焦 + 焦点归还 +
  Esc，**没有** Tab 循环陷阱。本轮补齐的是**层叠语义**（Esc 只关栈顶、滚动锁引用计数），
  不顺手做焦点陷阱——那需要同时改造抽屉、5 个既有模态与 `ConfirmDialog`，
  是一次独立的全站 a11y 改造，混进本轮会让文档功能的回归面无法收敛。建议作为下一轮候选。

---

## 实施过程发现的方案缺陷

> 记录人：Subtask #2 · Implementation Engineer ｜ 基线：spec **v2** + 现网 `d3e21a0`
> 按约定：**不静默偏离**。以下每条都写明「设计怎么说 / 照做会怎样 / 实际怎么做」，
> 并已按修正后的做法落地。F1 是唯一一条**照字面实现就会与 spec 自己的必过用例互相矛盾**的，
> 其余为设计未覆盖的落地细节。

### F1（对应评审 R2，**设计自相矛盾**）门禁「前进判定」不能用 `column_keys()` 的顺序

- **设计怎么说**：§2.4 铁律 4 写「判定式：`to_status` 在该实体的 `column_keys()` 顺序中
  **严格靠后于** `ticket.status`」。
- **照做会怎样**：现网 `REQUIREMENT_COLUMNS` 的顺序是
  `new, assigned, in_development, testing, **reviewing**, **bug_fixing**, done`
  ——`bug_fixing` 排在 `reviewing` **之后**（索引 5 > 4）。于是 `reviewing → bug_fixing`
  按列序会被判成「前进」，门禁开启且缺 `bug_evidence` 时会被拦下。
  而 §7.2 的必过用例 `test_gate_never_blocks_backward_move` **明确要求这一条必须 200**
  （R2 的原文也把 `reviewing → bug_fixing` 列为「回退」）。两者不可兼得。
- **实际怎么做**：在 `services/doc_policy.py` 里显式声明 `_STAGE_ORDER`——**流程推进档位**，
  与看板列的**展示顺序**分离。语义上 `bug_fixing` 是**返工态**，与 `in_development` 同档
  （order = 2），因此 `reviewing(4) → bug_fixing(2)` 是回退、`bug_fixing(2) → testing(3)`
  是前进、`bug_fixing → in_development`（同档）不受门禁。`is_forward()` 由此定义。
  额外收益：以后调整看板列的展示顺序不会再意外改变门禁行为。
  护栏：`test_is_forward_treats_bug_fixing_as_rework`（逐条钉死六个方向）。

### F2 `models/document.py` 需要 `TEXT_EXTENSIONS`，但它在 `service.py` 里会成环

- **设计怎么说**：§3.1 把 MIME 表、签名表、扩展名判定都放在
  `backend/services/documents/service.py`。
- **照做会怎样**：`Document.to_dict` 要回传 `editable`，判据需要 `TEXT_EXTENSIONS`；
  而 `service.py` 反过来 `from models.document import ...` —— 循环 import，
  `create_all` 阶段直接炸。
- **实际怎么做**：新增一个**只依赖 stdlib 的叶子模块** `backend/services/documents/mime.py`，
  存放 `TEXT_EXTENSIONS` / `INLINE_SAFE_MIMES` / `_MIME_BY_EXT` / `_SIGNATURES` /
  `extension_of` / `mime_for` / `signature_matches`。任何一层都可安全 import 它。
  这是本轮唯一一个**不在 §3.1 清单里**的新建后端文件。

### F3 multipart 表单是第四条整型输入路径，三条既有边界都不覆盖它

- **设计怎么说**：§2.3 闸 0 要求 `project_id`（**表单字段**）走
  `routes/requirements.py::_validate_project`。
- **照做会怎样**：`_validate_project` 接受的是一个**已经是 int 的值**。现网三条整型边界
  （`validation.want_int` 管 JSON 体、`scope.want_query_int` 管查询串、
  `BoundedIntConverter` 管 URL 路径）**都不覆盖表单字段**。直接 `int(form["project_id"])`
  时，`project_id=abc` 抛 `ValueError` → 兜底处理器 **500**，
  正是 R3 想消灭的那种失败模式（只是换了个触发方式）。
- **实际怎么做**：在 `routes/documents.py` 新增 `form_int(form, field)`，复述同一套判据
  （非整数 400、64 位硬界 400），并被 `ticket_documents.py` 复用。
  护栏：`test_non_integer_project_id_returns_400`。

### F4 `Document` 响应里的 `editable` 只能是四条判据里**不需要读文件**的那两条

- **设计怎么说**：§4.1 的 `Document` 响应形状带 `editable`；§2.6 又把 `editable` 定义为
  **四条**判据（文本扩展名 ∧ 未超编辑阈值 ∧ `not truncated` ∧ `encoding_confident`）。
- **照做会怎样**：后两条需要**读 blob 并尝试解码**。列表页一页 50 行 = 50 次磁盘读 + 50 次
  UTF-8 解码，只为渲染一个按钮的显隐——这与 §2.1「避免每行一次子查询」是同一类问题。
- **实际怎么做**：分层，并让分层在结构上安全：
  - `Document.to_dict().editable` = **结构判据**（扩展名 + 大小），零 IO。
    因为配置层钉死了 `DOC_TEXT_PREVIEW_MAX_BYTES > DOC_TEXT_EDIT_MAX_BYTES`
    （`doc_policy.assert_thresholds` 启动期断言），「大小 ≤ 编辑阈值」的文件
    **在结构上不可能**被预览截断，故这里省掉的两条不会造成误判为可编辑。
  - `GET /documents/:id/content` 的 `editable` = **四条判据的最终答案**（现读现判）。
  - `POST /documents/:id/versions` 的 JSON 分支**独立复核四条**，不满足即 409 带 `reason`。
  前端「编辑」按钮按前者显隐、编辑器按后者置只读并给出横幅说明原因——两处都不是防线，
  防线在第三处。

### F5 层栈必须接到 `components/ui/Modal.tsx`，只改 `TicketDrawer` 不够

- **设计怎么说**：§3.5 的前端修改清单里，只有 `TicketDrawer.tsx` 一项提到接入
  `lib/overlay-stack.ts`（并注明这是「本轮**唯一**必须改动的既有 a11y 代码」）。
- **照做会怎样**：本轮新增的四个模态（预览 / 编辑 / 绑定 / 版本历史）全部复用现网
  `components/ui/Modal.tsx`，而**它自己**也把 Esc 挂在 `window` 上、也对
  `document.body.style.overflow` 做 set/restore（`Modal.tsx:33-68`）。只改抽屉，
  R9 描述的两个缺陷会原封不动地从模态这一侧复现。要么在每个新模态里绕开 `Modal` 自己写一套
  （四份重复），要么把层栈接进 `Modal` 一次。
- **实际怎么做**：接进 `Modal.tsx`（Esc 前置 `layer.isTop()`；滚动锁交给层栈的引用计数），
  一处改动同时修好 5 个既有模态 + `ConfirmDialog` + 本轮 4 个新模态。
  §3.5 的清单据此**多出 `components/ui/Modal.tsx` 一项**。

### F6 `purge_demo_data` 的「孤儿 link 清理」由级联覆盖，未另加扫描

- **设计怎么说**：§3.2 要求 `tools/purge_demo_data.py`「清理因删单而孤儿的 link」。
- **实际怎么做**：该工具删工单**只经** `lifecycle.delete_ticket_cascade`，而本轮已在其中
  加了 `DocumentLink` 的删除（返回值追加 `document_links` 键）——因删单而产生的孤儿 link
  在源头就不会出现，无需第二遍扫描。故**未**在 `_purge_soft_tables` 里新增一类，
  以免改动其报告 shape、波及既有 `test_purge_demo_data.py`。
  `_user_references` 计入 `documents`、`_untouched_counts` 列出文档三表两项**已按设计落地**。

---

### 实测数据（供下一轮引用，勿再转述陈旧值）

- **后端用例总数：506**（开工基线 371，本轮新增 6 个测试文件共 **135** 条，零失败）。
  §7.1 预计「新增 60–75 条」偏保守，主要多在存储层与门禁的边界用例上。
- 前端 `npm run typecheck` 与 `npm run build` 均零错误；`/documents` 首屏 3.39 kB。
