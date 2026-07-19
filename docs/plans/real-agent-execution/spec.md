# AragonTeam —— 真实 Agent 执行引擎（去 Mock）设计方案

> **Feature**: `real-agent-execution`
> **文档版本**: v2（已评审 · P0/P1 已在正文修复）
> **作者角色**: Solution Architect（Anthropic 工程团队）
> **日期**: 2026-07-19
> **对应任务**: 「对项目中的所有 mock 逻辑进行真实代码编写，完善所有接口和功能，确保稳健可靠好用，确保主流程都 ok，不能有大的报错」
> **上游依赖**: 无 · **下游**: Subtask #1 方案评审 → Subtask #2 代码开发 → Subtask #3 Review 与提交

---

## 评审记录（Review Notes · v2）

> **评审人**: Senior Reviewer（Anthropic 工程团队）· **评审日期**: 2026-07-19
> **评审维度**: 可行性（Feasibility）/ 完备性（Completeness）/ 一致性（Consistency · 对照 `CLAUDE.md` 与代码约定）/ 尺度（Right-sizing）
> **结论前置**: **无 P0**；发现 **3 个 P1、6 个 P2**。全部 P1 已在本文 v2 正文**直接修复**；P2 为落地建议（多数已就近补入正文）。详见文末「评审结论」。

**核对基线（评审时逐文件核验，非纸面推断）**：`agent_runner.advance_one` 与 `AGENT_FORWARD` 形状（`(entity,kind,current_status)→(to,message)`）、`workflow.can_transition/is_terminal`、`routes.do_agent_advance`/`_agent_run_all` 的事务与 commit 节奏、`routes/agents.py` 的 `autorun`/`autorun-all`（`runs` 每 Agent 一项、逐 Agent 串行）、`config.TestConfig(TESTING=True, StaticPool)`、`tests/test_health.py`（仅断言 `status/service/db` 子集键，**非整字典等值**→ 加 `llm` 块安全）、`tests/test_agent_runner.py`/`test_agent_autopilot.py`（**无**对 Agent 评论正文/推进 message 的等值断言 → 启用 LLM 仅改 `comment.body` 内容，零测试破坏）、`observability.py`（结构化日志 + `X-Request-Id`）。核验结论：§0 审计「M1/M2 为唯一业务 Mock」**成立**（前端全仓无 mock/假数据命中；`seed.py`=演示种子；`ratelimit.py`=可用内存限流器，非 Mock）。

| # | 维度 | 严重度 | 概要 | 处置 |
|---|------|:---:|------|------|
| P1-1 | 可行性 / 稳健 | **P1** | LLM 调用落在 SQLite 写锁窗口内：§3.2 接缝在 `ticket.status=to` **之后**才调 `generate_work`，其 feed 查询触发 autoflush → 对 `ticket` 取 RESERVED 写锁，随后至多 30s 的 LLM 调用**全程持锁**；叠加本方案新加的 `threaded=True` + 默认文件 SQLite（`busy timeout=15s`），任一并发写将阻塞 15s 后抛 `database is locked` → 500，违背「不能有大的报错」。 | **正文修复**：重排接缝——`generate_work`（只读 feed + LLM）在**改状态之前**执行（`to` 早由 `plan()` 得到），LLM 期间 session 无挂起写、零持锁；改状态与建评论紧贴 commit。见 §3.1/§3.2/§3.8/§8 R11。 |
| P1-2 | 稳健 / 完备 | **P1** | 非 `LLMError` 异常会冒泡成 5xx：§3.5 决策表只对 `LLMError` 降级，但 Provider 解析 `resp["content"][0]["text"]` / `resp["choices"][0]["message"]["content"]` 在响应异形（空 `content`/`choices`、首块非 text、缺键）时会抛 `KeyError/IndexError/TypeError`，这些**非 LLMError**将逃逸 → 500，破坏「外部故障绝不冒泡」不变量。 | **正文修复**：(a) Provider 把一切解析/网络/HTTP 失败统一包成 `LLMError`；(b) `generate_work` 对 LLM 调用加**兜底 `except Exception`**，任何异常一律降级到 fallback。见 §3.3/§3.5/§5.2/§8 R4。 |
| P1-3 | 完备性 | **P1** | `ACTION_BRIEF` 键有碰撞且覆盖不全：§3.4 以 `(entity, kind, to_status)` 为键——(a) requirement/dev 的 `in_development→testing`（完成实现）与 `bug_fixing→testing`（修复缺陷）**碰撞**成同一键、语义合并丢失；(b) 未覆盖受支持的 `generic` kind 边，且**未定义键缺失时的缺省 brief**——缺失会把空/`None` 指引注入 prompt。 | **正文修复**：改用与 `AGENT_FORWARD` 逐字一致的键 `(entity, kind, current_status)`（1:1、无碰撞、可穷举），补齐全部 9 条边含 `generic`，`build_context` 键缺失回落通用 `DEFAULT_BRIEF`。见 §3.4。 |
| P2-1 | 稳健 / 好用 | P2 | `autorun-all` 在 LLM 启用下无同步时长硬上限：逐 Agent 串行，单 Agent 至多 `MAX_AUTOPILOT_STEPS=24` 次调用；N 个 Agent → 最坏 N×24 次串行调用于**同一 HTTP 请求**内，30s/次时可达数分钟，触发浏览器/网关超时（离线默认不受影响）。 | **建议 + 就近加固**：为 LLM 活跃时的 autopilot 增设可选 wall-clock 预算 `AGENT_LLM_WALL_BUDGET`（默认 120s，`0`=不限），超时其余单以 `reason="budget"` 跳过（沿用既有 skipped 语义）。离线态步进近瞬时、预算永不触发，测试与默认行为不变。见 §3.8/§5.3/§8 R5。异步化仍列根治未来项。 |
| P2-2 | 尺度 / 好用 | P2 | 默认模型 `claude-opus-4-8` 对批量 autopilot 偏重偏贵（多次串行调用放大时延与成本）。 | 建议 autopilot 密集/整队场景改用更快更省模型（Haiku 级），已在 §5.3 备注显著提示。 |
| P2-3 | 稳健 | P2 | Provider 解析需显式防空 `content`/`choices` 与首块非 text。 | 并入 P1-2 修复：空数组/异形块 → `LLMError(kind="parse")`。见 §3.3、§7 test 10。 |
| P2-4 | 安全 | P2 | 结构化日志务必不含鉴权头/密钥/完整请求体。 | §8 R7 补注：日志仅记 provider/model/latency/usage/retries/降级因，**从不**记 `Authorization`/`x-api-key` 与 payload。 |
| P2-5 | 可行性 | P2 | 两 provider 的 `base_url` 拼接不对称（Anthropic `{base}/v1/messages`、OpenAI `{base}/chat/completions`）易踩空 `/v1` 或双斜杠。 | §3.3/§5.3 钉死默认端点（openai 默认含 `/v1`）与安全拼接（拼接前去尾 `/`）。 |
| P2-6 | 稳健 | P2 | 交互单步路径叠加重试 `sleep`（默认 0.5s+1s）会抬高 p99。 | 可接受；p99 由 `max_retries`×`timeout` 组合可控，必要时单步降为 1 次重试。记于 §3.3。 |

