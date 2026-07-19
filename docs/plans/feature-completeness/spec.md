# AragonTeam 主流程完备化与页面可用性收官 —「每个主要功能都能端到端跑通、每个页面在异常与权限下都能正确使用」（Spec）

- **文档版本**: **v2**（v1 由 Subtask #0 · Solution Architect 产出；本 **v2** 由 Subtask #1「方案评审与修复」完成——文首新增「## 评审记录」、文末新增「## 评审结论」，并就地修复全部 P0/P1，见文首评审表）
- **Feature slug**: `feature-completeness`
- **作者角色**: Solution Architect（Anthropic Engineering）
- **本轮需求（第 2 轮）**: 「继续完善所有主要功能，确保每个功能都不报错，客户端页面都能够正确使用。」
- **全局目标**: 「完成对应的开发，确保稳健可靠好用，顶级。」
- **基线**: 建立在已合入的 9 个里程碑之上（MVP → Phase-2 → Phase-3 → 真实 Agent 执行 → 账号自助中心 → 全局搜索 → @提及自动补全 → 管理台建改闭环 → **稳健化收官 `reliability-hardening`**，最新 commit `c8c8e46`）。**本轮不新增业务大功能、不新增数据库表、不新增前后端运行时依赖**，只做**面向缺陷的功能完备化 + 页面可用性收口**——把「主流程走一半就断（自主 AI 团队跑不完一张单）/ 默认列表顺序错乱 / 少数坏输入仍 500 / 看板与抽屉在后端出错时永久卡骨架 / 会话过期后全站失灵却不跳登录 / 无权成员看到点了必 403 的按钮」这些真实缺口逐一堵住。
- **技术栈（沿用，零新增依赖）**: Next.js 14 App Router + React 18 + TypeScript + Tailwind + @dnd-kit + SWR ｜ Flask 3 + SQLAlchemy 2 + SQLite + flask-jwt-extended + Flask-CORS ｜ 后端 LLM 层仅用标准库 `urllib`。
- **目标读者**: 下游开发工程师（须可据此逐行实现，无需再做架构决策）。
- **审计方法**: 本方案基于对现网代码（`c8c8e46`）的**两支只读缺陷审计（后端一支、前端一支）+ Solution Architect 一手逐文件核验**。所有条目均给出精确 `file:line` 与可复现步骤；审计明确排除了 `reliability-hardening` 已修复项，并已剔除若干经核验的假阳性（见 §8）。

---

## 评审记录（Review Notes · Subtask #1 · v2）

> 评审人：Senior Reviewer（Anthropic Engineering）。方法：对照现网代码 `c8c8e46` 逐节四维评审——**可行性**（本栈能否落地）/ **完备性**（边界、错误路径、发布面有无遗漏）/ **一致性**（是否违背 `CLAUDE.md` 与既有约定）/ **尺度**（是否过度或欠设计）。下列每条均已按 `file:line` 复核证实；**P0/P1 已在本 v2 文档正文就地修复**，P2 以说明/备注形式落地。总体判定见文末「## 评审结论」。

| # | 维度 | 严重度 | 位置 | 结论 | 处置 |
|---|---|---|---|---|---|
| R1 | 完备性 / 正确性 | **P1** | §2.2 helper · §4-⑥ · §6.1 | 交接调用 `notify_assignment` 实为**死代码**——该 helper 仅通知**人类 assignee**（`notifications.py:82` 对非 `user` assignee 直接 `return`），而交接后 assignee 恒为 qa-**agent**，故永不发通知；却与「reporter 收到 `assigned` 通知」这条 **P1 验收断言**（§6.1）**直接矛盾**，测试必挂。 | ✅ 已修：改用 `notify_claim(ticket, entity, qa)`（收件人 = reporter、type = `assigned`），并同步 §4-⑥ / §6.1 文案。 |
| R2 | 完备性 | **P1** | §2.2 接线 | 交接只挂在「成功 `advance_one` 之后」，仅覆盖**本轮被推进入** `testing` / `verifying` 的单。**存量**已停在该状态、却指派给非-qa（dev/generic）的单——含 **seed 演示单**「接入 dev-agent 自动认领需求」（恒 `testing` / dev-agent，`seed.py:68`）与任何被人工 `move` 的 dev 单——会在交接之前 `NoAgentAction → break`，**永久卡死**，本轮欲消灭的症状仍在。 | ✅ 已修：在 `except NoAgentAction` 分支内追加同一 `_maybe_handoff_to_qa`（helper 双 guard 保证 no-op 安全），并强化 §2.2 净效果说明。 |
| R3 | 可行性 / 一致性 | P2 | §2.4-C1 | 「`want_int` 已 import」对 `agents.py` **不成立**——`agents.py:13` 仅 import `json_body, want_str`；照 v1 落地 C1 会 `NameError`。（`requirements.py:33` 确有 `want_int`，说明 v1 把两文件混淆。） | ✅ 已修：C1 明确要求补 `agents.py` 的 import。 |
| R4 | 完备性 | P2 | §2.2 执行序 | 「单轮 `autorun-all` 即达 `reviewing` / `closed`」依赖 `dev.id < qa.id`（`Agent.id.asc()` 迭代序）。seed 保证之（dev 先建，`seed.py:48-52`），但 pm 运行时以任意序建 qa→dev 时单轮只到 `testing`，需再跑一轮。设计跨轮仍正确、验收已 hedge（「反复…或造齐后单次」），但依赖须显式声明。 | ✅ 已注：§2.2 执行序补显式依赖说明。 |
| R5 | 一致性 | P2 | §2.6-E2 | offline 门禁只加在 autopilot（autorun/tick）与 `agent-advance?run=all`；**单步** `agent-advance`（非 `run=all`，`requirements.py:434-450`）仍会把 offline agent 推进一步，与「autopilot 尊重 offline」略不齐。属 pm/admin 显式单步操作，可接受，但须显式界定范围。 | ✅ 已注：§2.6 补范围说明（单步为人工显式操作，有意不纳 offline 门禁）。 |
| R6 | 完备性 | P2 | §2.5 | `want_str` 空串回退 `default` 仅当调用方带 `default`（且 ∈ `choices`）时安全；若未来有 `choices=` 而无 `default=` 的调用方，空串仍回退成非法 `""`。现网四个枚举调用方（`priority`/`severity`/`kind`/`role`）均带 default（已核验），无活缺陷，但不变量是隐式的。 | ✅ 已注：§2.5 补「枚举调用方必须带 `default` ∈ `choices`」不变量。 |

**未发现 P0**：无成功路径契约破坏、无新表 / 新依赖、无绕过状态机（交接只改多态 assignee、不碰 `status`/`position`）、无安全回归；与 `CLAUDE.md`「状态机是圣域 / 向后兼容 / 不过度设计」三条红线一致。§8 三处 `TODO` 边界项（改 `kind` 在制单、源列 position 空洞、铃铛 list error 分支）裁定合理，本轮不纳入，予以确认。**四维小结**：可行性——除 R3 一处 import 疏漏外，全部修复已按现网签名核验可落地；完备性——R1/R2 两处补齐后自主闭环对「新流入」与「存量」两类单均闭合；一致性——三红线无违背；尺度——范围克制、P2 均为低风险机械改动，无过度设计。

---

## 0. 背景：为什么还需要这一轮

`reliability-hardening`（第 1 轮）把「坏输入 500→400、SWR 形状崩溃、主列表页永久卡骨架、无效 JWT 422→401、抽屉写按钮门禁」这一批**最刺眼的稳健性缺口**收口了。但「不崩」不等于「都能用、都跑得通」。对现网代码做的第二轮系统性审计（覆盖 12 张蓝图、`services/*`、17 个前端页面 + 30+ 组件）暴露出**两类此前未覆盖的真实缺陷**，正是本轮主题：

