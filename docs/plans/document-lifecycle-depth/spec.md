# AragonTeam 文档全流程纵深（Document Lifecycle Depth）Spec

- **文档版本**: **v2**（Subtask #0 产出 v1 → Subtask #1 设计评审就地修订，评审记录见 §0.5，评审结论见文末 §11）
- **Feature slug**: `document-lifecycle-depth`
- **轮次**: 第 13 轮迭代（建立在 `ticket-document-management` 之上，最新 commit **`d7cb841`**）
- **本轮需求（与上轮同源）**: 「需求和 BUG 跟踪流程中缺少文档上传 / 查看 / 编辑 / 绑定环节，应在**全流程各环节**支持文档管理；界面美观优雅，功能完善稳健可靠。」
- **技术栈（沿用，零新增运行时依赖）**: Next.js 14 App Router + React 18 + TypeScript + Tailwind + @dnd-kit + SWR ｜ Flask 3.0.3 + SQLAlchemy 2.0.31 + SQLite + flask-jwt-extended + Flask-CORS + Werkzeug 3.0.3。
- **目标读者**: 下游实施工程师（须可据此逐行实现，无需再做架构决策）。
- **主题一句话**: **「上一轮把文档**存下来**了；这一轮让它在流程里真正被**找到、读懂、自动产出、以及安全地退回**——包括流程中唯一没有手的那个环节：Agent。」**

---

## 0.5 评审记录（Review Notes · v1 → v2）

评审人：Subtask #1 · Senior Reviewer。评审方式：**逐节读 spec + 逐条回现网代码取证**，
不接受 spec 自述的现网事实，全部重新 grep / 读文件核对（附录的 30 余条断言已逐条复核，
**除下列 V-16 外全部属实**——这是一份取证质量很高的设计文档，因此本次评审的重点不在
「事实对不对」，而在「照着做会不会出事」）。

四个维度的总体判断：

- **可行性**：四根支柱都能用现有栈实现，**零新增运行时依赖**属实（`frontend/package.json`
  确认只有 next / react / @dnd-kit ×3 / swr，无 markdown 与 diff 库）。但有 **2 处照做会直接
  出错**（V-01、V-02）、**2 处照做会违反本仓库已写明的硬约束**（V-03、V-04）。
- **完备性**：过滤点清单、失败路径、回滚顺序考虑得相当细，但**新老代码的接缝处**漏了
  4 处（V-05 ~ V-08）——共同特征是「spec 描述的是新代码该怎么写，没描述它落在既有函数的
  第几行、前面还有哪个 guard」。
- **一致性**：与 CLAUDE.md 的 `ADDITIVE_COLUMNS` 硬约束、状态机神圣性、`seed_records`
  登记约定均**无冲突**；§5.1 三条细节（不建外键 / 不加索引 / 默认 NULL）的论证是正确的。
  与既有测试断言面的对齐经复核**属实**（`test_documents.py:192-236` 确实只断言
  204/404/403/409/列表空/`doc_detached`，软删后逐条仍成立）。
- **规模**：四根支柱一轮做完偏大，但 §9 的六步切分是真实可停的，**不构成阻断**。
  唯一的规模问题是 V-09：一个默认开启的新写入源。

### P0（必须修复，否则功能错误或线上 500；且**本 spec 自带的用例抓不到**）

| # | 位置 | 问题 | 处置 |
|---|---|---|---|
| **V-01** | §2.3 C-2 `ARCHIVE_KIND` | **归档类别只按 `(entity, to_status)` 取，忽略了 `agent.kind`**。回现网 `AGENT_FORWARD` 逐条对照：`("requirement","testing")` 唯一由 **dev**-agent 到达（`in_development→testing` / `bug_fixing→testing`），`("bug","verifying")` 也唯一由 **dev**-agent 到达（`fixing→verifying`）。于是 **dev-agent 的「我已提交修复」正文会被归档成「测试计划」/「测试报告」并把 QA 的清单项点绿**——这正是 spec 自己在前置条件 1 里判死刑的「制造材料齐了的假象」，只不过换成了真实 LLM 产物。§0 又明确说本轮的意义是让 `DOC_STAGE_GATE` **有资格被打开**；门禁一旦打开，它放行的是一份没有任何 QA 参与过的「测试报告」。**更糟的是 C7 用例抓不到它**：C7 只断言 `ARCHIVE_KIND` 的值 ∈ 对应阶段的 `STAGE_DOC_EXPECTATIONS`，而这两格恰恰是**匹配**的——守卫会给这个 bug 盖章通过 | **已修复**：§2.3 C-2 的键改为 `(entity, agent_kind, to_status)` 三元组，删去两条由 dev-agent 到达的 QA 产物行，并把「Agent 只归档自己职能范围内的产物」写成模块级铁律；C7 用例改写为**同时**校验三元组的 agent_kind 与 `AGENT_FORWARD` 可达性，新增 C11 反向守卫 |
| **V-02** | §2.4 D-3 / §2.5 时序 B / §4.8 | **`?purge=1` 与 CLI 的彻底删除会在「软删但仍有绑定」的文档上抛 IntegrityError → 500 / CLI 崩溃**。`DocumentLink.document_id` 是**真外键**（`models/document_link.py:23`）且 `PRAGMA foreign_keys=ON` 在每条连接上真实生效（`extensions.py:61`）；而 D-3 的立身之本恰恰是「软删**不动** links」，所以**「回收站里的文档仍有绑定」是常态而非边界**。时序 B 给路由写了 `detach_all_links（若还有）`，但 D-3 又要求 CLI「走与 `?purge=1` **完全相同的服务函数** `trash.purge(document)`」——两句话合起来，detach 到底在路由里还是在 `trash.purge` 里是**未定义**的，写在路由里则 CLI 必炸。D11/D14 用例也抓不到：D11 大概率拿一份无绑定文档来测，D14 是 dry-run | **已修复**：§2.4 D-3 把 `trash.purge(document, actor)` 定义为**自包含**（内部先 `detach_all_links` 再 `delete_document`），路由与 CLI 共用同一入口；CLI 的 actor 钉死为 `("system", None)`；§2.5 时序 B 同步改写；新增 D16 用例专测「带绑定的回收站文档被 purge」 |

### P1（必须修复，否则实现会踩坑、违反既有硬约束或留下未定义行为）

| # | 位置 | 问题 | 处置 |
|---|---|---|---|
| **V-03** | §2.3 C-2 落点顺序 | **落盘（磁盘 IO）被放进了 SQLite 写锁窗口内**。`services/documents/service.py` 的模块 docstring 写着一条贯穿全模块的硬约束：「落盘（慢，无锁）在 `db.session` 的任何写入**之前**完成，事务内只做元数据写入」。而 spec 规定归档调用点在 `ticket.status = to` / `Comment` / `Activity.log` **之后**，且 `db.session.begin_nested()` 会先 flush 这些挂起写（→ 取得 SQLite 写锁），再在锁内调 `create_text_document` → `storage.digest_and_persist` 落盘。SQLite 是单写者，这与上一轮 R-7、与 `agent_prompts` 把 LLM 挪出写锁窗口是同一个坑 | **已修复**：§2.3 C-2 拆成**两段**——`archive_prepare()` 在 `generate_work_product` 之后、`ticket.status` 改写**之前**完成落盘（此刻 session 无挂起写），`archive_commit()` 在原位置只做元数据写入；目标 `stage` 由参数显式传入而非读 `ticket.status`。新增 C12 用例断言落盘发生在状态写入之前 |
| **V-04** | §2.3 C-2 / §8 R-4 | **`db.session.begin_nested()` 在 pysqlite 上是有名的坑，spec 把它当成了无条件可靠的安全网**。SQLAlchemy 的 pysqlite 方言文档明确列出 SAVEPOINT 不能开箱工作（pysqlite 的隐式 BEGIN 处理），需要 `isolation_level=None` + 手工 `BEGIN` 事件这套 workaround；本仓库 `extensions.py` **没有**做这个 workaround（只挂了 PRAGMA 监听）。它在本场景下**恰好**能工作，唯一原因是调用点之前已有挂起 DML、flush 后事务已开——**这是一个未写下来的前置条件**，一旦后人按 V-03 或别的理由把归档挪到前面，SAVEPOINT 就会在事务外发出，回滚不再隔离任何东西，而 C8 用例仍会绿（它只断言推进成功） | **已修复**：§2.3 C-2 把该前置条件写成模块 docstring 的强制内容；C8 用例加强为「归档失败 + **commit 之后**重新查库，工单状态 / 评论 / Activity 三者确已落库，且**没有半份文档行残留**」；§8 R-4 补上 pysqlite 注记与「若将来需要在无挂起写时使用 SAVEPOINT，须先加 workaround」的条件 |
| **V-05** | §2.2 B-0 | **给出的修法不足以达成它自己的目标**。现网 `decideMode`（`DocumentPreviewModal.tsx:26-31`）的**第一行**是 `if (!mime || !isInlineSafeMime(mime)) return "download"`，四分支（image/pdf/text/download），末尾的 `return "text"` 只是兜底。只「把 text 判据改成扩展名」而不动第一行，`.csv`/`.json`/`.yaml` **仍然在第一行就被短路成 download**——B-0 等于没修，而它是本轮唯一一条「独立价值、最小改动」的前端修复 | **已修复**：§2.2 B-0 直接给出**改写后的完整函数**（扩展名判据前置于 inline-safe 闸），并说明为什么顺序不能颠倒 |
| **V-06** | §2.2 B-3 / §4.2 | **回滚分支会被 `_reject_uneditable` 挡住**。现网 `create_version` 的 JSON 分支在读 `content` **之前**先调 `_reject_uneditable(document)`（`routes/documents.py:238-241`），四条判据是为「在线编辑文本」设的。回滚一份 `.png` / `.docx` / `.pdf` 与文本可编辑性毫无关系，却会拿到 409 `{"reason":"binary"}`——而 §4.2 的状态码表里**根本没有这个 409**，说明 spec 的意图是回滚对任意文档都可用 | **已修复**：§2.2 B-3 与 §4.2 明确规定 `from_version_id` 分支在 `_reject_uneditable` **之前**分流并**完全绕过**它，并说明理由；B 组新增 B8 用例（回滚一份二进制文档必须 201） |
| **V-07** | §2.4 D-2 第 1 行 | **`_get_document_or_404` 是 `db.session.get(Document, id)`（`routes/documents.py:57`），`session.get` 按主键取行，加不了 filter**；且同一个 helper 被 `delete_document` 复用，而 `?purge=1` 需要的是**相反**的过滤（**只**在回收站里找）。spec 只说「加软删过滤」，落地时必然要在这里做一次它没交代的结构改动 | **已修复**：§2.4 D-2 给出显式的双模式 helper 签名与实现约束（`include_trashed` 参数 + 改为 `Document.query.filter(...)`），并写明 `?purge=1` 的查找模式与 403/404/409 的判定顺序 |
| **V-08** | §2.1 A-3 | **漏了 `GlobalSearch` 的第三个集成点**。除了 `flat` 键盘索引，还有一处「有结果但没有高亮项时按 Enter」的兜底（`GlobalSearch.tsx:122-126`），它按 `counts` 在 requirements / bugs 之间二选一。加了文档桶之后，一次**只命中文档**的搜索按 Enter 会跳到 `/requirements/board`——一个空看板 | **已修复**：§2.1 A-3 补上该兜底的三态改写规则与「不确定时不跳转」的取向 |
| **V-09** | §2.3 C-1 / §3.2 | **`create_text_document()` 是一条绕过全部四道上传闸的新写入路径，spec 没规定它必须自持哪些不变量**。现网所有落盘都经 `_validate_upload`（存在性 / 文件名清洗 / **扩展名白名单** / 魔数嗅探）；模板与 Agent 归档都以「一段文本」入库，天然走不了这四闸（`add_version_from_text` 同理，但它复用当前版本的文件名与 MIME，身份是既定的；`create_text_document` 是**从零造身份**） | **已修复**：§2.3 C-1 写明 `create_text_document` 的四条自持不变量（扩展名恒为 `md` 且必须 ∈ `DOC_ALLOWED_EXTENSIONS`、正文长度上限、MIME 由扩展名推导不接受入参、复用同一条内容寻址落盘链路），并要求启动期断言 `md` 在白名单内 |
| **V-10** | §2.3 C-2 / §5.3 | **一个默认开启（`DOC_AGENT_ARCHIVE = True`）的新通知源**。归档复用 `bind_document` / `fanout_revision`，两者都会调 `notifications.notify_document` → 每次归档给 reporter 推一条 `document_added`。而 `run=all` 单次最多 6 步（`MAX_AGENT_STEPS`）、`autorun-all` 跨多张单循环调用；同时 spec 自己已把「通知类型不细分」列进 Non-Goals，于是用户在通知中心看到的是一串与人工上传**无法区分**的 `document_added`。默认开启意味着这是**升级即生效**的行为变更 | **已修复**：§2.3 C-2 规定归档路径**只写 Activity、不发通知**（与 `doc_detached`「收敛性/自动性操作不发通知」的既定取向一致，且 §2.5 时序 A 同步修正）；§5.3 保留 `DOC_AGENT_ARCHIVE = True` 但补上「首次上线建议先以 `False` 观察一轮」的运维注记；新增 C13 用例断言归档不产生 Notification |
| **V-11** | §4.6 vs §6.4 | **两节自相矛盾**。§4.6 把 `GET /api/documents/templates` 的响应体定义为**裸数组** `[{kind,label,summary}]`，§6.4 又要求「在这个端点的响应里顺带回传 `trash_retention_days`」——数组上挂不了这个键。且把回收站保留期塞进一个叫 templates 的端点本身就是错的抽象 | **已修复**：§4.6 改为 `GET /api/documents/meta`，响应体为对象 `{templates: [...], trash_retention_days: N}`，§6.4 与 §3.3/§3.4 同步；理由（一个只读配置端点、不为一个数字新开路由）保留，但名字与形状对得上 |

### P2（记录，不阻断；已顺手修正文档，实施时留意）

| # | 位置 | 问题 |
|---|---|---|
| V-12 | §2.1-A2 / §4.1 | `deleted=1` 对非 pm/admin **自动附加** `uploader_id = me`，但用户显式传了 `uploader_id=其他人` 时是覆盖、报 400 还是取交集，未定义。**已就地补**：显式值与自动值不一致时以自动值为准（收紧优先），不报错 |
| V-13 | 附录事实清单 | 唯一一条**不属实**的断言：「`TEXT_EXTENSIONS` 七项……前端镜像 `lib/constants.ts:246`」。前端**根本没有** `TEXT_EXTENSIONS`（全前端零引用），`:246` 是 `INLINE_SAFE_MIMES`。这不影响设计（§3.4 本就把它列为**新增**常量），但会让评审者误以为只需改判据不需建常量。**已就地更正** |
| V-14 | §3.4 | `lib/constants.ts` 在同一张表里出现**两行**（一行 `TEXT_EXTENSIONS`、一行 `ACTION_LABELS`）。**已合并为一行** |
| V-15 | §8 风险表 | 行序为 R-11 → **R-13** → R-12。**已调整为 R-11 → R-12 → R-13** |
| V-16 | §2.4 D-2 | 七处过滤点清单声称完整，实际还有第 8 处 `routes/ticket_documents.py:141`（`detach_ticket_document` 的 `session.get(Document)`）。它无害（解绑是幂等的，返 204 与返 204 无差别），但既然表格自称完整就该收口。**已补入表格并标注「可不改，但必须知道它在」** |
| V-17 | §5.2 | `DocumentLink.label` 保留 `agent:` 前缀，并要求前后端各加一道 400 前置校验——这是对既有端点 `POST /{entity}/:id/documents` 的**契约收紧**，但 §4.5 的状态码表没登记这条 400。**已在 §4.5 补登记** |
| V-18 | §7.2 D11 | 「blob 进入回收判定」的措辞是对的，但要提醒实施者：`storage.delete_blob` 有**宽限窗口**（`is_reapable` / `_grace_seconds`），刚落盘的 blob 立刻 purge **不会**被物理删除。用例必须断言「进入 `unreferenced_digests` 集合」而非「文件已消失」。**已在 §7.2 就地注明** |
| V-19 | §2.4 D-3 | 回收站里的文档**无法预览**（详情端点已被过滤成 404），用户只能凭标题决定要不要恢复。可接受（回收站不是阅读场所），但 §6.4 的空态与行内文案应说明「如需查看内容请先恢复」。**已在 §6.4 补** |

**未采纳的意见（记录理由，避免下一位评审重复提出）**：

- 「搜索桶应当带 `project_id` 作用域」——现网 `search_all` 对 requirements / bugs **本来就没有**
  项目作用域，只给文档加一层会造成三个桶行为不一致。要加就三个一起加，那是项目作用域那条线的题目。
- 「`sort=links` 应该做成物化列」——现网文档量级（个位数千行）下 `group_by` 子查询足够，
  与 §5.1「不加索引」的判断同源。
- 「Markdown 子集应该支持任务列表 / 删除线」——§10 已明确排除，且每加一条语法就是一条新的
  解析路径；本轮的取向（刻意小、结构性免疫 XSS）是对的。

---

## 0. 立场：为什么第二轮还是「文档」

上一轮（`ticket-document-management`，commit `d7cb841`）交付的是**能力的骨架**：
`Document / DocumentVersion / DocumentLink` 三表分离、SHA-256 内容寻址存储、12 条路由、
抽屉 / 文档库 / 看板徽章三触点、阶段清单与可选门禁。这套骨架是正确的，本轮**不动它的任何一条主干**。

但把需求原文再读一遍——「在**全流程流转的各个环节**，都要能支持文档相关的功能」——
拿现网代码逐个环节对照，会发现四处骨架撑不到的地方，且每一处都不是「锦上添花」，
而是**会让上一轮的投入无法兑现**的断点：

| # | 断点 | 现网证据 | 用户实际遭遇 |
|---|---|---|---|
| **E** | **找不到** | `services/search.py:39-47` 的 `search_all` 只聚合 `Requirement` 与 `Bug` 两个模型；`GlobalSearch.tsx:152` 的占位符逐字写着「搜索需求 / BUG…」 | 一份 PRD 传进来了，三周后想复用它——只能去 `/documents` 一页页翻，或者干脆再传一遍。**复用是上一轮三表分离的全部理由，而发现是复用的前提** |
| **F** | **看不懂** | `DocumentPreviewModal.tsx` 对文本一律以等宽 `<pre>` 渲染（上一轮 §2.6 明确「不引入 Markdown 渲染库」）；`DocumentVersionTimeline.tsx`（114 行）只能列版本、看单版本，**没有任何两版本之间的对比**；版本回滚只能「下载 v1 → 再上传一次」 | 团队里绝大多数交付物是 `.md`。用户点开「技术方案 v3」，看到的是一屏 `##` 与 `- ` 的裸符号；想知道 v3 相对 v2 改了什么，得自己下载两个文件用外部工具比 |
| **G** | **补不上** | `agent_runner.py:101-119`——Agent 推进一步时，`agent_executor.generate_work` 产出的**实质工作产物**被写进 `Comment.body` 就结束了；`doc_policy.agent_missing_hint`（`doc_policy.py:160`）只能写一条「你少了个文件」的提示 | 系统里**唯一全自动的那个环节**，恰恰是**唯一没有文档能力的环节**。Agent 能写出一份完整的测试报告，却只能把它埋进评论流，既不能下载、不能改版、不能复用，也**永远无法满足阶段清单**——于是阶段清单在自动流水线上永远是红的 |
| **H** | **退不回** | `routes/documents.py:196-199`：`delete_document` 直接删行，随后 `reap(orphans)` 回收 blob。**没有软删、没有回收站、没有任何撤销** | 「删除」是这套系统里目前唯一**不可逆**的破坏性操作。上一轮为工单建了完整的生命周期治理（`lifecycle.py`）、为演示数据建了可识别可清除的登记表（`seed_records`），却给文档留了一条一按就永久消失的路 |

