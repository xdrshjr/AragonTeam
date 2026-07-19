# 开发方案：评论 @提及自动补全（`mention-autocomplete`）

> **文档版本**：**v2**（Subtask #1 · 方案评审与修复）— 承 v1（Subtask #0 · 方案设计）
> **Loop 迭代**：Iteration 4/5 · 特性 `mention-autocomplete`
> **作者**：资深工程师（Anthropic Eng）｜**评审**：资深评审（Anthropic Eng）
>
> 前置脉络：
> - Iteration 1 已把**唯一的业务 Mock**（Agent 执行引擎罐头文案）真实化（`docs/plans/real-agent-execution/spec.md`，commit `12c5a4c`）。
> - Iteration 2 已把设置页占位真实化为账号自助中心（`docs/plans/account-settings/spec.md`，commit `1373e94`）。
> - Iteration 3 已把 Header「假搜索」真实化为统一全局搜索（`docs/plans/global-search/spec.md`，commit `9396400`），并在其 §10「后续迭代路线」把本轮选题**明确交棒**：**第 1 项即「@提及自动补全（C7）」**。
>
> **评审记录（Review Notes）**：见下方 `## 评审记录` 段（P0×0 / P1×2 / P2×3）。所有 P0/P1 已就地修复并标 `【v2 修复】`；`## 评审结论` 见文末。

---

## 评审记录（Review Notes）

> Subtask #1 · 逐节按 **可行性 / 完整性 / 一致性 / 适度性** 四维评审。评审前已对照源码逐条核验方案主张（`notifications.py`/`comments.py`/`CommentComposer.tsx`/`FeedTimeline.tsx`/`constants.ts`/`conftest.py`/`tsconfig.json`/`package.json` 等），下表仅列**经核实成立**的问题。核验已确认成立的方案主张（不构成问题，供实现方安心）：React `18.3.1` + Next `14.2.5`（事件委托根在 `window` 之下 → R1 的 `stopPropagation` 阻断抽屉 `window` 级 Escape 监听成立）；`tsconfig` `strict:true` 但**未开** `noUncheckedIndexedAccess`（`value[i-1]` 索引类型为 `string`，纯函数按 v1 写法可过 typecheck）；`/users` SWR key 与 `AssigneePicker` 同为 `"/users"`（去重成立）；`is_enabled` 对未知类型默认放行、`mentioned` 在 `NOTIFICATION_TYPES` 内（偏好闸不误伤）；既有 `test_mention_notifies_user` 只断言 `type=="mentioned"`（富文案不破回归，R6 成立）。

| # | 严重度 | 维度 | 问题 | 处置 |
|---|--------|------|------|------|
| **P1-1** | P1 | 完整性 / 一致性 | 全案**风险最高、最不直观**的逻辑是受控 textarea 的**光标数学**（`activeMention`/`applyMention`），但 §6.2 仅有 `typecheck`+`build`、§6.3 为人工冒烟——该逻辑**零自动化覆盖**。仓库无 JS 测试运行器（`package.json` 仅 `typecheck`/`build`，见核验），与 CLAUDE.md 第七节「公开行为都要有单元测试覆盖正常路径与至少一条异常路径」相悖。且 v1 把纯函数埋进 `MentionTextarea.tsx` 却自述「便于就近单测」，在无 runner 时是**言过其实**。 | **【v2 修复】** ①纯函数下沉到 `frontend/lib/mentions.ts`（纯、可被 `FeedTimeline`/`CommentComposer` 复用、将来接 runner 即可单测）——见 §2.3、§3；②§6.2.1 增**纯函数边界用例矩阵**（8 条，评审已随附验算）并列为 DoD 硬门（光标居中、`a@b` 不触发、`@` 位于串首、含邮箱前缀、CJK 紧邻 `请@member`、尾随空格后不误重开）。不新增测试依赖（守「零新依赖」基线）。 |
| **P1-2** | P1 | 完整性（幸福路径正确性） | `_create_comment` 先 `notify_comment` 再 `notify_mentions`，二者相互独立且 `notify()` 只对**自己**去重、不跨类型去重。故当被 @ 的人**同时是** reporter / 人类 assignee / 历史评论人时，一条评论会让其**同时收到 `commented` + `mentioned` 两条通知**。这是常见幸福路径（@ 的往往正是相关方），v1 全文未提，仅在 §9 把「dedup-merge」列为**未来**项——等于把「当前就会重复」这一既成行为**留白**，冒烟者易误判为 BUG。 | **【v2 修复】** 作出**显式设计裁定**并写入 §2.4：本轮**接受**双通知（`mentioned` 是更强的显式点名信号，与 `commented` 语义不同；统一去重合并按 §9 交棒 Iter5），并以回归用例 `test_mention_and_comment_coexist_for_participant` **锁死该契约**（见 §6.1），把「留白」变为「有意为之且被测」。 |
| **P2-1** | P2 | 健壮性（潜在踩坑） | `constants.ts` 导出的 `MENTION_RE` 带 `/g` 标志。`matchAll` 消费它是无状态安全的，但若**他处**误用 `.test()`/`.exec()`，全局正则的 `lastIndex` 会在多次调用间残留 → 间歇性漏配/错配。 | **【v2 采纳】** §2.5 在常量注释里加**用法约束**：`MENTION_RE` 仅供 `String.prototype.matchAll` 使用，禁止对其调用 `.test()`/`.exec()`；候选硬过滤另用**新鲜字面量** `/^[A-Za-z0-9_]+$/`（v1 已如此）。 |
| **P2-2** | P2 | 完整性（中文产品输入法） | 本品主语言为中文，评论正文常经 IME 组词输入。虽「下拉仅在光标位于**拉丁** `@token` 内才打开」天然规避了大部分 IME 冲突，但为稳妥应在**下拉打开时的按键拦截**入口显式短路组字态，避免 ↑/↓/Enter 在极端时序下劫持 IME 候选确认。 | **【v2 采纳】** §2.2 键盘拦截首行加防御 `if (e.nativeEvent.isComposing) return;`（透传给 IME / 父级）。 |
| **P2-3** | P2 | 适度性 / a11y | 下拉仅在 §4.2 暴露 `aria-label`，缺 combobox 语义（`role="listbox"`/`option`、`aria-activedescendant`、`aria-expanded`），与仓库既有交互组件的可达性水位略有落差。 | **不阻断**：列为「有条件通过」的**建议项**（§评审结论）。实现时若成本低可顺带补；不做也不影响本轮 DoD。 |