---

## 0. Mock 盘点（Audit — 本方案的事实依据）

本节先回答一个关键问题：**项目里到底有哪些「mock 逻辑」？** 只有把范围钉死，才能保证「所有 mock 都被真实化」这一目标可验证。经全仓 `grep`（`mock|fake|stub|offline|deterministic|simulat|placeholder|TODO`）+ 逐文件核对，结论如下：

| # | 位置 | 表面命中 | 判定 | 处理 |
|---|------|---------|------|------|
| M1 | `backend/services/agent_runner.py` · `AGENT_FORWARD` | 「确定性离线模拟」+ 罐头评论模板 | **真正的业务 Mock**：Agent 被指派工单后只是按查找表推进状态并写一句固定文案，并未真正「开发需求 / 修复 BUG」 | **本方案核心：接真实 LLM 执行** |
| M2 | `backend/services/agent_autopilot.py` | 复用 M1 的罐头文案 | 同 M1 的传导 | 随 M1 一并真实化（编排层不改，产物变真） |
| M3 | `backend/seed.py`（docstring 写「mock 数据」） | 首启示例数据（账号 / Agent / 工单） | **非业务 Mock**：是开箱即用的演示种子，已由 `SEED_ON_STARTUP` 门控，测试环境已关闭 | **保留**，仅将 docstring「mock 数据」措辞澄清为「示例种子数据」 |
| M4 | 前端 `placeholder="…"`（`Input/Select/Header/*Form`） | HTML 占位符 | 非 Mock（输入框提示文案） | 不动 |
| M5 | `AgentStatus="offline"`、`stats.agent_counts["offline"]` | 「offline」字样 | 非 Mock（Agent 真实状态枚举） | 不动 |

**核心结论**：全项目唯一的「模拟业务逻辑」是 **Agent 执行引擎**（M1/M2）。所有 REST 路由（CRUD / board / stats / notifications / comments / me / users / projects）均为真实实现，前端全部对接真实接口，无前端假数据。因此本方案聚焦于把 Agent 的「假装干活」变成「真的干活」，同时以「零破坏、可离线、全测试保持绿」为不可谈判的底线。

> **评审补注（P2 · 完备性）**：另有 `services/ratelimit.py` 为**可用的内存限流器**，带 `# TODO(ratelimit-distributed)` 的水平扩展注记——它是**真实逻辑而非 Mock**，分布式化（改 Redis）属独立后续项，明确**不在本方案范围**，此处点名以示未被遗漏。

---

## 1. Overview（概述）

AragonTeam 定位为「AI 时代的团队协作与研发管理平台」，其区别于 Jira/禅道的根本特征是 **Agent 是一等公民的执行者**：需求单与 BUG 单既能指派给人类，也能指派给 AI Agent（dev-agent / qa-agent）。当前平台已经把「Agent 参与协作」做成了可交互、可追溯、可测试的**机制骨架**——一张指派给 Agent 的工单能被推进一步，每步严格走状态机、留一条 Agent 评论、写一条 `actor_type=agent` 审计。然而这一步的「工作内容」是**罐头文案**（`AGENT_FORWARD` 查找表里的固定字符串），Agent 并没有真正阅读需求、产出实现思路、生成代码或测试用例。这正是本迭代要消除的最后一块「Mock」。

本方案在**不改动状态机、不破坏任何既有对外契约、不新增第三方依赖**的前提下，于 `agent_runner.advance_one` 这一唯一接缝处引入**真实 LLM 执行层**：当平台配置了可用的模型凭据时，dev-agent/qa-agent 在推进每一步时会真正调用大模型，读取工单标题、描述与最近讨论上下文，产出**该步骤对应的真实工作产物**（需求拆解与实现要点、变更说明、测试计划与用例、缺陷根因与修复摘要等），并将其作为 Agent 评论写入协作时间线。**状态迁移目标仍然完全由 `AGENT_FORWARD` + `workflow.can_transition` 裁决**，LLM 只负责「产出内容」，绝不决定「流转到哪」——这既让 Agent 的输出变真，又守住了「状态机是圣域」这一产品可信度地基。

稳健性是本方案的第一性要求。真实世界的 LLM 调用会超时、限流、返回空、网络抖动，而平台承诺「主流程都 ok，不能有大的报错」。因此执行层被设计为**优雅降级**：未配置凭据 / 测试环境 / 调用失败 / 返回空——任一情况都**回退到既有确定性文案**，工单照常推进、流程绝不中断、事务绝不因外部故障而回滚。这一降级路径同时是**向后兼容的保证**：现有 93 个 pytest 用例在无凭据环境下运行时，行为与今天**逐字节一致**，全部保持绿。换言之，本方案是「有凭据则真、无凭据则稳」的双模引擎，既顶配又不失底线。

---

## 2. 目标与非目标

**目标（Goals）**
1. 把 Agent 执行从「罐头文案」升级为「真实 LLM 产物」，覆盖需求开发（dev）、测试审查（qa）、BUG 修复（dev）、验证（qa）全部前进边。
2. 引入自包含的 LLM 服务层，支持 **Anthropic Messages API**（默认）与 **OpenAI 兼容 Chat Completions**（可选，覆盖国产/自建网关），**仅用 Python 标准库 `urllib`**，零新增依赖。
3. 生产级可靠性：可配置超时、有界重试、结构化日志、全链路优雅降级。
4. 严守「状态机唯一裁决迁移」；`agent-advance` / autopilot / 通知 / 审计 等对外契约与响应结构**零破坏**。
5. 全部既有测试保持绿；新增覆盖真实路径、降级路径、Provider 解析、超时/重试的单测。