1. **主要功能「半通」——端到端流程走不完或默认视图给错数据。** 最典型的两处：(a) **自主 AI 团队（旗舰演示）跑不完一张单**——`agent_autopilot.AGENT_CLAIMABLE` 中 `"qa": []`，且无 dev→qa 交接，dev-agent 把需求推到 `testing` 后 `NoAgentAction`，qa-agent 永远认领不到 `testing`/`verifying` 单，`/agents/autorun-all` 永远停在 `testing`（需求）/`fixing`（BUG），README 宣称的「一键运行整支 AI 团队一轮」从不产出一张走到 `reviewing`/`closed` 的单（`agent_autopilot.py:30-34` vs `agent_runner.py:38-39,47-48`）。(b) **需求/BUG 默认列表顺序错乱**——`list_requirements`/`list_bugs` 用 `order_by(position.asc(), id.asc())`，而 `position` 是**按状态列各自从 0 起算**的列内序号，用它排一个跨状态的扁平列表会把各列交错（`new#0, assigned#0, done#0, new#1…`），既非创建序也非最近序（`requirements.py:162` / `bugs.py:64`）。
2. **页面在「异常 / 权限」边界下不可用。** (a) 两个**看板页**（`requirements/board`、`bugs/board`）只解构 `useBoard()` 的 `{board,isLoading}`、不读 `error`，后端出错时 `SkeletonBoard` 永久渲染——这正是第 1 轮在列表页修掉、却**漏掉看板页**的同类缺陷（`requirements/board/page.tsx:71` / `bugs/board/page.tsx:44`）。(b) `TicketDrawer` 从不读 `useTicket().error`，点开一张**已删/不存在**的工单（通知直达、深链 `?ticket=`）→ 抽屉永久停在骨架（`TicketDrawer.tsx:293-294`）。(c) **会话过期无自动登出**——`api.ts` 抛 `ApiError(401)` 但无任何全局拦截，`auth.tsx` 只在启动 `restore()` 时清 token，登录后 token 过期/密钥轮换 → 之后每个请求都 401 但 UI 仍认为「已登录」、不跳登录页，全站陷入「重试也失败」（`api.ts:83-87` / `auth.tsx:33-50` / `(app)/layout.tsx:14-25`）。(d) **列表页内联「指派」按钮未按角色门禁**——后端 `/assign` 限 pm/admin，但列表行的「指派」按钮对所有成员可见，member 点「确认指派」必得 403（`requirements/page.tsx:183-198` / `bugs/page.tsx:187-202`）。

围绕这两类核心缺陷，加上一批「少数坏输入仍 500」「offline Agent 被自主编排清成 idle」「铃铛角标读后漂移」「建单带指派部分失败误报」等次级缺口，本轮做一次**收敛式完备化**：**让每个主要功能端到端跑通、默认视图给对数据、页面在异常与权限下都优雅可用**。范围克制、零新表、零新依赖、成功路径契约不破坏。

---

## 1. Overview（概述）

**本轮主题是「完备」与「可用」：让每一个已存在的主要功能都能端到端跑通并给出正确数据，让每一个客户端页面在后端异常、会话过期、权限不足这三类边界下都能被正确使用。** 它不追加新业务能力，而是把前 9 轮堆叠出来的功能面「补齐最后一公里」——凡是「流程走一半就断 / 默认视图给错顺序 / 后端出错就永久卡骨架 / 会话过期就全站失灵 / 无权却给按钮」的地方，一处不留。

技术路线延续本仓库一贯的「稳健取向」与 `CLAUDE.md` 清洁代码红线：**状态机是圣域、错误显式传播、在边界处一次性校验、不散落防御、不过度设计**。后端侧三条主线：(1) 让**自主 AI 团队闭环真正闭合**——在自主编排层（`agent_autopilot.autorun`）为 dev→qa 增加一处**确定性交接**（把推进到 qa 泳道状态的单重指派给一个可用 qa-agent），使 `/autorun`、`/tick`、`/autorun-all` 都能把需求带到 `reviewing`（待人工审批）、把 BUG 带到 `closed`；**所有状态迁移仍且只经 `workflow.can_transition`，交接只改多态 assignee、不新增任何迁移边**；(2) 让**默认列表视图给对顺序**——扁平列表按「最近更新」全局排序（与 `/me/work` 一致），`position` 仅用于看板列内排序；(3) 把 `reliability-hardening` **漏网的少数坏输入**（`claim_count`/`email`/`description` 非串）也收敛为 400，`want_str` 的枚举空串旁路一并修正——把「每个功能都不报错」做到真正闭合。

前端侧两条主线：(1) **错误态完备化**——补齐第 1 轮漏掉的**看板页、抽屉、团队页**的 `error`/空态分支，消灭「永久卡骨架/空表误读」；(2) **会话与权限的可用性收口**——新增**全局 401 自动登出**（`api.ts` 在 401 时清 token 并广播 `aragon:unauthorized`，`AuthProvider` 订阅后清态 → 外壳跳登录），把**列表页内联「指派」与看板「转 BUG」按角色门禁**（与后端权威一致，收敛「可见即可用」）。其余为一批低风险、机械化的就地加固（铃铛角标同步、指派弹窗防重复提交、建单部分失败精确反馈、抽屉连改级别的假并发冲突）。

**关键不变量（下游必须保持，任何实现都不得违反）**：

1. **状态机仍是圣域**：所有工单状态变更仍且只经 `services/workflow.py::can_transition` 裁决（见 `CLAUDE.md`「State machine is sacred」）。本轮 **dev→qa 交接只改 `assignee_type/assignee_id`（多态指派），不新增、不修改任何迁移边**；推进仍走 `agent_runner.advance_one → can_transition`。
2. **向后兼容**：不新增数据库表（延续「唯一新表是 Phase-3 `notifications`」）、不新增前后端运行时依赖、不改动任何**成功路径**的请求/响应 shape。唯一对外可见的行为变化是**列表默认排序更合理**（§4-①，不改响应 shape）与**两处坏输入 500→400**（§4-②）——都不破坏任何既有正常用法。
3. **不过度设计**：只堵审计发现的真实缺口，不借机重构。新增代码集中在「一处 qa 交接 helper + 一条前端 401 拦截 + 若干处就地小改」；其余均为增量。

---

## 2. Technical Design（技术设计）

### 2.1 架构增量（Delta）

```
后端 backend/
  ＋ services/agent_autopilot.py  ← 改：autorun 每步推进后调用 _maybe_handoff_to_qa()（dev→qa 交接，闭合自主闭环）
  ＋ routes/requirements.py       ← 改：list 排序改「最近更新」全局序；create/patch 的 description 走 want_str（防 500）
  ＋ routes/bugs.py               ← 改：同上（list 排序 + description）
  ＋ routes/agents.py             ← 改：claim_count 走 want_int（防 int("x") 500）；autopilot 尊重 offline；run=all 复用 _run_with_lock/busy 门禁
  ＋ routes/auth.py               ← 改：register 的 email 走 want_str（防非串 email 500）
  ＋ routes/users.py              ← 改：create/patch 的 email 走 want_str（防非串 email 500）
  ＋ services/validation.py       ← 改：want_str 枚举字段空串回退 default（不再落库非法 ""）
  （无新增文件、无新增依赖、无新增表）

前端 frontend/
  ＋ lib/api.ts                   ← 改：401（非 /auth/ 路径）→ 清 token + window 派发 aragon:unauthorized，随后照常抛 ApiError
  ＋ lib/auth.tsx                 ← 改：AuthProvider 订阅 aragon:unauthorized → setToken(null)+setUser(null)（触发外壳跳登录）
  ＋ app/(app)/requirements/board/page.tsx ← 改：读 useBoard().error → ErrorState；canConvert 门禁 onConvert
  ＋ app/(app)/bugs/board/page.tsx         ← 改：读 useBoard().error → ErrorState
  ＋ components/TicketDrawer.tsx  ← 改：读 useTicket().error → 抽屉内错误态（可关闭），不再永久骨架
  ＋ app/(app)/requirements/page.tsx · bugs/page.tsx ← 改：内联「指派」按 canAssign 门禁；指派弹窗防重复提交
  ＋ app/(app)/team/page.tsx      ← 改：补 loading 骨架 + error 态（空表不再误读为「无成员」）
  ＋ app/(app)/notifications/page.tsx ← 改：读/已读后一并 mutate 铃铛的 unread-count 与列表 key
  ＋ components/requirements/RequirementForm.tsx · bugs/BugForm.tsx ← 改：create 与 assign 分别处理结果（部分失败精确反馈 + 仍刷新）
  ＋ hooks/useTicket.ts           ← 改：patch 成功后以返回体的新 updated_at 落缓存，避免连改级别触发假 409
  ＋ app/(app)/dashboard/page.tsx ← 改：「本周活动数」卡改为非链接（去死链）
```