这四条合起来解释了本轮的取向：**上一轮解决的是「东西放哪」，本轮解决的是「东西怎么用」**。
E/F 面向人（找到与读懂），G 面向机器（自动产出），H 面向错误（安全退回）。
四者互不重叠，缺任何一条，「全流程各环节都支持文档」这句话就仍有一段是空的。

**特别说明 G 与门禁的化学反应**：上一轮把 `DOC_STAGE_GATE` 默认关掉，理由是「材料还得靠人传，
开着会挡住所有人」。本轮 G 落地后，`qa-agent` 推进到 `reviewing` 时会**自己产出并绑定测试报告**，
阶段清单在自动路径上第一次可能被自动满足——门禁才第一次具备「可以打开」的现实条件。
这不是本轮要求打开它（默认仍为 `False`），而是本轮让它**有资格**被打开。

---

## 1. Overview（概述）

本轮不新增领域实体，只在既有的 `Document / DocumentVersion / DocumentLink` 三表之上补四根支柱，
它们共享同一条设计原则：**不给用户新的概念，只给已有概念新的出口**。

**支柱 A · 发现**：把文档接进全局搜索（`GET /api/search` 新增 `documents` 桶，匹配标题、
描述与**当前版本的原始文件名**——用户记得住的往往是 `payment-v2.md` 而不是标题），
并把文档库页从「筛 kind + 关键词」升级为可按上传人、绑定状态、排序维度检索的真正的库。

**支柱 B · 理解**：新增两个**零依赖、纯前端**的能力——`lib/markdown.ts` 把 Markdown
渲染成 **React 元素树**（不是 HTML 字符串，因此 `dangerouslySetInnerHTML` 从不出现，
XSS 在结构上不可能），`lib/diff.ts` 做行级 LCS 对比。二者让「预览」从「看到字节」升级为
「看懂内容」与「看清变化」。后端只补一条**零字节成本**的版本回滚分支：内容寻址下，
回滚到 v1 = 新建一行指向同一个 sha256 的 v4，磁盘上不复制任何字节，历史一行不删。

**支柱 C · 产出**：两条路径把「知道缺什么」推进到「东西已经在了」。
其一是**文档模板**——阶段清单里的缺失项从「点一下打开上传框」升级为「上传文件 / 用模板新建」
二选一，模板即时生成一份带工单编号、阶段、责任人占位的 Markdown 骨架并完成绑定。
其二是 **Agent 交付物归档**——`agent_executor` 新增 `generate_work_product()` 返回带来源标记的
产物，`services/documents/agent_archive.py` 据此在**真实 LLM 产物**（而非降级模板）出现时，
把它按目标阶段归档成对应类别的文档并绑定到工单，`link.stage` 如实记下当时的环节。
**该路径在测试与离线环境恒不触发**（判据是 `from_llm`，而 `_llm_active()` 在 `TESTING` 下恒 False），
因此存量 506 条用例的行为逐字节不变。

**支柱 D · 治理**：`documents` 增加 `deleted_at` / `deleted_by_id` 两列，`DELETE` 由物理删改为
软删，新增 `POST /api/documents/:id/restore` 与回收站视图，过期清理交给一个默认 dry-run 的 CLI。
这里最容易出错的不是软删本身，而是**过滤点**：漏掉任何一处，被删除的文档就会变成「幽灵」——
在抽屉里看不见，却仍在替工单满足阶段清单。§2.4 给出了必须过滤的七处的完整清单与每一处的漏判后果。

**范围与取舍**：四根支柱都是 P0，但**实施顺序是可切分的**（§9）。若时间只够一半，
按 §9 的顺序做到第 4 步为止是一个自洽、可上线、可提交的交付面；第 5 步之后的每一步同样各自自洽。
明确不做的事写在 §10，与上一轮的 Non-Goals 合并去重。

---

## 2. 技术设计（Technical Design）

### 2.1 支柱 A · 发现：文档进搜索、库进筛选

#### A-1 后端：`services/search.py` 新增 documents 桶

现网 `search.py` 是一个 47 行的只读服务，只依赖 `Requirement` / `Bug`。本轮新增：

```python
def _document_like_clause(keyword: str):
    """文档命中面：标题 / 描述 / **当前版本的原始文件名**。

    第三项是刻意的：用户记得住的常常是 `payment-v2.md` 这个文件名，而不是
    上传时随手写的标题。它需要 outerjoin document_versions，故不能复用 _like_clause。
    """
    like = f"%{escape_like(keyword)}%"
    return or_(
        Document.title.ilike(like, escape="\\"),
        Document.description.ilike(like, escape="\\"),
        DocumentVersion.original_filename.ilike(like, escape="\\"),
    )


def search_documents(keyword: str, limit: int):
    q = (Document.query
         .outerjoin(DocumentVersion,
                    DocumentVersion.id == Document.current_version_id)
         .filter(trash.not_deleted())          # 【铁律】回收站里的文档绝不出现在搜索里
         .filter(_document_like_clause(keyword)))
    total = q.count()
    rows = (q.order_by(Document.updated_at.desc(), Document.id.desc())
             .limit(limit).all())
    return rows, total
```

`search_all` 的返回体追加 `"documents": [...]` 与 `counts["documents"]`。
序列化**必须**走 `services/documents/counts.py::serialize_documents(rows)`（现网已有，
批量预取 `link_count` 与当前版本），不要逐行 `to_dict()`——搜索下拉一次最多 20 行，
逐行 `to_dict()` 就是 40 次子查询（`models/document.py:87-89` 的兜底分支）。

**`routes/search.py` 必须同步改**（这是最容易漏的一处）：它的**空关键词分支手写了一份信封**
（`search.py:23-27`），只有 `requirements` / `bugs` 两个键。前端若按新形状解构，
空关键词时会拿到 `undefined` 并在 `.map` 上崩掉。空信封须补齐 `"documents": []` 与
`counts.documents: 0`。

**`outerjoin` 的一个真实陷阱**：`Document.query.outerjoin(...)` 之后 `q.count()` 在
`current_version_id` 为空的行上仍然只算一次（一对一 join），不会放大计数。
但若将来 join 改成关联到 `document_versions.document_id`（一对多），`count()` 会**重复计数**。
本设计固定 join 到 `current_version_id`，并以 `test_search_counts_documents_once` 钉死。

#### A-2 后端：`GET /api/documents` 的检索能力

现网已支持 `q` / `kind` / `project_id` / **`uploader_id`** / `limit` / `offset`
（`routes/documents.py:120-131`），排序**硬编码**为 `updated_at DESC, id DESC`。
新增三个查询参数，全部走既有边界（整型 `services/scope.py::want_query_int`，
枚举做白名单否则 400）：

| 参数 | 取值 | 语义 | 越界行为 |
|---|---|---|---|
| `sort` | `recent`（默认）/ `title` / `size` / `links` | 排序维度；`recent` = `updated_at DESC, id DESC`（与现网逐字一致，默认行为不变） | 非枚举值 **400**（不静默回退，与 `want_str(choices=...)` 同款态度） |
| `unlinked` | `1` | 只看**没有绑定任何工单**的文档（治理盲点：传了没用上的） | 其他值忽略 |
| `deleted` | `1` | **回收站视图**：只看软删的（见 §2.4） | 其他值忽略 |

> **注意（调研纠正）**：`uploader_id` **后端早已实现**，但**前端 UI 从未暴露**
> （`app/(app)/documents/page.tsx:128-147` 只有关键词框 + 类型下拉）。本轮它属于
> **前端补齐**，不是后端新增——实施时不要重复实现一遍后端筛选。

#### A-4 两个「有数据、没出口」的现存缺口（顺手补齐，成本极低）

调研在现网发现两处**后端已备好、前端从未消费**的能力，它们与「发现」是同一件事，
且各自只需十几行前端代码：

1. **`link_count` 点不进去**：文档库列「被引用 3」只是一个数字（`page.tsx:198`），
   而 `GET /api/documents/:id` 的 `links[]` 里**只有 `entity_type` / `entity_id`，没有工单标题**
   （`DocumentLink.to_dict()`）。本轮：详情端点的 `links[]` 各项**富化一个 `entity_title`**
   （批量取标题，`requirement` / `bug` 各一次查询，**不得逐 link 查一次**），
   前端把数字变成可点开的浮层，列出「这份文档正被这几张单使用」，点击即跳该工单。
   这是复用能力的最后一公里：用户在决定「能不能改这份 PRD」时，第一个问题就是「谁在用它」。
2. **`PATCH /api/documents/:id` 全前端无调用方**：`useDocumentLibrary.patch()` 已实现
   （`hooks/useDocumentLibrary.ts:71-78`），但**没有任何 UI 调它**——今天改一份文档的
   标题 / 类型 / 描述在界面上**做不到**。本轮补一个轻量的「编辑信息」模态（三个字段 +
   `expected_updated_at` 乐观锁，后端 `check_concurrency` 已就绪），入口放在文档库行操作与
   抽屉行操作菜单里。

`sort=size` 排的是**当前版本**的 `size_bytes`，`sort=links` 排的是绑定数——两者都需要 join，
实现约束写在 §4.1，要点是**必须保持单次查询**，不得退化为「先取 50 行再逐行算」。

#### A-3 前端：全局搜索的第三个分组

`GlobalSearch.tsx` 现网的 `Kind = "requirements" | "bugs"`，`onSelect` 一律
`router.push('/{kind}/board?ticket={id}')` 并派发 `aragon:open-ticket`（`:94-103`）。
文档的落点不同，**必须分流**：

- 新增 `onSelectDocument(id)` → `router.push('/documents?doc=' + id)`；
- `/documents` 页读 `?doc=` 参数，命中即打开该文档的预览模态（深链能力顺带解决了
  「把某份文档甩给同事」这一真实诉求）；
- 「查看全部」→ `/documents?q=<keyword>`；
- 无命中文案由「未找到匹配的需求或 BUG」改为「未找到匹配的需求、BUG 或文档」；
- 输入框 `placeholder` 与 `aria-label` 同步改为「搜索需求 / BUG / 文档…（/）」。

键盘导航（`:111-135` 的 `flat` 扁平索引）必须把文档组一并纳入，否则方向键会在第三组上失灵。

**【评审 V-08 · 还有第三个集成点，v1 漏了】** `GlobalSearch` 里与结果形状耦合的地方有
**三处**，不是两处：除了 `flatten()`（`:37-43`）与分组渲染的 `base` 偏移（`:199` / `:204`），
还有一处「**有结果但没有任何高亮项时按 Enter**」的兜底（`:122-126`）：

```ts
const counts = data?.counts;
const target: Kind = counts && counts.bugs > 0 && counts.requirements === 0
  ? "bugs" : "requirements";
```

它是一个**二选一**表达式。加了文档桶之后，一次**只命中文档**的搜索按 Enter 会落到
`else` 分支 → 跳 `/requirements/board` → 用户看到一个与关键词无关的空看板。
改写规则（三态，且**宁可不跳也不乱跳**）：

- 三个桶里恰有一个非零 → 跳该桶的落地页（文档桶跳 `/documents?q=<keyword>`）；
- 多个桶非零 → **跳第一个非零桶**，顺序固定为 requirements → bugs → documents
  （与视觉顺序一致，用户按 Enter 时看到的第一组就是它）；
- 全为零 → **什么都不做**（现网此时也不该跳，只是二选一表达式恰好总能给出一个答案）。

判定逻辑抽成一个 `pickFallbackTarget(counts)` 纯函数，避免第四个桶出现时又漏一处。

---

### 2.2 支柱 B · 理解：Markdown、Diff、回滚

#### B-0 先修一个现存的不一致：`.csv` / `.json` / `.yaml` 明明能预览却被推去下载

调研发现的既有缺陷：`DocumentPreviewModal.decideMode()`（`:26-31`）按 **MIME 是否 ∈
`INLINE_SAFE_MIMES`** 决定要不要走 text 分支，而 `text/csv`、`application/json`、
`application/yaml` **都不在**那张表里（`mime.py:19-22` 只有 7 项，含 `text/plain` 与
`text/markdown`）。于是一份 `.json` 会落到「该类型不支持在线预览，请下载后查看」，
**尽管 `GET /documents/:id/content` 完全能返回它的正文，而且它还是可在线编辑的**——
用户可以编辑它，却不能预览它。

修法与理由（**必须按这个理由改，不能按"把它们加进白名单"改**）：

- text 分支取正文走的是 **`/content` 这个 JSON 端点**，正文最终渲染进 `<pre>` 的**文本节点**，
  **全程不产生 `blob:` URL、不产生任何浏览器自主解析的文档**；
- 而 `INLINE_SAFE_MIMES` 的职责是「**哪些 MIME 允许被浏览器当作文档直接渲染**」
  （`blob:` 预览与 `Content-Disposition: inline` 的判据），二者根本不是同一个问题；
- 故：`decideMode` 的 text 判据改为**扩展名 ∈ `TEXT_EXTENSIONS`**（前端目前**没有**这个常量，
  需按 §3.4 新建；`documentIcon` 已在用扩展名，判定风格一致），`INLINE_SAFE_MIMES`
  **一个字节都不动**——它仍然只有 7 项，`image/svg+xml` 与 `text/html` 仍然不在其中。

**【评审 V-05 · 顺序是这条修复的全部】** 现网函数的**第一行就是 inline-safe 闸**
（`DocumentPreviewModal.tsx:26-31`，四分支 `image|pdf|text|download`）：

```ts
// 现网（错的那版）：csv/json/yaml 在第一行就被短路成 download，
// 无论后面的 text 判据怎么改都到不了。
function decideMode(mime: string | undefined): Mode {
  if (!mime || !isInlineSafeMime(mime)) return "download";
  if (mime.startsWith("image/")) return "image";
  if (mime === "application/pdf") return "pdf";
  return "text";
}
```

因此**只改「text 判据」是不够的，必须把扩展名判据前置到 inline-safe 闸之前**。
改写后的完整函数（实施时逐字照抄，注释一并保留）：

```ts
/**
 * 预览模式判定。
 *
 * 【为什么 text 分支用扩展名、而不用 INLINE_SAFE_MIMES】
 * 两个常量回答的是**不同的问题**：
 *   - TEXT_EXTENSIONS  = 「这份东西的正文能不能当纯文本读」——正文经 /content 这个
 *     JSON 端点取回，最终落进 <pre> 的**文本节点**，全程不产生 blob: URL、不产生
 *     任何由浏览器自主解析的文档，故它没有任何安全职责。
 *   - INLINE_SAFE_MIMES = 「哪些 MIME 允许被浏览器当作文档直接渲染」——它是 blob:
 *     预览与 Content-Disposition: inline 的判据，text/html 与 image/svg+xml 被刻意
 *     排除在外，因为它们能在本站源上执行脚本。
 * 把 csv/json/yaml 加进 INLINE_SAFE_MIMES 是一个看起来更短、实则把上一轮唯一还生效的
 * 防线撬松的改法（text/html 与它们只隔一行）。**不要那样做**（评审 R-13）。
 *
 * 【顺序不可颠倒】扩展名判据必须在 inline-safe 闸**之前**：text/csv、application/json、
 * application/yaml 都不在 INLINE_SAFE_MIMES 里，闸在前就永远到不了 text 分支——
 * 那正是本次要修的 bug 本身（评审 V-05）。
 */
function decideMode(mime: string | undefined, filename: string | undefined): Mode {
  if (isTextExtension(extensionOf(filename))) return "text";   // ← 前置
  if (!mime || !isInlineSafeMime(mime)) return "download";
  if (mime.startsWith("image/")) return "image";
  if (mime === "application/pdf") return "pdf";
  return "download";        // ← 兜底由 "text" 改为 "download"：走到这里说明
                            //    扩展名不是文本，再当文本读就是猜（原 "text" 只可能
                            //    被 text/plain / text/markdown 命中，已被第一行接管）
}
```

调用点须一并传入当前版本的 `original_filename`（模态已持有 `version`，无需新请求）。
`extensionOf` / `isTextExtension` 与 `TEXT_EXTENSIONS` 一同放进 `lib/constants.ts`
（§3.4），与后端 `mime.py:12` 的七项**逐字一致**。

**验收判据**：`INLINE_SAFE_MIMES` 的 diff 必须**为空**；手测第 14 条（`.json` / `.csv`
能看到正文）必须通过。两条缺一，这处修复就没有真正落地。

#### B-1 `frontend/lib/markdown.ts`——渲染成 React 元素，不是 HTML

**铁律（不可协商）**：渲染器的返回类型是 `ReactNode[]`，实现中**不得出现**
`dangerouslySetInnerHTML`、`innerHTML`、`document.write` 或任何字符串拼 HTML 的路径。
理由不是「更干净」，而是**结构性的**：只要产物是 React 元素，用户正文里的
`<img src=x onerror=alert(1)>` 就只能作为**文本节点**出现，XSS 不是「被过滤掉了」，
而是**没有可以注入的位置**。上一轮 §8 R-2 的教训（三道防线里两道在预览路径上失效）
在这里以「不给自己留后门」的方式解决。

支持的子集（**刻意小**，覆盖研发文档 95% 的写法）：

| 语法 | 产出 | 备注 |
|---|---|---|
| `# ~ ####` ATX 标题 | `h1~h4` | 不支持 setext 下划线式 |
| 围栏代码块 ` ```lang ` | `pre > code` | `lang` 只作为 `data-lang` 展示，**不做语法高亮**（那需要一整套词法器） |
| 行内 `` `code` `` | `code` | |
| `**粗**` / `*斜*` / `_斜_` | `strong` / `em` | 同一行内可嵌套，解析顺序：代码 → 链接 → 粗 → 斜 |
| `- ` / `* ` / `1. ` 列表 | `ul` / `ol` | 支持**一层**嵌套（两个或四个空格缩进）；更深的层级按纯文本处理 |
| `> ` 引用 | `blockquote` | 连续行合并为一个块 |
| `---` / `***` | `hr` | |
| `[文字](url)` | `a` | **仅 `http:` / `https:` / `mailto:`**；其余（含 `javascript:`、`data:`）**降级为纯文本**并保留原始字面。`target="_blank" rel="noopener noreferrer"` |
| GFM 表格 | `table` | 需要表头 + 分隔行；单元格内只做行内解析 |
| 图片 `![]()` | **纯文本** | **不渲染外链图片**——它会向第三方泄漏内网访问行为，且本产品的图片走 blob 预览。渲染为 `[图片: alt]` 字样 |
| 裸 HTML | **纯文本** | 逐字显示，不解析 |

实现形态：单遍**行扫描**切块（block splitter），块内再做行内解析（inline parser）。
两个函数、一个不超过 200 行的文件；圈复杂度以「块类型查找表 + 每类一个小函数」控制在 10 以内
（CLAUDE.md 第六节）。**不做**：脚注、任务列表勾选、HTML 实体解码、自动链接、删除线。

**接入点**：`DocumentPreviewModal` 在文本预览时，若当前版本扩展名 ∈ `{.md, .markdown}`，
默认走渲染视图，并提供「渲染 / 源码」切换（状态记在组件内，不持久化）。
其余文本类型（`.txt` / `.log` / `.json` / `.csv` …）行为**逐字节不变**，仍是 `<pre>`。

**超长保护**：正文可能被后端按 `DOC_TEXT_PREVIEW_MAX_BYTES`（1 MB）截断，
`content.truncated === true` 时渲染视图顶部必须给出一条明确横幅——
「已截断显示前 1 MB，渲染结果可能不完整（例如未闭合的代码块）」。
这是本轮唯一一处「渲染结果可能与源文件不一致」的地方，必须说出来。

#### B-2 `frontend/lib/diff.ts`——行级对比

```ts
export type DiffOp = "equal" | "insert" | "delete";
export interface DiffRow { op: DiffOp; leftNo: number | null; rightNo: number | null; text: string; }
export interface DiffResult { rows: DiffRow[]; added: number; removed: number; degraded: boolean; }
export function diffLines(left: string, right: string): DiffResult;
```

算法用**经典 LCS 动态规划**（不是 Myers）：实现只有二十来行、行为完全可预测，
对研发文档这个量级足够。**规模保护**是必须的：`left.length * right.length > DIFF_MAX_CELLS`
（常量 `4_000_000`，约等于两侧各 2000 行）时**不计算**，直接返回
`{ rows: [整块删除, 整块插入], degraded: true }`，UI 显示「文件过大，已降级为整块对比」。
浏览器主线程上跑一个 O(n·m) 的 DP 必须有闸，否则一个 5 万行的日志会让页面白屏——
**如实降级好过假装计算**。

尾随空白与行尾符：比较前统一 `\r\n → \n`，**不 trim**（缩进变化是真实变化）。

**入口**：`DocumentVersionTimeline` 每行加一个复选框，恰好选中两个版本时底部出现「对比这两版」。
点击后拉两次 `GET /documents/:id/content?version_id=`，交给 `DocumentDiffModal`。
**只对文本版本开放**：任一版本非文本（`content` 端点返 415）时，按钮置灰并给出提示。

#### B-3 版本回滚：内容寻址的免费红利

`POST /api/documents/:id/versions` 的 JSON 分支现网只接受 `{content, note}`（全文改写）。
新增互斥的第二形态 `{from_version_id, note}`：

```python
def add_version_from_existing(document, *, source_version, note, uploader):
    """把某个历史版本重新指定为最新版本（**不 commit**）。

    内容寻址的直接红利：新版本行与源版本行共享同一个 sha256，**磁盘上不写一个字节**，
    也不删任何历史行。回滚在这里是「加一行」，不是「退回去」——审计链完整可读：
    v1 → v2 → v3 → v4(= v1 的内容)。
    """