**非目标（Non-goals）**
- 不引入真实的代码库读写 / git 操作 / 沙箱执行（Agent 产物为「书面工作产物」，写入评论时间线；真正落盘执行留待后续迭代）。
- 不引入消息队列 / 后台任务框架（同步执行 + 步数上限 + busy 软锁已足够 MVP；异步化列入风险与未来项）。
- 不改状态机邻接表、不改 `AGENT_FORWARD` 的键值形状 `(to, message)`（否则破坏结构性单测）。
- 不新增/变更数据库表结构（保持「零 schema 迁移」，见 §6）。

---

## 3. Technical Design（技术设计）

### 3.1 架构总览

```
routes/requirements.py · routes/bugs.py        (do_agent_advance —— 不变)
routes/agents.py (autopilot —— 不变)
        │  调用
        ▼
services/agent_autopilot.py  (编排 —— 不变)
        │  调用
        ▼
services/agent_runner.advance_one()   ← 唯一接缝：本方案在此处替换「评论正文的生成」
        │  取正文
        ▼
services/agent_executor.generate_work(entity, ticket, agent, to_status, fallback)   ← 新增
        │  启用则调用            │  未启用/失败则回退
        ▼                        └────────────► 返回 fallback（= AGENT_FORWARD 文案）
services/llm/  (新增子包)
   ├─ config.py     LLMConfig.from_env()            —— 环境变量 → 配置
   ├─ prompts?      (放在 services/agent_prompts.py) —— 上下文与提示词
   ├─ providers.py  AnthropicProvider / OpenAICompatProvider (urllib)
   └─ __init__.py   is_enabled() / complete()  —— 对外公共 API（含重试）
```

**设计要点**：唯一被侵入的既有函数是 `agent_runner.advance_one`，仅改「评论正文从哪来 + LLM 调用相对状态变更的次序」这两点语义（见 §3.2 P1-1）；`advance_one` 的返回三元组 `(to, comment, activity)`、事务边界（不 commit）、审计写法均**保持不变**。编排层 `agent_autopilot`、路由层、通知层除 §3.8 P2-1 的**可选 wall-clock 预算判定**（默认宽松、离线不触发）外**一行不改**。

### 3.2 核心执行路径（The Seam）

`agent_runner.advance_one` 现状（简化）：

```python
to, message = planned                       # 来自 AGENT_FORWARD
if not workflow.can_transition(entity, ticket.status, to): raise RuntimeError(...)
frm = ticket.status
ticket.status = to; ticket.position = _next_position(type(ticket), to)
comment = Comment(..., body=message)        # ← 罐头文案
Activity.log(..., message=message)
```

改为（**唯一改动点**；且 LLM 调用刻意置于**改状态之前**，避免持写锁，见 §3.8 P1-1）：

```python
to, message = planned                       # message 继续作为「审计短句 + 降级兜底」
if not workflow.can_transition(entity, ticket.status, to): raise RuntimeError(...)
frm = ticket.status

# 【P1-1】先产出正文：generate_work 只读（feed 查询）+ 可选 LLM。此刻 session 无挂起写，
# feed 的 SELECT 不会 autoflush 出任何 UPDATE，故 LLM 全程不持有 SQLite 写锁。
body = agent_executor.generate_work(        # ← 真实产物或兜底文案
    entity, ticket, agent, to, fallback_message=message)

# 产出完成后再改状态、建评论——写事务窗口收敛到 commit 前的亚毫秒区间。
ticket.status = to; ticket.position = _next_position(type(ticket), to)
comment = Comment(..., body=body)           # 时间线呈现「真实工作产物」
Activity.log(..., message=message)          # 审计仍记「简短动作短句」，保持审计干净
```

> **为何次序即安全**：`build_context` 需要的 `frm` 就是此刻的 `ticket.status`（尚未改），`to` 早由 `plan()` 得到——故把 LLM 前移不损任何上下文，却把「持有 SQLite 写锁的时长」从「≈LLM 往返（可达 30s）」压到「几条 SELECT/INSERT（亚毫秒）」。这是 `threaded=True` 下并发写不再报 `database is locked` 的关键（§3.8）。

**为何审计仍用 `message` 而非 LLM 正文**：审计日志要短、稳定、可断言（`test_run_all_advances_until_no_action` 断言 `to_status` 序列，`agent_advanced` 审计短句保持确定）；而**丰富内容进入评论正文**（feed 展示）。二者职责分离，既让产物变真，又不动审计契约。

### 3.3 LLM 服务层（`services/llm/`）

**Provider 抽象**：统一签名 `complete(system: str, user: str, cfg: LLMConfig) -> LLMResult`。

- `AnthropicProvider`：`POST {base_url}/v1/messages`，头 `x-api-key`、`anthropic-version: 2023-06-01`、`content-type: application/json`；体 `{model, max_tokens, temperature, system, messages:[{role:"user", content:user}]}`；解析 `resp["content"][0]["text"]`，用量取 `resp["usage"]`。默认 `base_url=https://api.anthropic.com`（拼接前去尾 `/`），默认 `model=claude-opus-4-8`（可 env 覆盖）。
- `OpenAICompatProvider`：`POST {base_url}/chat/completions`，头 `Authorization: Bearer <key>`；体 `{model, temperature, max_tokens, messages:[{role:"system",content:system},{role:"user",content:user}]}`；解析 `resp["choices"][0]["message"]["content"]`。覆盖 OpenAI / 兼容网关（vLLM、DashScope 兼容端点等）。默认 `base_url=https://api.openai.com/v1`（**须含 `/v1`**，拼接前去尾 `/`，避免缺版本段或双斜杠，P2-5）。
- **解析健壮性【P1-2 / P2-3】**：两 provider 解析前显式校验 `content`/`choices` 非空、首块含 `text` / `message.content`；任何缺键 / 空数组 / 异形块一律 → 抛 `LLMError(kind="parse")`，**绝不**让 `KeyError/IndexError/TypeError` 裸逃逸。

**HTTP 实现**：仅用标准库 `urllib.request`（`Request` + `urlopen(timeout=...)`）+ `json`，**零第三方依赖**（延续项目「Phase-3 零新依赖」传统）。封装 `_post_json(url, headers, payload, timeout) -> dict`，非 2xx（凭 `HTTPError.code` 判 4xx/5xx）/ `URLError` / `socket.timeout` / JSON 解析失败 **一律**抛 `LLMError(kind=...)`——即 provider 层保证**只有 `LLMError` 会向上逃逸**（配合 §3.5 `generate_work` 的兜底 `except Exception`，双保险守住「外部故障绝不冒泡成 5xx」，P1-2）。交互单步会叠加重试 `sleep`（默认 `0.5s+1s`），p99 由 `max_retries`×`timeout` 组合可控（P2-6）。