**无新增数据库表、无新增第三方依赖。** 所有后端错误分支仍走 `errors.py` 的统一 JSON 契约。

### 2.2 后端 A：自主 AI 团队闭环真正闭合（dev→qa 交接 · 核心 P1）

**问题**（`agent_autopilot.py:30-34` / `agent_runner.py:30-51`）：`AGENT_CLAIMABLE = {"dev": [...], "generic": [...], "qa": []}`，`_claim_from_lane` 只认领 `assignee_id IS NULL` 的单；而 `AGENT_FORWARD` 里 qa 的两条前进边（`("requirement","qa","testing")→reviewing`、`("bug","qa","verifying")→closed`）作用的单**恒已指派给推进它到此的 dev-agent**。结果：dev-agent 把需求推到 `testing` 后无预置动作（`NoAgentAction`），qa-agent 又永远认领不到已指派单——`/autorun-all` 永远停在 `testing`/`verifying` 之前，**旗舰「运行 AI 团队」从不产出一张端到端完成的单**。

**修复**：在**自主编排层**（`agent_autopilot.autorun` 的每步成功推进之后）增加一处**确定性 dev→qa 交接**——若该单被推进到了 qa 泳道状态，且当前 assignee 不是 qa-agent，则把它**重指派给一个可用 qa-agent**（仅改多态 assignee，**不做任何状态迁移**，状态已由 `advance_one → can_transition` 合法推进到位）。qa-agent 在**同一轮或下一轮** autorun 中即可认领并推进（它现已在自己名下的 ticket 列表里）。无 qa-agent 时优雅 no-op（保持既有行为，逐字节兼容）。

```python
# services/agent_autopilot.py 顶部常量区新增：
from models.agent import Agent
# 推进到该「(entity)->status」即进入 qa 职责区，需交接给 qa-agent 继续。
_QA_HANDOFF_STATUS = {"requirement": "testing", "bug": "verifying"}


def _maybe_handoff_to_qa(entity, ticket):
    """dev/generic 把单推进到 qa 泳道状态后，重指派给一个可用 qa-agent（**不 commit、不改状态**）。

    只改多态 assignee（assignee_type='agent' + assignee_id=qa.id）——状态迁移已由 advance_one
    合法完成，本函数**绝不**触碰 status/position（不绕过状态机）。无可用 qa-agent → no-op。
    返回被交接到的 qa-agent 或 None。
    """
    if ticket.status != _QA_HANDOFF_STATUS.get(entity):
        return None
    # 已是 qa-agent 名下 → 无需交接。
    if ticket.assignee_type == "agent" and ticket.assignee_id is not None:
        cur = db.session.get(Agent, ticket.assignee_id)
        if cur is not None and cur.kind == "qa":
            return None
    # 取一个非 offline 的 qa-agent（优先 idle；busy 也可，下一轮会处理）。
    qa = Agent.query.filter_by(kind="qa").filter(Agent.status != "offline")\
        .order_by(Agent.id.asc()).first()
    if qa is None:
        return None
    ticket.assignee_type = "agent"
    ticket.assignee_id = qa.id
    Activity.log(
        entity, ticket.id, "assigned", actor=("agent", qa.id),
        from_status=ticket.status, to_status=ticket.status,
        message=f"{qa.name} 接手{_label(entity)}「{ticket.title}」进入测试/验证",
    )
    # 【评审 R1】通知源单 reporter（人类）qa 已接手：复用 notify_claim（收件人=reporter、
    # type="assigned"）。**绝不**用 notify_assignment——它仅通知**人类 assignee**，而此刻
    # assignee 已是 qa-agent（Agent），会在 notifications.py:82 直接 return、静默不发，
    # 使「reporter 收到交接通知」的验收断言（§6.1）落空。reporter 缺省（None）→ notify 自跳过。
    notifications.notify_claim(ticket, entity, qa)
    return qa
```

**接线（两处，覆盖「本轮推进入泳道」与「存量已停在泳道」两类单 —— 评审 R2 补齐第二处）**：

*(a) 每步成功推进之后*（`autorun` while 循环内，紧随 `advance` 追加与 `notify_advance` 之后、`if not run_all: break` 之前）——交接 dev/generic 本轮**刚推进入** `testing`/`verifying` 的单：

```python
                # —— dev→qa 交接（闭合自主闭环）；交接只改 assignee，随本步事务一并提交 ——
                handed = _maybe_handoff_to_qa(entity, ticket)
                if handed is not None:
                    db.session.commit()
                    break   # 本 agent 不再推进此单（已易主），交由 qa-agent 下一轮/本轮处理
```

*(b) `except NoAgentAction` 分支内*（`autorun` while 循环现有的 `except agent_runner.NoAgentAction:` 处，`break` 之前）——交接**存量**已停在 qa 泳道状态、却指派给非-qa（dev/generic）且无预置动作的单（**seed 演示单**「接入 dev-agent 自动认领需求」恒 `testing`/dev-agent；或被人工 `move` 到 `testing` 的 dev 单）。若不在此补一处，这些单会 `NoAgentAction → break` 于交接之前、**永久卡死**，正是本轮要消灭的症状：

```python
                except agent_runner.NoAgentAction:
                    # 【评审 R2】存量卡在 qa 泳道状态的非-qa 单也要交接，否则永远走不完。
                    handed = _maybe_handoff_to_qa(entity, ticket)
                    if handed is not None:
                        db.session.commit()
                        break   # 已易主，交 qa-agent 接力（本轮后续 / 下一轮）
                    if steps_this == 0:
                        skipped.append({"entity": entity, "id": ticket.id, "reason": "no-action"})
                    break
```

（`_maybe_handoff_to_qa` 内部以 `ticket.status != _QA_HANDOFF_STATUS.get(entity)` 与「已是 qa 名下」双重 guard，对「非泳道状态 / 已 qa」单严格 `return None` → no-op，故此分支对既有 `skipped(reason="no-action")` 语义**只增不减**：仅当命中泳道且有可用 qa 时才转为交接，否则原样记 skipped。）

**执行序保证**（`autorun-all` → 各 agent 顺序 `tick`，按 `Agent.id.asc()`；seed 中 dev-agent 先于 qa-agent，`seed.py:48-52`）：dev-agent 先跑，把需求推到 `testing` 并交接给 qa-agent（存量 `testing` 单经分支 *(b)* 交接）；随后 qa-agent 的 `tick→autorun` 扫描其名下工单，命中该 `testing` 单并推进 `testing→reviewing`（BUG 同理 `verifying→closed`）。**净效果**：`/autorun-all` 一次即可把（新流入 + 存量）需求带到 `reviewing`（`reviewing→done` 属人工审批，正确地停在这里）、把 BUG 带到 `closed`。**单 agent 的 `/autorun`/`/tick`** 也会正确交接（qa-agent 在下一次触发时接力），行为一致且确定。

> **实现约束**：
> - `_maybe_handoff_to_qa` 交接后 `break`（不在本 agent 继续推进已易主的单），避免同一步内 dev 又对 qa 的单发起推进；`MAX_AUTOPILOT_STEPS` 全局兜底不变。交接**不**改变 `advance_one` 契约（其本体不动）。
> - **【评审 R4】单轮 `autorun-all` 达终点依赖 `dev.id < qa.id`**（迭代序 `Agent.id.asc()`；seed 满足）。若运营侧以 qa 先于 dev 的顺序建 Agent，则单轮只把新单推到 `testing`/`verifying`，**需第二轮** `autorun-all` 才由 qa 接力到 `reviewing`/`closed`——跨轮仍确定收敛。验收（§6.1）据此写为「反复 `autorun-all`，或造齐 dev+qa（dev 先建）后单次」，两种写法均成立。

### 2.3 后端 B：默认列表视图给对顺序（P1）

**问题**（`requirements.py:162` / `bugs.py:64`）：`q.order_by(<Model>.position.asc(), <Model>.id.asc())`。`position` 由 `_next_position` **按状态列各自从 0 起算**，扁平（跨状态）列表按它排序会交错各列、且随数据增长两张不同列的单常共享同一 `position`——默认列表页顺序既非创建序也非最近序，观感混乱。