```

- `source_version` 由现网 `service.find_version(document, from_version_id)` 解析，
  **不属于本文档的 id 一律视为不存在**（现网语义，直接复用）→ 404。
- `from_version_id == document.current_version_id` → **409**，`detail.reason = "already_current"`。
  回滚到当前版本是一次无意义的写，静默接受只会在版本列表里制造一行噪音。
- 元数据（`original_filename` / `mime_type` / `size_bytes` / `sha256`）**逐字段抄自源版本**；
  `note` 缺省填充为 `f"回滚到 v{source_version.version_no}"`。
- blob 缺失（磁盘被外力删掉）→ **410**，与 `/download` 对齐；**不允许**建出一行指向空气的版本。
  校验方式：`storage.blob_exists(sha256)`（若现网无此函数，用 `os.path.exists(blob_path(...))` 
  的等价封装新增于 `storage.py`，保持「路径推导只有一处」）。
- 时间线：写 `doc_rolled_back`（新 action），并**复用现网 `service.fanout_revision`** 的扇出与上限
  （`DOC_FANOUT_MAX_LINKS`），响应体形状与既有 `DocumentRevisionResult` 完全一致——
  前端 `useDocumentContent` / 版本列表无需为回滚写第二套解析。

**互斥校验**：JSON 体同时带 `content` 与 `from_version_id` → **400**（`detail.reason = "ambiguous_source"`）。
两者都没有 → 现网既有的 400 分支不变。

**【评审 V-06 · 分流必须在 `_reject_uneditable` 之前】** 现网 `create_version` 的 JSON 分支
在读 `content` **之前**先调 `_reject_uneditable(document)`（`routes/documents.py:238-241`），
它的四条判据（文本扩展名 / 不超编辑阈值 / 未被截断 / 严格 UTF-8）是为「**在线编辑文本**」
设的：用户改一个字保存，截断即成为新版本的全部内容——那道闸拦的是**数据损毁**。

而回滚**不产生任何新内容**：它只是把一个已经存在的、字节完整的历史版本重新指为当前版本。
一份 `.png` / `.docx` / `.pdf` 的回滚与「能不能当文本编辑」毫无关系。若把 `from_version_id`
分支写在 `_reject_uneditable` 之后，回滚任何二进制文档都会拿到
`409 {"reason": "binary"}`——而 §4.2 的状态码表里**根本没有这一档**，足见设计意图是
回滚对**任意**文档可用。

故 JSON 分支的判定顺序**钉死**为：

```python
data = json_body()
note = want_str(data, "note", max_len=255) or None
expected = want_int(data, "expected_version_id")
# …既有的 expected_version_id 乐观锁 409 复核（对回滚同样生效：并发下
#   「我以为我在从 v3 回滚」而实际已是 v5，应当照样冲突）…

from_version_id = want_int(data, "from_version_id")
if from_version_id is not None:
    if isinstance(data.get("content"), str):
        return _bad_source("ambiguous_source")          # 400
    return _rollback(document, from_version_id, note)    # ← 完全绕过 _reject_uneditable

blocked = _reject_uneditable(document)                   # ← 只管在线编辑那条路
if blocked:
    return blocked
...既有 content 分支不变...
```

`_rollback` 内部按 §2.5 时序 C 依次判 404 / 409 / 410，随后走
`add_version_from_existing` + `fanout_revision`，与 content 分支汇合到同一个 201 响应体。
B 组新增 **B8** 用例：对一份 `.png` 文档回滚必须 **201**，不得 409。

---

### 2.3 支柱 C · 产出：模板与 Agent 归档

#### C-1 文档模板

新建**叶子模块** `backend/services/documents/templates.py`（只依赖 stdlib + `models.document`
的常量，任何一层都可安全 import——与上一轮 `mime.py` 同款位置，见其 F2 教训）：

```python
TEMPLATE_KINDS = ("requirement_spec", "design", "test_plan", "test_report", "release_note")

def render(kind: str, *, entity: str, ticket, author_name: str, stage_label: str) -> str:
    """产出一份 Markdown 骨架正文。占位符只用已知事实填充，**绝不编造内容**。"""
```

每份模板的首部是统一的元信息块（工单编号 `REQ-42` / `BUG-7`、工单标题、创建阶段、创建人、日期），
随后是该类别的章节骨架，例如 `test_report` 是「测试范围 / 用例执行结果 / 缺陷汇总 / 结论与风险 / 附件」。
**模板正文不含任何「待填写」以外的断言**——一份自称"全部通过"的空报告比没有报告更危险。

八个 kind 里只给五个模板：`bug_evidence`（复现材料本质是录屏/日志，模板无意义）、
`reference`、`other` **不提供**，前端对这三类只显示「上传文件」。

**端点**：不新增路由，扩展 `POST /api/{entity}/:id/documents` 的 JSON 分支为三态：

| JSON 体 | 行为 |
|---|---|
| `{"document_id": N, "label"?}` | 绑定已有（现网，不变） |
| `{"template_kind": "test_plan", "title"?}` | **新增**：按模板建文档（v1）并绑定 |
| 其他 | 400（现网，不变） |

模板新建走 `service.create_text_document(...)`（新增，见 §3.2），文件名
`{kind}-{entity}-{ticket.id}.md`，标题缺省 `f"{ticket.title} · {kind_label}"`（超 200 字符按
`want_str(max_len=200)` 的既有规则截断前置校验 → 400）。落库路径与人工上传**完全同一条**
（同样经内容寻址、同样建 v1、同样写 `doc_attached`），**不新开第二条写入路径**。

**【评审 V-09 · `create_text_document` 是一条绕过四道上传闸的新写入路径，必须自持不变量】**
现网所有落盘都经 `_validate_upload` 的四道闸（存在性 / 文件名清洗 / **扩展名白名单** /
魔数嗅探），而「一段文本入库」天然走不了它们。`add_version_from_text` 之所以安全，
是因为它**复用当前版本的文件名与 MIME**——文件身份是既定的、早已过闸的；
而 `create_text_document` 是**从零造身份**，这是本轮唯一一处新增的「无闸落盘」。
故它必须自持以下四条，逐条写进函数 docstring：

1. **扩展名恒为 `md`，不接受调用方指定**。签名里没有 `extension` / `mime_type` 参数；
   MIME 由 `mimetable.mime_for("md")` 推导（= `text/markdown`），与「`Content-Type`
   请求头一律不信任」的既定原则一致。
2. **启动期断言 `"md" in DOC_ALLOWED_EXTENSIONS`**，与 `doc_policy.assert_thresholds`
   并列注册。运维把 md 从白名单里摘掉却留着模板功能，应当**起不来**，而不是在用户点
   「用模板新建」时抛一个语义不明的 500。
3. **正文长度上限 = `DOC_TEXT_EDIT_MAX_BYTES`**（默认 512 KB）。模板正文只有几百字，
   Agent 归档正文受 `agent_executor._MAX_BODY_CHARS = 20000` 约束，两者都远在限内；
   这条闸是为「将来第三个调用方」准备的。超限 → `ValidationError` → 400。
4. **落盘链路逐字复用 `storage.digest_and_persist`**（含去重与 mtime 触碰），
   `_append_version` 仍是 `current_version_id` 的唯一写入点。**不新写一行落盘代码。**

调用方只有两个：模板新建（本节）与 Agent 归档（C-2）。两者都只传 `title / kind /
content / project_id / uploader`。

#### C-2 Agent 交付物归档（本轮技术含量最高的一处）

**第一步：给产物加来源标记，且零破坏。**
`agent_executor.generate_work` 现网返回 `str`，唯一调用点是 `agent_runner.py:101`。
本轮**不改它的签名**（改了会牵动 `real-agent-execution` 一轮的全部叙述与潜在测试桩），
而是新增：

```python
class WorkProduct(NamedTuple):
    text: str
    from_llm: bool          # True 仅当真实 LLM 返回了被采纳的正文

def generate_work_product(entity, ticket, agent, to_status, fallback_message) -> WorkProduct:
    """现 generate_work 的全部逻辑搬到这里，只是回传时带上来源。"""

def generate_work(entity, ticket, agent, to_status, fallback_message) -> str:
    """薄包装，保持既有签名与语义不变（零破坏）。"""
    return generate_work_product(entity, ticket, agent, to_status, fallback_message).text
```

`from_llm` 为真的条件与现网「采纳 LLM 正文」的条件**逐字相同**：`_llm_active()` 为真
且返回非空、且未超 `_MAX_BODY_CHARS`。所有降级路径一律 `from_llm=False`。

**第二步：归档模块** `backend/services/documents/agent_archive.py`

```python
# (entity, agent_kind, to_status) → 该步骤的产物应归为哪一类文档。
#
# 【铁律 · 键必须含 agent_kind（评审 V-01）】**一个 Agent 只能产出自己职能范围内的
# 交付物**。少了 agent_kind 这一维，键就退化成「谁走到这一步都算数」，于是：
#   - ("requirement", "testing") 唯一由 **dev**-agent 到达（in_development→testing 与
#     bug_fixing→testing 两条边，见 agent_runner.AGENT_FORWARD），
#   - ("bug", "verifying")       唯一由 **dev**-agent 到达（fixing→verifying），
# 而这两个阶段的清单期望项分别是「测试计划」与「测试报告」——dev-agent 的一段
# 「我已提交修复」正文会被归档成 QA 的交付物，并把 QA 的清单项**点绿**。
# 那正是本模块前置条件 1 判死刑的「制造材料齐了的假象」，只是换成了真实 LLM 产物；
# 而 §0 又说本轮的意义是让 DOC_STAGE_GATE **有资格被打开**——门禁一旦打开，
# 它会放行一份没有任何 QA 参与过的「测试报告」。这条错误比不归档坏得多。
#
# 键的两条选择标准（缺一不可）：
#   1. 该类别恰好是**目标阶段**的清单期望项（doc_policy.STAGE_DOC_EXPECTATIONS）；
#   2. 该类别确实属于**这个 kind 的 Agent 的职能**。
# 两条由 §7.2 的 C7（正向）与 C11（反向）双向守卫。
ARCHIVE_KIND: dict[tuple[str, str, str], str] = {
    # dev-agent：产出的是实现侧材料。
    ("requirement", "dev", "in_development"): "design",       # 期望 (requirement_spec, design)
    ("bug",         "dev", "fixing"):         "bug_evidence", # 期望 (bug_evidence,)
    # qa-agent：产出的是验证侧材料。
    ("requirement", "qa",  "reviewing"):      "test_report",  # 期望 (test_report,)
    ("bug",         "qa",  "closed"):         "test_report",  # 期望 (test_report,)
    # generic-agent：**故意不配**。它的两条边（requirement/assigned→in_development、
    # bug/assigned→fixing）产出的是泛化认领说明，归成任何一类都是硬套。
}
```

**被刻意删掉的两格，以及为什么删掉比配错好**：

| 曾经的键 | 曾经的值 | 唯一到达者 | 删除理由 |
|---|---|---|---|
| `("requirement", "testing")` | `test_plan` | **dev**-agent | 测试计划是 QA 在进入测试前写的；dev-agent 交完代码时写不出它。这一格**应当**红着，直到 QA 或人补上 |
| `("bug", "verifying")` | `test_report` | **dev**-agent | 同上，且更危险：`verifying` 的整个语义就是「等着被别人验」，让提交修复的人自己出具验收报告，等于取消这个状态 |

同理，`("requirement", "in_development")` 归 `design` 而**不**补 `requirement_spec`——
需求说明书是人的输入，让 Agent 代写它是本末倒置；这一格清单**应当**保持红色直到有人上传。
以上三条取舍必须逐条写进代码注释，否则后人会以为是漏配，好心把它们补回来。

**触发的四条前置条件（全部满足才归档，缺一即静默跳过）**：

1. `product.from_llm` 为真——**降级模板绝不归档**。一句「dev-agent 已认领需求」存成文档，
   只会往文档库里灌垃圾，还会把阶段清单点绿，制造「材料齐了」的假象。**这条同时是
   存量 506 条用例零影响的机制性保证**：`_llm_active()` 在 `TESTING` 下恒 False。
2. `current_app.config["DOC_AGENT_ARCHIVE"]` 为真（默认 **True**，运维注记见 §5.3）。
3. `(entity, agent.kind, to_status) ∈ ARCHIVE_KIND`。
4. `len(product.text.strip()) >= DOC_AGENT_ARCHIVE_MIN_CHARS`（默认 200）——
   两句话的产出不值得成为一份「交付物」。

**复用而非泛滥**：同一张单被反复推进（`bug_fixing → testing → bug_fixing → testing`）时，
不能每次都新建一份 `test_plan`。识别依据**复用既有列，不加新列**：
绑定时把 `DocumentLink.label` 写成 `agent:{kind}`；归档前先查该工单上是否已有
`label == f"agent:{kind}"` 的 link——

- 有 → 对那份文档**追加新版本**（`service.add_version_from_text`，note 记
  `f"{agent.name} 在「{stage_label}」阶段更新"`）；
- 无 → 新建文档 + 绑定（`link.stage` 取**推进后的目标状态**，因为这份材料属于新阶段）。

**【评审 V-03】归档必须拆成两段：落盘在写锁之外，元数据写入在事务之内。**

`services/documents/service.py` 的模块 docstring 写着一条贯穿全模块的硬约束：

> 落盘（慢，无锁）在 `db.session` 的任何写入**之前**完成，事务内只做元数据写入。
> 这与 `agent_prompts` 把 LLM 调用挪出写锁窗口是同一手法（§8 R-7）。

v1 把归档整体放在 `ticket.status = to` / `Comment` / `Activity.log` **之后**，而
`db.session.begin_nested()` 会先 flush 这些挂起写（→ 取得 SQLite 写锁），然后才在锁内
调 `digest_and_persist` 落盘。SQLite 是单写者，这是上一轮 R-7 那个坑的原样重演。
故本轮把 `archive` 拆成两个函数：

```python
def archive_prepare(entity, ticket, agent, to_status, product) -> Optional[ArchivePlan]:
    """四条前置条件判定 + **落盘**。此刻 session 必须无挂起写（调用点保证）。

    Returns:
        ArchivePlan(kind, blob, existing_link, target_stage)；不满足条件时 None。
        **本函数不碰 db.session 的写路径**，只做只读查询（查既有 agent:{kind} link）
        与磁盘 IO。失败时抛异常由调用方按下面的语义兜底。
    """

def archive_commit(plan, entity, ticket, agent) -> None:
    """把 plan 落成元数据行（**不 commit**）。全程无磁盘 IO，写锁窗口收敛到亚毫秒。"""
```

**事务与失败语义（铁律）**：两段都整体包在 `try/except Exception` 里，失败只
`log.warning` **绝不阻断 Agent 推进**——取向与 `agent_executor` 对 LLM 的兜底完全一致：
**自动流水线不能因为一个附属动作失败而停摆**。
`archive_commit` 在**独立的 SAVEPOINT** 中执行（`db.session.begin_nested()`），
失败时只回滚该嵌套事务，主推进事务不受影响。
（`archive_prepare` 无需 SAVEPOINT：它不写 session。它落盘失败留下的至多是一个孤儿
blob，`tools/gc_orphan_blobs.py` 本就为此存在——**在两种失败模式之间永远选可修复的那个**。）

> **【评审 V-04 · pysqlite 的 SAVEPOINT 有前置条件，必须写进模块 docstring】**
> SQLAlchemy 的 pysqlite 方言文档明确列出 SAVEPOINT **不能开箱工作**（pysqlite 的隐式
> BEGIN 处理），需要 `isolation_level=None` + 手工 `BEGIN` 事件那套 workaround；
> 本仓库 `extensions.py` **没有**做这个 workaround（只挂了 PRAGMA 监听）。
> 它在本场景下能工作，**唯一原因**是 `archive_commit` 的调用点之前已经有挂起 DML
> （`ticket.status` / `Comment` / `Activity`），`begin_nested()` 的 flush 会先发出它们，
> 事务因此已经打开，SAVEPOINT 落在事务内。
> **这是一个必须写下来的前置条件**：任何把 `archive_commit` 挪到「session 尚无挂起写」
> 位置的改动，都会让 SAVEPOINT 在事务外发出、回滚不再隔离任何东西，**而 C8 用例仍会绿**
> （它只断言推进成功）。若将来确实需要在无挂起写时使用 `begin_nested`，
> 必须先给 `extensions.py` 补上 pysqlite workaround，那是一次独立的、需要单独回归的改动。

**落点与调用顺序**（`agent_runner.advance_one` 内，逐行）：

```python
product = agent_executor.generate_work_product(entity, ticket, agent, to, fallback_message=message)
body = product.text

# ① 落盘：此刻 session 无挂起写（generate_work_product 只读 feed），不持有 SQLite 写锁。
#    target_stage 显式传 `to`，**不**读 ticket.status——此时它还是旧状态。
plan = agent_archive.archive_prepare(entity, ticket, agent, to, product)   # ← 新增

doc_policy.agent_missing_hint(entity, ticket, to)     # 现网，位置不变
ticket.status = to
ticket.position = _next_position(...)
db.session.add(Comment(...))
activity = Activity.log(...)