**`complete()` 客户端**（`services/llm/__init__.py`）：
- `is_enabled() -> bool`：`LLMConfig.from_env()` 解析成功且 `provider != "none"` 且 `api_key` 非空。
- `complete(system, user, *, max_tokens=None, temperature=None) -> LLMResult`：选 Provider → **有界重试循环**（`max_retries` 默认 2，指数退避 `0.5s, 1s`，仅对超时/5xx/网络类错误重试，对 4xx（鉴权/参数）不重试直接抛）→ 记结构化日志（provider、model、latency_ms、usage、retries）→ 成功返回 `LLMResult`。
- 数据结构：`LLMResult(text, model, provider, latency_ms, usage: dict|None)`；`LLMError(Exception)` 带 `.kind ∈ {config, http_4xx, http_5xx, timeout, network, parse}`。

### 3.4 Prompt 与上下文构建（`services/agent_prompts.py`）

- `ACTION_BRIEF: dict[tuple[str,str,str], str]`：**键与 `AGENT_FORWARD` 逐字一致**——`(entity, kind, current_status)`【P1-3：改用**当前态**而非目标态为键，保证与 `AGENT_FORWARD` 1:1、无碰撞、可穷举；原以 `to_status` 为键会让 `in_development→testing`（完成实现）与 `bug_fixing→testing`（修复缺陷）碰撞、语义合并丢失】。值为**该步骤的交付物说明**，**须覆盖全部 9 条前进边（含 `generic`）**：
  - `("requirement","dev","assigned")` → 「作为高级工程师，认领并给出实现方案：任务拆解、关键模块与接口、数据结构、边界与风险，说明本步已做什么、下一步交接给谁。」
  - `("requirement","dev","in_development")` → 「给出实现与自测结论、变更要点、遗留风险，说明可转测试的依据。」
  - `("requirement","dev","bug_fixing")` → 「针对测试打回的缺陷：给出根因、修复要点、回归自测结论。」
  - `("requirement","qa","testing")` → 「作为 QA，给出测试计划与用例（正常路径 + 至少一条异常路径）、执行结论与是否放行。」
  - `("bug","dev","assigned")` → 「认领缺陷，给出复现步骤与根因定位方向。」
  - `("bug","dev","fixing")` → 「给出根因定位、修复要点、回归自测结论。」
  - `("bug","qa","verifying")` → 「作为 QA，给出验证用例与结论、是否可关闭。」
  - `("requirement","generic","assigned")` / `("bug","generic","assigned")` → 「作为通用 Agent，认领并给出本步的处理说明与产物。」
  - **缺省兜底**：`build_context` 以 `ACTION_BRIEF.get(key, DEFAULT_BRIEF)` 取值，`DEFAULT_BRIEF`＝「针对本步目标态，作为该角色 Agent 给出简洁、聚焦、可交接的工作产物」——即便未来新增前进边漏配，也绝不把 `None`/空指引注入 prompt。
- `build_context(entity, ticket, agent, to_status) -> tuple[str, str]`：
  - **system**：定义 Agent 人格（dev-agent = 资深研发；qa-agent = 资深测试；generic = 通用协作 Agent）、平台背景（AI 时代协作平台，产出会进入工单协作时间线）、**输出规范**（简体中文、Markdown、克制精炼、聚焦本步产物）、**硬约束**：不得声称自己改变了工单状态（状态由平台裁决）、不得编造外部系统/链接、控制在约 `max_tokens` 内。
  - **user**：装配工单上下文——`title` / `description` / `priority|severity`（按 entity 取）/ `frm→to`（`frm=ticket.status`，因 §3.2 已把本调用置于改状态之前）/ **最近 N 条 feed 摘要**（复用 `Comment` 查询取该工单最近评论，给 LLM 以讨论上下文）+ 对应 `ACTION_BRIEF`（键 `(entity, agent.kind, ticket.status)`，缺失回落 `DEFAULT_BRIEF`）。
  - 缺省 N=6，单条截断到约 500 字，防 prompt 膨胀。

### 3.5 优雅降级与确定性回退（可靠性核心）

`agent_executor.generate_work` 决策表：

| 条件 | 行为 |
|------|------|
| `current_app.config["TESTING"]` 为真 | 直接返回 `fallback_message`（测试恒离线、无网络） |
| `llm.is_enabled()` 为假（无凭据） | 返回 `fallback_message`（开箱即用、离线可跑） |
| 启用且 `llm.complete` 成功且 `text.strip()` 非空 | 返回 `text.strip()` |
| 启用但 `complete` 抛 `LLMError` | `logger.warning` 记因，返回 `fallback_message` |
| 启用但返回空 / 超长 | 记 warning，返回 `fallback_message` |
| **启用但抛任何非预期异常【P1-2】** | **`generate_work` 以兜底 `except Exception` 捕获，`logger.warning` 记因，返回 `fallback_message`——保证任何外部/解析故障绝不冒泡成 5xx** |

**关键不变量**：无论 LLM 成败，`advance_one` 都返回一条**非空** body 的评论、都完成状态推进、都不抛异常给上层——`generate_work` 以**兜底 `except Exception`** 收口（外部/解析故障绝不冒泡成 5xx，P1-2）。这保证「不能有大的报错」，也保证既有断言 `assert body["comment"]["body"]` 恒真。

### 3.6 状态机不可侵犯

LLM 完全不参与「迁移到哪」的决策：`to` 恒取自 `AGENT_FORWARD`，并二次经 `workflow.can_transition` 防御复核。`AGENT_FORWARD` 的键值形状 `(to, message)` **保持不变**，`test_agent_forward_edges_are_all_legal`（遍历 `.items()` 解包 `(to, _msg)`）继续通过。

### 3.7 序列图（agent-advance，启用 LLM）