**修复**：扁平列表改为**全局最近更新序**，与 `/me/work` 的 `_assigned/_reported`（`me.py:48-54` 用 `updated_at.desc(), id.desc()`）保持一致：

```python
# routes/requirements.py list_requirements：
q = q.order_by(Requirement.updated_at.desc(), Requirement.id.desc())
# routes/bugs.py list_bugs：
q = q.order_by(Bug.updated_at.desc(), Bug.id.desc())
```

`position` 仅继续服务**看板列内排序**（`board.py` 分列分组后各自按 position，无需改动）。**这是有意的行为变化**（列表不是看板，列内序号对扁平列表无意义），响应 shape 不变。**下游须同步核对** `tests/test_requirements.py`/`test_bugs.py`/`test_search.py` 中任何对列表**顺序**的断言（多数断言「某单是否出现 / 数量」，不受影响；若有硬编码首元素 id 的断言，改为按新序或按集合断言）。

### 2.4 后端 C：`reliability-hardening` 漏网的少数坏输入 500→400（P1，直击「每个功能都不报错」）

第 1 轮宣称「坏输入 500→400 全覆盖」，但审计发现三处字段仍未过 `want_*`，坏类型会 500：

- **C1 · `claim_count` 非整 → 500**（`agents.py:168` `claim_count = data.get("claim_count", 1)` → `agent_autopilot.py:148` `int(claim_count or 0)`；传 `"x"` → `ValueError` → 500）。**修复**：`agents.py agent_tick` 内改为
  ```python
  claim_count = want_int(data, "claim_count", default=1, minimum=0, maximum=20)
  ```
  **【评审 R3】** `agents.py:13` 当前只 import 了 `json_body, want_str`，须先把该行改为 `from services.validation import json_body, want_str, want_int`（否则 `NameError`；`requirements.py` 已有 `want_int`，勿与之混淆）。非整即 400；上限 20 防滥用。`agent_autopilot.tick(claim_count=...)` 收到的恒为 int，内部 `int(claim_count or 0)` 可保留（幂等）。
- **C2 · 非串 `email` → 500 at commit**（`auth.py:63` / `users.py:30,68` 均 `email = data.get("email")`；传 `{"email":{"x":1}}` 绑到 `String` 列 → commit 触 `InterfaceError` → 500）。**修复**：三处统一改为
  ```python
  email = want_str(data, "email", required=False) or None   # 缺省/空 → None；非串 → 400
  ```
  （`patch_user` 侧改为 `if "email" in data: user.email = want_str(data, "email", required=False) or None`）。**不**新增格式校验（保持 `register`/`users` 既有宽松语义；格式校验仍只在 `me.py` 自助改资料处，见 §8 决策）。
- **C3 · 非串 `description` → 500 at commit**（`requirements.py:185` create `description=data.get("description")`、`:229` patch `req.description = data["description"]`；`bugs.py` 对应处；传 `{"description":{"x":1}}` 绑到 `Text` 列 → commit 触 500）。**修复**：create 处
  ```python
  description = want_str(data, "description", required=False, strip=False) or None
  ```
  patch 处 `if "description" in data: <model>.description = want_str(data, "description", required=False, strip=False) or None`。**`strip=False`** 保留描述的换行/缩进格式（描述可为多行工作说明）；非串即 400。

### 2.5 后端 D：`want_str` 枚举字段空串旁路（P2）

**问题**（`validation.py:64`）：`if choices is not None and v and v not in set(choices)`——`and v` 短路使**空串**跳过枚举校验，且因 key 存在（`v is None` 为假）不落 `default` → `priority:""`/`severity:""`/`kind:""`/`role:""` 被落库，前端 badge/label 映射查不到键。**修复**：枚举字段的空串回退到 `default`（枚举字段调用方恒带 default）：

```python
    if choices is not None and not v:
        # 有枚举 + 归一后为空 → 回退 default（不落库非法空串；required=True 的空串已在上面 raise）
        return default
    if choices is not None and v not in set(choices):
        raise ValidationError(f"{key} is invalid", field=key,
                              expected=f"one of {sorted(set(choices))}")
```

（替换原第 64-66 行；`required=True` 的空串在第 60-61 行已 raise，故到此的空串必为非必填，回退 default 安全。）

> **【评审 R6】不变量（须写入 `want_str` docstring 并在评审清单核对）**：**凡传 `choices=` 的调用方，必须同时传 `default`（且 `default ∈ choices`）**。本回退把「空串」映射到 `default`——若某调用方带 `choices=` 却省略 `default`（此时 `default=""`），空串仍回退成非法 `""`，绕过枚举。现网四个枚举调用方（`priority`→`medium`/`severity`→`major`/`kind`→`generic`/`role`→`member`）均满足此不变量（已逐一核验），故无活缺陷；此处显式声明以防未来新增调用方复现该洞。

### 2.6 后端 E：Agent 软锁 / offline 语义收口（P2）

- **E1 · 自主编排尊重 `offline`，且 finally 恢复原状态**（`agents.py:19-28` `_run_with_lock`、门禁 `:113,:147-148,:164-165`）。现状：`_run_with_lock` 硬编码 `finally: agent.status = "idle"`，门禁只挡 `busy`——一个被 pm/admin 置 `offline` 的 Agent 仍会被 `/autorun` 跑起来、且跑完被清成 `idle`（丢失 offline）。**修复**：
  - `autorun`/`tick` 入口门禁在 `busy` 之外加 `offline`：`if agent.status in ("busy", "offline"): 409 {"error": "agent is busy or offline"}`；`autorun-all` 循环内 `if agent.status in ("busy", "offline"): skip(reason=agent.status); continue`。
  - `_run_with_lock` 记录并恢复**原状态**：`prev = agent.status; agent.status = "busy"; ... finally: agent.status = prev`（此时 prev 恒为 idle——offline/busy 已被门禁挡在外——但显式恢复更正确、防未来回归）。
- **E2 · `agent-advance?run=all` 补 busy 门禁并统一软锁语义**（`requirements.py:453-484` `_agent_run_all`，`:459` 无前置检查即置 busy；经 `do_agent_advance:431-432` 到达）。现状与 `/autorun`、`/tick` 不一致：per-ticket 的 `run=all` 从不检查软锁，盲目置 busy、finally 归 idle，并发下会提前释放另一条 run 的锁。**修复**：在 `do_agent_advance` 进入 `_agent_run_all` 前加 `if agent.status in ("busy", "offline"): return 409`；`_agent_run_all` 内改用与 `_run_with_lock` 相同的「记录 prev → busy → finally 恢复 prev」语义（可直接复用 `_run_with_lock`，把循环体作为 `fn` 传入，集中软锁）。

> **【评审 R5】offline 门禁范围（有意界定）**：本轮 offline 门禁覆盖**自主编排**（`/autorun`、`/tick`、`/autorun-all`）与 **`agent-advance?run=all`**（软锁窗口存在处）。**单步** `agent-advance`（非 `run=all`，`requirements.py:434-450`）为 pm/admin 对单张工单的**显式手动推进**、无软锁窗口，**有意不纳入 offline 门禁**——管理员对某张单点一步推进的语义应即时生效，与「autopilot 不应自动跑 offline agent」正交。如后续产品决定「offline 即全面停用」，再在单步入口补同一门禁即可（非本轮范围）。

> **说明**：`reliability-hardening` §R1 已就「SQLite 写锁争用致并发 500」诚实标注为 dev-only 已接受风险（生产 Postgres 行级锁化解）。E2 修的是**软锁语义不一致**（可复现、非并发依赖），与该风险正交。

### 2.7 前端 A：错误态完备化（消灭永久卡骨架 / 空表误读 · P1）