**评审判断**：无 P0（设计自洽、向后兼容、恪守三约定，可直接实现）。2 项 P1 已就地修复，3 项 P2 中 2 项（P2-1/P2-2）已低成本采纳、1 项（P2-3）列为建议项。结论见文末 `## 评审结论`。

---

## 0. 剩余占位 / 半成品盘点（本轮选题依据）

承接 `global-search/spec.md §10` 与 `account-settings/spec.md §0` 的全仓审计结论——**业务路由中已无任何伪造 / 硬编码的 API 响应**。本轮从 §10 路线图**按价值/风险排序取第 1 项**，对应审计项 **C7**：

| # | 位置 | 现状（本轮复核确认仍存在） | 类型 | 本轮 |
|---|------|------|------|------|
| C7 | `frontend/components/collab/CommentComposer.tsx:48` | 纯 `<textarea>`，占位文案宣传「@用户名 可提醒对方」，但**无任何自动补全 UI**；用户必须凭记忆逐字打对 `username` 才能命中，打错则**静默失败**（`notify_mentions` 找不到用户，不报错也不提醒）。 | 前端半成品（言行不一） | **✅ 纳入** |
| C7-back | `backend/services/notifications.py:19,147-158` | `notify_mentions` 已能解析 `@username` 并扇出 `mentioned` 通知（`test_mention_notifies_user` 已过），但正则 `@([A-Za-z0-9_]+)` **无左边界**：邮箱 `name@example.com` 会被误解析为提及 `example`；提及通知文案为固定「你在需求 #3 的评论中被提及」，缺少工单标题与评论摘要，弱于 `notify_comment`。 | 后端健壮性缺口 | **✅ 一并加固** |

其余审计项（D8–D11 管理台 UI、A4 LLM 运行时配置、搜索增强）继续按 §10 路线图交棒 **Iteration 5**，本轮**不贪多**——聚焦把「@提及」这一条链路**端到端做真、做稳**。

### 选题理由

`notify_mentions` 是 Phase-3 就已落地、却**长期闲置**的后端能力：唯一的入口（评论框）从不引导用户产出可被解析的 `@username`。这与 Iter1–3「把一处言行不一的 UI 真实化、由现成后端能力兜底」的模式完全一致，且**自洽、低风险、零新表**。做完后，「评论里 @ 队友 → 队友收到 `mentioned` 通知 → 点通知直达工单」这条协作闭环才算真正跑通，契合本轮「组织团队协作」的产品主线与「稳健可靠好用，顶级」的目标。

---

## 1. 概述（Overview）

本方案把评论框的「@提及」从**占位宣传**升级为**可用能力**。核心交付是一个提及感知的输入组件 `MentionTextarea`：当用户在评论框中键入 `@` 后，实时弹出**团队成员下拉**（复用现成的 `GET /api/users`，与 `AssigneePicker` 共用 SWR 缓存），支持键盘（↑/↓ 选择、Enter/Tab 确认、Esc 关闭）与鼠标点选；选中后**精确插入 `@username `（含尾随空格）**，从根本上保证后端正则一定能解析命中。这样把「用户是否记得准确 username」这一失败源彻底消除，让被 UI 承诺、却从未真正可用的提及能力落地。