```
Client ──POST /api/{req|bug}/:id/agent-advance──▶ routes.do_agent_advance
  do_agent_advance ──▶ agent_runner.advance_one(entity, ticket, agent)
     advance_one ──plan()──▶ AGENT_FORWARD → (to, template)
     advance_one ──can_transition(frm,to)──▶ ✔
     advance_one 置 ticket.status=to, position
     advance_one ──▶ agent_executor.generate_work(...)
        generate_work ──_llm_active?──▶ 是 ──▶ agent_prompts.build_context()
        generate_work ──▶ llm.complete(system,user)
           llm.complete ──▶ Provider.complete ──urllib POST──▶ 模型网关
           （失败→重试/降级；成功→text）
        generate_work ◀── body(真实产物 或 template)
     advance_one 建 Comment(body) + Activity(template) ◀──
  do_agent_advance ──db.commit()──▶ notify_advance ──commit──▶ 200 JSON
```

### 3.8 并发 / 延迟 / 事务考量

- **事务与 SQLite 写锁【P1-1 修正】**：`generate_work` 只读（查 feed 上下文），不写库。**关键**：LLM 调用必须发生在**改 `ticket.status` 之前**（§3.2 接缝已如此排序）。原设计把 LLM 放在「已改 status、未 commit」窗口内是**错误**的——SQLAlchemy 会在随后任一查询处 autoflush 出 `UPDATE ticket`，对 SQLite 取 RESERVED 写锁；叠加本方案新加的 `threaded=True` 与默认文件库（`busy timeout=15s`），至多 30s 的 LLM 调用将**全程持锁**，任一并发写阻塞 15s 后抛 `database is locked` → 500。修正后：LLM 期间 session 无挂起写、零持锁；写事务窗口收敛为「改 status → 建评论 → commit」的亚毫秒区间，失败降级不回滚——语义安全。
- **延迟**：`run=all`（≤ `MAX_AGENT_STEPS=6` 步）与 `autorun-all`（整队，逐 Agent 串行、`runs` 每 Agent 一项）会串行多次调用，总延迟 = Σ 单步。单调用以超时 `AGENT_LLM_TIMEOUT`（默认 30s）封顶；默认 `AGENT_LLM_MAX_TOKENS=700` 压低单步耗时。
- **autopilot 时长硬上限【P2-1 加固】**：`autorun`/`autorun-all` 在 LLM 活跃时新增可选 wall-clock 预算 `AGENT_LLM_WALL_BUDGET`（默认 120s，`0`=不限）：单次调用累计 LLM 墙钟超预算即停止推进，其余单以 `reason="budget"` 计入 `skipped`（沿用 `agent_autopilot.autorun` 既有 skipped 语义，向后兼容）。此为编排层**唯一**新增——一处 `time.monotonic()` 预算判定；离线态步进近瞬时、预算永不触发，故 93 用例与默认行为**逐字节不变**。异步化仍列未来项（§8 R5）。
- **并发**：`agent.status="busy"` 软锁已串行化同一 Agent 的自主运行（并发触发 → 409）；本方案不引入新并发问题。
- **阻塞**：Flask dev server 单请求阻塞期间不应拖垮健康探针——`app.run` 增设 `threaded=True`（小而安全，见 §4）；配合本节首条的写锁收敛，`threaded` 下并发写不再被长 LLM 调用阻塞。

---

## 4. File / Module Change Plan（文件变更清单）

> 约束：单文件 ≤ 800 行、单函数 ≤ 50 行、参数 ≤ 5、嵌套 ≤ 4、圈复杂度 ≤ 10（遵 `CLAUDE.md`）。

| 文件 | 动作 | 一句话意图 |
|------|------|-----------|
| `backend/services/llm/__init__.py` | **新增** | LLM 公共 API：`is_enabled()`、`complete()`（含重试/日志）、导出 `LLMResult`/`LLMError` |
| `backend/services/llm/config.py` | **新增** | `LLMConfig` dataclass + `from_env()`：解析 `AGENT_LLM_*` 环境变量，计算 `enabled` |
| `backend/services/llm/providers.py` | **新增** | `AnthropicProvider` / `OpenAICompatProvider` + `_post_json`（urllib）+ `get_provider(cfg)` |
| `backend/services/agent_prompts.py` | **新增** | `ACTION_BRIEF` 表 + `build_context(entity,ticket,agent,to)`：装配 system/user 提示词与工单上下文 |
| `backend/services/agent_executor.py` | **新增** | `generate_work(entity,ticket,agent,to,fallback_message)` + `_llm_active()`：真实产物或优雅降级的唯一决策点 |
| `backend/services/agent_runner.py` | **修改** | `advance_one` 内评论正文改由 `agent_executor.generate_work` 提供；审计仍用短句；更新 docstring（「确定性离线」→「确定性回退 + 可选真实 LLM」）；**`AGENT_FORWARD` 键值形状不变** |
| `backend/app.py` | **修改** | `app.run(..., threaded=True)`；`/api/health` 附加 `llm:{enabled,provider,model}` 只读块（**additive**，不删既有键） |
| `backend/seed.py` | **修改（措辞）** | docstring/注释「mock 数据」→「示例种子数据」，澄清其为演示种子而非业务 Mock（逻辑不变） |
| `backend/tests/test_agent_executor.py` | **新增** | 覆盖：降级=模板、启用=LLM 正文、LLMError 降级、空返回降级、状态仍由状态机裁决、prompt 含工单上下文 |
| `backend/tests/test_llm.py` | **新增** | Provider 解析（Anthropic/OpenAI）、超时→LLMError、重试后成功、4xx 不重试、`is_enabled` 真值表 |
| `backend/README` 段 / `README.md` | **修改** | 新增 `AGENT_LLM_*` 环境变量表与「真实 vs 离线」说明 |
| `start-dev.ps1` | **修改（可选）** | 注释示范如何设置 `AGENT_LLM_API_KEY` 等（默认不设＝离线模式，开箱即用） |
| `frontend/lib/types.ts` · `.../health` 展示（可选打磨） | **修改（可选）** | 读取 `health.llm.enabled`，在 Agents 页/抽屉显示「AI 执行：真实/离线」小徽标（纯 additive，不改现有类型语义） |

**新增子包注册**：`services/llm/` 为标准包（含 `__init__.py`），`from services.llm import ...` 即可，无需改 `services/__init__.py`（现有 `from services import x` 用法不受影响）。

---

## 5. Interface Design（接口设计）

### 5.1 对外 REST（契约零破坏，仅一处 additive 增强）