# ② 元数据写入：无磁盘 IO；SAVEPOINT 的前置条件（已有挂起写）由上面四行保证。
agent_archive.archive_commit(plan, entity, ticket, agent)                  # ← 新增
return to, comment, activity
```

`link.stage` 取的是**推进后的目标状态**（由 `plan.target_stage` 携带，不依赖调用时
`ticket.status` 的取值），因为这份材料属于新阶段。

**时间线与通知**：归档复用 `service.bind_document(...)` / `add_version_from_text(...)`
的时间线写入，因此自动得到 `doc_attached` / `doc_revised`。
actor 为 `("agent", agent.id)`——`Activity.log` 已支持该 actor_type（现网 `agent_advanced`
即如此）。

> **【评审 V-10 · 归档路径不发通知】** v1 直接复用 `bind_document` / `fanout_revision`，
> 而两者内部都会调 `notifications.notify_document` → 每次归档给 reporter 推一条
> `document_added`。`run=all` 单次最多 6 步（`MAX_AGENT_STEPS`）、`autorun-all` 还会跨多张单
> 循环调用；而 §10 已把「通知类型不细分」列进 Non-Goals，于是用户在通知中心看到的是一串
> 与人工上传**无法区分**的 `document_added`——且 `DOC_AGENT_ARCHIVE` 默认为 `True`，
> 这是升级即生效的行为变更。
> 故本轮规定：**归档路径只写 Activity、不发任何 Notification**。落地方式是给
> `bind_document` / `fanout_revision` 增加一个 `notify: bool = True` 关键字参数，
> 归档路径传 `notify=False`——**既有全部调用点行为逐字节不变**。
> 理由与 `doc_detached`「解除绑定刻意不发通知——它是一次收敛性操作」同源：
> **自动化产生的附属动作不该占用人的注意力预算**，时间线上有留痕，需要时查得到。
> `notifications._ticket_humans` 只取人类收件人，Agent 本就不会给自己发通知，这一层不用改。
> C13 用例断言：归档发生后 `Notification` 表零新增。

---

### 2.4 支柱 D · 治理：软删除、回收站、过期清理

#### D-1 数据与语义

`documents` 新增两列（DDL 与登记见 §5.1）：`deleted_at DATETIME`、`deleted_by_id INTEGER`。
`Document.is_deleted` 为 `self.deleted_at is not None`。

`DELETE /api/documents/:id` 的**外部契约保持不变**（仍 204、仍 409、仍 403），只是内部
由「删行 + reap」改为「置位 deleted_at」：

| 场景 | 现网 | 本轮 |
|---|---|---|
| 无绑定 | 删行 + 回收 blob | **软删**，仍返回 204 |
| 有绑定，无 `force` | 409 `document is still linked` | **不变** |
| 有绑定 + `?force=1`（pm/admin） | 解绑全部 + 删行 | 解绑全部（`doc_detached` 照写）+ **软删**，仍 204 |
| 回收站中的文档 + `?purge=1` | — | **新增**：物理删行 + `reap(orphans)`；**仅 admin**；非回收站中的文档返回 409 |

现网四条删除用例（`test_documents.py:192/200/205/211/224`）断言的是 204 / 404 / 403 / 409 /
「列表里没有了」/「有 doc_detached」——**软删后逐条仍然成立**，前提是 D-2 的过滤点全部落地。
这不是巧合，是本设计刻意对齐了既有断言面，以免用「改测试」掩盖语义变更。

#### D-2 过滤点清单（**漏一处即产生幽灵文档**）

新增 `backend/services/documents/trash.py`，导出**唯一的**谓词：

```python
def not_deleted():
    """`Document.deleted_at.is_(None)` 的唯一出处。所有列表 / 查找 / 计数一律引用它。"""

def is_deleted():
    """`Document.deleted_at.isnot(None)`——回收站视图与 purge / restore 的唯一出处。

    两个谓词都放在这里而不是散在调用点，是为了让「软删的判据是什么」在全仓库只有
    一个答案；将来若改成 `deleted_by_id IS NOT NULL` 或加第三态，只改这两行。
    """
```

必须接上它的**八处**，以及漏掉各自的后果：

| # | 位置 | 漏掉的后果 |
|---|---|---|
| 1 | `routes/documents.py::_get_document_or_404`（`:56`） | 被删文档仍可被详情 / 下载 / 改版 / 编辑访问——**删除等于没删**。**注意它需要结构改动，见下方【评审 V-07】** |
| 2 | `routes/documents.py::list_documents`（`:114`） | 文档库里仍然列着它 |
| 3 | `service.ticket_documents_query`（`:255`） | 工单抽屉里仍然列着它 |
| 4 | **`service.bound_kinds`（`:264`）** | **阶段清单仍被它点绿、门禁仍被它放行**——最隐蔽也最危险的一处 |
| 5 | `counts.link_counts` / `document_link_counts`（`:22` / `:63`） | 看板与列表的回形针徽章数字虚高，点进去只有 2 份却显示 3 |
| 6 | `search.search_documents`（本轮新增） | 搜得到、点进去 404 |
| 7 | `routes/ticket_documents.py::_bind_existing`（`:84`） | 能把一份已删文档重新绑到单上，回收站语义直接失效 |
| 8 | `routes/ticket_documents.py::detach_ticket_document`（`:141`） | **可不改，但必须知道它在**（评审 V-16）：解绑是幂等的，过滤与不过滤都返回 204，行为无差别。列在这里只为让上面那句「七处」不再是一句需要读者自己去验证完整性的断言——**第 8 处的正确处置是「有意不改」，而不是「没看见」** |

第 4、5 两处涉及 join：`bound_kinds` 与 `link_counts` 都是从 `DocumentLink` 出发的聚合，
必须 `join(Document, Document.id == DocumentLink.document_id).filter(trash.not_deleted())`。
**这是本轮最容易写漏的两行**，§7.2 为它们各配了一条专门的用例。

**【评审 V-07 · 第 1 处不是「加一个 filter」，是一次结构改动】**
现网 `_get_document_or_404` 的实现是 `db.session.get(Document, document_id)`
（`routes/documents.py:57`）——`session.get` 按主键直取（还会命中 identity map），
**加不了 filter**。而同一个 helper 被 `delete_document` 复用，`?purge=1` 需要的恰恰是
**相反**的过滤（**只**在回收站里找）。故它必须改成显式双模式：

```python
def _get_document_or_404(document_id, *, mode: str = "live"):
    """按 id 取文档。

    Args:
        mode: "live"（默认，**只**取未删的——全部读写端点走这一档）
            | "trashed"（**只**取回收站里的——`?purge=1` 与 restore 走这一档）。

    为什么不做 "any" 档：一个「两边都能取到」的入口迟早会被某个新端点默认用上，
    而它恰恰是本节全部风险的来源。**宁可两个调用方各写一次 mode，也不留一个默认放行的口子。**
    """
    query = Document.query.filter(Document.id == document_id)
    query = query.filter(trash.not_deleted() if mode == "live" else trash.is_deleted())
    document = query.first()
    if document is None:
        return None, (jsonify({"error": "document not found"}), 404)
    return document, None
```

`DELETE` 的判定顺序据此钉死（**顺序不可换**，否则错误码会漂）：

```
DELETE /api/documents/:id?purge=1
  1. mode="trashed" 取文档 → 取不到时**再**用 mode="live" 探一次：
       - live 里有   → 409 {"reason": "not_deleted"}   （文档在，只是没被删）
       - 两边都没有  → 404                              （文档根本不存在）
  2. role != admin → 403
  3. trash.purge(document, actor) → commit → reap(orphans) → 204
```

第 1 步的「探两次」是刻意的：把「你删错对象了」（404）与「你得先删一次」（409）
分开，是 §4.4 状态码表的直接要求，而单次查询给不出这个区分。两次查询都走主键，
代价可忽略。

#### D-3 恢复、清理与 GC 的相互作用

- `POST /api/documents/:id/restore`：`deleted_at = None`，权限 `can_manage_document`；
  非回收站中的文档 → 409（`reason: "not_deleted"`）。绑定关系**从未解除过**（软删不动 links），
  因此恢复后工单抽屉里的位置、`link.stage` 快照全部原样回来——这正是软删相对
  「删了再传一遍」的全部价值。
  例外：走 `?force=1` 软删的那些，links 已被解除且写了 `doc_detached`，恢复只能恢复文档本体，
  **绑定不会自动回来**。这一点必须在前端恢复确认框里如实说明。
- **时间线**：软删 / 恢复对其**每一个绑定工单**写一条 `doc_trashed` / `doc_restored` Activity，
  复用 `DOC_FANOUT_MAX_LINKS` 上限与 `fanout_truncated` 的如实汇报。**均不发通知**
  （收敛性操作，与现网 `doc_detached` 同理）。
- **与 blob GC 的关系（关键，且天然安全）**：软删**不删** `document_versions` 行，
  因此 `service.unreferenced_digests` 判定这些摘要仍被引用，`tools/gc_orphan_blobs.py`
  **不会**回收它们——回收站里的文档恢复出来一定是完整的。这条不需要写任何新代码，
  但**必须写一条测试钉死它**（`test_gc_keeps_blobs_of_soft_deleted_documents`），
  因为它是一条「靠不变量成立、但极易被将来某次优化打破」的性质。
- **【评审 V-02 · P0】`trash.purge()` 必须是自包含的，否则回收站里的常态文档一 purge 就 500**：
  `DocumentLink.document_id` 是**真外键**（`models/document_link.py:23`），且
  `PRAGMA foreign_keys=ON` 在每条连接上真实生效（`extensions.py:61`）。
  而软删的立身之本恰恰是「**绑定关系从未解除过**」——所以
  **「回收站里的文档仍有绑定」是常态，不是边界**。对这样一份文档直接
  `service.delete_document(document)`（内部 `db.session.delete`）会撞外键 →
  `IntegrityError` → 路由 500 / CLI 崩溃。
  v1 只在时序图里给路由写了一句「detach_all_links（若还有）」，却又要求 CLI
  「走与 `?purge=1` **完全相同的服务函数** `trash.purge(document)`」——detach 到底在
  路由里还是在服务函数里是**未定义**的；写在路由里，CLI 必炸。
  故本轮**钉死**：

  ```python
  def purge(document, actor) -> set:
      """把一份**回收站中**的文档彻底删除（**不 commit**），返回可回收的摘要集合。

      自包含：先解绑（逐单写 doc_detached，受 DOC_FANOUT_MAX_LINKS 约束）再删行。
      **绝不假设调用方已经解过绑**——软删默认保留全部绑定，「还有 link」才是常态；
      把 detach 留在路由里，CLI 路径就会在第一份带绑定的过期文档上撞外键（评审 V-02）。

      Args:
          actor: HTTP 路径为 ("user", uid)；CLI 路径恒为 ("system", None)。

      Raises:
          ValueError: 该文档不在回收站（调用方的判定漏了，属于编程错误，不吞）。
      """
      if document.deleted_at is None:
          raise ValueError(f"document {document.id} is not in trash")
      service.detach_all_links(document, actor)
      return service.delete_document(document)
  ```

  路由与 CLI **共用这一个入口**，两条路径的差别只有 actor 与「谁来 commit / reap」。
  §7.2 新增 **D16** 用例专测「一份**仍有绑定**的回收站文档被 purge」——
  D11 大概率拿的是无绑定文档，抓不到这个 500。

- **过期清理**：新增 `backend/tools/purge_trash.py`，与现网 `gc_orphan_blobs.py` 同款形态——
  **默认 dry-run**，`--apply` 才真删，`--days N` 覆盖 `DOC_TRASH_RETENTION_DAYS`（默认 30）。
  它对每个过期文档调 `trash.purge(document, actor=("system", None))`，
  commit 之后调用 `reap(orphans)`。**逐个文档各自 try/except**：一份文档清理失败
  （例如 blob 权限问题）只记进 `skipped` 并继续，不让整批停摆。
  **不自动调度**——本项目没有调度器，
  且不可逆操作应当由人按下（与 GC 工具、`purge_demo_data` 一致的既定取向）。
- `backend/tools/purge_demo_data.py` 的 `_untouched_counts` 增加一行「回收站中的文档」，
  与它既有的「文档三表两项」并列。它**不**清理回收站——那是 `purge_trash.py` 的职责，
  两个工具各自单一职责。

---

### 2.5 关键时序

**时序 A · Agent 归档（支柱 C-2）**

```
POST /api/agents/:id/advance  (或 tick / autorun)
  └─ routes/agents.py → agent_runner.advance_one(entity, ticket, agent)
       1. product = agent_executor.generate_work_product(...)      # 可能触网，session 无挂起写
       2. plan = agent_archive.archive_prepare(entity, ticket, agent, to, product)
            ├─ 四条前置条件任一不满足 → return None（静默，不写日志噪音）
            └─ 【此刻 session 仍无挂起写 → 不持有 SQLite 写锁】（评审 V-03）
                 ├─ 只读查 label == f"agent:{kind}" 的既有 link
                 └─ storage.digest_and_persist(...)                # 磁盘 IO 全部发生在这里
       3. doc_policy.agent_missing_hint(...)                       # 现网，位置不变
       4. ticket.status = to ; ticket.position = ...
       5. db.session.add(Comment(body=product.text))
       6. Activity.log("agent_advanced", ...)
       7. agent_archive.archive_commit(plan, entity, ticket, agent)
            └─ with db.session.begin_nested():                     # SAVEPOINT
                 │  【前置条件】4~6 已产生挂起写，flush 后事务必已打开（评审 V-04）
                 ├─ 有既有 link → service.add_version_from_text(..., notify=False)
                 │                 └─ fanout_revision(..., notify=False)   # 只写 doc_revised
                 └─ 无         → service.create_text_document(...)         # 复用已落盘的 blob
                                  └─ service.bind_document(..., label=f"agent:{kind}",
                                                           actor=("agent", agent.id),
                                                           notify=False)   # 只写 doc_attached
       8. return to, comment, activity
  └─ 路由层统一 db.session.commit()
  └─ commit 后：无 reap（归档只增不减）
```

失败路径：第 2 步异常 → `log.warning` + `plan = None`（至多留下一个孤儿 blob，
交给 `gc_orphan_blobs.py`）；第 7 步异常 → 嵌套事务回滚 → `log.warning` →
**第 8 步照常返回**。两种情况用户看到的都是「Agent 推进成功、只是这一步没有产出文档」，
而不是一个 500。

**时序 B · 软删与恢复（支柱 D）**

```
DELETE /api/documents/42            → can_manage_document 否 → 403
  ├─ _get_document_or_404 (已过滤软删) → 已在回收站 → 404
  ├─ link_count > 0 且无 force       → 409（不带 allowed 键）
  ├─ force=1 且 role ∈ {pm, admin}   → detach_all_links → doc_detached ×N
  ├─ trash.soft_delete(doc, actor)
  │    ├─ doc.deleted_at = utcnow() ; doc.deleted_by_id = user.id
  │    └─ 对前 DOC_FANOUT_MAX_LINKS 个 link 写 doc_trashed（不发通知）
  ├─ db.session.commit()
  └─ 204（**无 reap**：行还在，blob 必须留着）

POST /api/documents/42/restore
  ├─ 只在 deleted 集合里查 → 不在 → 409 {"reason": "not_deleted"}
  ├─ can_manage_document 否 → 403
  ├─ deleted_at = None ; deleted_by_id = None ; 写 doc_restored
  └─ 200 + Document 响应体

DELETE /api/documents/42?purge=1
  ├─ mode="trashed" 取 → 取不到时再 mode="live" 探一次（评审 V-07）
  │    ├─ live 里有  → 409 {"reason": "not_deleted"}
  │    └─ 两边都无   → 404
  ├─ role != admin → 403
  ├─ trash.purge(doc, actor=_actor())        # 自包含：内部先 detach_all_links 再删行
  │    └─ doc_detached ×N（受 DOC_FANOUT_MAX_LINKS 约束）→ orphans
  ├─ commit → reap(orphans)
  └─ 204
```

> **注意**：`?purge=1` 的目标**几乎总是仍有绑定**——软删刻意不解绑，这是 D-3 的立身之本。
> 因此「先 detach 再删行」是**主路径**而非兜底；它被收进 `trash.purge` 内部，
> 路由与 CLI 共用同一条（评审 V-02）。

**时序 C · 版本回滚（支柱 B-3）**

```
POST /api/documents/42/versions  {"from_version_id": 7, "note": null}
  ├─ can_manage_document 否 → 403
  ├─ 同时带 content → 400 ambiguous_source
  ├─ find_version(doc, 7) 为空 → 404
  ├─ 7 == current_version_id → 409 already_current
  ├─ storage.blob_exists(v7.sha256) 否 → 410
  ├─ add_version_from_existing(...)  → v_new（复制元数据，共用 sha256，零字节写盘）
  ├─ Activity "doc_rolled_back" + fanout_revision（上限 20，如实回传 truncated）
  └─ 201 DocumentRevisionResult（形状与既有改版完全一致）