与前端补全对称，本方案对后端做两处**健壮性加固**，让整条链路「稳」：其一，给提及正则加**左边界负向断言** `(?<![A-Za-z0-9_])`，使 `name@example.com` 这类邮箱不再被误判为提及，同时保持对中文紧邻场景（`请@member`）的兼容；其二，给 `notify_mentions` 传入工单对象，让 `mentioned` 通知文案携带**工单标题 + 评论摘要**，与 `notify_comment` 的信息密度对齐。前端 `FeedTimeline` 亦同步把评论正文中的 `@token` 渲染为**高亮 chip**，使时间线里的提及一眼可辨。

范围严格自洽：**零新表、零既有 API shape 变更、零状态机改动**（恪守 CLAUDE.md「状态机神圣、向后兼容、通知收口唯一」三约定）。提及仅面向**人类用户**（Agent 由 autopilot 驱动、不入 `/users`），与既有「通知只发人类、不发 Agent」的语义天然一致。既有 `notify_mentions` 的 `mentioned` 通知类型、`NotificationType` 枚举、`notificationIcon` 映射均已存在，无需新增。

---

## 2. 技术设计（Technical Design）

### 2.1 架构与接缝

```
┌─────────────────────────── 前端（frontend/） ───────────────────────────┐
│  TicketDrawer.tsx                                                        │
│    └─ CommentComposer.tsx                                                │
│         └─ MentionTextarea.tsx   ← 新增：提及感知输入 + 下拉             │
│              ├─ useSWR<User[]>("/users", swrFetcher)  （与 AssigneePicker 同 key，去重）
│              ├─ activeMention(value, caret)  纯函数：算出当前 @token
│              └─ applyMention(...)            纯函数：插入 @username + 定位光标
│  FeedTimeline.tsx  ← 改：评论正文 @token 渲染为 chip（用共享 MENTION_RE）│
│  lib/constants.ts  ← 加：MENTION_RE 共享正则（与后端语义镜像）          │
└─────────────────────────────────────────────────────────────────────────┘
                                   │ POST /api/{entity}/{id}/comments  (既有，无改)
                                   ▼
┌─────────────────────────── 后端（backend/） ───────────────────────────┐
│  routes/comments.py:_create_comment                                     │
│    notifications.notify_comment(obj, entity, comment, actor)   （既有）  │
│    notifications.notify_mentions(comment, actor, ticket=obj)   ← 改：传 ticket
│  services/notifications.py                                               │
│    _MENTION_RE = (?<![A-Za-z0-9_])@([A-Za-z0-9_]+)   ← 改：加左边界      │
│    notify_mentions(comment, actor, ticket=None)      ← 改：富文案 + 兜底 │
└─────────────────────────────────────────────────────────────────────────┘
```

**关键设计原则**：前端补全的插入格式（`@username`）与后端解析正则（`@([A-Za-z0-9_]+)`）**逐字对齐**——补全只提供 `username` 匹配 `^[A-Za-z0-9_]+$` 的成员，绝不建议一个「补出来也解析不了」的提及。前后端边界语义同样镜像（左边界为「非单词字符」）。

### 2.2 前端：`MentionTextarea` 交互序列

```
用户在评论框键入字符 / 移动光标
        │
        ▼
onChange / onKeyUp / onClick → syncMention(value, caret)
        │
        ├─ activeMention 返回 null（光标不在 @token 内）→ 关闭下拉
        └─ 返回 {query, anchor} → 打开下拉，按 query 过滤 users（≤6 条），activeIndex=0
        │
        ▼
下拉打开时的 onKeyDown 拦截：
   【v2 修复·P2-2】首行防御：if (e.nativeEvent.isComposing) return;  // IME 组字态直接透传，绝不劫持中文候选
   ↓ / ↑        → 移动 activeIndex（环绕），preventDefault
   Enter / Tab  → 选中 candidates[activeIndex]，preventDefault + stopPropagation
   Esc          → 关闭下拉，preventDefault + stopPropagation（避免冒泡触发抽屉 Esc 关闭）
   其它键        → 透传给父级 onKeyDown（Cmd/Ctrl+Enter 发送不受影响）
        │
        ▼
选中 → applyMention：value = before(anchor) + "@" + username + " " + after(caret)
        onChange(value)；把光标定位到插入串末尾；关闭下拉；保持焦点
```