- **A1 · 两个看板页接 `useBoard().error`**（`requirements/board/page.tsx:19,71` / `bugs/board/page.tsx:14,44`；`useBoard` 已返回 `error`，见 `useBoard.ts:96`）。改为 `const { board, error, isLoading, move, mutate } = useBoard(...)`，主区渲染：`error && !board` → `<ErrorState message="无法加载看板" onRetry={() => mutate()} />`；否则维持 `isLoading || !board ? <SkeletonBoard/>`。机械改动，逐页一处。
- **A2 · `TicketDrawer` 接 `useTicket().error`**（`TicketDrawer.tsx:53-56,293-294`；`useTicket` 已返回 `error`，见 `useTicket.ts:24-28,93`）。解构 `error: ticketError`；把 `{!ticket ? <SkeletonDrawer/> : (...)}` 改为三态：`ticketError && !ticket` → 抽屉内错误面板（一句「无法加载该工单（可能已被删除）」+ 现有右上「关闭」按钮已在 header 中可用，无需额外关闭件；可选加一个「关闭」按钮）；`!ticket`（加载中）→ `<SkeletonDrawer/>`；否则正常。**根除**深链 `?ticket=<已删 id>` / 过期通知点击导致的永久骨架抽屉。
- **A3 · 团队页补加载/错误态**（`team/page.tsx:16`）。现状 `const { data: users, mutate } = useSWR<User[]>("/users", swrFetcher)` 无 `error`、无骨架——失败时渲染空表（误读为「无成员」）。改为 `const { data: users, error, isLoading, mutate } = useSWR(...)`：`error && !users` → `<ErrorState message="无法加载团队成员" onRetry={() => mutate()} />`；`!users` → `<SkeletonRows rows={5} />`（复用既有骨架）；否则表格。

### 2.8 前端 B：会话过期全局 401 自动登出（P1）

**问题**（`api.ts:83-87` / `auth.tsx:33-50` / `(app)/layout.tsx:14-25`）：无全局 401 拦截；登录后 token 过期/密钥轮换 → 每请求 401 但 `user` 仍真、外壳不复检，全站「重试也失败」却不跳登录。

**修复**（复用既有 `CustomEvent` 事件总线模式，`api.ts` 不 import `auth`，无环依赖）：

1. `lib/api.ts` 的 `request()` 与 `getWithHeaders()`，在 `if (!res.ok)` 分支内、抛 `ApiError` 之前，插入：
   ```ts
   // 会话过期/失效的全局信号：清 token 并广播，由 AuthProvider 落地为登出+跳登录。
   // 排除 /auth/ 路径——登录接口的 401（凭据错误）不是「会话过期」，不应触发登出重定向。
   if (res.status === 401 && !path.startsWith("/auth/") && typeof window !== "undefined") {
     setToken(null);
     window.dispatchEvent(new CustomEvent("aragon:unauthorized"));
   }
   ```
   （随后照常 `throw new ApiError(...)`，调用方的 catch 逻辑不变。）
2. `lib/auth.tsx` 的 `AuthProvider` 增一个 effect 订阅：
   ```ts
   useEffect(() => {
     function onUnauth() { setToken(null); setUser(null); }
     window.addEventListener("aragon:unauthorized", onUnauth);
     return () => window.removeEventListener("aragon:unauthorized", onUnauth);
   }, []);
   ```
   `setUser(null)` 触发 `(app)/layout.tsx` 既有 effect（`!loading && !user → router.replace("/login")`）自动跳登录。**净效果**：token 一旦失效，用户被干净地送回登录页，而非卡在失效 UI。

### 2.9 前端 C：权限门禁补全（无权不给必 403 的按钮 · P1）

- **C1 · 列表页内联「指派」按 canAssign 门禁**（`requirements/page.tsx:183-198` / `bugs/page.tsx:187-202`；两页已有 `canCreate = role∈{admin,pm}`，`/assign` 后端亦限 pm/admin）。复用同一判据：仅当 `canCreate`（即 `canAssign`）时渲染行内「指派」`<Button>`（无权成员不再看到点了必 403 的按钮）；指派 `<Modal>` 亦随之无从触发。**后端仍是权威，前端仅收敛「可见即可用」。**
- **C2 · 看板「转 BUG」按角色门禁**（`requirements/board/page.tsx`；`KanbanCard` 的「转 BUG」仅按状态 `testing/reviewing` 门禁、未按角色，而 `convert-to-bug` 后端限 pm/admin）。在需求看板页用 `useAuth()` 计算 `canConvert = role∈{admin,pm}`，把传给 `KanbanBoard` 的 `onConvert` 改为 `onConvert={canConvert ? onConvert : undefined}`（`KanbanCard` 已在无 `onConvert` 时不渲染该按钮）。member 不再看到必 403 的「转 BUG」。

### 2.10 前端 D：一批交互正确性缺口（P2）

- **D1 · 铃铛角标读后同步**（`notifications/page.tsx:30-56` + `useNotifications.ts:13-22`）。整页读单/`read-all` 后只 `mutate` 自身 key `/notifications?limit=100`，铃铛用的两个 key（`/notifications/unread-count`、`/notifications?limit=15`）不刷新 → 角标滞留至多 ~20s。**修复**：页面用 `useSWRConfig().mutate` 在 `openItem`/`readAll` 后一并 `mutate("/notifications/unread-count")`（并可 `mutate("/notifications?limit=15")`），即时同步铃铛。
- **D2 · 指派弹窗防重复提交**（`requirements/page.tsx:82-96,236` / `bugs/page.tsx:82-96,237`）。`doAssign` 无 `submitting` 守卫、「确认指派」按钮不禁用 → 慢网双击触发两次 `PATCH /assign`。**修复**：加 `const [assigning, setAssigning] = useState(false)`，`doAssign` 首尾 `setAssigning(true/false)`，footer 按钮 `disabled={assigning}`（与建单表单一致）。
- **D3 · 建单带指派部分失败精确反馈**（`RequirementForm.tsx:44-59` / `BugForm.tsx:44-58`）。现状 `POST /:entity` 成功但随后 `PATCH /:id/assign` 失败（如所选 assignee 被删 → 404）时，单一 catch 报「创建失败」，但单**已创建**（未指派、`new`），`onCreated` 不触发（列表不刷新、弹窗不关）——用户被误导且留下一张孤单。**修复**：把 create 与 assign 拆为两个结果——create 成功即视为成功；assign 失败时**仍调用 `onCreated(created)`**（刷新列表 + 关闭弹窗）并 `toast.info("已创建，但指派失败：<原因>")`，而非笼统「创建失败」。
- **D4 · 抽屉连改级别不触发假并发冲突**（`useTicket.ts:68-82` + `TicketDrawer.tsx:202-210,324-333`）。`patch` 携 `expected_updated_at = ticket.updated_at`；连续改优先级/严重度时，第二次 PATCH 若在 `mutateTicket()` 回来前发出，携的是**旧** `updated_at` → 后端比对已前进的 `updated_at` → 409（无 allowed）→ `handleWriteError` 误报「该工单已被他人更新」（实为用户自己的上一次编辑）。**修复**：`useTicket.patch` 成功后**用 PATCH 返回体的新 ticket 落缓存**（`mutateTicket(updated, { revalidate: false })`，`api.patch` 已返回最新 ticket 含新 `updated_at`），使下一次乐观并发写携带新鲜时间戳；连续自我编辑不再假冲突。
- **D5 · 仪表盘「本周活动数」去死链**（`dashboard/page.tsx:54`）。该卡 `href:"/dashboard"` 被包进 `<Link>`（看似可点、实为原地跳转）。**修复**：把四张卡渲染区分为「可导航（前三张，保留 `<Link>`）」与「纯展示（本周活动数）」——本周活动数改渲染为普通 `<div>`（同视觉、无 `href`），或指向有意义目标（本轮取非链接 `<div>`，最小改动）。

---

## 3. File / Module Change Plan（文件变更计划）

> 图例：**［改］**=就地修改（增量，不破坏成功路径契约）。本轮**无新建文件**。优先级 **P1**=核心必做；**P2**=强烈建议/时间允许则做。

### 3.1 Backend

| 文件 | 变更 | 优先级 | 意图（一句话）|
|---|---|---|---|
| `backend/services/agent_autopilot.py` | ［改］ | P1 | 新增 `_maybe_handoff_to_qa()` 并在 `autorun` 每步后接线：dev→qa 交接，闭合自主 AI 团队闭环（只改 assignee，不碰状态机）|
| `backend/routes/requirements.py` | ［改］ | P1 | list 排序改 `updated_at.desc(),id.desc()`（默认视图给对序）；create/patch `description` 走 `want_str(strip=False)`（防 500）|
| `backend/routes/bugs.py` | ［改］ | P1 | 同需求侧（list 排序 + `description`）|
| `backend/routes/agents.py` | ［改］ | P1 | `claim_count` 走 `want_int`（防 `int("x")` 500）；autopilot 尊重 `offline`；`agent-advance?run=all` 补 busy/offline 门禁 + 统一软锁（§2.6）|
| `backend/routes/auth.py` | ［改］ | P1 | register `email` 走 `want_str`（防非串 500）|
| `backend/routes/users.py` | ［改］ | P1 | create/patch `email` 走 `want_str`（防非串 500）|
| `backend/services/validation.py` | ［改］ | P2 | `want_str` 枚举字段空串回退 `default`（不落库非法 `""`）|