```

---

### 2.6 权限矩阵（本轮新增动作）

| 动作 | 谁可以 | 判据来源 |
|---|---|---|
| 搜索到文档 | 任何已认证用户 | 与工单读权限对齐（沿用上轮 §2.7 的理由） |
| 模板新建并绑定 | `can_manage_ticket(user, ticket)` | 与「绑定已有」完全同一判据（`ticket_documents.py` 现网） |
| 回滚版本 | `can_manage_document(user, doc)` | 与「新建版本」同判据（`auth_helpers.py:75`） |
| 软删 / 恢复 | `can_manage_document`（上传者本人 或 pm/admin） | 同上 |
| `?force=1` 连带解绑 | pm/admin | 现网 `routes/documents.py:193` 不变 |
| **`?purge=1` 彻底删除** | **admin only** | 本轮新增；它是全系统唯一不可逆的文档操作，收口到最高角色 |
| 查看回收站 | 任何已认证用户可看**自己可管理的**；pm/admin 看全部 | `GET /documents?deleted=1` 对非 pm/admin **自动附加 `uploader_id = me`** |
| Agent 归档 | 系统内部，不经 HTTP | 无端点，无法被外部触发 |

前端 `lib/permissions.ts` 增加镜像 `canPurgeDocument(user)`（`role === "admin"`），
与既有 `canManageDocument` 并列，沿用「前端镜像、后端权威」的既定模式。

---

## 3. 文件 / 模块变更计划

### 3.1 后端 · 新建

| 文件 | 意图 |
|---|---|
| `backend/services/documents/templates.py` | 5 类文档的 Markdown 骨架 + `render()`；**叶子模块**，只依赖 stdlib 与 `models.document` 常量（避免上轮 F2 的循环 import） |
| `backend/services/documents/agent_archive.py` | `ARCHIVE_KIND` 三元组表 + `archive_prepare()` / `archive_commit()` 两段式（落盘在写锁外、元数据在 SAVEPOINT 内）；四条前置条件；模块 docstring 必须写明 pysqlite 的 SAVEPOINT 前置条件（评审 V-01 / V-03 / V-04） |
| `backend/services/documents/trash.py` | 软删 / 恢复 / 彻底删除 / 过期扫描的唯一实现；导出两个过滤谓词 `not_deleted()` / `is_deleted()`；`purge(document, actor)` **自包含**（内部先 detach 再删行，评审 V-02） |
| `backend/tools/purge_trash.py` | 回收站过期清理 CLI，默认 dry-run，`--apply` / `--days N`；形态与 `gc_orphan_blobs.py` 一致 |
| `backend/tests/test_document_trash.py` | 软删 / 恢复 / purge / 七处过滤点 / GC 交互 |
| `backend/tests/test_document_templates.py` | 模板渲染 + `template_kind` 绑定分支 |
| `backend/tests/test_agent_archive.py` | 四条前置条件、复用 vs 新建、SAVEPOINT 失败不阻断、`ARCHIVE_KIND` 与阶段清单一致性 |
| `backend/tests/test_document_rollback.py` | 回滚的 5 条失败路径 + 零字节写盘 + 扇出 |
| `backend/tests/test_search_documents.py` | 搜索桶、空关键词信封、软删过滤、计数不放大 |

### 3.2 后端 · 修改

| 文件 | 改动 |
|---|---|
| `backend/models/document.py` | `Document` 加 `deleted_at` / `deleted_by_id` 两列 + `is_deleted` 属性；`to_dict()` 增 `deleted_at` 字段（前端回收站需要显示「删于何时」）。**不加新索引**，理由见 §5.1 |
| `backend/services/schema_sync.py` | `ADDITIVE_COLUMNS` **追加两条**——`("documents","deleted_at","DATETIME")`、`("documents","deleted_by_id","INTEGER")`。**这是 CLAUDE.md 的硬约束**：漏登记则存量 `aragon.db` 上每一次文档查询都 `no such column` → 全线 500 |
| `backend/services/search.py` | 新增 `search_documents` / `_document_like_clause`；`search_all` 增 `documents` 键与计数 |
| `backend/routes/search.py` | **空关键词分支的手写信封必须补 `documents: []` 与 `counts.documents: 0`**（漏了前端空查询时崩） |
| `backend/routes/documents.py` | ① `_get_document_or_404` 由 `db.session.get` **改写为双模式查询**（`mode="live"｜"trashed"`，评审 V-07——`session.get` 按主键取，加不了 filter）；② `list_documents` 加 `sort`/`unlinked`/`deleted` 三参（`uploader_id` **现网已有**，勿重复实现）；③ `delete_document` 改软删 + `?purge=1` 分支（走自包含的 `trash.purge`，评审 V-02）；④ 新增 `restore_document`；⑤ `create_version` 加 `from_version_id` 分支——**分流必须在 `_reject_uneditable` 之前**（评审 V-06）——与互斥校验；⑥ 详情端点的 `links[]` 富化 `entity_title`（批量取标题，每种实体一次查询）；⑦ **新增 `GET /api/documents/meta`**（模板清单 + `trash_retention_days`，§4.6，评审 V-11） |
| `backend/routes/ticket_documents.py` | JSON 分支扩展出 `template_kind` 三态；`_bind_existing` 的文档查找加软删过滤 |
| `backend/services/documents/service.py` | 新增 `create_text_document()`（四条自持不变量，§2.3 C-1）、`add_version_from_existing()`；`ticket_documents_query` / `bound_kinds` 接上 `trash.not_deleted()`；`bind_document` / `fanout_revision` / `add_version_from_text` 增 `notify: bool = True` 关键字参数（**既有调用点行为逐字节不变**，仅 Agent 归档传 `False`，评审 V-10） |
| `backend/services/documents/counts.py` | `link_counts` / `document_link_counts` join `documents` 并过滤软删（否则徽章数字虚高） |
| `backend/services/documents/storage.py` | 新增 `blob_exists(digest) -> bool`（回滚前置校验；路径推导仍只有一处） |
| `backend/services/agent_executor.py` | 新增 `WorkProduct` 与 `generate_work_product()`；`generate_work` 降为薄包装（**签名与语义零变化**） |
| `backend/services/agent_runner.py` | 改用 `generate_work_product`；**两处**接线（评审 V-03）：`archive_prepare(...)` 在 `ticket.status` 改写**之前**（落盘在写锁外）、`archive_commit(plan, ...)` 在 `Activity.log` 之后；更新模块 docstring 说明为什么是两段 |
| `backend/config.py` | 新增 `DOC_AGENT_ARCHIVE` / `DOC_AGENT_ARCHIVE_MIN_CHARS` / `DOC_TRASH_RETENTION_DAYS` 三项（§5.3） |
| `backend/tools/purge_demo_data.py` | `_untouched_counts` 增列「回收站中的文档」；**不**清理它 |
| `backend/README.md`（若存在）/ 根 `README.md` | 新增配置项与两个 CLI 的一段说明 |

### 3.3 前端 · 新建

| 文件 | 意图 |
|---|---|
| `frontend/lib/markdown.ts` | Markdown 安全子集 → **React 元素树**（禁 `dangerouslySetInnerHTML`） |
| `frontend/lib/diff.ts` | 行级 LCS diff + `DIFF_MAX_CELLS` 降级 |
| `frontend/components/documents/MarkdownView.tsx` | 渲染容器：渲染 / 源码切换、截断横幅、`overflow-x` 保护 |
| `frontend/components/documents/DocumentDiffModal.tsx` | 双版本对比（统一视图 + 并排视图切换） |
| `frontend/components/documents/DocumentTemplateMenu.tsx` | 缺失项 chip 的「上传文件 / 用模板新建」二选一菜单 |
| `frontend/components/documents/TrashPanel.tsx` | 文档库的回收站视图（恢复 / 彻底删除 / 剩余保留天数） |
| `frontend/components/documents/DocumentMetaModal.tsx` | 「编辑信息」：标题 / 类型 / 描述三字段 + 乐观锁——接通现网**已实现却无人调用**的 `PATCH` 与 `useDocumentLibrary.patch()` |
| `frontend/components/documents/DocumentLinksPopover.tsx` | 「被引用 N」点开后的工单清单（用详情端点新富化的 `entity_title`），点击跳工单 |
| `frontend/hooks/useDocumentTrash.ts` | 回收站列表 + restore + purge，收敛失效逻辑 |

### 3.4 前端 · 修改

| 文件 | 改动 |
|---|---|
| `components/documents/DocumentPreviewModal.tsx` | ① `decideMode` 按 §2.2 B-0 的**完整改写版**替换：扩展名判据**前置**于 inline-safe 闸、兜底由 `"text"` 改为 `"download"`、签名增 `filename`（评审 V-05；**`INLINE_SAFE_MIMES` 一字不动**）；② `.md/.markdown` 默认走 `MarkdownView` 并提供源码切换；其余类型行为不变 |
| `components/documents/DocumentVersionTimeline.tsx` | 每行复选框（恰选两个时出现「对比这两版」）+ 行内「回滚到此版本」（带二次确认） |
| `components/documents/StageChecklist.tsx` | 缺失 chip 的 `onFill` 由「直接开上传」改为弹 `DocumentTemplateMenu`；三个无模板的 kind 保持原行为 |
| `components/documents/DocumentPanel.tsx` | 接线 diff / 模板 / 回滚三个新入口；行操作菜单增「对比版本」 |
| `app/(app)/documents/page.tsx` | 排序下拉 / **上传人筛选（后端早已支持，仅缺 UI）** / 未绑定筛选；「文档 / 回收站」两个 tab；读 `?doc=` 深链自动开预览；行操作增「编辑信息」；「被引用」数字改为可点开 |
| `components/documents/DocumentRow.tsx` | 行操作菜单增「编辑信息」「对比版本」两项（`RowAction` 结构不变） |
| `components/layout/GlobalSearch.tsx` | 第三个命中分组 + 独立的 `onSelectDocument` 路由分流 + 键盘扁平索引纳入 + **Enter 兜底 `pickFallbackTarget(counts)` 三态改写（`:122-126`，评审 V-08）** + 文案更新（占位符 `:152`、无命中文案 `:191-193`） |
| `lib/types.ts` | `DocumentSummary` 增 `deleted_at: string \| null`；`SearchResults`（`types.ts:298-303`）增 `documents` 与 `counts.documents`；新增 `DocumentMeta`、`DocumentTemplate`、`DiffRow` 等 |
| `lib/constants.ts` | ① 新增共享常量 `TEXT_EXTENSIONS` + `extensionOf` / `isTextExtension`（与后端 `mime.py:12` 七项逐字一致，供 `decideMode` 使用）；与既有 `INLINE_SAFE_MIMES`（`:246`）并列并**各自注明职责不同、不可互换**。**注意：前端目前没有 `TEXT_EXTENSIONS`，这是新建而非改动**（评审 V-13）。② **`ACTION_LABELS`（`:94-112`，现有 4 条 `doc_*`）追加 `doc_rolled_back` / `doc_trashed` / `doc_restored` 三项**——漏登记不会报错，只会让时间线出现裸英文（上轮 R10 的原样重演） |
| `lib/permissions.ts` | 新增 `canPurgeDocument(user)`（admin only） |
| `lib/api.ts` | 无需改动（复用既有 `api.post` / `downloadBlob`）；若回收站需要 `X-Total-Count`，`listFetcher` 已支持 |

### 3.5 前端 · 不改但需复核

`lib/swr-keys.ts::invalidateDocumentViews` 已覆盖 `/documents` 前缀，回收站与筛选的 key
均以该前缀开头，**无需新增失效前缀**；但软删会改变工单侧徽章数字，因此软删 / 恢复 / purge
之后**必须同时调 `invalidateTicketViews`**（上轮 R7 的同一课）。

---

## 4. 接口设计（REST）

新增 / 变更端点一览。**所有 4xx 响应体沿用现网 `{"error": str, "detail": {...}}` 形状；
409 一律不带 `allowed` 键**（前端看板据其有无分流状态机冲突，上轮 §2.4 铁律 3）。

### 4.1 `GET /api/documents`（扩展）

新增查询参数见 §2.1-A2。**实现约束**：

- `sort=size` → `outerjoin(DocumentVersion, DocumentVersion.id == Document.current_version_id)`
  后 `order_by(DocumentVersion.size_bytes.desc().nulls_last())`；
- `sort=links` → `outerjoin` 一个 `link_counts` 子查询（`group_by(document_id)`），
  **不得**先取页再逐行 count；
- `unlinked=1` → 上述子查询 `having`/`is_(None)` 过滤；
- `deleted=1` → `trash.is_deleted()`，且非 pm/admin 自动附加 `uploader_id = me`；
  排序改为 `deleted_at DESC`（回收站按删除时间看才有意义）。
  **【评审 V-12】自动值与用户显式传入的 `uploader_id` 冲突时，以自动值为准，不报错**——
  它是一道**权限收紧**，不是用户的检索意图；把一次越权检索渲染成 400 只会告诉攻击者
  「这里有东西」，而静默收紧的结果（看到自己的那些）恰好就是正确答案。
  pm/admin 不受影响，他们传什么就筛什么。
- 分页仍走 `services/pagination.py::paginate`，裸数组 + `X-Total-Count`（既有契约）。

### 4.2 `POST /api/documents/:id/versions`（新增回滚分支）

请求（JSON，三选一）：`{content, note?}`（现网）｜ `{from_version_id, note?}`（**新增**）
｜ multipart `file`（现网）。

| 码 | 条件 |
|---|---|
| 201 | `DocumentRevisionResult`（形状与现网一致：`document` / `version` / `deduped` / `fanout_*` / `link_count`） |
| 400 | 同时带 `content` 与 `from_version_id`（`reason: ambiguous_source`）；`from_version_id` 非整数 |
| 403 | `can_manage_document` 不通过 |
| 404 | 文档不存在 / 已在回收站；`from_version_id` 不属于本文档 |
| 409 | `from_version_id` 已是当前版本（`reason: already_current`） |
| 410 | 源版本的 blob 已缺失 |

### 4.3 `POST /api/documents/:id/restore`（新增）

| 码 | 条件 |
|---|---|
| 200 | 恢复成功，回传完整 `Document` 响应体 |
| 403 | `can_manage_document` 不通过 |
| 404 | 文档不存在 |
| 409 | 文档不在回收站（`reason: not_deleted`） |

### 4.4 `DELETE /api/documents/:id`（语义变更 + `?purge=1`）

| 码 | 条件 |
|---|---|
| 204 | 软删成功（默认）｜ `?force=1` 解绑后软删 ｜ `?purge=1` 彻底删除 |
| 403 | 非可管理者；`force=1` 但非 pm/admin；`purge=1` 但非 admin |
| 404 | 不存在或已在回收站（`purge=1` 时除外——它**只**在回收站集合里查找） |
| 409 | 仍有绑定且未带 `force`（现网，不变）；`purge=1` 但文档不在回收站 |

### 4.5 `POST /api/{requirements|bugs}/:id/documents`（新增 `template_kind` 分支）

请求 JSON：`{"template_kind": "test_plan", "title"?: str, "label"?: str}`

| 码 | 条件 |
|---|---|
| 201 | `TicketDocument`（含 `link`），与「绑定已有」同形状 |
| 400 | `template_kind` 不在 `TEMPLATE_KINDS`（`detail.allowed` 回传合法值）；`title` 超 200；**`label` 以 `agent:` 开头**（评审 V-17：该前缀为 Agent 归档保留，见 §5.2；这是对既有端点的一处契约收紧，故在此显式登记，不让它成为一个没写在表里的 400） |
| 403 | `can_manage_ticket` 不通过 |
| 404 | 工单不存在 |
| 503 | 存储不可用（`StorageUnavailable`，与上传路径一致） |

### 4.6 `GET /api/documents/meta`（新增，只读）

**【评审 V-11】** v1 把这个端点命名为 `/documents/templates` 并定义响应体为**裸数组**
`[{kind,label,summary}]`，而 §6.4 又要求「在这个端点的响应里顺带回传
`trash_retention_days`」——数组上挂不了这个键，两节直接矛盾；且把「回收站保留期」
塞进一个叫 templates 的端点本身就是错的抽象。故改为：

```jsonc
GET /api/documents/meta          // jwt_required，无参数，响应可被前端长缓存
{
  "templates": [ {"kind": "test_plan", "label": "测试计划", "summary": "…"}, … ],
  "trash_retention_days": 30     // = DOC_TRASH_RETENTION_DAYS，前端**不得硬编码**（R-11）
}
```

「一个只读配置端点、不为一个数字新开路由」的原则保留，但名字与形状对得上了。
中文标题仍由后端下发，避免在前端再写一份（与 `stage_label` 不另建映射同一条原则）。

**路由冲突核验**：`documents` 蓝图的 URL 前缀是 `/api/documents`，既有详情路由是
`/<int:document_id>`（整型转换器），`meta` 是字符串段，**不会**被它捕获。已核对现网
`routes/documents.py:138`。

### 4.7 `GET /api/search`（响应扩展）

```jsonc
{
  "query": "支付",
  "requirements": [...], "bugs": [...],
  "documents": [ /* Document 响应体，含 current_version 与 link_count */ ],
  "counts": {"requirements": 3, "bugs": 1, "documents": 2}
}
```

空关键词信封同样带 `documents: []` 与 `counts.documents: 0`（§3.2 已强调）。

### 4.8 CLI

```bash
python -m tools.purge_trash                 # dry-run：列出超过保留期的文档，不改任何东西
python -m tools.purge_trash --days 7        # 覆盖保留期
python -m tools.purge_trash --apply         # 真删（行 + 释放的 blob）
```

输出与 `gc_orphan_blobs.py` 同款报告结构：`scanned` / `expired` / `deleted` / `blobs_reaped` /
`skipped`（并给出 skip 原因）。**退出码**：0 正常，2 前置条件失败（如 UPLOAD_DIR 不存在）。

---

## 5. 数据模型

### 5.1 DDL 与 additive 登记

```sql
-- 由 db.create_all() 在全新库上建出；存量库由 schema_sync 补列。
ALTER TABLE documents ADD COLUMN deleted_at DATETIME;
ALTER TABLE documents ADD COLUMN deleted_by_id INTEGER;
```

```python
# backend/services/schema_sync.py
ADDITIVE_COLUMNS = [
    ("users", "is_active", "BOOLEAN NOT NULL DEFAULT 1"),
    ("projects", "archived_at", "DATETIME"),
    ("documents", "deleted_at", "DATETIME"),          # ← 本轮新增
    ("documents", "deleted_by_id", "INTEGER"),        # ← 本轮新增
]
```

**三条必须遵守的细节**：

1. **`deleted_by_id` 不建外键**。模型侧写 `db.Column(db.Integer, nullable=True)` 而**不是**
   `db.ForeignKey("users.id")`。理由是**两条建表路径必须产出同一个 schema**：`create_all` 会为
   `ForeignKey` 生成 `REFERENCES users(id)`，而 `schema_sync` 的 `ADD COLUMN` 片段不会——
   于是全新库与存量库的约束不一致，且 `PRAGMA foreign_keys=ON` 在两种库上表现不同。
   宁可少一个约束，也不要两种库跑出两种行为。用户解析沿用 `_resolve_author("user", id)` 的
   「已删除降级为占位」策略，本就不依赖外键。
2. **不新增索引**。`schema_sync` 的能力边界是 ADD COLUMN，加不了索引；若只在模型里写
   `db.Index`，新库有、存量库没有——这是最难排查的一类性能与行为差异。
   现网 `documents` 表规模（个位数千行量级）下，`deleted_at IS NULL` 的全表扫描代价可忽略。
   **何时该改**：文档数进入十万量级时，一并上 Alembic 建索引（与 CLAUDE.md 对
   「第一次改类型 / 加约束就换迁移工具」的判断同源）。
3. **默认值必须是 NULL**。`deleted_at` 无 `NOT NULL`、无 `DEFAULT`，存量行天然全部「未删除」，
   零回填。

### 5.2 `Document` 响应体（新增字段）

```jsonc
{
  "id": 42, "title": "支付方案", "kind": "design",
  "...": "（其余字段不变）",
  "deleted_at": null            // ← 新增；非空即在回收站
}
```

`DocumentLink.label` **不改结构**，但新增一条约定：`agent:{kind}` 前缀为 Agent 归档保留，
人工绑定的 label 不应使用该前缀（前端绑定表单对以 `agent:` 开头的 label 输入给出 400 前置校验，
后端同样校验——**两处都要**，前端是体验、后端是防线）。

### 5.3 配置项

| 键 | 环境变量 | 默认 | 语义 |
|---|---|---|---|
| `DOC_AGENT_ARCHIVE` | 同名 | `True` | Agent 交付物归档总开关；关掉即完全回到上一轮行为。**运维注记（评审 V-10）**：它是本轮唯一一个「升级即生效、且会自动产生用户可见数据」的开关。默认 `True` 是对的（否则这根支柱等于没上线），但**首次上线建议先以 `DOC_AGENT_ARCHIVE=false` 跑一轮**，确认 LLM 产物质量与 `ARCHIVE_KIND` 的归类符合预期后再打开。README 须写明这一条 |
| `DOC_AGENT_ARCHIVE_MIN_CHARS` | 同名 | `200` | 短于此长度的产物不值得建成文档 |
| `DOC_TRASH_RETENTION_DAYS` | 同名 | `30` | 回收站保留期（仅 `purge_trash.py` 读取，运行时不据此自动删任何东西） |

`TestConfig` **必须显式** `DOC_AGENT_ARCHIVE = False`——虽然 `from_llm` 判据已保证测试
不触发归档，但配置层再钉一道，可让「归档相关用例」通过 `monkeypatch` 精确开启，
而不必担心某天有人放宽了 `_llm_active()`。

### 5.4 前端类型（`lib/types.ts`）

```ts
export interface DocumentSummary { /* 既有字段 */ deleted_at: string | null; }

export interface DocumentTemplate { kind: DocumentKind; label: string; summary: string; }

export interface SearchResults {
  query: string;
  requirements: RequirementSummary[];
  bugs: BugSummary[];
  documents: DocumentSummary[];                       // ← 新增
  counts: { requirements: number; bugs: number; documents: number };
}