**光标回填**：因 `value` 受控，插入后需在下一次渲染后用 `textareaRef.current.setSelectionRange(pos, pos)` 回填光标。实现用一个 `pendingCaretRef`（number|null），在 `useEffect(() => {...}, [value])` 内消费一次并清空。

### 2.3 前端：纯函数（**【v2 修复·P1-1】下沉到 `frontend/lib/mentions.ts`**）

> v1 把这两个纯函数埋在 `MentionTextarea.tsx` 内并自述「便于就近单测」，但仓库无 JS 测试运行器（见 §评审记录核验），该说法无从兑现。v2 将其**下沉为独立纯模块** `frontend/lib/mentions.ts`（与 `constants.ts` 的共享正则同处 `lib/`，纯 TS、无 React 依赖、可被 `MentionTextarea` 复用，将来接入 runner 即可直接单测）。`MentionTextarea.tsx` 改为 `import { activeMention, applyMention } from "@/lib/mentions"`。逻辑与 v1 逐字一致：

```ts
// 从 caret 处向左吃 [A-Za-z0-9_]，若紧邻左侧是 '@' 且 '@' 左边界非单词字符 → 命中。
export function activeMention(value: string, caret: number): { query: string; anchor: number } | null {
  const WORD = /[A-Za-z0-9_]/;
  let i = caret;
  while (i > 0 && WORD.test(value[i - 1])) i--;
  if (i === 0 || value[i - 1] !== "@") return null;
  const at = i - 1;                                   // '@' 的下标
  if (at > 0 && WORD.test(value[at - 1])) return null; // 左边界必须非单词字符（镜像后端 lookbehind）
  return { query: value.slice(i, caret), anchor: at };
}

export function applyMention(value: string, anchor: number, caret: number, username: string) {
  const before = value.slice(0, anchor);
  const insert = `@${username} `;
  return { next: before + insert + value.slice(caret), nextCaret: (before + insert).length };
}
```

**候选过滤**（`query` 小写化）：
- `query === ""`（刚敲 `@`）：展示成员前若干条（去掉当前登录用户自己）；
- 否则：`username.toLowerCase().includes(q) || (display_name||"").toLowerCase().includes(q)`；
- **硬约束**：只保留 `/^[A-Za-z0-9_]+$/.test(u.username)` 的成员（不建议无法解析的提及）；排除 `useAuth().user`（自己 @ 自己无意义、后端也不自我通知）；
- 排序：`username` 或 `display_name`「以 q 开头」者优先；`limit = 6`。

### 2.4 后端：正则左边界 + 富文案

`services/notifications.py`：

```python
# @提及正则：左边界为「非单词字符 / 行首」，避免把 name@example.com 误判为提及 example；
# 用负向后顾而非 \s，兼容中文紧邻（请@member）。用户名字符集 [A-Za-z0-9_] 与 users.username 现况一致。
_MENTION_RE = re.compile(r"(?<![A-Za-z0-9_])@([A-Za-z0-9_]+)")


def notify_mentions(comment, actor, ticket=None):
    """解析评论 body 中的 @username，向存在的用户各发一条 mentioned 通知（去重、排除自己）。

    ticket 可选：提供时文案带工单标题 + 评论摘要（与 notify_comment 对齐）；缺省回退旧文案，
    保持函数独立可用（无调用方回归风险）。
    """
    names = set(_MENTION_RE.findall(comment.body or ""))
    if not names:
        return
    users = User.query.filter(User.username.in_(names)).all()
    if ticket is not None:
        title = _short(getattr(ticket, "title", "") or "")
        snippet = _short(comment.body, 30)
        message = f"{_label(comment.entity_type)}「{title}」中有人提到你：{snippet}"
    else:
        message = f"你在{_label(comment.entity_type)} #{comment.entity_id} 的评论中被提及"
    for u in users:
        notify(
            u.id, "mentioned",
            entity_type=comment.entity_type, entity_id=comment.entity_id, actor=actor,
            message=message,
        )
```

`routes/comments.py:_create_comment` 第 71 行改为：

```python
notifications.notify_mentions(comment, actor, ticket=obj)
```

**去重与不自我通知**：`names` 是 `set`，天然对重复 `@member @member` 去重；`notify()` 内既有的 `actor_type=="user" and actor_id==user_id` 分支保证作者 @ 自己不落库；偏好闸（`notification_prefs.is_enabled`）继续生效。**均为既有不变量，本方案不触碰。**