### 3.2 Backend 测试（`backend/tests/`）

| 文件 | 变更 | 优先级 | 意图 |
|---|---|---|---|
| `tests/test_agent_autopilot.py` | ［改/增］ | P1 | `autorun-all?run=all` 后：需求可达 `reviewing`、BUG 可达 `closed`（dev→qa 交接生效）；无 qa-agent 时优雅停在 `testing`/`verifying`（no-op 回归）；offline agent 被 `/autorun` 拒（409）且状态不被清成 idle |
| `tests/test_requirements.py` · `test_bugs.py` | ［改］ | P1 | list 默认按 `updated_at desc` 返回（新序断言）；`description={"x":1}` → 400（非 500）；既有正路保持绿 |
| `tests/test_search.py` | ［改］ | P2 | 核对/更新任何依赖旧 `position` 排序的断言，改为按集合/新序断言 |
| `tests/test_agent_autopilot.py`（tick）· `test_agents`（若有） | ［增］ | P1 | `POST /agents/:id/tick {"claim_count":"x"}` → 400（非 500）|
| `tests/test_auth.py` · `test_settings.py`/`test_admin_console.py` | ［增］ | P1 | register/create/patch user `email={"x":1}` → 400（非 500）|
| `tests/test_validation.py` | ［增］ | P2 | `priority:""`/`severity:""`/`kind:""`/`role:""` → 回退 default（不落库 `""`）|

### 3.3 Frontend

| 文件 | 变更 | 优先级 | 意图 |
|---|---|---|---|
| `app/(app)/requirements/board/page.tsx` | ［改］ | P1 | 接 `useBoard().error`→`ErrorState`；`canConvert` 门禁 `onConvert`（§2.7-A1 / §2.9-C2）|
| `app/(app)/bugs/board/page.tsx` | ［改］ | P1 | 接 `useBoard().error`→`ErrorState`（§2.7-A1）|
| `components/TicketDrawer.tsx` | ［改］ | P1 | 接 `useTicket().error`→抽屉内错误态（可关闭），根除已删工单永久骨架（§2.7-A2）|
| `lib/api.ts` | ［改］ | P1 | 401（非 `/auth/`）→ 清 token + 广播 `aragon:unauthorized`（§2.8）|
| `lib/auth.tsx` | ［改］ | P1 | `AuthProvider` 订阅 `aragon:unauthorized`→清态（触发外壳跳登录，§2.8）|
| `app/(app)/requirements/page.tsx` · `bugs/page.tsx` | ［改］ | P1 | 内联「指派」按 `canAssign` 门禁（§2.9-C1）；指派弹窗防重复提交（§2.10-D2）|
| `app/(app)/team/page.tsx` | ［改］ | P1 | 补 loading 骨架 + `error` 态（空表不再误读，§2.7-A3）|
| `hooks/useTicket.ts` | ［改］ | P2 | `patch` 成功后以返回体新 `updated_at` 落缓存，避免连改级别假 409（§2.10-D4）|
| `components/requirements/RequirementForm.tsx` · `bugs/BugForm.tsx` | ［改］ | P2 | create 与 assign 分别处理结果（部分失败精确反馈 + 仍刷新，§2.10-D3）|
| `app/(app)/notifications/page.tsx` | ［改］ | P2 | 读/已读后一并 mutate 铃铛 `unread-count` 与列表 key（§2.10-D1）|
| `app/(app)/dashboard/page.tsx` | ［改］ | P2 | 「本周活动数」卡改非链接（去死链，§2.10-D5）|

### 3.4 文档

| 文件 | 变更 | 优先级 | 意图 |
|---|---|---|---|
| `docs/plans/feature-completeness/spec.md` | ［新］ | — | 本文档 |
| `README.md` | ［改］ | P2 | 追加「主流程完备化与页面可用性收官」一节：自主 AI 团队闭环闭合（dev→qa 交接）、默认列表排序修正、残余坏输入 500→400、看板/抽屉/团队页错误态、全局 401 自动登出、列表/看板写按钮门禁 |

---

## 4. Interface Design（接口设计 · 仅列语义变更，签名与成功响应 shape 不变）

> 统一约定沿用既有：JSON in/out；非 2xx 错误体恒为 `{error, detail?}`（状态机迁移类附 `allowed`）；写接口需 `Authorization: Bearer`。**成功路径的路径、请求体、成功响应 shape 全部不变。** 本轮只新增/修正**错误分支与默认排序**——都是「变得更对」，不破坏既有正常用法。

```
# ① 列表默认排序更合理（无契约 shape 变化，仅顺序）
GET /api/requirements | /api/bugs   （无 status= 时）
  → 仍是裸数组 + X-Total-Count；顺序由「列内 position」改为「updated_at 降序,id 降序」（最近更新在前）
  （此前跨状态交错、顺序无意义；看板 GET /api/board/* 不受影响，仍按列内 position）

# ② 残余坏输入统一 400（此前 500）
POST /api/agents/:id/tick        {"claim_count": "x"}          → 400 {"error":"claim_count must be an integer","detail":{"field":"claim_count","expected":"integer"}}
POST /api/auth/register          {"...","email": {"x":1}}      → 400 {"error":"email must be a string","detail":{"field":"email"}}
POST/PATCH /api/users            {"...","email": {"x":1}}      → 400（同上）
POST /api/requirements|bugs      {"title":"t","description":{"x":1}} → 400 {"error":"description must be a string","detail":{"field":"description"}}

# ③ 枚举字段空串回退默认（此前落库非法 ""）
POST /api/requirements {"title":"t","priority":""}   → 201，priority="medium"（不再是 ""）
（severity:"" → "major"；kind:"" → "generic"；role:"" → "member"）

# ④ 自主编排尊重 offline（此前 offline 被跑起来并清成 idle）
POST /api/agents/:id/autorun | /tick   （agent.status=="offline"）→ 409 {"error":"agent is busy or offline"}
POST /api/agents/autorun-all           （某 agent offline）→ 该 agent 计入 runs.skipped(reason="offline")，状态不被改写

# ⑤ 单步 run=all 补软锁门禁（此前无 busy 检查）
POST /api/requirements|bugs/:id/agent-advance?run=all   （assignee agent busy/offline）→ 409 {"error":"agent is busy or offline"}

# ⑥ 自主 AI 团队闭环闭合（行为增强，无接口签名变化）
POST /api/agents/autorun-all?run=all
  → 需求可被带到 reviewing（reviewing→done 属人工审批，正确止步）、BUG 可被带到 closed；
    runs[].advanced 现会包含 qa-agent 对 testing→reviewing / verifying→closed 的推进；
    交接会为源单 reporter 扇出一条 assigned 通知（**经 notify_claim**，收件人=reporter；
    **不**用 notify_assignment——后者仅通知人类 assignee，交接后 assignee 已是 qa-agent 会静默 no-op，见评审 R1）；
    无 qa-agent 时行为与此前逐字节一致
```

**前端消费约定**：`lib/api.ts` 的 401 拦截仅对**非 `/auth/` 路径**触发登出广播（`/auth/login` 的凭据错误 401 不触发重定向）；`ApiError` 结构不变（`status/detail/allowed`），既有 409 分流逻辑（状态机 vs 并发）不受影响。

---

## 5. Data Model（数据模型）

**本轮无任何数据库 schema 变更**——不新增表、不改列、不加索引、不迁移。延续「唯一新表是 Phase-3 `notifications`」。`aragon.db` 已 gitignore，dev 首启即建全。

仅涉及两处**既有字段的语义/用法澄清**（非结构变更）：