export type DiffOp = "equal" | "insert" | "delete";
export interface DiffRow { op: DiffOp; leftNo: number | null; rightNo: number | null; text: string; }
export interface DiffResult { rows: DiffRow[]; added: number; removed: number; degraded: boolean; }
```

> 现网 `SearchResults` 的确切名称与形状在 `lib/types.ts` 中，实施前须核对；
> `counts` 是**必填对象**（`GlobalSearch.tsx:191` 直接读 `data.counts.requirements`），
> 因此后端空信封补齐 `documents` 计数是**类型与运行时的双重要求**。

---

## 6. 前端设计（信息架构与交互）

### 6.1 三个触点的增量（不新增第四个触点）

1. **工单抽屉**：阶段清单的缺失 chip 从「一次点击 → 上传框」升级为「一次点击 → 二选一菜单」。
   这多出来的一次点击是**值得**的：它把「我没有现成文件」这个最常见的死路变成了出路。
   菜单只有两项、无子菜单、Esc 即关，不构成认知负担。
2. **文档库页**：顶部由单行筛选升级为「筛选行 + 排序下拉 + 两个 tab（文档 / 回收站）」。
   回收站 tab 上带计数徽章，为空时**不显示徽章也不显示 tab**——一个永远为 0 的入口
   只是噪音（与「侧边栏恰 8 项」同款克制）。
3. **全局搜索**：第三个分组，图标用回形针以与前两组的状态色区分。

### 6.2 预览模态的两态

```
┌ 支付方案.md · v3                       [渲染|源码]  [下载] [×] ┐
│ ⚠ 已截断显示前 1 MB，渲染结果可能不完整                        │  ← 仅 truncated 时
│                                                                │
│ ## 背景                                                        │
│ 现有支付链路在超时后…                                          │
└────────────────────────────────────────────────────────────────┘
```

- 切换按钮是**分段控件**（segmented control），不是两个独立按钮——它表达的是互斥态。
- 渲染视图的排版规范：正文行高 1.75、段间距 `mt-4`、`h1~h4` 递减字号且**不使用超大字号**
  （模态内的 h1 若比模态标题还大，视觉层级立刻塌掉，实测取 `text-lg / base / sm / sm+粗`）。
  代码块 `bg-bg border border-border rounded-lg overflow-x-auto`，**横向滚动收在块内**，
  模态本体永不横滚。表格同样包一层 `overflow-x-auto`。
- 全部沿用既有设计令牌 `bg / surface / border / ink / ink-muted / clay`，**不引入新配色**。

### 6.3 版本对比

```
┌ 版本历史 · 支付方案                                        [×] ┐
│ ☑ v3  8.2 KB  李工  07-19  当前            [预览] [下载]      │
│ ☑ v2  7.9 KB  李工  07-18                  [预览] [回滚到此版] │
│ ☐ v1  6.1 KB  王工  07-15                  [预览] [回滚到此版] │
│                                    [对比选中的两个版本 ▸]      │
└────────────────────────────────────────────────────────────────┘
```

- 选中数 ≠ 2 时对比按钮禁用并给出 `title` 说明（不是隐藏——**禁用+解释**比消失更可学习）。
- 对比模态默认统一视图（移动端唯一可行的视图），宽屏提供并排切换。
  增删行用左侧 4px 色条 + 极浅底色标注，**不靠纯色块**（色觉障碍友好），
  并在行首标注 `+` / `-` 字符——颜色永远只是冗余通道。
- `degraded === true` 时顶部横幅：「文件过大（两侧共 N 行），已降级为整块对比」。
- 「回滚到此版本」必走 `ConfirmDialog`，文案：
  > 将以 v2 的内容创建一个新版本 v4。**历史版本不会被删除**，随时可以再滚回来。

### 6.4 回收站

每行展示：标题、类型徽章、删除人、删除时间、**剩余保留天数**（`30 - 已过天数`，≤3 天时用警示色）。
操作：`[恢复]`，admin 额外可见 `[彻底删除]`（危险色，置于分隔线之下）。
空态文案：「回收站是空的。删除的文档会在这里保留 N 天。」（N 由下发值填充）
**保留期的展示与后端 `DOC_TRASH_RETENTION_DAYS` 必须一致**——前端不得硬编码 30，
统一由 `GET /api/documents/meta` 的 `trash_retention_days` 提供（§4.6，评审 V-11）。

**【评审 V-19】** 回收站里的文档**无法预览**——详情 / `/content` / `/download` 三个端点
都已被 §2.4 的第 1 处过滤成 404，这是有意的（回收站不是阅读场所，让被删文档继续可读
等于删除没生效）。但界面必须**说出来**，否则用户会以为是坏了：
行内不提供「预览」按钮，并在面板顶部给一句说明——
「回收站中的文档不可预览或下载，**如需查看内容请先恢复**。」

### 6.5 a11y

- 层叠语义**已由上一轮的 `lib/overlay-stack.ts` 解决**（`useOverlayLayer(active)` +
  Esc 只交给栈顶 + 滚动锁引用计数），本轮所有**模态**（diff / 元信息编辑 / 回收站确认）
  **必须**复用 `components/ui/Modal.tsx`，即自动继承该契约。**不要**自己挂 `window` 级 Esc 监听。
- **模板菜单不是模态，不进层栈**——它与现网 `DocumentRow` 的 ⋯ 菜单同类（轻量、点外即关、
  不锁滚动）。把一个下拉菜单推进层栈会让它抢走抽屉的 Esc，这正好是上一轮 R9 的镜像错误。
  实现沿用 `DocumentRow` 的既有写法：`role="menu"` + `role="menuitem"`，方向键上下移动、
  Esc 关闭并把焦点还给触发它的 chip。
- 版本行复选框有可见 label（`aria-label="选择 v2 用于对比"`）。
- diff 表格用 `role="table"`，增删行加 `aria-label="新增行"` / `"删除行"`，
  让屏幕阅读器不必依赖颜色。
- 渲染视图的链接一律 `rel="noopener noreferrer"`，外链后加视觉提示（↗）。

---

## 7. 测试与验收标准

### 7.1 质量闸

- 后端：`cd backend` → `python -m pytest -q`。**判据相对化**：开工前先跑一次记录基线
  （上一轮完工实测 **506**），完工后要求**零失败**且总用例数**不低于**基线 + 本轮新增。
  CLAUDE.md 里的「380+」与更早的「93」均已陈旧，**以实测为准**。
- 前端：`cd frontend` → `npm run typecheck` 与 `npm run build`，均要求**零错误**。
- 两个 CLI 各自跑一次 dry-run，确认零副作用（`git status` 与 `aragon.db` mtime 均不变）。

### 7.2 后端必过用例（每条对应一种真实失败模式）

**支柱 A · 发现**

| # | 用例 | 钉死什么 |
|---|---|---|
| A1 | `test_search_returns_documents_bucket` | 标题命中出现在 `documents` 桶里 |
| A2 | `test_search_matches_original_filename` | 只有文件名含关键词也能命中（join 生效） |
| A3 | `test_search_excludes_trashed_documents` | 回收站里的文档搜不到 |
| A4 | `test_empty_query_envelope_has_documents_key` | 空关键词信封含 `documents` 与 `counts.documents`（**前端崩溃的唯一护栏**） |
| A5 | `test_search_counts_documents_once` | outerjoin 不放大 `count()` |
| A6 | `test_list_sort_by_size_and_links` | 两种 join 排序结果正确且**只发一次查询** |
| A7 | `test_list_rejects_unknown_sort_with_400` | 非枚举 sort 400，不静默回退 |
| A8 | `test_list_unlinked_filter` | `unlinked=1` 只返回零绑定文档 |
| A9 | `test_detail_links_carry_entity_title` | `links[]` 每项带 `entity_title`，且工单标题**批量取**（每种实体至多 1 次查询，不逐 link 查） |
| A10 | `test_detail_link_title_survives_deleted_ticket` | 工单已被删（link 理论上已级联删除，但防御性路径仍需返回占位而非 500） |

**支柱 B · 理解**

| # | 用例 | 钉死什么 |
|---|---|---|
| B1 | `test_rollback_creates_new_version_sharing_digest` | 新版本 `sha256` 与源版本相同，**磁盘文件数不变** |
| B2 | `test_rollback_keeps_history_intact` | 回滚后版本总数 +1，历史一行不少 |
| B3 | `test_rollback_to_current_returns_409` | `already_current` |
| B4 | `test_rollback_with_foreign_version_returns_404` | 跨文档的 version_id 视为不存在 |
| B5 | `test_rollback_with_missing_blob_returns_410` | 不允许建出指向空气的版本 |
| B6 | `test_rollback_and_content_are_mutually_exclusive` | 400 `ambiguous_source` |
| B7 | `test_rollback_fanout_is_capped` | 复用 `DOC_FANOUT_MAX_LINKS` 并如实回传 `fanout_truncated` |
| **B8** | **`test_rollback_works_on_binary_document`** | **回滚一份 `.png` 必须 201**——分流发生在 `_reject_uneditable` **之前**（评审 V-06）。这条用例的存在本身就是那处顺序约束的护栏 |

**支柱 C · 产出**

| # | 用例 | 钉死什么 |
|---|---|---|
| C1 | `test_template_kind_creates_and_binds_document` | 201、`link` 存在、`link.stage` == 工单当前状态 |
| C2 | `test_template_document_satisfies_stage_checklist` | 建完之后 `document-checklist` 对应项 `satisfied` 变真（**闭环的证据**） |
| C3 | `test_unknown_template_kind_returns_400_with_allowed` | 400 且 `detail.allowed` 可用 |
| C4 | `test_archive_skips_when_product_is_fallback` | 降级模板**绝不**归档（存量用例零影响的机制护栏） |
| C5 | `test_archive_creates_document_on_llm_product` | 强制 `from_llm=True` 时建文档 + 绑定 + `doc_attached` |
| C6 | `test_archive_appends_version_on_second_pass` | 同一单同一 kind 第二次推进 → **版本 +1，文档数不变** |
| C7 | `test_archive_kind_matches_stage_expectations` | `ARCHIVE_KIND` 的每个值 ∈ 对应阶段的 `STAGE_DOC_EXPECTATIONS`，**且每个键的 `(entity, agent_kind, to_status)` 在 `AGENT_FORWARD` 里真实可达**（后半句是评审 V-01 补的：v1 只有前半句，而出错的那两格恰恰**满足**前半句，守卫会给 bug 盖章通过） |
| **C11** | **`test_dev_agent_never_produces_qa_artifacts`** | **反向守卫（评审 V-01 · P0）**：遍历 `AGENT_FORWARD`，对每条 `kind == "dev"` 的边断言 `ARCHIVE_KIND` 要么没有该键、要么其值 ∉ `("test_plan", "test_report")`。**这条是本轮最重要的一条用例**——它挡住的是「dev-agent 自己出具验收报告、把门禁点绿」这一类静默的信任崩塌，而 C7 结构上抓不到它 |
| C8 | `test_archive_failure_does_not_block_advance` | monkeypatch 让 `archive_commit` 抛异常 → 推进仍 200；**且 commit 之后重新查库**：工单状态已变、评论在、`agent_advanced` Activity 在、**没有半份文档行 / 版本行 / link 残留**（评审 V-04：只断言「推进成功」的话，SAVEPOINT 即使完全失效用例也照绿） |
| **C12** | **`test_archive_persists_blob_before_status_write`** | **落盘发生在状态写入之前**（评审 V-03）：monkeypatch `storage.digest_and_persist`，在其中断言 `ticket.status` 仍是**旧**值且 `db.session.new`/`dirty` 不含 Comment——把「磁盘 IO 不在 SQLite 写锁窗口内」这条口头约束变成可执行断言 |
| **C13** | **`test_archive_writes_activity_but_no_notification`** | 归档后 `doc_attached` / `doc_revised` Activity 在，**`Notification` 表零新增**（评审 V-10） |
| C9 | `test_archive_respects_min_chars` | 短产物不归档 |
| C10 | `test_generate_work_signature_unchanged` | 薄包装仍返回 `str`（零破坏的护栏） |

**支柱 D · 治理**

| # | 用例 | 钉死什么 |
|---|---|---|
| D1 | `test_delete_soft_deletes_and_keeps_row` | 204 后行仍在、`deleted_at` 非空 |
| D2 | `test_deleted_document_is_404_everywhere` | 详情 / 下载 / content / 改版 五个端点全 404 |
| D3 | `test_deleted_document_leaves_ticket_panel` | 抽屉列表里消失 |
| D4 | **`test_deleted_document_no_longer_satisfies_checklist`** | **阶段清单重新变红**（最隐蔽的一处过滤点） |
| D5 | `test_deleted_document_drops_out_of_badge_count` | 看板 / 列表徽章数字同步下降 |
| D6 | `test_cannot_bind_deleted_document` | 绑定接口 404 |
| D7 | `test_restore_brings_back_links_and_checklist` | 恢复后 D3/D4/D5 全部逆转 |
| D8 | `test_restore_of_live_document_returns_409` | `not_deleted` |
| D9 | `test_purge_requires_admin` | pm 也不行 |
| D10 | `test_purge_only_works_on_trashed` | 409 |
| D11 | `test_purge_removes_rows_and_reaps_blob` | 行没了、blob 进入回收判定。**【评审 V-18】断言的是「摘要进入 `unreferenced_digests` 集合」，不是「文件已从磁盘消失」**——`storage.delete_blob` 带宽限窗口（`is_reapable` / `_grace_seconds`），刚落盘的 blob 立刻 purge **不会**被物理删除，按后者写会得到一条随时间随机失败的用例 |
| **D16** | **`test_purge_document_that_still_has_links`** | **P0 护栏（评审 V-02）**：软删一份**仍绑着 2 张单**的文档（不带 `force`，这是回收站的**常态**）→ `?purge=1` → **204 而非 500**，links 全没、两张单的时间线各有一条 `doc_detached`。D11 拿的是无绑定文档，撞不到 `document_links` 的真外键 |
| D12 | **`test_gc_keeps_blobs_of_soft_deleted_documents`** | **软删期间 blob 绝不被 GC 回收**（恢复出空壳的唯一护栏） |
| D13 | `test_trash_writes_activity_on_each_link` | `doc_trashed` 逐单落时间线且受上限约束 |
| D14 | `test_purge_trash_cli_dry_run_changes_nothing` | dry-run 零副作用 |
| D15 | `test_schema_sync_adds_document_trash_columns` | **存量库补列生效**（CLAUDE.md 硬约束的直接护栏） |

预计新增 **60 ~ 75** 条（v2 追加 B8 / C11 / C12 / C13 / D16 五条评审用例）。
若实测显著低于此数，多半是漏了 D 组的过滤点用例。

**评审补充的五条用例有一个共同点，值得单独说一句**：它们守的都不是「功能对不对」，
而是「**v1 的守卫为什么抓不到那个 bug**」——C7 结构上会给 V-01 盖章通过、
C8 在 SAVEPOINT 完全失效时照绿、D11 拿的样本天生撞不到外键。
一条抓不到自己那类 bug 的用例，比没有用例更危险，因为它会让人停止怀疑。

### 7.3 前端 / 端到端手测清单

1. 全局搜索输入「支付」→ 出现需求、BUG、文档三组；点文档 → 跳 `/documents?doc=N` 并自动开预览。
2. 清空搜索框 → 下拉不崩（空信封的 `documents` 键生效）。
3. 打开一份 `.md` → 默认渲染视图，标题 / 列表 / 代码块 / 表格排版正确；切「源码」→ 等宽原文。
4. 在 `.md` 正文里写 `<img src=x onerror=alert(1)>` 与 `[点我](javascript:alert(1))` → **均以纯文本呈现，无弹窗**。
5. 版本历史勾选 v1 与 v3 → 对比按钮亮起 → 统一视图正确、并排视图正确、增删计数正确。
6. 「回滚到 v1」→ 二次确认 → 版本列表出现 v4，内容与 v1 一致，v1~v3 仍在。
7. 阶段清单缺失 chip → 菜单二选一 → 「用模板新建」→ 文档出现在列表且**该项立刻变绿**。
8. 删除一份被 2 张单绑定的文档 → 409；`force` 删除 → 两张单的抽屉里都消失、徽章 -1、时间线有记录。
9. 回收站 tab → 看到它 → 「恢复」→ 文档回到列表（若走的是 `force`，确认框如实说明绑定不会回来）。
10. 非 admin 账号在回收站里**看不到**「彻底删除」按钮。
11. 抽屉内打开对比模态 → 按 Esc **只关模态、抽屉仍开、背景仍锁滚**（层栈继承验证）。
12. 移动端宽度（375px）：文档库两 tab 可用、对比模态用统一视图且不横向溢出。
13. 键盘：`/` 聚焦搜索 → 方向键可走到文档组 → Enter 打开。
14. 上传一份 `.json` 与一份 `.csv` → 点预览 → **能看到正文**（不再是「该类型不支持在线预览」），
    且 `.svg` / `.html` 仍不可上传（扩展名白名单未变）。
15. 文档库行操作 →「编辑信息」→ 改标题与类型 → 列表即时更新；两个标签页同时打开时，
    后保存的一方拿到 409（乐观锁生效）。
16. 文档库「被引用 3」→ 点开 → 列出三张单的标题 → 点其中一张跳转并打开抽屉。
17. 打开真实 LLM（本地配置模型凭据）跑一次 **qa-agent** 的 `agent-advance` 到 `reviewing` →
    抽屉里出现 Agent 产出的「测试报告」文档，`link.stage` 显示「审批中」，
    阶段清单变绿，时间线有 `doc_attached`，**通知中心零新增**（评审 V-10）。
18. **（评审 V-01）** 同一环境下跑一次 **dev-agent** 的 `agent-advance`
    （`bug: fixing → verifying`）→ **不产生任何文档**，`verifying` 的「测试报告」
    清单项**仍然是红的**。这条是 P0 修复的人工验收面：绿了就说明 `ARCHIVE_KIND`
    的 `agent_kind` 维度没落地。
19. **（评审 V-02）** 删除一份**绑着 2 张单**的文档（走 `force`）→ 回收站里能看到它 →
    admin 点「彻底删除」→ **204，不是 500**；再跑一次 `python -m tools.purge_trash --apply`
    对另一份同样带绑定的过期文档，CLI **不崩**且报告里 `deleted` 计数正确。
20. **（评审 V-06）** 对一份 `.png` 文档「回滚到 v1」→ **成功**，不是
    「该文档不支持文本编辑」。

### 7.4 Definition of Done

- §7.1 三个质量闸全绿；后端零失败且总数不低于基线。
- §7.2 全部用例存在且通过；§7.3 **二十条**手测逐条走过（第 18~20 条是评审 P0/P1 的人工验收面）。
- `git status` 干净：无 `backend/var/uploads` 残留、无临时脚本、无 `.claude-index/` 之类的无关产物。
- 新增的三个配置项、两个 CLI 在 README 中各有一段说明。
- 本文件补上「实施过程发现的方案缺陷」一节（若有），格式沿用上一轮：
  **设计怎么说 / 照做会怎样 / 实际怎么做**。**不静默偏离**。

---

## 8. 风险与缓解

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| **R-1** | **漏登记 `ADDITIVE_COLUMNS`** | 存量 `aragon.db` 上**每一次**文档查询 `no such column` → 全线 500 | §3.2 / §5.1 双处强调；D15 用例直接针对存量库补列；CLAUDE.md 已有明文，评审须逐项核对 |
| **R-2** | **七处过滤点漏掉任意一处** | 幽灵文档：删了却仍在替工单满足阶段清单（第 4 处）或让徽章说谎（第 5 处） | 唯一谓词 `trash.not_deleted()` 收口；D2~D6 五条用例逐处覆盖；评审时按 §2.4 表格逐行打勾 |
| **R-3** | **Agent 归档污染文档库** | 每次 tick 生成一份新文档，几天后库里全是 `agent:` 垃圾 | 四条前置条件（尤以 `from_llm` 与 `MIN_CHARS`）+ 「同 kind 追加版本而非新建」+ 总开关可关 |
| **R-4** | **归档失败连累 Agent 推进** | 自动流水线因为一个附属动作停摆——这是本项目最不能接受的失败模式 | SAVEPOINT + `except Exception` 兜底 + C8 用例；取向与 `agent_executor` 对 LLM 的处理完全一致 |
| **R-5** | **Markdown 渲染成为新的 XSS 面** | 预览一份文档就被打穿；上一轮 R6 已经在这条路上摔过一次 | **返回 React 元素而非 HTML 字符串**（结构性免疫）+ 协议白名单 + 图片不外链 + 裸 HTML 按文本；手测第 4 条为显式验收 |
| **R-6** | **diff 在大文件上冻结主线程** | 打开一次对比页面白屏十几秒 | `DIFF_MAX_CELLS` 硬闸 + 如实降级横幅；**不**引入 Web Worker（为一个对比功能引入 worker 生命周期管理，复杂度不成比例） |
| **R-7** | **`sort=links` / `unlinked` 退化成 N+1** | 文档库一页 50 行 → 50 次子查询，与上一轮 R8 同一个坑 | 一律以 `group_by` 子查询 join；A6 用例断言查询次数 |
| **R-8** | **回滚建出指向空气的版本** | 用户点回滚 → 拿到一个下载即 410 的版本，且它已成为「当前版本」 | 回滚前 `blob_exists` 前置校验 → 410；B5 用例 |
| **R-9** | **`generate_work` 改造波及 real-agent-execution 一轮的契约** | 既有测试或调用点静默失效 | **不改既有签名**，新增 `generate_work_product` 并让旧函数成为薄包装；C10 用例锁死 |
| **R-10** | **前端 `ACTION_LABELS` 漏登记三个新 action** | 时间线出现裸英文——上一轮 R10 的原样重演，且不会报错 | §3.4 明文列出；手测第 8 条会看到时间线文案 |
| **R-11** | **回收站保留期前后端不一致** | 前端说「还剩 3 天」，后端配置是 7 天，用户按错误信息做决定 | 保留期由后端下发（§6.4），前端**不得硬编码** |
| **R-12** | **本轮范围偏大，实施节奏失控** | 四根支柱各做一半，哪一根都不能上线 | §9 的六步实施顺序，**每一步各自可提交、可回归、可上线**；时间不足时在任意步骤边界停下都是自洽交付面 |
| **R-13** | **B-0 被实现成「把 csv/json/yaml 加进 `INLINE_SAFE_MIMES`」** | 那张表控制的是「允许浏览器直接渲染的 MIME」，扩容它等于亲手把上一轮唯一还生效的两道防线之一撬松，而 `text/html` 就在同一个语义邻域 | §2.2 B-0 写明「改 `decideMode` 的判据、`INLINE_SAFE_MIMES` 一字不动」，并要求把这条理由留在代码注释里；评审须核对该常量的 diff **为空** |
| **R-14** | **Agent 归档把不属于自己职能的产物点绿到清单上**（评审 V-01） | dev-agent 的修复说明成为「测试报告」，门禁打开后放行一份无人验证过的交付——比不归档坏得多，因为它**看起来**是合规的 | `ARCHIVE_KIND` 的键含 `agent_kind`；C7 正向 + **C11 反向**双守卫；`generic` kind 一格不配 |
| **R-15** | **`?purge=1` / CLI 在带绑定的回收站文档上撞外键 500**（评审 V-02） | 回收站的**常态**（软删不解绑）一按彻底删除就 500；CLI 批量清理在第一份带绑定的文档上崩掉，后面的全不处理 | `trash.purge()` 自包含 detach；路由与 CLI 共用同一入口；CLI 逐文档 try/except；D16 用例 |
| **R-16** | **SAVEPOINT 在 pysqlite 上静默失效**（评审 V-04） | 归档失败时嵌套回滚不隔离，可能连累主推进事务——而 C8 的 v1 写法照绿 | 前置条件（调用点之前必有挂起写）写进模块 docstring；C8 加强为 commit 后重新查库断言；任何挪动调用点的改动都必须重新评估这一条 |

---

## 9. 建议实施顺序（每步各自可提交）

1. **地基 · 软删数据层**：`models/document.py` 两列 + `schema_sync` 两条登记 +
   `services/documents/trash.py`（`not_deleted` / `is_deleted` / `soft_delete` / `restore` /
   **自包含的 `purge`**）+ 八处过滤点逐处处置（第 8 处是「有意不改」）+
   `_get_document_or_404` 双模式改写 + D1~D8、D12、D15 用例。
   **此步完成后既有 506 条必须仍全绿**——第 4、5 两处 join 改写错了不会抛异常，
   只会让阶段清单与徽章安静地说谎，越早跑全量回归越便宜。
2. **治理 · 端点与工具**：`DELETE` 语义切换、`restore` 端点、`?purge=1`（含「探两次」的
   404/409 分流）、`purge_trash.py` CLI + D9~D11、**D16**、D13、D14 用例。
   > **D16 先写、先看到它红**（放行条件 1）：带绑定的回收站文档是常态，撞外键即 500。
3. **发现 · 后端**：`search.py` 文档桶 + `routes/search.py` 空信封 + 列表三个新参数
   + 详情 `links[]` 富化 `entity_title` + A 组用例。
4. **理解 · 后端**：`storage.blob_exists` + `add_version_from_existing` +
   回滚分支（**分流点在 `_reject_uneditable` 之前**）+ B 组用例（含 **B8** 二进制回滚）。
   > **到这里为止是一个完整、自洽、可上线的交付面**：文档可被搜到、可回滚、可安全删除与恢复。
5. **产出 · 后端**：`templates.py` + `create_text_document`（四条自持不变量）+
   `template_kind` 分支 + `WorkProduct` / `generate_work_product` +
   `agent_archive.py`（**三元组 `ARCHIVE_KIND` + 两段式 prepare/commit**）+
   `agent_runner` 两处接线 + `notify=False` 参数 + C 组用例。
   > **C11 先写、先看到它红**（放行条件 1）：dev-agent 不得产出 QA 交付物。
6. **前端一次性接入**：`decideMode` 完整改写（B-0，最小改动、独立价值；**核对
   `INLINE_SAFE_MIMES` 的 diff 为空**）→ `lib/markdown.ts` →
   `lib/diff.ts` → 新模态（diff / 元信息编辑 / 引用浮层 / 回收站）→ 版本历史与阶段清单改造 →
   文档库两 tab 与三个筛选 → `GlobalSearch` 第三组 →
   `types.ts` / `constants.ts` / `permissions.ts` 登记 → `typecheck` + `build` + §7.3 手测。

前端**刻意整体放在最后一步**：本轮六个前端改动点共享 `types.ts` 与 `constants.ts` 两个文件，
拆成多次提交只会制造反复的类型冲突；而后端每一步都能独立回归。

---

## 10. 明确不做（Non-Goals）

延续上一轮的取向：每一项都被认真考虑过并**有意排除**，写下来是为了让实施者不必反复权衡。

- **文档正文的全文检索**：本轮搜索仍只覆盖标题 / 描述 / 文件名。真正的正文检索需要
  倒排索引（SQLite FTS5 虚拟表），而 FTS5 表**不在** `db.create_all()` 与 `schema_sync`
  的能力范围内，必须先有迁移工具。属于「上 Alembic 那一轮」的议题。
- **多人协同编辑**：仍以 `expected_version_id` 的乐观锁给出「冲突可检测」的下限，
  不引入 OT / CRDT / WebSocket。
- **语法高亮**：代码块只做等宽 + 横滚。高亮需要每种语言一套词法器或一个新依赖，
  与「零新增运行时依赖」的既定约束冲突。
- **服务端转码预览**（docx → PDF / 图片缩略图）：需要重型依赖，office 文档一律下载查看。
- **文档级权限（私有 / 指定人可见）**：读权限继续与工单对齐。
- **对象存储 / 云盘对接**：`storage.py` 的窄接口仍为此预留，但本轮仍是本地磁盘。
- **回收站的自动定时清理**：本项目没有调度器，`purge_trash.py` 只在人按下 `--apply` 时工作。
  引入定时任务意味着引入一个能在无人值守时**不可逆删除用户数据**的组件，那需要单独一轮
  来讨论它的可观测性与熔断，不该作为本轮的附赠品。
- **Agent 归档产物的质量评估**：系统不判断 LLM 写的测试报告是否"合格"，
  只如实记录「这是 Agent 在这个阶段产出的材料」。人的审阅无法也不应被自动化替代——
  这正是 `reviewing` 这个状态存在的理由。

以下是**本轮调研新发现的真实缺口**，有意留到下一轮，写在这里以免被当成疏漏：

- **通知类型不细分**：改版复用 `document_added`，用户在通知中心分不清「新增了文档」与
  「文档改到 v3」。细分需要新增 `NOTIFICATION_TYPES` 项并同步前端手写镜像
  （`NotificationPrefsCard.tsx:21`）——改动本身很小，但它会**改变所有存量用户的通知面**
  （「无行 = 开启」意味着零回填即全员开始收新类通知），这类影响面应当独立一轮评估，
  不该混在文档功能里搭车。
- **评论附件与 `#doc-123` 引用语法**：`routes/comments.py` 与 `MentionTextarea` 目前对文档
  零感知。它需要一套新的行内引用解析 + 渲染 + 权限回显，量级接近本轮的一整根支柱。