**【v2 修复·P1-2】跨类型通知的显式裁定**：`_create_comment` 先 `notify_comment` 再 `notify_mentions`，两者独立、`notify()` 只对**自己**去重、**不跨类型去重**。故当被 @ 的人**同时是** reporter / 人类 assignee / 历史评论人时，一条评论会让其**同时收到 `commented` + `mentioned` 两条通知**。本轮**有意接受**此行为，理由：`mentioned`（显式点名）与 `commented`（你参与的单有新评论）是**语义不同的两个信号**，点名是更强的召唤，短期内并存不构成错误，反而信息量更足；「同一收件人 `mentioned`↔`commented` 的去重合并」是更大的产品决策，按 §9 交棒 Iteration 5。为防止「留白」被误判为缺陷，§6.1 增回归用例 `test_mention_and_comment_coexist_for_participant` **把该行为锁成契约**（既定、且被测）。

### 2.5 前端：`FeedTimeline` 提及高亮

`lib/constants.ts` 新增共享正则（**不含左边界断言的全局版**，用于渲染切分；渲染层不需要精确到「能否解析」，只需把 `@token` 视觉标出）：

```ts
// 时间线渲染用：把评论正文里的 @token 标为 chip。与后端解析口径一致的字符集。
// 【v2·P2-1】带 /g，仅供 String.prototype.matchAll（无状态）使用；
// 禁止对其调用 .test()/.exec()——全局正则的 lastIndex 会跨调用残留、引发间歇性错配。
// 需要「单个 username 是否可解析」的判定请用新鲜字面量 /^[A-Za-z0-9_]+$/（见 §2.3 候选硬过滤）。
export const MENTION_RE = /@([A-Za-z0-9_]+)/g;
```

`FeedTimeline.tsx` 把第 115 行 `{item.body}` 改为调用就近 helper `renderBody(item.body)`：用 `String.prototype.matchAll(MENTION_RE)` 切分，命中段包成 `<span className="rounded bg-clay/10 px-1 font-medium text-clay-dark">@name</span>`，非命中段原样输出；保留外层 `whitespace-pre-wrap`。helper 返回 `ReactNode[]`，故置于 `.tsx`（`constants.ts` 仅存正则常量，避免把 JSX 放进 `.ts`）。

---

## 3. 文件 / 模块变更计划（File / Module Change Plan）

| # | 文件 | 动作 | 一句话意图 |
|---|------|------|-----------|
| 1 | `frontend/lib/mentions.ts` | **新增** | **【v2·P1-1】** 纯 TS 模块：`activeMention`/`applyMention` 光标数学纯函数（无 React 依赖，可复用、可单测）。 |
| 2 | `frontend/components/collab/MentionTextarea.tsx` | **新增** | 提及感知 textarea：`@` 触发成员下拉 + 键鼠导航 + 精确插入 `@username`；`import` 自 `@/lib/mentions`（不再内联纯函数）。 |
| 3 | `frontend/components/collab/CommentComposer.tsx` | 修改 | 用 `MentionTextarea` 替换裸 `<textarea>`；把 Cmd/Ctrl+Enter 发送逻辑改由 `onKeyDown` 透传（下拉打开时不误触发送）。 |
| 4 | `frontend/components/collab/FeedTimeline.tsx` | 修改 | 评论正文 `@token` 渲染为 clay chip（`renderBody` helper + 共享 `MENTION_RE`）。 |
| 5 | `frontend/lib/constants.ts` | 修改 | 新增导出 `MENTION_RE`（前端渲染切分用，与后端字符集镜像；仅供 `matchAll`，见 §2.5·P2-1）。 |
| 6 | `backend/services/notifications.py` | 修改 | `_MENTION_RE` 加左边界 `(?<![A-Za-z0-9_])`；`notify_mentions` 增 `ticket=None` 形参与富文案（带兜底）。 |
| 7 | `backend/routes/comments.py` | 修改 | `_create_comment` 调用改为 `notify_mentions(comment, actor, ticket=obj)`。 |
| 8 | `backend/tests/test_notifications.py` | 修改 | 新增 ≥5 条提及回归用例（含 P1-2 共存契约锁定，见 §6.1）。 |

**不改动**：`lib/types.ts`（复用 `User`）、`models/*`（零 schema 变更）、`workflow.py`（零状态机改动）、`useTicket.ts`（`addComment` 契约不变）、`NotificationType` 枚举 / `notificationIcon`（`mentioned` 已存在）。

---

## 4. 接口设计（Interface Design）

### 4.1 复用的 REST 接口（无新增、无改 shape）

- `GET /api/users` → `User[]`（`jwt_required`，任意登录用户可列；`AssigneePicker` 已在用）。补全下拉的数据源，SWR key `"/users"` 与 `AssigneePicker` 一致，**天然去重不额外发请求**。
- `POST /api/{requirements|bugs}/{id}/comments` → `201 Comment`（既有；请求体 `{ body }` 不变）。提及在此路径被解析与扇出。

### 4.2 组件契约：`MentionTextarea`