- `POST /api/requirements/:id/agent-advance`、`POST /api/bugs/:id/agent-advance`（含 `?run=all`）：**请求/响应结构完全不变**。唯一可观测差异——启用 LLM 时 `comment.body` 从固定文案变为真实产物（既有断言仅校验 `body` 非空，兼容）。
- `POST /api/agents/:id/{claim-next,autorun,tick}`、`POST /api/agents/autorun-all`：**不变**（编排层未改）。
- `GET /api/health`（**additive**）：新增只读块，不删既有 `status/service/db`：
  ```json
  { "status":"ok","service":"aragonteam-backend","db":"ok",
    "llm": { "enabled": true, "provider": "anthropic", "model": "claude-opus-4-8" } }
  ```
  未配置时 `"llm": { "enabled": false, "provider": "none", "model": null }`。不回传任何密钥。

### 5.2 内部 Service 接口（新增，供实现严格照签名落地）

```python
# services/llm/config.py
@dataclass(frozen=True)
class LLMConfig:
    provider: str          # "anthropic" | "openai" | "none"
    api_key: str
    base_url: str
    model: str
    max_tokens: int
    temperature: float
    timeout_seconds: int
    max_retries: int
    @classmethod
    def from_env(cls) -> "LLMConfig": ...
    @property
    def enabled(self) -> bool: return self.provider != "none" and bool(self.api_key)

# services/llm/__init__.py
def is_enabled() -> bool: ...
def complete(system: str, user: str, *, max_tokens: int | None = None,
             temperature: float | None = None) -> "LLMResult": ...
@dataclass
class LLMResult:
    text: str; model: str; provider: str; latency_ms: int; usage: dict | None
class LLMError(Exception):
    def __init__(self, kind: str, detail: str): ...   # kind ∈ config|http_4xx|http_5xx|timeout|network|parse

# services/llm/providers.py
def get_provider(cfg: LLMConfig): ...                 # -> AnthropicProvider | OpenAICompatProvider
def _post_json(url, headers, payload, timeout) -> dict: ...

# services/agent_prompts.py
def build_context(entity: str, ticket, agent, to_status: str) -> tuple[str, str]: ...  # (system, user)

# services/agent_executor.py
# generate_work 恒返回非空正文；对 LLM 调用以 except Exception 兜底 → 任何失败降级 fallback（P1-2）。
def generate_work(entity: str, ticket, agent, to_status: str,
                  fallback_message: str) -> str: ...
def _llm_active() -> bool: ...                         # is_enabled() and not TESTING
```

### 5.3 环境变量（全部有默认值 → 未设即离线模式，开箱即用）

| 变量 | 默认 | 说明 |
|------|------|------|
| `AGENT_LLM_PROVIDER` | `none` | `anthropic` / `openai` / `none`；`none`＝离线（用确定性文案） |
| `AGENT_LLM_API_KEY` | 空（回退 `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`） | 模型凭据；为空即离线 |
| `AGENT_LLM_MODEL` | `claude-opus-4-8`（anthropic）/ `gpt-4o-mini`（openai） | 模型 ID |
| `AGENT_LLM_BASE_URL` | 各 provider 官方端点 | 自建/兼容网关覆盖点 |
| `AGENT_LLM_MAX_TOKENS` | `700` | 单步产物上限（控延迟/成本） |
| `AGENT_LLM_TEMPERATURE` | `0.4` | 采样温度 |
| `AGENT_LLM_TIMEOUT` | `30` | 单次调用超时（秒） |
| `AGENT_LLM_MAX_RETRIES` | `2` | 超时/5xx/网络错误的重试次数 |
| `AGENT_LLM_WALL_BUDGET` | `120` | 单次 autopilot 调用的 LLM 墙钟预算（秒）；超则其余单 `skipped(reason="budget")`；`0`=不限（P2-1） |

> **备注（P2-2 / P2-5）**：`AGENT_LLM_MODEL` 默认 `claude-opus-4-8` 追求质量；**autopilot 密集 / 整队场景建议改用更快更省的模型（如 Haiku 级）**以压低串行时延与成本。`AGENT_LLM_BASE_URL` 对 openai 兼容端点**须含 `/v1`**（默认 `https://api.openai.com/v1`），anthropic 默认 `https://api.anthropic.com`（内部再拼 `/v1/messages`）；两者拼接前统一**去尾 `/`**，避免双斜杠或缺版本段。

---

## 6. Data Model（数据模型）

**本方案零数据库 schema 变更**，理由与权衡：

- 项目无 Alembic 等迁移框架，建表靠 `db.create_all()`——它**只建缺失的表，不为既有表补列**。若给 `comments` 加列，老 `aragon.db` 不会自动 ALTER，将触发 `no such column` 运行期错误。为守住「稳健、无破坏」，**放弃新增列**。
- Agent 真实产物直接写入既有 `Comment.body`（`Text`，容量充足），复用既有 `author_type="agent"` 与 feed 合并逻辑——前端时间线**无需任何改动**即可渲染真实产物。
- **产物溯源信息**（provider / model / latency_ms / usage / 是否降级）不落库，改为写入**结构化日志**（`current_app.logger`，随 `X-Request-Id` 关联，见 `observability.py`），满足可观测与排障，且零 schema 成本。

**配置模型**：见 §5.2 `LLMConfig`（进程内内存对象，`from_env()` 解析；不落库）。

**内存 / 载荷形状**：`LLMResult`、`LLMError` 见 §5.2。评论与审计沿用既有 `Comment.to_dict()` / `Activity` 结构，字段不增不减。

---

## 7. Testing & Acceptance Criteria（测试与验收）

### 7.1 单元 / 集成测试（新增，均在 `TestConfig` 无网络下可跑）

`tests/test_agent_executor.py`：
1. `test_falls_back_to_template_when_disabled`：默认（TESTING）下 `generate_work` 返回 `fallback_message`；`agent-advance` 评论正文 == 模板。
2. `test_uses_llm_output_when_active`：monkeypatch `agent_executor._llm_active`→True、`agent_executor.llm.complete`→返回 `LLMResult(text="真实产物X")`；断言评论 `body == "真实产物X"` **且** `status` 仍 == `AGENT_FORWARD` 目标。
3. `test_llm_error_degrades_to_template`：`complete` 抛 `LLMError`；断言评论 == 模板、状态照常推进、HTTP 200（无 5xx）。
4. `test_empty_output_degrades`：`complete` 返回 `text=""`；断言回退模板。
5. `test_state_machine_still_authoritative`：即便 LLM 返回乱码，`to_status` 恒 == `AGENT_FORWARD` 目标（守圣域）。
6. `test_prompt_includes_ticket_context`：`build_context` 产出的 user 文本含标题/描述/目标态/ACTION_BRIEF。
7. `test_non_llmerror_exception_degrades`【P1-2】：monkeypatch `llm.complete` 抛 `KeyError`（模拟响应异形逃逸）；断言 `generate_work` 仍降级到模板、状态照常推进、HTTP 200（`except Exception` 兜底生效）。
8. `test_generic_and_missing_brief_have_default`【P1-3】：`generic` kind 边与「未配置的键」经 `build_context` 均得到**非空** `DEFAULT_BRIEF`，prompt 无 `None`/空指引。