- **文档的批量操作**：`services/bulk_ops.py` 的 `_ROLE_GATES` 只有 6 个工单维度 action，
  文档库页也没有多选列。补齐意味着把「逐项裁决·部分成功」三桶契约扩展到第三类实体——
  是一次值得单独做的、有明确验收面的改造。
- **粘贴上传（Ctrl+V 截图直接成为 `bug_evidence`）**：全前端目前零 `onPaste` / clipboard 处理。
  它对 BUG 复现材料的价值很高，但需要同时处理剪贴板图片命名、格式判定与抽屉焦点归属，
  单独做更干净。
- **既有页面的全面响应式改造**：`components/documents/` 全目录只有 **1 处** Tailwind 响应式前缀
  （`DocumentRow.tsx:74`），模态宽度是硬编码像素。本轮**只保证新增界面在 375px 下可用**
  （§7.3 手测第 12 条），**不**回头重做文档库表格、抽屉与既有模态的断点体系。
- **跨项目绑定的校验**：现网允许把 A 项目的文档绑到 B 项目的工单上
  （`ticket_documents.py:113-115` 只在 `project_id` 缺省时继承工单）。**本轮有意保持现状**——
  跨项目复用一份通用规范是真实诉求，贸然禁止会伤到正当用法；正确的解法是「允许但在 UI 上
  标注来源项目」，那属于项目作用域那条线的议题。

- **全站焦点陷阱（focus trap）**：上一轮已记入 Non-Goals 并说明理由（需同时改造抽屉、
  5 个既有模态与 `ConfirmDialog`，是一次独立的全站 a11y 改造）。本轮新增的三个模态
  同样只继承既有的层叠语义，**不**顺手做焦点陷阱。它仍是一个值得单独立项的候选。

---

## 附：本文件引用的现网事实清单（供评审逐条核对）

| 断言 | 出处 |
|---|---|
| `search_all` 只聚合 Requirement / Bug | `backend/services/search.py:39-47` |
| 全局搜索空关键词分支手写信封 | `backend/routes/search.py:23-27` |
| `GlobalSearch` 的 `counts` 直接解构 | `frontend/components/layout/GlobalSearch.tsx:191` |
| Agent 产物只落评论 | `backend/services/agent_runner.py:101-119` |
| `generate_work` 唯一调用点 | `backend/services/agent_runner.py:101` |
| `_llm_active()` 在 TESTING 下恒 False | `backend/services/agent_executor.py:28-32` |
| 删除是物理删 + reap | `backend/routes/documents.py:196-199` |
| `can_manage_document` = 上传者 或 pm/admin | `backend/services/auth_helpers.py:75` |
| `force=1` 需 pm/admin | `backend/routes/documents.py:192-194` |
| 既有删除用例只断言 204/404/403/409/列表空/有 doc_detached | `backend/tests/test_documents.py:192-236` |
| `ADDITIVE_COLUMNS` 现有两条 | `backend/services/schema_sync.py:19-22` |
| `schema_sync` 只支持 ADD COLUMN | `backend/services/schema_sync.py:8-11` |
| 阶段清单期望表（7 态 + 5 态） | `backend/services/doc_policy.py:22-35` |
| `bound_kinds` 是清单的唯一判据来源 | `backend/services/doc_policy.py:90` / `services/documents/service.py:264` |
| `link_counts` / `document_link_counts` 是徽章数字来源 | `backend/services/documents/counts.py:22,63` |
| `find_version` 对跨文档 id 视为不存在 | `backend/services/documents/service.py:191` |
| `DOC_FANOUT_MAX_LINKS` 默认 20 | `backend/config.py:87` |
| 预览 / 编辑阈值与启动期断言 | `backend/config.py:84-85`、`services/doc_policy.py:57` |
| 层栈契约已落地于 `Modal.tsx` | 上一轮 F5（`docs/plans/ticket-document-management/spec.md:1291`） |
| 前端文档类型定义齐备（含 `DocumentRevisionResult`） | `frontend/lib/types.ts` |
| `invalidateDocumentViews` / `invalidateTicketViews` | `frontend/lib/swr-keys.ts:42-51`、`hooks/useDocumentLibrary.ts:41-46` |
| `uploader_id` 筛选后端已有、前端未暴露 | `backend/routes/documents.py:120-131` ↔ `frontend/app/(app)/documents/page.tsx:128-147` |
| `PATCH /documents/:id` 前端零调用方 | `frontend/hooks/useDocumentLibrary.ts:71-78`（已实现）↔ 全前端无引用 |
| `links[]` 不含工单标题、无 UI 消费 | `backend/models/document_link.py` 的 `to_dict()`、`routes/documents.py:144-148` |
| `decideMode` 按 MIME 判 text，csv/json/yaml 落到下载 | `frontend/components/documents/DocumentPreviewModal.tsx:26-31` ↔ `backend/services/documents/mime.py:12,19-22` |
| 后端 `TEXT_EXTENSIONS` 七项、`INLINE_SAFE_MIMES` 七项且不含 html/svg | `backend/services/documents/mime.py:12,19-22` |
| **前端只镜像了 `INLINE_SAFE_MIMES`，`TEXT_EXTENSIONS` 全前端零引用**（评审 V-13 更正 v1 的表述；故 §3.4 是**新建常量**而非改判据） | `frontend/lib/constants.ts:246-258`（`INLINE_SAFE_MIMES` + `isInlineSafeMime`）↔ 全前端无 `TEXT_EXTENSIONS` |
| `decideMode` 是四分支且**第一行就是 inline-safe 闸** | `frontend/components/documents/DocumentPreviewModal.tsx:20,26-31` |
| `GlobalSearch` 的 Enter 兜底是 requirements/bugs 二选一 | `frontend/components/layout/GlobalSearch.tsx:122-126` |
| `document_links.document_id` 是**真外键**，且 `PRAGMA foreign_keys=ON` 每连接生效 | `backend/models/document_link.py:23`、`backend/extensions.py:61` |
| `extensions.py` **未做** pysqlite 的 SAVEPOINT workaround（只挂 PRAGMA 监听） | `backend/extensions.py:42-77` |
| `create_version` 的 JSON 分支先调 `_reject_uneditable` 再读 `content` | `backend/routes/documents.py:238-246` |
| `_get_document_or_404` 是 `db.session.get`（按主键，加不了 filter） | `backend/routes/documents.py:56-60` |
| 落盘必须在 session 写入之前（模块级硬约束） | `backend/services/documents/service.py:5-7` 模块 docstring |
| `storage.blob_exists` **现网不存在**，需新增；`delete_blob` 带宽限窗口 | `backend/services/documents/storage.py`（`is_reapable` / `_grace_seconds`） |
| `MAX_AGENT_STEPS = 6`（`run=all` 单次上限） | `backend/services/agent_runner.py:25` |
| 前端零 markdown / diff 依赖 | `frontend/package.json:12-29`（next / react ×2 / @dnd-kit ×3 / swr） |
| `useOverlayLayer(active)` 是层栈的公开入口 | `frontend/lib/overlay-stack.ts` |
| `DocumentRow` 的 ⋯ 菜单**不进层栈** | `frontend/components/documents/DocumentRow.tsx` |
| 改版复用 `document_added` 通知类型 | `backend/services/documents/service.py:311` → `notifications.notify_document` |
| 侧边栏第 9 项即 `/documents` | `frontend/components/layout/Sidebar.tsx:71-76` |
| `ADDITIVE_COLUMNS` 与文档相关条目为**零**（本轮是第一次给 documents 加列） | `backend/services/schema_sync.py:19-22` |
| 门禁调用点 | `backend/routes/requirements.py:385-391`、`backend/routes/bugs.py:244-250` |
| 文档相关测试共 6 个文件、98 个测试函数（参数化后 135 条） | `backend/tests/test_document*.py`、`test_doc_policy.py` |

---

## 11. 评审结论（Review Verdict）

### 结论：**有条件通过**

v1 是一份取证质量很高的设计文档——附录 30 余条现网断言经逐条复核**仅 1 条不实**
（V-13，且不影响设计判断）；与 CLAUDE.md 四条硬约束（`ADDITIVE_COLUMNS` 登记、
状态机神圣性、`seed_records` 登记、质量闸相对化）**均无冲突**；
§5.1 的三条数据层细节（不建外键 / 不加索引 / 默认 NULL）论证正确；
四根支柱的切分与 §9 的六步可停顺序是真实可执行的。

但 v1 有一个**系统性的盲区**，四个 P0/P1 全部落在它上面：
**它写清楚了新代码该做什么，却没写清楚新代码落在既有函数的第几行、前面还有哪个 guard。**
`decideMode` 的第一行是 inline-safe 闸（V-05）、`create_version` 的 JSON 分支先调
`_reject_uneditable`（V-06）、`_get_document_or_404` 是 `session.get` 加不了 filter（V-07）、
`GlobalSearch` 还有第三个结果形状耦合点（V-08）——每一处都是「设计正确、落地即错」。
另外两处（V-01 `ARCHIVE_KIND` 少一维、V-02 `trash.purge` 不自包含）更严重：
**它们各自的守卫用例在结构上就抓不到自己那类 bug**（C7 会给 V-01 盖章通过，
D11 的样本天生撞不到外键）——一条抓不到自己那类 bug 的用例，比没有用例更危险。

上述 **2 个 P0 + 9 个 P1 已在 v2 正文中逐条修复**，修复处均带 `【评审 V-xx】` 标记
并保留了「v1 怎么说 / 照做会怎样 / 现在怎么做」三段式，便于实施者对照；
8 个 P2 也已顺手就地更正。**当前无未解决的 P0 / P1。**

### 放行条件（三条，实施完成后须逐条出示证据）

1. **P0 的两条护栏必须先于功能代码存在**：
   `test_dev_agent_never_produces_qa_artifacts`（C11）与
   `test_purge_document_that_still_has_links`（D16）**先写、先看到它们红**，再写实现。
   这两条是本轮唯二「错了不会报错、只会安静地错」的地方（一个把门禁点绿、
   一个在常态路径上 500），TDD 在这里不是风格问题。
2. **三条口头约束必须落成可执行断言**：C12（落盘在状态写入之前）、
   C8 加强版（commit 后重新查库、无残留）、`INLINE_SAFE_MIMES` 的 diff 为空。
   本仓库已经有过一次「测试全绿 + 每个文件都损坏」的教训（`_validate_upload` 的出口
   不变量），凡是靠「实施者会记得」成立的性质，都必须变成一条会红的用例。
3. **质量闸按 §7.1 相对判据出示实测**：开工前记录 `pytest -q` 基线，完工后零失败且
   总数不低于基线 + 本轮新增；前端 `npm run typecheck` 与 `npm run build` 零错误；
   两个 CLI 各跑一次 dry-run 确认零副作用。**不接受「应该没问题」，只接受命令输出。**

### 附：给实施者的三条提醒（非阻断）

- §9 第 1 步（软删数据层）完成后**必须**先跑一次全量回归再往下走。八处过滤点里第 4 处
  （`bound_kinds`）和第 5 处（`link_counts`）是 join 改写，错了不会抛异常，只会让数字和
  清单**安静地说谎**——越早发现越便宜。