```ts
interface MentionTextareaProps {
  value: string;
  onChange: (v: string) => void;
  onKeyDown?: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void; // 下拉未消费按键时透传（Cmd/Ctrl+Enter 发送）
  placeholder?: string;
  rows?: number;
  disabled?: boolean;
  id?: string;
  "aria-label"?: string;
}
```

### 4.3 后端函数签名变更（向后兼容）

```python
notify_mentions(comment, actor, ticket=None)   # ticket 新增、可选、默认 None → 旧行为
```

唯一调用方 `routes/comments.py` 本轮同步更新为传 `ticket=obj`；其余无调用方（全仓 grep 确认）。

---

## 5. 数据模型（Data Model）

**无变更。** 复用：

- `User`（`username`/`display_name`/`avatar_color`）——补全下拉的展示与插入源；插入用 `username`，展示用 `display_name`。
- `Notification`（`type="mentioned"`，Phase-3 既有表）——提及扇出落库目标；`message VARCHAR(255)`，富文案经 `_short`/`_clip` 截断确保不溢出。

零新表 / 零列变更 / 零索引变更，符合 CLAUDE.md「Phases 2 & 3 只新增 `notifications` 一张表」的向后兼容基线。

---

## 6. 测试与验收标准（Testing & Acceptance）

### 6.1 后端 pytest（新增，追加到 `test_notifications.py`）

沿用 `conftest` 既有 fixtures（`client`/`auth`/`make_requirement`/`data`；`alice→member`、`bob→member2`）：

1. `test_mention_inside_email_not_triggered`：评论 `"联系 name@member.com 即可"`（`@member` 内嵌于邮箱域名右侧，左邻为 `e`）→ member **不**收 `mentioned`。守住左边界断言。
2. `test_mention_dedupes_repeated`：评论 `"@member @member 看下"` → member 的 `mentioned` 通知**恰好 1 条**（`set` 去重）。
3. `test_mention_nonexistent_user_no_notification`：评论 `"@nobody 在吗"` → 全库无 `mentioned` 通知产生，且请求 `201`（不因未知用户报错）。
4. `test_mention_resolves_by_username_not_display_name`：以某成员的 `display_name`（非 `username`）作 `@` 目标 → 不命中；以其 `username` → 命中。**锁死「补全必须插入 username」这一契约。**
5. `test_mention_message_includes_title`（**【v2·P1-1 起改为必测】** 原「可选」）：断言 member 收到的 `mentioned` 通知 `message` 含工单标题片段（验证富文案接线；富文案是本轮后端核心交付，必须有断言守护）。
6. `test_mention_and_comment_coexist_for_participant`（**【v2 新增·P1-2】**）：以 `make_requirement(assignee=("user", member_id))`（member 是人类 assignee ⇒ `commented` 收件人），由 pm 评论 `"@member 看下"` → member **同时**收到**恰好 1 条 `mentioned` + 恰好 1 条 `commented`**（两类各一、互不吞没）。锁死「co-recipient 双通知」为**有意契约**，防止后续误当 BUG「修掉」。

**回归**：既有 `test_mention_notifies_user`（`"cc @member 请看"`，`@` 左邻空格）必须**仍绿**——左边界断言不影响「空格/行首/中文后」的正常提及。

### 6.2 前端质量门（无前端单测框架，走 typecheck + build）

- `cd frontend && npm run typecheck` → 0 error（`lib/mentions.ts` 纯函数、`MentionTextarea` props、`renderBody` 的 `ReactNode[]` 均需类型正确）。
- `cd frontend && npm run build` → 成功（含 TicketDrawer 所在受影响页）。

### 6.2.1 【v2 修复·P1-1】纯函数边界矩阵（`lib/mentions.ts`，DoD 硬门）

全案最易出错的是**光标数学**，而仓库无 JS runner。故将 `activeMention`/`applyMention` 下沉为纯模块后，实现方**必须逐条核对**下表期望值（可用一次性 `node -e "..."`/临时 `.mjs` 就地验算，**不得**为此给仓库新增测试依赖；将来接入 runner 时本表即为用例来源）。任一条不符即视为未完成：

| 输入 | 期望 | 守护 |
|------|------|------|
| `activeMention("@", 1)` | `{query:"", anchor:0}` | 刚敲 `@` 触发（空 query） |
| `activeMention("cc @mem", 7)` | `{query:"mem", anchor:3}` | 正常提及（左邻空格） |
| `activeMention("请@mem", 5)` | `{query:"mem", anchor:1}` | CJK 紧邻仍触发（镜像后端左边界） |
| `activeMention("a@b", 3)` | `null` | 邮箱式「左邻拉丁词字符」→ 不触发 |
| `activeMention("name@member.com", 11)` | `null` | 邮箱域名右侧不误判 |
| `activeMention("hi", 2)` | `null` | 无 `@` → 关下拉 |
| `activeMention("@mem ", 5)` | `null` | 尾随空格后光标 → 不误重开（配合插入串带空格，R7） |
| `applyMention("cc @me", 3, 6, "member")` | `{next:"cc @member ", nextCaret:11}` | 精确插入 `@username␠` + 光标落末尾 |