- **`Requirement.position` / `Bug.position`（`models/requirement.py:30`）**：本轮明确其**仅用于看板列内排序**；扁平列表不再据其排序（§2.3）。列定义、默认值、`_next_position` 逻辑均不变。
- **多态 assignee（`assignee_type`∈{user,agent} + `assignee_id`）**：dev→qa 交接（§2.2）通过改写这两列实现「工单易主」，**不触碰 `status`/`position`**（状态迁移已由 `advance_one` 合法完成）。`resolve_assignee()`/`to_dict()` 原样序列化，无需改动。

新增一处**进程内（in-memory）常量与 helper**（非持久化，`agent_autopilot.py`）：

```python
_QA_HANDOFF_STATUS = {"requirement": "testing", "bug": "verifying"}   # 进入 qa 职责区的状态
_maybe_handoff_to_qa(entity, ticket) -> Agent | None                  # dev→qa 重指派（不 commit、不改状态）
```

前端新增一处**事件契约**（非持久化）：`window` 上的 `CustomEvent("aragon:unauthorized")`——`api.ts` 在会话失效（非 `/auth/` 路径 401）时派发，`AuthProvider` 订阅后登出。与既有 `aragon:open-ticket`/`aragon:search` 同为「window 事件总线」模式，零新依赖。

---

## 6. Testing & Acceptance（测试与验收标准）

### 6.1 后端 pytest（现约 **222** 用例全绿，`backend/tests/` 19 个文件；本轮**只增不减、既有断言语义保持**——除 §2.3 排序变更须同步更新的顺序类断言）

- **自主 AI 团队闭环（P1，硬指标，`test_agent_autopilot.py`）**：
  - 造一张指派给 dev-agent 的需求，反复 `POST /api/agents/autorun-all?run=all`（或造齐 dev+qa 后单次），断言该需求**最终到达 `reviewing`**（经 dev→testing 交接给 qa→reviewing）；BUG 场景断言**到达 `closed`**。
  - **无 qa-agent** 时（删除/离线所有 qa）断言优雅停在 `testing`/`verifying`（no-op 回归，行为与旧版一致）。
  - **存量单回归（评审 R2）**：预置一张 `testing`/`verifying` 且 `assignee=dev-agent` 的单（模拟 seed 演示单），`autorun-all?run=all` 后断言其经交接到达 `reviewing`/`closed`（验证 `except NoAgentAction` 分支的交接）。
  - 交接后源单 reporter 收到一条 `assigned` 通知（`_maybe_handoff_to_qa` 经 **`notify_claim`** 扇出，收件人=reporter；**注意**不可用 `notify_assignment`——其对 agent assignee 直接 `return`，见评审 R1）；被交接单的 `assignee` 变为 qa-agent。
- **Agent 软锁 / offline（P1，`test_agent_autopilot.py`）**：`PATCH /agents/:id {"status":"offline"}` 后 `POST /agents/:id/autorun` → 409，且事后 `GET /agents/:id` 仍为 `offline`（未被清成 idle）；`autorun-all` 中 offline agent 计入 `skipped(reason="offline")`。
- **残余坏输入 500→400（P1，`test_validation.py`/`test_agent_autopilot.py`/`test_auth.py`/`test_admin_console.py`）**：`tick {"claim_count":"x"}`、`register/users {"email":{"x":1}}`、`create requirement/bug {"description":{"x":1}}` 各 → **400 且断言状态码 `!= 500`**。
- **默认列表排序（P1，`test_requirements.py`/`test_bugs.py`）**：造多张不同状态/更新时间的单，断言 `GET /api/requirements`（无过滤）按 `updated_at` 降序返回；更新任何依赖旧 position 序的断言。
- **枚举空串回退（P2，`test_validation.py`）**：`priority:""`→`medium`、`severity:""`→`major`、`kind:""`→`generic`、`role:""`→`member`（断言落库非空且合法）。
- **门禁命令**（Windows PowerShell，命令分开执行，**不用 `&&`**）：
  ```
  cd backend
  pytest -q
  ```
  **验收**：全部用例（≥222 + 新增）green；`pytest -q` 退出码 0。

### 6.2 前端质量门禁

```
cd frontend
npm run typecheck   # tsc --noEmit → 0 error
npm run build       # next build → 成功
```

**验收**：`tsc --noEmit` 0 error；`next build` 成功（全部页面产出）。

### 6.3 手工验收（P1 路径，冒烟）

1. **自主闭环**：以 pm 登录 → Agents 页「▶ 运行 AI 团队一轮」→ 需求看板出现被推进到 `审批中/reviewing` 的单、BUG 看板出现 `已关闭/closed` 的单；时间线含 qa-agent 的推进评论。
2. **看板错误态**：停后端 → 打开 `/requirements/board` → 显示「无法加载看板 + 重试」（非永久骨架）；启后端点重试 → 恢复。
3. **抽屉 404**：深链 `/bugs/board?ticket=999999` → 抽屉显示错误态且可关闭（非永久骨架）。
4. **会话过期**：登录后清除 `localStorage.aragon_token`（模拟失效）或等 token 过期 → 触发任一请求 → 自动跳 `/login`（非全站「重试失败」）。
5. **权限门禁**：以 member（alice）登录 → 需求/BUG 列表**不出现**行内「指派」按钮；需求看板卡片**不出现**「转 BUG」。以 pm 登录 → 两者可见且可用。
6. **建单部分失败**：选一个随后被删的 assignee 建单 → 提示「已创建，但指派失败」且列表刷新出该单（不误报「创建失败」、不留孤单不刷新）。

### 6.4 验收判定汇总（Definition of Done 对齐）

- 后端 `pytest -q` 退出码 0（≥222 + 新增全绿）；前端 `tsc --noEmit` 0 error、`next build` 成功。
- §6.3 六条手工冒烟全通过。
- 全仓 `grep` 复核：`list_requirements`/`list_bugs` 不再按 `position` 排扁平列表；`claim_count`/`email`/`description` 均经 `want_*`；`api.ts` 401 分支存在且排除 `/auth/`；两看板页与 `TicketDrawer` 均读 `error`。

---

## 7. Risks & Mitigations（风险与缓解）

| 风险 | 等级 | 缓解 |
|---|---|---|
| **dev→qa 交接改动自主编排、可能破坏既有 `test_agent_autopilot` 断言** | 中 | 交接仅在「推进到 qa 泳道状态」时触发、**只改 assignee 不改状态**；无 qa-agent 时严格 no-op（保证既有「无 qa 场景」断言逐字节兼容）。新增用例覆盖有/无 qa 两路；实现前先 `pytest -q` 建基线，逐步核对。 |
| **列表排序 `position→updated_at` 改变默认顺序，破坏顺序类测试断言** | 中 | 有意的行为变化（列表非看板）。§3.2 明列须核对 `test_requirements/test_bugs/test_search`；多数断言按「存在/数量/集合」不受影响；硬编码首元素 id 的断言改为按新序或集合断言。看板 `board.py` 不受影响。 |
| **全局 401 拦截误伤登录页 / 造成重定向抖动** | 中 | 仅对**非 `/auth/` 路径**的 401 触发（登录凭据错误不触发）；`setToken(null)+setUser(null)` 幂等，`(app)/layout` 既有守卫落地跳转，无循环（登录页不在 `(app)` 段内）。 |
| **交接使工单在一次 `autorun-all` 内被两个 agent 连续处理，步数超预期** | 低 | 交接后 `break`（本 agent 不再推进已易主单）；`MAX_AUTOPILOT_STEPS`（24）/`MAX_AGENT_STEPS`（6）全局兜底不变；qa 推进沿用同一上限。 |
| **`want_str` 枚举空串回退改动影响既有依赖「空串即报错」的调用方** | 低 | 现网枚举调用方（`priority/severity/kind/role`）**均带 default**，回退 default 语义正确；`required=True` 的空串仍在既有分支 raise，无回退。新增 `test_validation` 用例锁定。 |
| **SQLite + `threaded=True` 下交接/推进的写锁争用** | 低（dev-only 已接受） | 沿用 `reliability-hardening` §R1 结论：dev-only 已知风险，生产经 `DATABASE_URL` 用 Postgres 行级锁化解；本轮不引入新的并发面（交接与推进同事务提交）。 |
| **`description` 改 `want_str(strip=False)` 后既有「description 为对象/None」用例** | 低 | `required=False` + `or None` 保证缺省/空 → None（与现状一致）；仅新增「非串 → 400」；`strip=False` 保留正文格式，正路无感。 |