`tests/test_llm.py`：
9. `test_anthropic_parse` / `test_openai_parse`：monkeypatch `urllib.request.urlopen` 返回罐头 JSON，断言 `LLMResult.text` 解析正确。
10. `test_malformed_response_raises_parse_llmerror`【P1-2 / P2-3】：`content=[]` / 首块非 text / 缺键 → `LLMError(kind="parse")`（**不**裸抛 `KeyError`）。
11. `test_timeout_raises_llmerror`：`urlopen` 抛 `socket.timeout` → `LLMError(kind="timeout")`。
12. `test_retry_then_success`：前 2 次超时、第 3 次成功 → 返回结果，且调用次数符合 `max_retries`。
13. `test_4xx_no_retry`：401 → 立即 `LLMError(kind="http_4xx")`，不重试。
14. `test_is_enabled_matrix`：`provider/api_key` 组合的 `enabled` 真值表。
15. `test_disabled_never_calls_network`：禁用时 monkeypatch `urlopen` 为「一旦被调即失败」，确认从不触网。

### 7.2 回归门禁（必须全绿）
- 后端：`cd backend && pytest -q` —— 既有 **93 用例** + 新增用例全部通过（无凭据环境）。
- 前端（若动可选项）：`npm run typecheck` 0 error、`npm run build` 通过。