> 说明：§6.3 冒烟覆盖「集成后的观感」，本表覆盖「纯逻辑的正确性」，二者互补——这是在无 runner 约束下对 P1-1 的最小充分补救。

### 6.3 手动冒烟（Definition of Done 级）

1. 打开任一工单抽屉 → 评论框键入 `@` → 弹出成员下拉；键入 `me` → 过滤到 `member`；↓/↑ 高亮移动、Enter 选中 → 文本变为 `@member `、光标在其后、下拉消失。
2. 提交该评论 → 被 @ 的成员（换账号）通知中心出现一条 `mentioned`，点击直达该工单。
3. 时间线里该评论的 `@member` 显示为高亮 chip。
4. 下拉打开时按 Esc → 仅关闭下拉、**抽屉不被关闭**；下拉关闭时按 Esc → 抽屉正常关闭（既有行为不回归）。
5. 评论含 `name@example.com` → 时间线可正常显示；提交后**不**产生对 `example` 的误提及。
6. Cmd/Ctrl+Enter：下拉关闭时正常发送；发送/清空/禁用逻辑与旧版一致。

### 6.4 验收判定

- 后端 `pytest -q` 全绿（既有 Iter3 基线 159 passed + 本轮 ≥4 新增，**无既有断言改动**）；
- 前端 `npm run typecheck` 0 error 且 `npm run build` 成功；
- §6.3 六项冒烟全过。

---

## 7. 风险与缓解（Risks & Mitigations）

| # | 风险 | 类型 | 缓解 |
|---|------|------|------|
| R1 | Esc 关下拉时冒泡触发抽屉 `window` 级 Escape → 连带关抽屉、丢失草稿 | 交互回归 | 下拉打开时 `onKeyDown` 对 Escape `preventDefault() + stopPropagation()`；React onKeyDown 的 `stopPropagation` 会终止事件冒泡至 `window`，阻断抽屉监听。§6.3-4 冒烟专项覆盖。 |
| R2 | 下拉展开被评论框底部/抽屉边缘裁切 | 布局 | 容器 `relative`，下拉**上开**（`absolute bottom-full mb-1`），紧贴输入框顶部；`max-h` + `overflow-y-auto` 兜底长列表。 |
| R3 | 补全出 `username` 含非 `[A-Za-z0-9_]` 字符（如 `dev.ops`），插入后端解析不了 → 假成功 | 结果错误 | 候选**硬过滤** `^[A-Za-z0-9_]+$`，从不建议无法解析的成员；手打异形 username 无法解析属**既有后端限制**，本轮不扩后端字符集（会破坏既有正则契约），记入本表交后续。 |
| R4 | 左边界断言过严，误伤中文紧邻提及（`请@member`） | 兼容性 | 用 `(?<![A-Za-z0-9_])` 而非 `(?<=\s)`：中文字符不在单词类中，`请@member` 仍命中；仅拦截**左邻为拉丁单词字符**的场景（邮箱）。§6.1-1 与既有 `test_mention_notifies_user` 双向守护。 |
| R5 | 改密/新增用户后 `/users` SWR 缓存陈旧、补全漏人 | 数据新鲜度 | SWR 默认 `revalidateOnFocus`；补全非强一致场景，抽屉打开即重验；与 `AssigneePicker` 同 key 共享，行为一致。 |
| R6 | 富文案改动破坏既有 `mentioned` 通知断言 | 回归 | 既有唯一提及用例只断言 `type=="mentioned"`，不校验 message；`ticket` 形参可选带兜底，`notify_mentions` 独立调用行为逐字不变。 |
| R7 | 受控 textarea 插入后光标错位（回到末尾/开头） | 交互 | `pendingCaretRef` + `useEffect([value])` 内 `setSelectionRange` 精确回填；插入串带尾随空格，`activeMention` 随即返回 null，下拉不误重开。 |
| R8 | `@` 高频输入压 `/users` 后端 | 性能 | `/users` SWR 全量拉一次并缓存（与 AssigneePicker 共享），过滤纯前端；下拉 `limit≤6`，无逐键请求。 |

---

## 8. 实施顺序与回滚（Implementation Order & Rollback）

**建议落地顺序**（每步可独立编译/测试，便于回滚）：