- `DOC_AGENT_ARCHIVE` 首次上线建议先 `false`（§5.3 运维注记）。它是本轮唯一一个
  「升级即生效、且会自动产生用户可见数据」的开关。
- §7.4 要求的「实施过程发现的方案缺陷」一节请照写。上一轮那份记录（6 条实施发现、
  1 条与 spec 直接矛盾）是这一轮能做到证据式评审的直接原因——**不静默偏离**这条约定
  正在产生复利。

---

**评审人**：Subtask #1 · Senior Reviewer
**评审对象**：`docs/plans/document-lifecycle-depth/spec.md` v1（1159 行 / 12 章）
**评审范围**：仅 `spec.md`；**未改动任何源代码，未执行 `git commit`**
**产出**：v2 —— §0.5 评审记录（2 P0 / 9 P1 / 8 P2 + 3 条未采纳意见及理由）、
正文逐条修复、§7.2 新增 5 条守卫用例、§7.3 新增 3 条手测、§8 新增 3 条风险、
附录补 11 条新取证事实


---

## 12. 实施过程发现的方案缺陷（Issues Found During Implementation）

格式沿用上一轮：**设计怎么说 / 照做会怎样 / 实际怎么做**。**不静默偏离。**
本节由 Subtask #2（实施）追加，未改动 §0~§11 的任何一个字。

### I-1（**阻断级 · 与 §2.4 D-1 直接矛盾**）「回收站里的文档仍有绑定是常态」在本 spec 自己定义的 HTTP 契约下**永远不成立**

- **设计怎么说**：§2.4 D-3 与评审 V-02 反复强调「软删**不动** links」「**『回收站里的文档仍有绑定』
  是常态而非边界**」，并据此把 `trash.purge` 定义为自包含；D7 用例要求「恢复后 D3/D4/D5
  全部逆转」，D16 用例要求「软删一份**仍绑着 2 张单**的文档（**不带 `force`**）→ `?purge=1` → 204」。
- **照做会怎样**：**造不出这个状态**。同一节的 §2.4 D-1 状态表明确保留了现网契约：
  「有绑定，无 `force` → **409 不变**」，而「有绑定 + `?force=1` → **解绑全部**（`doc_detached`
  照写）+ 软删」。两条路径穷尽了 HTTP 删除的全部入口：不带 force 的删除**根本进不去回收站**，
  带 force 的删除**进去时 links 已经没了**。过滤点 7（禁止绑定已删文档）又堵死了「先软删再绑定」。
  于是 D16 逐字照写会在第一行 `assert 204` 上拿到 409；D7 的「绑定原样回来」同样无从验证。
  更要命的是 **D3 / D4 / D5 三条过滤点用例会变成假绿**：若用 `force` 造样本，抽屉消失、
  清单变红、徽章下降全部是**解绑**造成的，八处过滤点一行不写用例也照样通过——
  那正是本 spec §7.2 结尾自己点名的「一条抓不到自己那类 bug 的用例，比没有用例更危险」。
- **实际怎么做**：**保留 §2.4 D-1 的 409 契约不动**（改它会直接推翻既有
  `test_delete_linked_document_conflicts`，违反「既有 506 全绿」），而把「回收站中 + 仍有绑定」
  这个状态**在服务层**造出来——`tests/test_document_trash.py::trash_keeping_links` 直接调
  `trash.soft_delete(document, actor)`（那正是不变量真正所在的层）。D3/D4/D5/D7/D13/D16 全部改用它，
  并在该 helper 的 docstring 里写清「为什么不走 HTTP，以及为什么这不是偷懒」。
  另补 `test_force_deleted_document_restores_without_its_links` 覆盖 §2.4 D-3 那条**例外**
  （force 路径恢复不带回绑定），前端恢复确认框如实说明了这一点。
  `trash.purge` 的自包含**照旧落地**：它守的不再只是「常态」，而是「库里一旦出现这种行
  （CLI、直接操作、或将来某次放宽 409），路由与 CLI 都不能 500」——D16 与
  `test_purge_trash_cli_survives_a_document_with_links` 双向钉死，实施期已实测：
  注掉 `purge` 里的 `detach_all_links` 一行，两条用例立刻变红。
- **给下一轮的建议**：**409 这条规则本身值得重新讨论**。它当初的全部理由是「物理删除不可逆」；
  删除变成可撤销之后，理由已经消失，而它正在挡住软删最大的那个卖点（恢复把绑定一起带回来）。
  改它是一次独立的、需要改既有用例的契约变更，不该混在本轮里搭车。

### I-2（**契约级 · §7.1「既有 506 全绿」与 §4.7 不可兼得**）搜索信封扩展必然打破三条既有断言

- **设计怎么说**：§7.1 要求「零失败且总用例数不低于基线（506）」；§4.7 要求 `GET /api/search`
  的响应体与空信封都新增 `documents` 与 `counts.documents`；A4 用例专门守空信封。
- **照做会怎样**：`tests/test_global_search.py` 有三处用**整体字典相等**断言信封形状
  （`body["counts"] == {"requirements": 1, "bugs": 1}` 与 `body == {...}`）。契约一扩，三条必红。
  这不是实现错误，而是 spec 要求的**有意契约扩展**碰上了精确形状断言。
- **实际怎么做**：就地把三处断言扩为三键，并在改动处注明「这是 §4.7 要求的信封扩展」。
  **没有放宽任何一条断言的强度**（仍是整体相等，只是多了一个键）。这与 §2.4 D-1 刻意对齐
  既有删除断言面的做法一致：能不改就不改，必须改时把理由写在断言旁边。

### I-3（P1）`create_text_document` 的签名给不出 §2.3 C-1 自己要求的文件名

- **设计怎么说**：§2.3 C-1 一边规定文件名为 `{kind}-{entity}-{ticket.id}.md`，一边规定
  「调用方只传 `title / kind / content / project_id / uploader`」。
- **照做会怎样**：叶子函数拿不到 `entity` 与 `ticket.id`，只能退化成固定文件名——而文件名正是
  §2.1 A-1 新增的**搜索命中面之一**（「用户记得住的是 `payment-v2.md`」），退化会直接削弱那条能力。
- **实际怎么做**：加一个 `filename_stem` 参数（**扩展名仍恒为 `md`，不接受调用方指定**，
  不变量 1 一字未动），由路由与归档各自用 `templates.filename_stem()` 拼好传入。
  把 `ticket` 传进叶子模块只为拼一个字符串会给它凭空加一层领域依赖，这是更差的选择。

### I-4（P1）两段式归档要求「元数据阶段零磁盘 IO」，而 §2.5 时序 A 指定的两个服务函数都会落盘

- **设计怎么说**：§2.5 时序 A 的第 7 步（`archive_commit`，SAVEPOINT 内）调
  `service.add_version_from_text(...)` 或 `service.create_text_document(...)`，并注明
  「复用已落盘的 blob」；§2.3 C-2 要求这一段「全程无磁盘 IO」。
- **照做会怎样**：现网 `add_version_from_text` 与新建的 `create_text_document` **内部都会调
  `storage.digest_and_persist`**——照原样调用，落盘会重新发生在 SAVEPOINT 内，
  即 SQLite 写锁窗口之内。V-03 修的那个坑会原样长回来，**而 C12 抓不到它**
  （C12 断言的是「第一次落盘发生在状态写入之前」，第二次落盘在它之后照样通过）。
- **实际怎么做**：抽出 `service.persist_text(content) -> (payload, blob)`（**纯磁盘 IO，
  不碰 `db.session`**），`archive_prepare` 只调它；`create_text_document` 与
  `add_version_from_text` 各加一个 `blob=None` 关键字参数，归档路径把 `plan.blob` 传进去，
  此时这两个函数**一个字节都不写盘**。缺省行为（`blob=None` → 自己落盘）与现网逐字节一致。

### I-5（P2）`add_version_from_text` 的 `notify` 参数是死代码

- **设计怎么说**：§3.2 要求给 `bind_document` / `fanout_revision` / `add_version_from_text`
  三个函数都加 `notify: bool = True`。
- **照做会怎样**：`add_version_from_text` **自己不发任何通知**（通知在 `fanout_revision` 里），
  给它加一个永不被读取的参数就是一处误导性死代码——读者会以为它有通知职责。
- **实际怎么做**：只给真正发通知的两个函数（`bind_document` / `fanout_revision`）加 `notify`。
  归档路径显式调 `fanout_revision(..., notify=False)`。C13 与
  `test_archive_revision_sends_no_notification_either` 覆盖两条分支，效果与设计意图完全相同。

### I-6（P2）过滤点 5 里的 `document_link_counts` 加软删过滤是**无用且有害**的

- **设计怎么说**：§2.4 过滤点表第 5 行把 `counts.link_counts`（`:22`）与
  `counts.document_link_counts`（`:63`）并列，后果写作「徽章数字虚高」。
- **照做会怎样**：那句后果只对 `link_counts` 成立（它按**工单**聚合，被删文档会虚高工单徽章）。
  `document_link_counts` 是按**文档**聚合、供文档库列表用的，而它的输入永远是**已经过筛的**
  文档集合：正常列表已过滤软删（过滤点 2），搜索已过滤（过滤点 6）。加上过滤在这两处是
  **no-op**，在**回收站视图**里却会把每一行的 `link_count` 打成 0——用户于是看不到
  「这份要彻底删的文档还绑着 2 张单」，而那恰恰是他做决定最需要的信息。
- **实际怎么做**：`link_counts` **加**过滤（`test_deleted_document_drops_out_of_badge_count` 守卫），
  `document_link_counts` **有意不加**，理由写在过滤点清单的同一处。取向与第 8 处
  （`detach_ticket_document`「有意不改」）一致：**清单的价值在于每一处都有明确处置，
  而不是每一处都改**。

### I-7（P2）`doc_rolled_back` 无法作为文档实体的 Activity 落库

- **设计怎么说**：§2.2 B-3 要求「写 `doc_rolled_back`（新 action），并复用现网
  `service.fanout_revision` 的扇出与上限」。
- **照做会怎样**：两句话合起来是歧义的——若理解成「先写一条文档维度的 Activity、再扇出
  `doc_revised`」，那么 `Activity.entity_type` 只有 `("requirement", "bug")` 两个合法值
  （`models/activity.py:8`），文档不是合法实体；且同一次回滚会在时间线上留下两条语义重复的记录。
- **实际怎么做**：给 `fanout_revision` 加 `action` 与 `message` 两个关键字参数，回滚**复用同一次
  扇出**但写 `doc_rolled_back` 与「回滚到 v1」的文案。既有全部调用点行为逐字节不变
  （默认仍是 `doc_revised`）。`test_rollback_writes_doc_rolled_back_activity` 断言恰好一条。

### I-8（P2）`link.stage` 要记「推进后的目标状态」，而 `bind_document` 硬编码读 `ticket.status`

- **设计怎么说**：§2.3 C-2 规定归档的 `link.stage` 取**推进后**的目标状态，「由
  `plan.target_stage` 携带，不依赖调用时 `ticket.status` 的取值」。
- **照做会怎样**：`archive_commit` 的调用点在 `ticket.status = to` **之后**，看似读 `ticket.status`
  也对；但 §2.5 时序 A 与 V-03 又要求把落盘提前——一旦将来有人把 `archive_commit` 也往前挪
  （或在别处复用 `bind_document`），`stage` 会静默记成旧阶段，且不会有任何报错。
- **实际怎么做**：`bind_document` 增加 `stage=None` 关键字参数（缺省仍读 `ticket.status`，
  既有调用点零变化），归档显式传 `plan.target_stage`。
  `test_archive_creates_document_on_llm_product` 断言 `link.stage == "reviewing"`。

### I-10（**实施期自查发现的 HIGH · 已修复**）`purge_trash.py` 的批量事务会删掉**已复活文档**的物理文件

- **设计怎么说**：§2.4 D-3 只写了「**逐个文档各自 try/except**：一份文档清理失败只记进
  `skipped` 并继续，不让整批停摆」，没有规定事务边界。
- **照做会怎样**：v1 实现照字面写成「循环里逐个 `try/except` + 循环**之后**统一
  `db.session.commit()`」。但 `db.session` 只有**一个**事务——循环里任何一次
  `except` 分支的 `rollback()` 都会把**本批已经处理过的全部文档**一起回滚，
  而它们的摘要早已并进 `orphans`。于是循环结束后：这些文档的行被复活了，
  `reap(orphans)` 却照样把它们的物理文件删掉——**留下一批行还在、`/download` 与
  `/content` 恒 410、版本历史不可恢复的空壳**。宽限窗口救不了：按定义这些 blob
  已经在回收站里躺了 `DOC_TRASH_RETENTION_DAYS`（默认 30）天，`is_reapable` 恒为真。
  触发条件是完全现实的——本工具跑在**活动库**上，第二份文档撞一次
  `database is locked` 就够了。**而 D14（dry-run 零副作用）结构上抓不到它**：
  dry-run 全程回滚且从不 `reap`，只有 `--apply` 会踩。报告还会同时说谎
  （把复活的文档列进 `deleted`）。
- **实际怎么做**：改为**逐个 commit**，且**摘要只在 commit 成功之后才并入 `orphans`**；
  dry-run 改为每份处理完立刻 `rollback`（既真实走一遍 FK 路径、又逐份隔离）。
  新增 **`test_purge_trash_cli_isolates_a_failing_document`**：造两份过期文档、让第二份
  的 `purge` 抛异常，断言①第一份确实已删、②第二份仍在回收站、③**第二份的 blob 仍在磁盘上**。
  已实测：把实现改回「批量 commit」的写法，该用例立刻变红（`assert <Document 1> is None`）。

### I-11（**已修复**）`archive_commit` 的兜底会把**主事务**的 flush 失败误报成「归档失败」

- **设计怎么说**：§2.3 C-2 规定 `archive_commit` 整体包在 `try/except Exception` 里，
  失败只 `log.warning` 绝不阻断推进。
- **照做会怎样**：`begin_nested()` 会**先 flush 挂起写再发出 SAVEPOINT**（那正是模块
  docstring ② 依赖的前置条件）。若失败的是**主推进事务自己的写**
  （`ticket.status` / `Comment` / `Activity`），异常在 SAVEPOINT **之外**抛出，
  被这层兜底记成一条「归档失败」的 warning 然后静默返回；调用方随后 `commit()` 才炸出
  `PendingRollbackError`，用户拿到一个 500，而唯一的日志线索指向一个跟它毫无关系的子系统。
- **实际怎么做**：把 `db.session.flush()` 提到 `try` **之外**。两类失败就此分得开：
  主事务的失败原样冒泡（带真实堆栈），归档自己的失败才走兜底。顺带把「调用点之前必有
  挂起写」这条前置条件从**隐式依赖**变成了**显式语句**。

### I-12（**已修复**）截断横幅硬编码「1 MB」，与 R-11 自相矛盾

- §6.2 的界面稿把横幅文案写作「已截断显示前 1 MB」，而 `DOC_TEXT_PREVIEW_MAX_BYTES`
  是可配的（`config.py:84`）。运维调成 256 KB 之后，那句提示就是一个 4 倍错的数字——
  与 §6.4 明令「保留期前端不得硬编码」是同一条 R-11。
- **实际怎么做**：`GET /api/documents/meta` 增回传 `text_preview_max_bytes`，
  `MarkdownView` 用 `formatBytes()` 渲染下发值；拿不到时退化为不报数字的文案。

### I-13（**已修复**）`list_documents` 的三处 `filter_by` 只因语句顺序才正确

- `Query.filter_by` 绑定的是**最后一次 join 进来的实体**，而 `unlinked=1` 与
  `_apply_sort` 都会 `outerjoin`（`document_versions` 或计数子查询）。今天 `kind` /
  `project_id` / `uploader_id` 三处恰好写在 join **之前**所以是对的——但那是语句顺序在兜底。
  将来任何一次「顺手把新筛选加在后面」都会静默去筛错表；在 `deleted=1` 那条路上，
  那意味着**上传人收紧直接失效**（一个越权读取）。
- **实际怎么做**：三处改为显式 `filter(Document.x == ...)`，顺序不再重要，并把理由留在代码里。

### I-9（记录，无需处置）`sort=size` 有意不使用 `NULLS LAST`

- §4.1 写的是 `order_by(DocumentVersion.size_bytes.desc().nulls_last())`。SQLite 把 NULL 视为
  最小值，`DESC` 天然把「没有版本的文档」排在最后；而 `NULLS LAST` 语法需要 SQLite ≥ 3.30。
  没有理由为一个排序引入运行时版本依赖，故实现用 `.desc()` 并在代码注释里写明等价性。

---

**质量闸实测（§7.1 / 放行条件 3，命令输出为准）**

| 闸 | 命令 | 结果 |
|---|---|---|
| 后端基线（开工前） | `cd backend && python -m pytest -q` | **506 passed / 0 failed**（exit 0） |
| 后端完工 | 同上 | **597 passed / 0 failed**（exit 0）——基线 506 + 本轮新增 91 条，零失败、总数不低于基线 |
| 前端类型 | `cd frontend && npx tsc --noEmit` | **0 error** |
| 前端构建 | `cd frontend && npm run build` | **Compiled successfully**，17 个路由全部产出 |
| CLI ①（新增） | `python tools/purge_trash.py` | exit 0，dry-run 报告正确，`aragon.db` mtime **未变**、`git status` **未变** |
| CLI ②（既有） | `python tools/gc_orphan_blobs.py` | exit 0，同上零副作用 |

**§7.3 手测 3 / 4 / 5 的可自动化部分已在运行时实证**（把 `lib/markdown.ts` 与 `lib/diff.ts`
编译后以桩 `createElement` 跑了一遍，断言的是**元素树本身**而不是截图）：

- 手测 3（排版）：`h1` / 一层嵌套 `ul` / `ol` / `blockquote` / `pre>code` /
  `table+thead+tbody+th+td` / `hr` / `strong` / `em` 全部产出，围栏内正文原样保留。
- 手测 4（XSS）：9 条攻击载荷——`<img onerror>`、`javascript:`（含 `JaVaScRiPt:` 与前导空格
  绕过尝试）、`data:`、`vbscript:`、`![](javascript:)`、`<script>`、裸 `<a href='javascript:'>`
  ——**全部**满足：无危险 `href`、无 `dangerouslySetInnerHTML`、无 `img` 元素；裸 HTML 逐字
  作为文本节点出现。合法的 `https:` / `mailto:` 仍放行且带 `target=_blank rel="noopener noreferrer"`。
- 健壮性：13 条对抗性输入（未闭合围栏 / 纯竖线行 / 只有表头的表 / 500 个列表标记 /
  200 个 `>` / 未闭合强调与行内代码 / 10 万字符单行 / 空串）**无一崩溃或超时**。
- 手测 5（diff）：增删计数、行号连续性、纯增 / 纯删、**不 trim**（缩进变化算变化）、
  `

` 归一全部正确；2500×2500 触发 `DIFF_MAX_CELLS` 降级且 <300ms（**未分配 DP 表**），
  闸内 2000×2000 实测 71ms。

**放行条件 1 的实测证据（两条 P0 护栏「先看到红」）**：实施期分别向源码注入对应的 bug 并实跑：

- 把 `("requirement","dev","testing") → test_plan` 与 `("bug","dev","verifying") → test_report`
  两格加回 `ARCHIVE_KIND` → **C11 `test_dev_agent_never_produces_qa_artifacts` 变红，
  而 C7 `test_archive_kind_matches_stage_expectations` 照绿**——与评审 V-01 的预判逐字一致。
- 删掉 `trash.purge` 里的 `service.detach_all_links(document, actor)` 一行 →
  **D16 与 `test_purge_trash_cli_survives_a_document_with_links` 双双变红**，其余用例全绿。

两处 bug 均已在验证后立即还原。