### 7.3 验收标准（Definition of Done）
- **A1（去 Mock）**：§0 盘点的 M1/M2 已真实化——启用凭据时，dev/qa Agent 推进产出真实 LLM 工作产物（人工连一次真实模型冒烟：`agent-advance` 后评论正文为针对该工单的实质内容，非固定文案）。
- **A2（不破坏）**：无凭据/测试环境下行为与改造前逐字节一致；93 用例全绿；对外契约与响应结构不变。
- **A3（稳健）**：断网/超时/限流/空返回/**响应异形**下主流程不报错、不 5xx、工单照常推进（由 test 3/4/7/10 + 人工拔网验证；`generate_work` 兜底 `except Exception` 保证外部/解析故障绝不冒泡，P1-2）。
- **A4（圣域）**：`test_agent_forward_edges_are_all_legal` 及 test 5 通过——迁移仅由状态机裁决。
- **A5（可观测/好用）**：`GET /api/health` 反映 `llm.enabled`；日志含每次 LLM 调用的 provider/model/latency/降级原因。

---

## 8. Risks & Mitigations（风险与缓解）

| # | 风险 | 影响 | 缓解 |
|---|------|------|------|
| R1 | 既有 DB 加列破坏老库 | 运行期 `no such column` | **不加列**（§6），产物写既有 `Comment.body`，溯源进日志 |
| R2 | 改 `AGENT_FORWARD` 形状破坏结构性单测 | `test_agent_forward_edges_are_all_legal` 红 | 保持 `(to, message)` 形状；`message` 复用为审计短句 + 降级兜底 |
| R3 | 测试联网/需要真凭据导致 CI 不稳 | 93 用例不可复现 | `_llm_active()` 在 `TESTING` 恒 False；真实路径测试用 monkeypatch 注入假 `complete`，绝不触网 |
| R4 | LLM 超时/限流/网络抖动/**响应异形** | 主流程报错、5xx | 超时 + 有界重试 + **全路径优雅降级**到模板；provider 只逃逸 `LLMError` + `generate_work` 兜底 `except Exception`（P1-2），异常绝不冒泡（test 3/4/7/10） |
| R5 | `run=all`/`autorun-all` 串行多次调用致延迟高 | 请求久、超浏览器/网关超时 | `MAX_AGENT_STEPS=6` × 每步超时封顶；autopilot 可选 wall-clock 预算 `AGENT_LLM_WALL_BUDGET`（默认 120s，超则 `skipped(reason="budget")`，P2-1）；默认 `max_tokens=700`；`app.run(threaded=True)` 防阻塞探针；异步化列未来项 |
| R6 | Prompt 注入（工单标题/描述含恶意指令） | Agent 产出被操纵 | system 提示固化人格与硬约束（不得改状态、不得编造）；产物仅为文本评论，不触发任何副作用/执行 |
| R7 | 密钥泄露 | 安全事故 | 密钥仅从 env 读；`health`/响应/日志**从不回传密钥**——结构化日志只记 provider/model/latency/usage/retries/降级因，**绝不**记 `Authorization`/`x-api-key` 头与请求 payload（P2-4）；`.env`/密钥不入库不提交（`.gitignore` 已忽略 `aragon.db` 等） |
| R8 | 新增第三方 SDK 带来供应链/许可风险 | 依赖膨胀 | **仅用标准库 `urllib`**，零新增依赖（延续项目传统） |
| R9 | 引入 service→service 循环 import | 启动即崩 | 依赖单向：`agent_runner → agent_executor → {llm, agent_prompts, models}`；`agent_prompts/executor` 不反向 import `agent_runner`/`autopilot` |
| R10 | 长文产物撑爆 feed/前端 | 渲染卡顿 | `max_tokens` 上限 + 产物为 Markdown，前端既有时间线已可滚动展示；必要时后续加折叠（未来项） |
| R11 | LLM 调用持 SQLite 写锁致并发 `database is locked` | 并发下 500、主流程报错 | **改状态前**调 LLM（§3.2/§3.8 P1-1）：LLM 期间零挂起写、不持写锁；写事务收敛到 commit 前亚毫秒窗口，`threaded=True` 下并发写不再被阻塞 |

---

## 9. 实施顺序（供 Subtask #2 逐步落地）

1. `services/llm/config.py`：`LLMConfig` + `from_env()`（先让 `is_enabled()` 可判定）。
2. `services/llm/providers.py`：`_post_json` + 两个 Provider + `get_provider`。
3. `services/llm/__init__.py`：`is_enabled()` + `complete()`（重试/日志/异常）。
4. `tests/test_llm.py`：Provider/重试/超时/真值表（此时可独立跑绿）。
5. `services/agent_prompts.py`：`ACTION_BRIEF` + `build_context`。
6. `services/agent_executor.py`：`generate_work` + `_llm_active`（降级决策表）。
7. `services/agent_runner.py`：接缝改 1 行取正文 + 更新 docstring（勿动 `AGENT_FORWARD` 形状）。
8. `tests/test_agent_executor.py`：真实/降级/圣域/上下文。
9. `app.py`：`threaded=True` + health `llm` 块；`seed.py` 措辞澄清。
10. `README.md`（+ `start-dev.ps1` 可选）：环境变量与「真实/离线」说明。
11. 全量回归：`pytest -q`（93 + 新增）全绿；如动前端可选项再 `typecheck`/`build`。

## 10. 兼容性与回滚

- **默认离线、开箱即用**：不设任何 `AGENT_LLM_*` 即为今日行为；升级无感。
- **一键回滚**：置 `AGENT_LLM_PROVIDER=none`（或清空 `AGENT_LLM_API_KEY`）即回退确定性文案，无需改码、无需迁移、无需重启依赖。
- **契约稳定**：对外 REST 响应结构不变，唯一 additive 是 `health.llm` 只读块与 `comment.body` 内容变真——均向后兼容。

---

*（文档版本 v2 · Subtask #1 评审已补「评审记录 / 评审结论」，P0/P1 已在正文修复）*

---

## 评审结论（Review Verdict）

**结论：有条件通过（Approved with Conditions）。**

方案的核心判断经逐文件核验**成立且扎实**：全项目唯一的业务 Mock 是 Agent 执行引擎（M1/M2），前端无假数据；在 `agent_runner.advance_one` 单一接缝接真实 LLM、状态迁移仍由状态机独裁、无凭据/测试/失败一律优雅降级到确定性文案——这一「有凭据则真、无凭据则稳」的双模设计既契合「去 Mock、稳健可靠好用」的全局目标，又守住了 `CLAUDE.md` 的三条硬约束（状态机是圣域、向后兼容零 schema 迁移、`pytest -q` 全绿），且零新增第三方依赖、零数据库变更。**无 P0**。

评审发现的 **3 个 P1 已在本文 v2 正文直接修复**，无遗留：

1. **P1-1（SQLite 写锁窗口）**——接缝重排为「先产出正文再改状态」，将持写锁时长从「≈LLM 往返」压到亚毫秒（§3.1/§3.2/§3.8/§8 R11）。
2. **P1-2（非 LLMError 冒泡 5xx）**——provider 层统一把解析/网络/HTTP 失败包成 `LLMError`，`generate_work` 再加兜底 `except Exception`，双保险守住「外部故障绝不冒泡」（§3.3/§3.5/§5.2/§8 R4，新增 test 7/10）。
3. **P1-3（ACTION_BRIEF 键碰撞/缺覆盖）**——改用与 `AGENT_FORWARD` 逐字一致的 `(entity,kind,current_status)` 键、补齐全部 9 条边含 `generic`、缺失回落 `DEFAULT_BRIEF`（§3.4，新增 test 8）。

**放行条件（落地 Subtask #2 必须遵守）**：

- **C1**：实现严格照 v2 接缝次序——**LLM 调用先于任何会 autoflush 的写/查询**，不得回退到「先改 status 再调 LLM」。
- **C2**：`generate_work` 必须以 `except Exception` 兜底且 provider 只逃逸 `LLMError`；须落地 test 7、test 10 佐证「任何异常/异形响应均降级、不 5xx」。
- **C3**：`ACTION_BRIEF` 须覆盖 9 条边并提供 `DEFAULT_BRIEF`；须落地 test 8。
- **C4（建议项 P2，强烈推荐）**：落地 `AGENT_LLM_WALL_BUDGET` 预算保护（P2-1）；autopilot 密集场景文档提示改用低时延模型（P2-2）；日志严禁记密钥/鉴权头（P2-4）；`base_url` 拼接去尾 `/` 并保证 openai 含 `/v1`（P2-5）。
- **C5（不可谈判底线）**：无凭据/测试环境下行为与改造前**逐字节一致**，既有 **93 用例全绿**；新增用例一律 monkeypatch、绝不触网。

满足以上条件即视为完全达标，可进入 Subtask #2 编码。

---

## 实施过程发现的方案缺陷（Issues Found During Implementation · Subtask #2）

> 记录 Subtask #2（编码）落地时发现的方案不一致，并说明采取的纠正做法（遵「不静默偏离」约束）。

### I1 —— §4 文件变更清单遗漏 `backend/services/agent_autopilot.py`（已按正文修正）

- **现象**：C4 / P2-1 与正文 §3.1、§3.8、§8 R5 明确要求在 **autopilot 编排层**新增可选墙钟预算
  `AGENT_LLM_WALL_BUDGET`（"编排层唯一新增——一处 `time.monotonic()` 预算判定"），但 §4「File /
  Module Change Plan」表**未列** `agent_autopilot.py` 一行，二者不一致。
- **裁定与处置**：以正文 + 放行条件 C4 为准（强烈推荐落地）。已在 `agent_autopilot.autorun` 增设
  **单点、离线零触发**的预算判定：`budget = agent_executor.wall_budget_seconds()`（离线 / 测试 /
  未配置恒 `None`）+ 每张单前 `_over_budget(budget, started)`，超预算的其余单以 `reason="budget"`
  记入既有 `skipped`（沿用其语义，向后兼容）。因 `_llm_active()` 在 `TESTING` 恒 False，`budget`
  恒 `None`、`_over_budget` 恒 False，**93 用例与默认离线行为逐字节不变**。
- **影响面**：仅 `agent_autopilot.py` 增 `import time`、`from services import ... agent_executor`、
  一处预算判定与一个私有 `_over_budget` 助手；不改任何对外契约与响应结构。

### I2 —— §4 可选项 `frontend/lib/types.ts` 徽标未实现（有意从简）

- §4 将「读取 `health.llm.enabled` 在前端显示『AI 执行：真实/离线』小徽标」明确标注为 **可选打磨**。
  为「保持 diff 聚焦、不引入非必要前端改动」，本轮**未实现**该纯装饰项；后端 `health.llm` 只读块已就位，
  前端如需徽标可后续零风险追加（additive）。此为**有意的范围收敛**，非遗漏。