1. 后端 §2.4：改 `_MENTION_RE` + `notify_mentions(ticket=None)` + `comments.py` 传参 → 跑 `pytest -q` 确认既有全绿。
2. 后端 §6.1：补 ≥4 回归用例 → `pytest -q` 全绿。
3. 前端 §2.5：`constants.ts` 加 `MENTION_RE` + `FeedTimeline` 高亮 → `typecheck`。
4. 前端 §2.2/§2.3：新增 `MentionTextarea` → `typecheck`。
5. 前端 §3-2：`CommentComposer` 接入 `MentionTextarea` → `typecheck` + `build` + §6.3 冒烟。

**回滚边界**：前端 5 个改动互不耦合到后端；后端 1/2 步是纯增量（新形参可选 + 更严正则），单独回退任一步不破坏其余。全部改动零 schema 迁移，`git revert` 即可干净回退。

---

## 9. 后续迭代路线（本轮 Out of Scope，交棒 Iteration 5）

承接 `global-search/spec.md §10` 未尽项，按价值/风险续排：

1. **管理台 UI**（D8–D11）：Team 页「新增成员 / 改姓名邮箱 / 重置密码」（接 `POST /api/users`、全量 `PATCH /api/users/<id>`）、Agents 页「建/改 Agent」（接 `POST/PATCH /api/agents`）、项目管理页（接 `projects.py`）。
2. **LLM 运行时配置**（A4，谨慎）：坚持「仅存 provider/model/base_url + 密钥走 env/密钥库引用」，admin-only，明文密钥不落库。
3. **提及增强（可选）**：`@` 补全纳入 Agent（当前仅人类用户）；后端 `username` 字符集与提及正则联合放宽以支持 `.`/`-`（需同步扩正则契约与回归）；`mentioned` 与 `commented` 对同一收件人的去重合并。

---

## 评审结论（Review Verdict）

**结论：有条件通过（Approved with conditions）。**

方案**可行、完整、与既有约定一致、尺度得当**：选题准（把「言行不一的 @ 占位」由现成后端 `notify_mentions` 兜底做真）、恪守 CLAUDE.md 三约定（状态机神圣 / 向后兼容 / 通知收口唯一）、零新表 / 零 API shape 变更 / 零状态机改动 / 零新依赖，回滚边界清晰。逐条核验源码后，v1 的关键技术主张（React 18 下 `stopPropagation` 阻断抽屉 Escape、`tsconfig` 未开 `noUncheckedIndexedAccess` 故索引写法可 typecheck、`/users` SWR 同 key 去重、偏好闸不误伤 `mentioned`、富文案不破既有断言）**均成立**。

**无 P0。** 2 项 P1、2 项 P2（P2-1/P2-2）已**就地修复**并标 `【v2 修复/采纳】`：
- **P1-1**：纯函数下沉 `frontend/lib/mentions.ts` + §6.2.1 边界矩阵（8 条，已随评审验算通过）作 DoD 硬门 → 补齐「最高风险逻辑零自动化覆盖」。
- **P1-2**：显式裁定并接受「co-recipient 双通知」，以 `test_mention_and_comment_coexist_for_participant` 锁成契约 → 消除幸福路径行为留白。
- **P2-1**：`MENTION_RE` 仅供 `matchAll` 的用法约束写入注释。
- **P2-2**：键盘拦截入口加 IME `isComposing` 防御短路。

**放行条件（须在 Subtask #2 落地时满足，非阻断设计）：**
1. **（承 P1-1）** 实现严格遵循 §3 的 8 文件清单——纯函数**必须**在 `lib/mentions.ts`、`MentionTextarea.tsx` 仅 `import`；提交前逐条对齐 §6.2.1 矩阵，任一不符即返工。
2. **（承 P1-2）** `test_mention_and_comment_coexist_for_participant` 与 §6.1 其余 ≥5 用例须随代码同批加入并全绿；既有 `test_mention_notifies_user` 保持不改、仍绿。
3. **（承 P2-3，建议非强制）** `MentionTextarea` 下拉若成本可控，补 combobox a11y（`role="listbox"`/`option`、`aria-activedescendant`、`aria-expanded`）；本轮不做亦不影响 DoD。
4. 验收以 §6.4 为准：后端 `pytest -q` 全绿（Iter3 基线 159 + 本轮 ≥5 新增）、前端 `typecheck` 0 error + `build` 成功、§6.3 六项冒烟全过。

满足上述条件即可进入 Subtask #2 代码开发。

---

*—— 方案设计：资深工程师（Anthropic Eng）· Subtask #0 ·｜ 评审与修复（v2）：资深评审（Anthropic Eng）· Subtask #1 · Loop Iteration 4/5 · 特性 `mention-autocomplete`*