---

## 8. 审计核验说明与假阳性剔除（供实现者放心据此落地）

**经两支只读审计 + 一手核验确认为「非缺陷、本轮不动」的项**（列出以省下游复核时间）：

- **删除级联健全**：`delete_requirement` 删前置空 `Bug.related_requirement_id`（FK 安全）并清评论 + 通知；`delete_bug` 清评论 + 通知；`activities` 有意保留为不可变审计（`requirements.py:242-260` / `bugs.py:241-252`）。**无悬挂/孤儿，不改。**
- **乐观并发往返正确**：`utcnow()` 为 naive-UTC、`_iso` 追加 `Z`、微秒保留，`expected_updated_at` 比对精确（`requirements.py:110-127`）。**不改。**
- **`require_role`/`can_manage_ticket` 读库内 `User.role`（非 JWT claim）**（`auth_helpers.py:36-72`）——角色变更服务端**即时生效**，不存在「改角色不生效」的服务端缺陷。前端 `useAuth` 上下文持旧角色至刷新属客户端显示、非安全问题，本轮不纳入。
- **@提及 + 评论「双通知」**（同一用户可能同收 `mentioned` + `commented`）为**有意设计**（`test_mention_and_comment_coexist_for_participant` 锁定），不去重。
- **通知自跳过 / 去重 / 已读 / 未读计数 / `X-Total-Count`** 均按测试语义正确，不改。
- **同列拖拽重排** 前端乐观路径（`useBoard.ts:43-54`）与后端 `_reindex_column`（`requirements.py:57-75`）索引一致；跨列拖入终态经 409/`allowed` 干净回滚——**不改**。
- **`reliability-hardening` 已修项**（SWR 形状、主列表页 ErrorState、GlobalSearch 回车、Badge 兜底、通知偏好抛错、TicketDrawer 写按钮门禁、`move` status 归一、无效 JWT 401、LIKE 转义、Activity 截断、LLM 优雅降级）**均已核验落地，本轮不重复**。

**评审裁定留待 Subtask #1 复核的边界项**（本 v1 倾向「纳入」，标注供评审确认）：
- `patch_agent` 改 `kind` 会使在制单（`in_development` 等）的 `agent-advance` 落 `NoAgentAction`（`agents.py:82-83`）——本 v1 **暂不纳入**（edge，且 dev→qa 交接后 in-flow 单多已易主至 qa；强行禁改 kind 会削管理灵活性），记 `# TODO(agent-kind-inflight)` 备评审裁定。
- 跨列移动后**源列 position 残留空洞**（`requirements.py:341-346`，只重编目标列）——本 v1 **暂不纳入**（§2.3 改扁平列表排序后空洞不再影响观感；列内 `position asc, id asc` 仍稳定），记 `# TODO(source-column-reindex)` 备后续数据整洁化。
- 铃铛下拉 list 拉取无 error 分支（`useNotifications.ts` list 失败 → 下拉永久「加载中…」）——本 v1 **暂不纳入**（P2 边缘，铃铛为轮询非关键路径），记 `# TODO(bell-list-error)`。

---

## 9. 实施顺序建议（供 Subtask #2）

1. **先建基线**：`cd backend; pytest -q`（记录当前绿数）；`cd frontend; npm run typecheck`。
2. **后端 P1**（互不耦合，可并行）：§2.2 dev→qa 交接 → §2.3 列表排序 → §2.4 残余 500 → §2.6 offline/软锁；每改一处跑相关测试。
3. **后端 P2**：§2.5 枚举空串回退。
4. **前端 P1**：§2.8 全局 401（api.ts + auth.tsx）→ §2.7 三处错误态 → §2.9 两处门禁；`npm run typecheck` 逐步验证。
5. **前端 P2**：§2.10 D1–D5。
6. **回归**：后端 `pytest -q` 全绿、前端 `tsc --noEmit` 0 error + `next build` 成功；§6.3 手工冒烟。
7. 若实现中发现方案缺陷，记入本文档新增的「## 实施过程发现的方案缺陷」段（不回滚既有设计）。

---

*（v1 由 Solution Architect 产出，篇幅与 `file:line` 精度已满足「下游可逐行实现、无需再做架构决策」。本 **v2** 由 Subtask #1 逐节四维评审并就地修复全部 P0/P1，见文首「## 评审记录」与下方「## 评审结论」。）*

---

## 评审结论（Review Verdict · Subtask #1）

**判定：有条件通过（Approved with conditions）。**

方案针对第 2 轮需求「继续完善所有主要功能，确保每个功能都不报错、客户端页面都能正确使用」，命中的是**真实、可复现、按 `file:line` 逐条核验属实**的缺陷面（自主 AI 团队半通、默认列表顺序错乱、残余坏输入 500、看板/抽屉/团队页永久卡骨架、会话过期全站失灵、无权却给必 403 的按钮）。四维评审结论：

- **可行性**：全部修复已对现网 `c8c8e46` 的函数签名 / 返回体 / 事件总线逐一核验可落地（`notify_claim`/`Activity.log`/`Agent` 模型/`useBoard().error`/`useTicket().error`/`api.ts` 双出口的 `path` 参数/`(app)/layout` 跳转守卫均已确认）。原 v1 唯一的落地绊脚石（R3 的 `want_int` 未 import）已在正文修正。
- **完备性**：原 v1 在**核心修复**（自主闭环交接）上有两处会致其自身验收失败的漏洞——R1（交接通知是死代码、与 P1 断言矛盾）与 R2（交接遗漏存量卡死单，含 shipped seed 演示单）。**两者均已在 v2 正文就地修复**（改用 `notify_claim`；在 `except NoAgentAction` 分支补交接），自主闭环对「新流入」与「存量」两类单均闭合。
- **一致性**：与 `CLAUDE.md` 三条红线（状态机是圣域 / 向后兼容不新增表·依赖 / 不过度设计）完全一致——交接只改多态 assignee、不新增迁移边、不碰 `status`/`position`；沿用既有 `CustomEvent` 事件总线，`api.ts` 不 import `auth`，无环依赖。
- **尺度**：范围克制、无过度设计；P1 集中于「一处 qa 交接 helper + 一条前端 401 拦截 + 三处错误态 + 两处门禁」，P2 均为低风险机械改动。§8 三处 `TODO` 边界项的延后裁定合理，予以确认。

**放行条件（下游 Subtask #2 实现时必须满足，逐条已在正文对应处标注）**：

1. **[R1]** `_maybe_handoff_to_qa` 的交接通知必须用 `notify_claim(ticket, entity, qa)`；**严禁** `notify_assignment`（对 agent assignee 静默 no-op）。
2. **[R2]** dev→qa 交接必须接线**两处**：`autorun` while 循环内「成功推进之后」**与** `except NoAgentAction` 分支内；后者用于解救已停在 `testing`/`verifying` 的存量非-qa 单（含 seed 演示单），并新增其回归用例（§6.1）。
3. **[R3]** 落地 §2.4-C1 前，先给 `agents.py:13` 的 import 补上 `want_int`。
4. **[R4]** 验收自主闭环时按「反复 `autorun-all` 或造齐 dev+qa（dev 先建）后单次」执行；若运营侧以任意序建 Agent，单轮可能只到 `testing`/`verifying`，需第二轮接力（设计跨轮确定收敛）。
5. **[R5/R6]** offline 门禁范围按 §2.6 界定（单步 `agent-advance` 有意不纳入）；`want_str` 的「凡 `choices=` 必带 `default ∈ choices`」不变量须写入 docstring 并纳入评审清单。
6. **不变量兜底**：所有工单状态迁移仍且只经 `workflow.can_transition`；后端 `pytest -q` 退出码 0（≥222 + 新增全绿）、前端 `tsc --noEmit` 0 error + `next build` 成功；§6.3 六条手工冒烟全过（新增「存量 `testing`/dev 单经交接达 `reviewing`」一条）。

满足以上条件即视为**通过**。无 P0/P1 遗留（P1 已就地修复，P2 已以说明/不变量落地）。

*（本 v2 评审由 Senior Reviewer（Anthropic Engineering）完成。评审仅修改本 `spec.md`，未触碰源码、未 `git commit`。）*
