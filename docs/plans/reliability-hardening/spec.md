# AragonTeam 稳健化收官 — 「每个功能都不报错、每个客户端页面都能正确使用」（Spec）

- **文档版本**: **v2**（Subtask #1「方案评审与修复」已逐节四维评审并就地修复 P0/P1；见文首「## 评审记录」与文末「## 评审结论」。v1 由 Subtask #0 · Solution Architect 产出）
- **Feature slug**: `reliability-hardening`
- **作者角色**: Solution Architect（Anthropic Engineering）
- **本轮需求（第 2 轮）**: 「继续完善所有主要功能，确保每个功能都不报错，客户端页面都能够正确使用。」
- **全局目标**: 「完成对应的开发，确保稳健可靠好用，顶级。」
- **基线**: 建立在已合入的 8 个里程碑之上（MVP → Phase-2 → Phase-3 → 真实 Agent 执行 → 账号自助中心 → 全局搜索 → @提及自动补全 → 管理台建改闭环，最新 commit `529686b`）。**本轮不新增任何业务功能、不新增数据库表、不新增运行时依赖**，只做**面向缺陷的稳健化加固**——把「点了会 500 / 换页会崩 / 后端抖动就卡骨架 / 无权却给按钮」这些真实缺口逐一堵住。
- **技术栈（沿用，零新增依赖）**: Next.js 14 App Router + React 18 + TypeScript + Tailwind + @dnd-kit + SWR ｜ Flask 3 + SQLAlchemy 2 + SQLite + flask-jwt-extended + Flask-CORS ｜ 后端 LLM 层仅用标准库 `urllib`。
- **目标读者**: 下游开发工程师（须可据此逐行实现，无需再做架构决策）。

---

## 评审记录（Review Notes · Subtask #1）

> 评审方式：以「资深评审」视角，对 v1 逐节做四维评审（**可行性 / 完备性 / 一致性 / 合理规模**），并对文档所有 `file:line` 引用与行为断言**在现网代码上逐一核验**（读了 `routes/{auth,requirements,agents,me,comments}.py`、`services/{workflow,pagination,search,agent_runner}.py`、`models/{activity,agent}.py`、`errors.py`、`frontend/{lib/api.ts,app/(app)/agents/page.tsx,app/(app)/requirements/page.tsx}` 等）。核验结论：**v1 的两个核心缺陷（前端 SWR key 形状冲突崩溃、后端 JSON 边界 500）完全属实、定位精确、修复方向正确**；同时发现下列需就地修正的偏差。P0/P1 均已在本 v2 正文修复。
>
> **核验为真、无需改动的关键断言**（供实现者放心据此落地）：`requirements/page.tsx:69` 在无筛选时 `listKey` 恰为 `/requirements`，与 `agents/page.tsx:36` 的 `swrFetcher("/requirements")` 同键异形 → `workload()` 对 `{items,total}` 调 `.filter` 崩溃（**P0 属实**）；`move` 的 `is_valid_status` 走 `status in _table`（dict）→ 非串 `unhashable` 500（**属实**，`services/workflow.py:74-75`）；`patch_agent` 可置 `busy`（`busy ∈ AGENT_STATUSES`）→ autopilot 死锁（**属实**，B3 有效）；`errors.py:45-48` `invalid_token_loader` 确为 **422**（C2 属实；但 `revoked_token_loader` 现已是 401，见 R6）；列表端点 `assignee_type=agent` 可**单独**作为过滤项（`requirements.py:146-147`，§2.5-A1 假设 (a) **成立**）。

| 编号 | 维度 | 严重度 | 位置 | 问题 | 处置 |
|---|---|---|---|---|---|
| R1 | 可行性 / 一致性 | **P1** | §2.3-B2 | `agent-advance` 的 `NoAgentAction` **现已返回 409**（`routes/requirements.py:440-442`），并非 500；「改 200 `{advanced:false}`」既非必要、又破坏既有 `test_agent_*` 对 409 的断言、且吞掉「越界」信号（违反 CLAUDE.md「错误显式传播」）。所谓「并发触发 `advance_one` 的 `RuntimeError` 复核 → 500」**不可复现**：该复核只在 `AGENT_FORWARD` **静态配置**出非法边时抛出（`ticket.status` 读一次同时用于查表与复核，并发无从触发），为其加 `except RuntimeError` 反而违反 CLAUDE.md「不为理论上不会发生的分支写防御 try/except」。 | 已在 §2.3-B2 / §4 / §6.1 / §3 就地重写：**保持既有 409、不改码**；真正可复现的并发 500（SQLite 写锁争用）诚实降级为 dev-only 已接受风险（生产 Postgres 行级锁化解），记 `# TODO(advance-concurrency)`。 |
| R2 | 可行性 | **P1** | §2.5-A1 / §3.3 / §4 / §6 | `limit=500` 会被 `services/pagination.py` 的 `MAX_LIMIT=200` **静默钳到 200**（已核验），主方案给出一个达不到的数值，未真正修复「负载截断」。 | 已改为 `limit=200`（即分页上限），并诚实标注「>200 个 agent 指派单仍会截断，属当前规模可接受」；**不**上调 `MAX_LIMIT`（共享契约，避免连带影响）。 |
| R3 | 一致性 / 完备性 | **P1** | §2.2.3 表 | 「修复的失败场景」列**高估**了枚举字段的 500 风险：`ROLES/PRIORITIES/SEVERITIES/AGENT_KINDS/AGENT_STATUSES/ASSIGNEE_TYPES` 均为 **tuple**，`x not in tuple` 用 `==` 比较，**非串/非法值不会 500，本就返回 400**。真正的 500 向量是：① 非对象体 → `.get` AttributeError；② `(truthy 非串) .strip()`；③ 非标量主键进 `db.session.get`；④ `check_password`/`@提及正则` 收非串；⑤ `status in _table`（dict）。 | 已在 §2.2.3 表订正各行「失败场景」，明确 `choices` 字段的 `want_*` 是「归一/清洁」而非「堵 500」；测试计划（§6.1）改为对**真正会 500** 的字段取负例，避免假绿。 |
| R4 | 一致性 / 合理规模 | **P1** | §2.2.3 注 | 对 `assign` 的 `assignee_id` 强加 `want_int` 会**回退**既有 `_validate_assignee` 的数字串容忍（现 `int(assignee_id)` 接受 `"5"`），违反本轮自定的「严格向后兼容」不变量；且 `_validate_assignee` 已完成类型+存在性校验（无 500）。 | 已改：`assign` **保持既有 `_validate_assignee`**，仅在体层加 `json_body()`（防非对象体 500）；不重复 `want_int`。 |
| R5 | 完备性 | P2 | §2.4-C3 / §5 | `Activity.log` 截断写 `(message or "")[:255]` 会把合法的 `message=None` 强转为 `""`（该列 `nullable=True`），改变语义。 | 已改为**保 None** 的截断：`message[:255] if isinstance(message, str) else message`。 |
| R6 | 一致性 / 准确性 | P2 | §2.4-C2 | 文案称「`revoked_token_loader` 若有改 401」——现网 `revoked_token_loader` **已是 401**（`errors.py:54-56`），仅 `invalid_token_loader` 需 422→401。 | 已在 §2.4-C2 澄清：只改 `invalid_token_loader` 一处。 |
| R7 | 准确性 | P2 | §6.1 / §6.4 / §3.2 | 测试基线「现 168 用例」不准；`pytest --collect-only` 实测为 **179**（CLAUDE.md 的「93」亦为早期陈旧值）。 | 已把全文测试基线订正为 **179**。 |
| R8 | 合理规模 / 决策 | P2 | §2.4-C5 | 「`GET /api/users` 邮箱可见性」被留给评审裁决。 | **评审裁定：有意保留**——内部团队协作工具，组织内成员邮箱可见属可接受设计；不纳入本轮，记 `# TODO(users-email-visibility)` 备产品复核。 |
| R9 | 完备性（正向确认） | — | §2.2.3 / §7 | 全仓 `grep "get_json(silent=True) or {}"` 命中 **8 个写路由文件共 24 处**（auth/users/agents/projects/requirements/bugs/comments/me），与 §2.2.3 覆盖面**一致**；`board/stats/search/notifications` 不解析体，无遗漏。 | 无需改动，记录以佐证覆盖完整。 |

**评审总评**：范围克制、零新表零新依赖、向后兼容——**合理规模，未过度设计**。核心 P0 判断精准。上述 P1 均为「实现细节与既有代码的对齐偏差」，已就地修复；不动摇任何主线设计。

---

## 0. 背景：为什么需要这一轮

前 7 个迭代把 AragonTeam 从「可运行骨架」推进到「自主协作的研发中枢 + 真实 Agent 执行 + 全套管理台/搜索/@提及/账号中心」。功能面已足够宽，`routes/__init__.py` 注册了 12 张蓝图（`auth users agents projects requirements bugs board stats comments notifications me search`，见 `backend/routes/__init__.py:16-30`），前端 17 个页面 + 30+ 组件全部就位。**契约层是健康的**：一次全量交叉核对确认——前端每一个 `api.*` / SWR / `listFetcher` 调用的 URL、方法、响应字段都能在后端找到对应实现，**没有 404、没有缺失端点、没有 mock/占位残留**（唯一的字面量是登录页刻意保留的演示账号提示 `frontend/app/login/page.tsx:12-17`）；状态机 `services/workflow.py::can_transition` 是迁移合法性的唯一裁决，无任何旁路；LLM 层在无凭据/超时/5xx/空响应各失败模式下都能优雅降级、不冒泡 5xx。

但「功能都在、契约都对」不等于「都不报错、都能用」。对现网代码做的一次系统性缺陷审计（前端 + 后端各一遍逐文件走查）暴露出**两类真实、可复现的缺陷**，正是本轮要收口的对象：

1. **后端「输入类型」边界失守 → 可复现 500（含公开接口）。** 全后端写路径普遍用 `data = request.get_json(silent=True) or {}` 取体、再用 `(data.get(k) or "").strip()` 取字段（例如登录 `backend/routes/auth.py:15-17`）。这套写法只防「字段缺失」，**不防「类型错误」**：一个格式合法但非对象的 JSON 体（`5` / `[1]` / `"x"`）是**真值**，`data.get(...)` 变成 `list.get` → `AttributeError`；一个非字符串字段（`{"username":123}`）是**真值**，没有 `.strip()` → `TypeError`。两者都在边界处冒泡成 **500**，且 `POST /api/auth/login` **无需登录即可触发**——这是「稳健可靠」最刺眼的反例。
2. **前端「SWR 缓存形状冲突」→ 正常翻页即崩溃。** Agents 页用 `useSWR<Requirement[]>("/requirements", swrFetcher)`（`frontend/app/(app)/agents/page.tsx:36`，`swrFetcher` 回**裸数组**），而需求列表页用**同一个 key** `"/requirements"` 配 `listFetcher`（`frontend/app/(app)/requirements/page.tsx:69-70`，回 `{items,total}` **对象**）。SWR **纯按 key 缓存**，用户「先开需求列表（默认无筛选，key 恰为 `/requirements`）再开 Agents 页」时，Agents 页会同步拿到 `{items,total}` 对象，`workload()` 里 `(reqs ?? []).filter(...)`（`agents/page.tsx:59`）对对象调用 `.filter` → `TypeError: filter is not a function` → 触发错误边界，**整页崩**。反向路径则让列表页显示「共 undefined 条」。

围绕这两类核心缺陷，加上一批「后端在坏输入/并发下会 500」「前端后端抖动就永久卡骨架」「无权用户却看到写按钮（点了必 403）」的次级缺口，本轮做一次**收敛式加固**：**一个新的输入校验模块 + 若干处就地防御**把后端的 500 归零，**一条 SWR key/fetcher 形状一致性规则 + 全页 error 态**把前端崩溃与卡死归零，**按权限门禁写操作按钮**把「可见即可用」补齐。范围克制、零新表、零新依赖、严格向后兼容。

---

## 1. Overview（概述）

**本轮的唯一主题是「稳健」：让每一个已存在的功能在正常路径、异常输入、并发与后端抖动下都不产生未捕获错误，让每一个客户端页面在任意导航顺序下都能正确渲染与操作。** 它不追加任何新业务能力，而是把前 7 轮快速堆叠出来的功能面「焊死」——凡是「点了会崩 / 会 500 / 会卡死 / 会误导」的地方，一处不留。衡量标准是硬的：后端在坏输入与并发下**不返回 5xx**（该 400 的返回 400、该 409 的返回 409），前端在任意页面切换顺序与后端错误下**不抛未捕获异常、不永久卡骨架**，无权用户**看不到会必然 403 的写按钮**。

技术路线遵循本仓库一贯的「稳健取向」与 `CLAUDE.md` 的清洁代码红线：**在边界处一次性校验、错误显式传播、不散落防御、不过度设计**。后端侧的核心动作是把「取 JSON 体 / 取受校验字段」从 12 个路由里重复且脆弱的手写片段，收敛成一个**可复用、可单测**的 `services/validation.py` 边界模块——所有类型错误统一走既有的 `{error, detail}` JSON 400 契约，而不是冒泡 500；这一个模块即可根治 1 个 P0 与 4 个 P1 后端缺陷。前端侧的核心动作是确立并落实一条不变量——**「一个 SWR key 在全应用只能对应一种 fetcher 返回形状」**——据此拆开 Agents 页与列表页的 key 冲突，并顺带修掉由同一根因导致的「共 undefined 条」与「工单负载被分页截断到 50」。其余为一批低风险、机械化的就地加固。

**关键不变量（下游必须保持，任何实现都不得违反）**：

1. **状态机仍是圣域**：所有工单状态变更仍且只经 `services/workflow.py::can_transition` 裁决（见 `CLAUDE.md`「State machine is sacred」）。本轮不新增、不修改任何迁移边，只是让「拿到非法/异常输入时」以 4xx 优雅拒绝而非 500。
2. **向后兼容**：不新增数据库表（延续「唯一新表是 Phase-3 `notifications`」的历史）、不新增前后端运行时依赖、不改动任何**成功路径**的请求/响应 shape。唯一的对外可见变化是**两处「变得更对」的错误码**（坏输入 500→400、无效 JWT 422→401，见 §4），二者都不会破坏任何既有正常用法。
3. **不过度设计**：只堵审计发现的真实缺口，不借机重构。新增代码集中在一个校验模块与一个前端错误态组件；其余均为就地小改。

---

## 2. Technical Design（技术设计）

### 2.1 架构增量（Delta）

```
后端 backend/
  ＋ services/validation.py      ← 新增：json_body() + want_str/want_int/want_bool + ValidationError
  ＋ errors.py                    ← 改：注册 ValidationError→400 处理器；无效 JWT 422→401
  ＋ routes/{auth,users,agents,projects,requirements,bugs,comments,me}.py
                                   ← 改：用 json_body()/want_* 替换 `get_json() or {}` + `(x or "").strip()`
  ＋ routes/{requirements,bugs}.py← 改：list 过滤 q= 复用 search 的 LIKE 转义（agent-advance 经核验已正确，〔R1〕不改）
  ＋ routes/agents.py             ← 改：patch_agent 禁止手动置 busy
  ＋ services/search.py           ← 改：导出 escape_like() 供列表过滤复用
  ＋ models/activity.py           ← 改：Activity.log 截断 message 到 255（跨库安全）
  ＋ services/llm/providers.py    ← 改：decode 异常归一为 LLMError（守住「仅 LLMError 逃逸」契约）

前端 frontend/
  ＋ lib/api.ts（约定）           ← 不变；确立「一个 key 一种 fetcher 形状」不变量
  ＋ components/ui/ErrorState.tsx ← 新增：内联错误 + 重试（onRetry=mutate）
  ＋ app/(app)/agents/page.tsx    ← 改：改用不冲突的 key + listFetcher，修负载截断
  ＋ app/(app)/{requirements,bugs,my-work,projects,dashboard,notifications}/page.tsx
                                   ← 改：读 error 渲染 ErrorState（消灭永久卡骨架）
  ＋ components/TicketDrawer.tsx  ← 改：写操作按钮按 can_manage/pm-admin 门禁；convert 跳转直达
  ＋ app/(app)/requirements/board/page.tsx ← 改：转 BUG 后用 ?ticket= 而非死参 ?highlight=
  ＋ components/layout/GlobalSearch.tsx     ← 改：回车无选中行时跳到「真有命中」的分组
  ＋ components/ui/Badge.tsx      ← 改：style 缺省兜底，避免枚举越界崩溃
  ＋ components/settings/ProfileCard.tsx    ← 改：颜色从真实值初始化，避免无操作也写色
  ＋ hooks/useNotificationPreferences.ts    ← 改：切换失败向上抛出以触发 toast
```

**无新增数据库表、无新增第三方依赖。** 所有后端错误分支仍走 `errors.py` 的统一 JSON 契约。

### 2.2 后端加固 A：JSON 输入边界校验（核心 · P0 + 4×P1）

这是本轮**收益最高**的单点改造：一个模块根治「坏输入 → 500」整类问题。

#### 2.2.1 新增 `services/validation.py`

```python
"""统一 JSON 输入边界校验（本轮硬化新增）。

【为什么】既有路由用 `request.get_json(silent=True) or {}` + `(data.get(k) or "").strip()`，
只防「字段缺失」，不防「类型错误」：非对象 JSON 体（5/[1]/"x"）为真值 → .get 触 AttributeError；
非字符串字段（123）为真值 → .strip()/正则触 TypeError；均在边界冒泡成 500（含公开 /login）。
本模块把「拿到一个 dict」「取一个受校验字段」收敛为可复用、可单测的边界函数，
错误统一走 400 JSON 契约 {error, detail:{field, expected}}，绝不 500。
"""
from typing import Optional, Iterable
from flask import request


class ValidationError(Exception):
    """边界校验失败 → 由 errors.py 统一渲染为 400。稳定异常类，勿更名（对外错误契约）。"""
    def __init__(self, message: str, *, field: Optional[str] = None, expected: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.field = field
        self.expected = expected


def json_body() -> dict:
    """始终返回 dict：非 JSON / 非对象体一律回 {}（缺字段交由各字段的必填/默认校验）。"""
    d = request.get_json(silent=True)
    return d if isinstance(d, dict) else {}


def want_str(data: dict, key: str, *, required: bool = False, default: str = "",
             strip: bool = True, max_len: Optional[int] = None,
             choices: Optional[Iterable[str]] = None) -> str:
    v = data.get(key, None)
    if v is None:
        if required:
            raise ValidationError(f"{key} is required", field=key, expected="non-empty string")
        return default
    if not isinstance(v, str):
        raise ValidationError(f"{key} must be a string", field=key, expected="string")
    if strip:
        v = v.strip()
    if required and not v:
        raise ValidationError(f"{key} is required", field=key, expected="non-empty string")
    if max_len is not None and len(v) > max_len:
        raise ValidationError(f"{key} is too long", field=key, expected=f"length<={max_len}")
    if choices is not None and v and v not in set(choices):
        raise ValidationError(f"{key} is invalid", field=key, expected=f"one of {sorted(set(choices))}")
    return v


def want_int(data: dict, key: str, *, required: bool = False, default: Optional[int] = None,
             minimum: Optional[int] = None, maximum: Optional[int] = None) -> Optional[int]:
    v = data.get(key, None)
    if v is None:
        if required:
            raise ValidationError(f"{key} is required", field=key, expected="integer")
        return default
    # bool 是 int 子类，需显式排除；不接受数字字符串（JSON 体应传数字）。
    if isinstance(v, bool) or not isinstance(v, int):
        raise ValidationError(f"{key} must be an integer", field=key, expected="integer")
    if minimum is not None and v < minimum:
        raise ValidationError(f"{key} is out of range", field=key, expected=f">={minimum}")
    if maximum is not None and v > maximum:
        raise ValidationError(f"{key} is out of range", field=key, expected=f"<={maximum}")
    return v


def want_bool(data: dict, key: str, *, default: bool = False) -> bool:
    v = data.get(key, None)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise ValidationError(f"{key} must be a boolean", field=key, expected="boolean")
    return v
```

> **query-param 侧（可选，若审计确认 limit/offset/assignee_id 无 try/except）**：追加 `want_int_arg(name, *, default, minimum=None)`，内部 `try: int(request.args.get(name, ""))` 失败 → `ValidationError`，供列表过滤的 `assignee_id/reporter_id/limit/offset` 复用（`request.args` 的值恒为字符串，与 JSON 体分开处理）。若 `services/pagination.py` 已对 `limit/offset` 做了 try/except，则仅需覆盖新增的 `assignee_id/reporter_id`。

#### 2.2.2 `errors.py`：注册 400 处理器（在 `register_error_handlers(app, jwt)` 内）

```python
from services.validation import ValidationError

@app.errorhandler(ValidationError)
def _on_validation_error(e: ValidationError):
    body = {"error": e.message}
    if e.field is not None:
        body["detail"] = {"field": e.field, "expected": e.expected}
    return jsonify(body), 400
```

#### 2.2.3 逐路由替换（把脆弱写法换成 `json_body()` + `want_*`）

对每个 POST/PATCH 处理器，把开头的 `data = request.get_json(silent=True) or {}` 换成 `data = json_body()`（**这一步是普适的 P0 修复**：非对象体 `5`/`[1]`/`"x"` 现会让后续 `data.get(...)` 抛 `AttributeError` → 500，`json_body()` 归一为 `{}` 后交由字段级校验）；再把每处 `(data.get(k) or "").strip()` / 直接 `data[k]` 换成对应的 `want_*`。

**〔R3 订正〕关于「失败场景」列的准确口径**：经核验，本仓所有枚举（`ROLES/PRIORITIES/SEVERITIES/AGENT_KINDS/AGENT_STATUSES/ASSIGNEE_TYPES`）均为 **tuple**，`x not in tuple` 走 `==` 比较——**非串/非法枚举值不会 500，现状本就返回 400**。因此 `choices` 字段的 `want_str(choices=…)` 属于**归一与清洁**（集中类型判定、错误体统一为 `{error,detail}`），**并非在堵 500**。**真正会 500 的向量**只有：① 非对象体（→ `json_body()`）；② `(truthy 非串).strip()`（title/name/username/display_name/body 等）；③ 非标量主键进 `db.session.get`（`project_id`/`related_requirement_id`）；④ `check_password`/`@提及正则` 收非串。下表「失败场景」已按此订正。

**逐字段替换清单**（下游据此逐行替换，不再做判断）：

| 文件:行（现状） | 字段 | 替换为 | 真实失败场景（→ 现状） |
|---|---|---|---|
| `routes/auth.py:15-17` login | `username`/`password` | `want_str(data,"username",required=True)` / `want_str(data,"password",required=True,strip=False)` | 体传 `5` → `.get` **500**（公开接口）；`{"username":123}` → `.strip()` **500** |
| `routes/auth.py:54-59` register | `username`/`password`/`display_name`；`role`(choices=ROLES,归一)/`email`(required=False) | 同上 + `role` 用 `choices`；`email` 用 `want_str(...,required=False)` | 非串 `username`/`display_name` → `.strip()` **500**（`role` 现已 400，属归一）|
| `routes/users.py:26,68-69` create/patch user | `username`/`display_name`/`password`；`role`(choices=ROLES,归一) | `want_str/want_str(choices=ROLES)` | 非串 `username`/`display_name` → `.strip()` **500** |
| `routes/requirements.py:169,184,229` create/patch | `title`(required,max_len=200)/`description`；`priority`(choices,归一) | `want_str` | 非串 `title` → `.strip()` **500**（`description` 直接赋值、`priority` tuple 现已 400）|
| `routes/requirements.py:103` create | `project_id` | `want_int(data,"project_id")` | list/dict 主键 → `db.session.get` **500** |
| `routes/bugs.py:71,82,90,134` create/patch | `title`/`description`；`severity`(choices,归一)/`related_requirement_id`(want_int) | `want_str`/`want_int` | 非串 `title` → `.strip()` **500**；list `related_requirement_id` → `db.session.get` **500** |
| `routes/agents.py:41,77` create/patch | `name`(required)；`kind`(choices,归一) | `want_str(choices=…)` | 非串 `name` → `.strip()` **500**（`kind`/`status` tuple 现已 400；`status` 另见 §2.3-B3）|
| `routes/projects.py:24-25` create | `name`(required)/`key` | `want_str` | 非串 `name`/`key` → `.strip()` **500** |
| `routes/comments.py:55-56` create comment | `body`(required) | `want_str(data,"body",required=True)` | 体非对象或非串 `body` → `.get`/`.strip`/`@提及正则` **500** |
| `routes/me.py:83,97,110,127-131` profile/password/prefs | `display_name`/`avatar_color`/`current_password`/`new_password`（密码 `strip=False`）| `want_str` | 非对象体 → `"display_name" in data` **500**；非串 `display_name` → `.strip()` **500**；非串密码 → `check_password` **500**（注：`email` 现已 `str(...)` 强转，安全）|

> **实现约束**：
> - `move` 的 `status` 字段单列见 §2.3-B1（须在进入 `workflow` 前保证是 str）。
> - **〔R4 订正〕`assign` 保持既有 `_validate_assignee`，不重复 `want_int`**：`_validate_assignee`（`requirements.py:75-92`）已对 `assignee_type`（∈`ASSIGNEE_TYPES`）与 `assignee_id`（`int()` 兜底 + 存在性校验）做了**无 500** 的完整校验，且**有意容忍数字串**（`"5"→5`）。对其强加严格 `want_int` 会回退这份容忍、违反本轮「严格向后兼容」不变量。故 `assign`/`claim-next` 等仅在**体层**加 `json_body()`（防非对象体 500），字段层不动。
> - **成功路径的字段名、默认值、返回体 shape 一律不变**——`choices` 字段是「把已有的 400 归一得更干净」，`.strip()`/主键/密码类字段才是「把 500 变 400」。

### 2.3 后端加固 B：状态机 / Agent 运行时在坏输入与并发下不 500

- **B1 · move 的 `status` 必须先是字符串再进状态机**（`routes/requirements.py:312` / `routes/bugs.py:194` 附近的 `not to or not workflow.is_valid_status(entity, to)`）。现状：`to` 若为非空 list（`{"status":["assigned"]}`）是真值，`status in _table`（`services/workflow.py:75,81`）对不可哈希类型 → `unhashable type: 'list'` 500。**修复**：取值改为 `to = want_str(data, "status", required=True)`；`want_str` 保证非串即 400，`is_valid_status` 只会收到 str。**同列早退分支（`frm==to`）与并发守卫顺序不变。**
- **B2 · 单步 `agent-advance` 的错误分支现状已正确——本轮不改码，仅诚实标注并发风险〔R1 重写〕**。**核验结论**（推翻 v1 判断）：`do_agent_advance`（`routes/requirements.py:438-442`）**已** `try` 包住 `advance_one`，`except agent_runner.NoAgentAction` **已返回 409** `{error:"agent has no action for this state", detail:{kind,status}}`——**并非 500**。故 v1「无动作现 500、改 200」的前提有误；且「改 200」会破坏既有 `test_agent_*` 对 409 的断言、并吞掉「越界请求」信号（违反 CLAUDE.md「错误显式传播」），**撤销该改动**。至于 `advance_one` 内的防御性 `can_transition` 复核（`services/agent_runner.py:90-93`）——它**只在 `AGENT_FORWARD` 静态配置出非法前进边时**抛 `RuntimeError`：`ticket.status` 在同一次调用中读取一次，既用于 `plan(...)` 查表、又用于 `can_transition(...)` 复核，二者恒一致，**并发无从触发它**；为这条「理论上不会发生」的分支加 `except RuntimeError` 反而违反 CLAUDE.md「不要为理论上不会发生的分支写防御性 try/except」。**真正可复现的并发 500** 是 `threaded=True`（`app.py`）+ SQLite 下两个请求同时推进同一工单的**写锁争用 / 丢失更新**——这**不是** `advance_one` 能拦的，本轮与 §7 对 `_next_position` 竞态的口径一致，**接受为 dev-only 已知风险**（生产经 `DATABASE_URL` 用 Postgres，行级锁化解），记 `# TODO(advance-concurrency)`。**净结果：B2 从「改 `do_agent_advance` 代码」降级为「核验既有 409 正确 + 文档诚实标注」，不新增任何代码，`requirements.py`/`bugs.py` 的 `agent-advance` 不动。**
- **B3 · `patch_agent` 禁止把 Agent 手动置 `busy`**（`routes/agents.py:87-91`）。`busy` 是 autopilot 的运行期软锁；若被 pm/admin 经 PATCH 置为 `busy`，后续 `/autorun`、`/tick` 恒返回 `409 agent is busy`（`agents.py:148,165`）且无自动恢复，Agent 被永久「卡死」。**修复**：`status = want_str(data, "status", choices={"idle", "offline"})`（当字段存在时）；传 `busy` → 400 `{error:"status must be idle or offline"}`。这样 pm/admin 仍可把误锁的 Agent 手动置回 `idle`，但无法制造死锁。

### 2.4 后端加固 C：一批低风险就地加固（P2）

- **C1 · 列表过滤 `q=` 复用 LIKE 元字符转义**（`routes/requirements.py:155-157` / `routes/bugs.py:57-58`）。现状直接 `ilike(f"%{q}%")`，用户搜 `%`/`_` 会过度匹配，且与 `services/search.py`（已正确转义 `% _ \`）不一致。**修复**：在 `services/search.py` 导出 `escape_like(s: str) -> str`（若现为私有 `_escape_like`/`_like_clause`，改为公开或新增薄封装），列表过滤改为 `Model.title.ilike(f"%{escape_like(q)}%", escape="\\")`（title 与 description 各一处）。
- **C2 · 无效 JWT 返回 401 而非 422**（`errors.py:45-48` 的 `invalid_token_loader`）。现状无效/密钥轮换后的 token 返回 422，而前端仅在 401 时自动登出重定向（`lib/api.ts` / `lib/auth.tsx`），导致会话「卡死」——每个请求都 422 却不跳登录。**修复**：**只改 `invalid_token_loader` 一处** `return jsonify({"error": ...}), 401`，与 `expired`/`unauthorized` 一致。〔R6 订正〕现网 `revoked_token_loader`/`expired_token_loader`/`needs_fresh_token_loader` **已经是 401**（`errors.py:50-60`），**无需改动**——v1 的「revoked 若有改 401」措辞误导，删去。
- **C3 · `Activity.log` 截断 message 到 255**（`models/activity.py:24` `message` 为 `VARCHAR(255)`）。删除/转 BUG 审计文案含工单标题（如 `routes/requirements.py:260,373`），超长标题在 Postgres/MySQL（`DATABASE_URL` 支持）会溢出报错；SQLite 不校验长度只是隐患。**修复**：在 `Activity.log` 内做**保 None** 的截断——`message = message[:255] if isinstance(message, str) else message`。〔R5 订正〕**不可**用 `(message or "")[:255]`：该列 `nullable=True`，合法的 `message=None` 会被强转为 `""`，改变时间线语义（`to_dict` 直接回传）。
- **C4 · LLM `decode` 异常归一为 `LLMError`**（`services/llm/providers.py:57` `resp.read().decode("utf-8")`）。非 UTF-8 上游响应体会抛裸 `UnicodeDecodeError`，违反本层「仅 `LLMError` 逃逸」的约定（当前被 `agent_executor.generate_work` 的 `except Exception` 兜住，暂不 5xx，但契约不纯）。**修复**：把 `.decode` 纳入 `_post_json` 的 `try`，失败 `raise LLMError("parse", str(e))`。
- **C5 · `GET /api/users` 的 email 可见性**（`routes/users.py:13-17`）。`list_users` 仅 `@jwt_required()`，`to_dict()` 含 `email`，任何登录成员可见全员邮箱。〔R8 评审裁定：**有意保留，不纳入本轮**〕——AragonTeam 是**内部团队协作工具**，组织内成员邮箱互见是团队协作的常见且可接受设计（@提及、指派均需识别成员）；为此加 `include_email` 门禁属**过度设计**，与本轮「不借机重构」相悖。记 `# TODO(users-email-visibility)` 留待产品明确保密要求时再评估。**本轮不做。**

### 2.5 前端加固 A：SWR key / fetcher 形状一致性（P0 崩溃根因）

**不变量（写入本轮的前端约定，评审须确认）**：**同一个 SWR key 字符串，在全应用中只能对应一种 fetcher 返回形状。** `swrFetcher` 回裸数组、`listFetcher` 回 `{items,total}`——二者**绝不可共用同一 key**。

- **A1 · 修 Agents 页崩溃**（`frontend/app/(app)/agents/page.tsx:36-37`）。改为使用**与列表页不冲突的 key** 且统一走 `listFetcher`，同时用**只取 Agent 已指派工单**的过滤把「负载被分页截断到 50」（`services/pagination.py` `DEFAULT_LIMIT=50`）一并缓解：
  ```ts
  // 〔R2 订正〕limit 用 200（= services/pagination.py MAX_LIMIT），不用 500（会被静默钳到 200）。
  const { data: reqData } = useSWR("/requirements?assignee_type=agent&limit=200", listFetcher<Requirement>);
  const { data: bugData } = useSWR("/bugs?assignee_type=agent&limit=200", listFetcher<Bug>);
  const reqs = reqData?.items ?? [];
  const bugs = bugData?.items ?? [];
  ```
  `workload()`（`agents/page.tsx:58-66`）改从 `reqs/bugs`（现为数组）按 `assignee_id` 过滤计数。**〔R2〕两点已核验/定论**：(a) 列表端点接受 `assignee_type=agent` **单独**出现（`requirements.py:146-147`：各过滤项独立可选、AND 组合，**已核实成立**）；(b) `paginate` 的 `limit` **上限为 `MAX_LIMIT=200`**（`pagination.py:10,24`），`limit=500` 会被 `min(limit, 200)` **静默钳到 200**——故取 `limit=200`。**已知可接受限制**：当某项目「指派给 Agent 的需求/BUG」**总数 > 200** 时，负载计数仍会截断（当前团队规模远未触及）；**不上调 `MAX_LIMIT`**（它是全站列表共享契约，上调会连带影响所有列表页的默认返回量与前端渲染成本），记 `# TODO(agent-workload-count)` 备未来以「按 `assignee_id` 分组的轻量计数端点」根治。`revalidateAll()`（`agents/page.tsx:48-56`）中 `mutate("/requirements")`/`mutate("/bugs")` **必须**相应改为上述新 key（否则自主运行后 Agents 页负载不刷新）。
- **A2 · 「共 undefined 条」反向冲突**（`requirements/page.tsx:101` / `bugs/page.tsx:101`）为**同一根因**，A1 拆 key 后自动消失（列表页保持 `/requirements` + `listFetcher` 不变，Agents 页不再污染该 key）。

### 2.6 前端加固 B：全页 error 态与重试（消灭永久卡骨架）

现状：列表/详情页普遍只解构 `data`/`mutate`，从不读 `error`（`requirements/page.tsx:70`、`bugs/page.tsx:70`、`my-work/page.tsx:93`、`projects/page.tsx:19`、`dashboard/page.tsx:43`、`notifications/page.tsx:26`、`agents/page.tsx:35-38`）。SWR 出错时 `data` 恒为 `undefined` 且**不在渲染期抛错**（错误边界 `(app)/error.tsx` 不触发），页面永久停在骨架/「—」，无重试。

- **B1 · 新增 `components/ui/ErrorState.tsx`**：`{ message?: string; onRetry?: () => void }`，渲染一段克制的错误文案 + 「重试」按钮（`onClick={onRetry}`），风格与既有 `EmptyState` 一致。
- **B2 · 逐页接线**：上述每个页面 `const { data, error, mutate } = useSWR(...)`；在「未加载完且无 error」时保持骨架，**`error` 为真时渲染 `<ErrorState onRetry={() => mutate()} />`**。这是机械改动，逐页各一处。

### 2.7 前端加固 C：一批交互正确性缺口（P2）

- **C1 · TicketDrawer 写按钮按权限门禁**（`components/TicketDrawer.tsx:296-332,316,339`）。抽屉可由任意成员从列表/看板/我的工作打开，但「保存详情」(`PATCH /:id`)、`AssigneePicker`(`PATCH /:id/assign`，pm/admin) 与「让 Agent 处理」(`/agent-advance`) 对所有查看者可见 → 无权成员点击必得 403 toast。**修复**：在抽屉内计算 `canManage = role∈{admin,pm} || ticket.reporter_id===me.id || (ticket.assignee_type==="user" && ticket.assignee_id===me.id)`、`canAssign = role∈{admin,pm}`；「保存详情」与「让 Agent 处理」按 `canManage` 隐藏/禁用（与后端 `agent-advance` 门禁「pm/admin 或 can_manage_ticket」一致），`AssigneePicker`/改派按 `canAssign` 隐藏。后端仍是权威，前端仅收敛「可见即可用」。
- **C2 · 转 BUG 后直达新卡**：`requirements/board/page.tsx:46` 把跳转的死参 `?highlight=${bug.id}` 改为 `?ticket=${bug.id}` 并 dispatch `aragon:open-ticket`（看板只监听 `?ticket=` 与该事件，见 `bugs/board/page.tsx:19-21`）；`TicketDrawer.tsx:200-210` 的 `onConvert` 把 `router.push("/bugs/board")` 改为 `router.push("/bugs/board?ticket=${bug.id}")`，避免落到空看板。
- **C3 · GlobalSearch 回车分流**（`components/layout/GlobalSearch.tsx:114-116`）：无高亮行时 `onSeeAll` 改为跳到**真有命中**的分组（`counts.bugs>0 && counts.requirements===0 ? "bugs" : "requirements"`，或按命中多者），避免命中 BUG 却跳到空的需求列表。
- **C4 · Badge 兜底**（`components/ui/Badge.tsx:16`）：`style` 为 `undefined` 时（`PRIORITY_STYLES[p]`/`SEVERITY_STYLES[s]` 枚举越界）当前直接取 `.bg/.fg/.label` 崩溃。**修复**：Badge 内 `const s = style ?? { bg:"#EFEAE0", fg:"#6E6A62", label:"—" }`（中性兜底）；或在 `lib/constants.ts` 增 `priorityStyle()/severityStyle()` 带兜底并在各调用点改用。后端当前强约束枚举，此为防御性。
- **C5 · ProfileCard 颜色初始化**（`components/settings/ProfileCard.tsx:22,31`）：`user.avatar_color` 为 `null` 时 `color` 初始化成 `PALETTE[0]`，导致「无任何操作直接保存」也会写入 `avatar_color:"#C15F3C"`。**修复**：记录 `initialColor = user.avatar_color`，`buildDiff()` 仅当 `color !== initialColor` 时纳入 `avatar_color`。
- **C6 · 通知偏好切换失败要提示**（`hooks/useNotificationPreferences.ts:45` + `settings/NotificationPrefsCard.tsx:24-31`）：`setPreference` 用 SWR `mutate` + `rollbackOnError:true` 但**不再抛出**，卡片的 `try/catch` 永不触发，失败时开关默默回滚、零反馈。**修复**：`mutate(..., { rollbackOnError: true, throwOnError: true })` 或在 hook 内 `catch` 后 `throw`，让卡片 `catch` 弹 toast。

---

## 3. File / Module Change Plan（文件变更计划）

> 图例：**［新］**=新建，**［改］**=就地修改（增量，不破坏成功路径契约）。优先级 **P0**=核心必做；**P1**=强烈建议；**P2**=增强/时间允许则做。

### 3.1 Backend

| 文件 | 变更 | 优先级 | 意图（一句话）|
|---|---|---|---|
| `backend/services/validation.py` | ［新］ | P0 | `json_body()` + `want_str/want_int/want_bool` + `ValidationError`：JSON 边界一次性类型校验，坏输入 400 不 500 |
| `backend/errors.py` | ［改］ | P0 | 注册 `ValidationError→400 {error,detail}`；`invalid_token_loader` 422→401（§2.4-C2）|
| `backend/routes/auth.py` | ［改］ | P0 | login/register 用 `json_body()`+`want_*`（含公开 login，堵可复现 500）|
| `backend/routes/requirements.py` | ［改］ | P0 | create/patch/move 字段 `want_*`（`assign` 保持既有 `_validate_assignee`，仅体层加 `json_body()`）；`move` status 先成 str（§2.3-B1）；list `q=` LIKE 转义（C1）。〔R1〕`agent-advance` **不改码**（既有 409 已正确）|
| `backend/routes/bugs.py` | ［改］ | P0 | 同需求侧（含 `severity`/`related_requirement_id`/B1/C1；〔R1〕`agent-advance` 同样不改码）|
| `backend/routes/agents.py` | ［改］ | P0 | create/patch `want_*`；`patch_agent` 禁手动 `busy`（§2.3-B3）|
| `backend/routes/users.py` | ［改］ | P0 | create/patch user `want_*`；（可选）email 收敛（C5）|
| `backend/routes/projects.py` | ［改］ | P1 | create `want_*` |
| `backend/routes/comments.py` | ［改］ | P1 | comment `body` `want_str(required=True)`（防非串 @提及正则 500）|
| `backend/routes/me.py` | ［改］ | P1 | profile/password/prefs `want_*`（密码 `strip=False`，防 `check_password` 500）|
| `backend/services/search.py` | ［改］ | P1 | 导出 `escape_like()` 供列表过滤复用（C1）|
| `backend/models/activity.py` | ［改］ | P2 | `Activity.log` 截断 message 到 255（跨库安全，C3）|
| `backend/services/llm/providers.py` | ［改］ | P2 | decode 异常归一 `LLMError`（守住「仅 LLMError 逃逸」，C4）|

### 3.2 Backend 测试（`backend/tests/`）

| 文件 | 变更 | 优先级 | 意图 |
|---|---|---|---|
| `tests/test_validation.py` | ［新］ | P0 | 非对象体（`5`/`[1]`/`"x"`）、非串字段（`username=123`）对 login/register/create/patch/move/comment/me 各返回 **400 且非 500**；含公开 login 回归 |
| `tests/test_requirements.py` · `test_bugs.py` | ［改］ | P0 | `move` 传非串/list status → 400（非 500）；已有正路保持绿 |
| `tests/test_agent_autopilot.py` · `test_agent_runner.py` | ［改］ | P1 | `patch_agent` 置 busy → 400、置 idle → 200（B3）；〔R1〕单步 advance「无动作」**保持既有 409** 回归断言（不改为 200，不新增并发用例）|
| `tests/test_auth.py` | ［改］ | P1 | 无效/伪造 JWT → 401（非 422）|
| `tests/test_search.py` | ［改］ | P2 | 列表 `q=%`/`q=_` 转义后不过度匹配 |
| `tests/test_llm.py` | ［改］ | P2 | 上游非 UTF-8 响应 → 优雅降级（不 5xx，落回模板）|

### 3.3 Frontend

| 文件 | 变更 | 优先级 | 意图 |
|---|---|---|---|
| `components/ui/ErrorState.tsx` | ［新］ | P0 | 内联错误 + 重试（`onRetry=mutate`）|
| `app/(app)/agents/page.tsx` | ［改］ | P0 | 拆 SWR key 冲突（崩溃根因）+ 负载改用 `limit=200` 上限（§2.5-A1，〔R2〕）|
| `app/(app)/requirements/page.tsx` · `bugs/page.tsx` | ［改］ | P0 | 接 `error`→`ErrorState`；「共 undefined 条」随 A1 消失 |
| `app/(app)/my-work/page.tsx` · `projects/page.tsx` · `dashboard/page.tsx` · `notifications/page.tsx` | ［改］ | P1 | 接 `error`→`ErrorState`（消灭永久卡骨架，§2.6-B2）|
| `components/TicketDrawer.tsx` | ［改］ | P1 | 写按钮按 `canManage/canAssign` 门禁；convert 直达新卡（C1/C2）|
| `app/(app)/requirements/board/page.tsx` | ［改］ | P1 | 转 BUG 用 `?ticket=` 而非死参 `?highlight=`（C2）|
| `components/layout/GlobalSearch.tsx` | ［改］ | P2 | 回车无选中行跳到「真有命中」分组（C3）|
| `components/ui/Badge.tsx` | ［改］ | P2 | `style` 缺省兜底，防枚举越界崩溃（C4）|
| `components/settings/ProfileCard.tsx` | ［改］ | P2 | 颜色从真实值初始化，避免无操作也写色（C5）|
| `hooks/useNotificationPreferences.ts` | ［改］ | P2 | 切换失败向上抛出以触发 toast（C6）|

### 3.4 文档

| 文件 | 变更 | 优先级 | 意图 |
|---|---|---|---|
| `docs/plans/reliability-hardening/spec.md` | ［新］ | — | 本文档 |
| `README.md` | ［改］ | P2 | 追加「稳健化收官」一节：输入边界校验、SWR 形状不变量、全页错误态、错误码修正（500→400 / 422→401）|

---

## 4. Interface Design（接口设计 · 仅列语义变更，签名与成功响应不变）

> 统一约定沿用既有：JSON in/out；非 2xx 错误体恒为 `{error, detail?}`（状态机迁移类附 `allowed`）；写接口需 `Authorization: Bearer`。**成功路径的路径、请求体、成功响应 shape 全部不变**。本轮只新增/修正**错误分支**——都是「变得更正确」，不破坏任何既有正常用法。

```
# 1) 坏输入统一 400（此前多为 500）—— 全体 POST/PATCH
任意写接口，若 JSON 体非对象、或字段类型错误（如 username=123 / status=["assigned"] / project_id=[1]）：
  → 400 {"error": "<field> must be a string|integer|...", "detail": {"field": "<name>", "expected": "<type>"}}
  （典型：POST /api/auth/login {"username":123,...} 此前 500，现 400）

# 2) 单步 Agent 推进的错误分支（现状已正确，本轮不改）〔R1〕
POST /api/requirements/:id/agent-advance | /api/bugs/:id/agent-advance
  无可执行下一步 → 409 {"error": "agent has no action for this state", "detail": {"kind","status"}}（既有行为，保持不变）
  说明：v1 曾计划改为 200，评审核验后撤销——既有即 409（非 500），改动无必要且会破坏既有断言。
  并发写锁争用（SQLite/dev）→ 接受为已知风险（生产 Postgres 行级锁化解），见 §7 / # TODO(advance-concurrency)

# 3) Agent 状态不可手动置 busy
PATCH /api/agents/:id  {"status": "busy"}  → 400 {"error": "status must be idle or offline"}
  （{"status": "idle"|"offline"} 仍 200）

# 4) 无效 JWT 归一为 401（此前 422）
任意受保护接口携无效/伪造/密钥轮换后的 token → 401 {"error": "invalid token"}
  （前端据 401 自动登出重定向；422 会卡死会话）

# 5) 列表关键字过滤转义（无契约变化，仅结果更正确）
GET /api/requirements?q=%25   → % 作字面量匹配（此前作通配过度匹配）
```

**前端消费约定**：`lib/api.ts` 的 `ApiError` 已携 `status`/`detail`/`allowed`；400 校验错误可用 `err.detail.field` 定位字段做行内提示（可选增强）；409「并发/状态已变」复用既有 409 刷新分流（`ApiError.allowed` 有无区分「状态机非法」与「并发冲突/状态已变」）。

---

## 5. Data Model（数据模型）

**本轮无任何数据库 schema 变更**——不新增表、不改列、不加索引、不迁移。延续「唯一新表是 Phase-3 `notifications`」的历史，`db.create_all()` 无新对象可建。`aragon.db` 已 gitignore，dev 首启即建全。

仅新增两个**进程内（in-memory）契约形状**（非持久化）：

```python
# services/validation.py —— 边界校验的稳定异常与返回契约
ValidationError(message: str, field: str | None, expected: str | None)   # errors.py 渲染为 400
json_body() -> dict           # 非对象 JSON 体一律 {}
want_str(...) -> str          # 非串 → ValidationError；strip / required / max_len / choices
want_int(...) -> int | None   # 非 int（排除 bool）→ ValidationError；minimum / maximum
want_bool(...) -> bool        # 非 bool → ValidationError
```

```ts
// components/ui/ErrorState.tsx —— 前端错误态 props
interface ErrorStateProps { message?: string; onRetry?: () => void }
```

`Activity.log` 的 `message` 写前截断到既有列宽 `VARCHAR(255)`（`models/activity.py:24`），不改列定义，仅保证写入值不越界（跨库安全）。

---

## 6. Testing & Acceptance（测试与验收标准）

### 6.1 后端 pytest（`pytest --collect-only` 实测 **179** 用例全绿，见 `backend/tests/`；本轮**只增不减、既有断言语义保持**。〔R7〕v1 记的「168」与 CLAUDE.md 记的「93」均为早期陈旧值，已订正为 179）

- **新增 `test_validation.py`（P0，硬指标）**：
  - `POST /api/auth/login` 传体 `5` / `[1]` / `"x"` / `{"username":123,"password":"x"}` → **400，且断言状态码 `!= 500`**（公开接口回归，最刺眼缺陷）。
  - 〔R3〕对**真正会 500** 的字段取负例并**断言非 500**：`title`/`name`/`username`/`display_name`/`body`（非串 → `.strip()`）、`project_id`/`related_requirement_id`（list → `db.session.get`）、`current_password`/`new_password`（非串 → `check_password`）各挑 1 例 → 400 `{error, detail.field}`。枚举 `choices` 字段（`role`/`priority`/`severity`/`kind`）现状即 400，仅作归一回归，**不**作为「500→400」断言（避免假绿）。
  - **正路回归**：合法体仍 200/201（成功 shape 不变）。
- **`test_requirements.py` / `test_bugs.py`（P0）**：`PATCH /:id/move {"status":["assigned"]}` → 400（**断言非 500**，覆盖 `unhashable` 崩溃）；合法 move 仍 200。
- **`test_agent_runner.py` / `test_agent_autopilot.py`（P1）**：`PATCH /agents/:id {"status":"busy"}` → 400、`{"status":"idle"}` → 200（B3）。〔R1〕单步 advance「无动作」**保持既有 409** 断言（不改为 200；「并发→409」不可复现，不新增）。
- **`test_auth.py`（P1）**：伪造/篡改 token 访问受保护接口 → **401**（非 422）。
- **`test_search.py`（P2）**：`?q=%` / `?q=_` 结果不过度匹配（转义生效）。
- **`test_llm.py`（P2）**：mock 上游返回非 UTF-8 字节 → 工单仍推进（落回确定性模板）、**响应非 5xx**。
- **门禁命令**（Windows PowerShell，命令分开执行，不用 `&&`）：
  ```
  cd backend
  pytest -q
  ```
  **验收**：全部用例（≥179 + 新增）green；`pytest -q` 退出码 0。

### 6.2 前端质量门禁

```
cd frontend
npm run typecheck   # tsc --noEmit → 0 error
npm run build       # next build → 成功
```

### 6.3 手动验收清单（关键路径，须逐条过）

1. **SWR 崩溃回归**：登录 → 打开「需求」列表（默认无筛选）→ 再打开「Agents」页 → **页面正常渲染、无错误边界**（此前必崩）；反向导航列表页副标题显示正确条数（非「共 undefined 条」）。
2. **Agent 负载**：项目工单 >50 时，Agents 卡上的负载计数与真实指派数一致（不被截断到 50）。
3. **坏输入不 500**：用 curl/Postman 对 `POST /api/auth/login` 发体 `123` → 收到 **400**（非 500）。
4. **后端抖动不卡死**：停掉后端再切换列表/仪表盘/我的工作/通知页 → 每页出现 **ErrorState + 重试**（非永久骨架）；恢复后端点「重试」→ 正常加载。
5. **权限门禁**：以 member（如 `alice`）打开一张**非本人**工单抽屉 → 无「保存详情/改派/让 Agent 处理」按钮（不会点出 403）；以 pm/admin 打开 → 按钮齐全可用。
6. **转 BUG 直达**：在需求看板/抽屉转 BUG → 落到 BUG 看板并**自动打开新 BUG 抽屉**（非空看板）。
7. **无效会话自愈**：手动改坏 localStorage 的 token → 下次请求 **401 并跳登录**（非 422 卡死）。

### 6.4 Definition of Done（本轮）

- `pytest -q` 全绿（含新增 `test_validation.py` 等）；`tsc --noEmit` 0 error；`next build` 通过。
- §6.3 手动清单 7 条全过。
- 后端在坏输入/并发下**无 5xx**；前端在任意导航顺序与后端错误下**无未捕获异常、无永久卡骨架**。
- 无新增数据库表、无新增前后端运行时依赖；成功路径契约零变更。

---

## 7. Risks & Mitigations（风险与缓解）

| 风险 | 等级 | 缓解 |
|---|---|---|
| **批量替换 `get_json()`/`.strip()` 遗漏某处 → 仍留 500** | 中 | §2.2.3 提供逐文件·逐字段替换表；`test_validation.py` 对每个写接口至少 1 条负例把关；实现后全仓 `grep "get_json(silent=True) or {}"` 应仅剩 `json_body()` 内部一处 |
| **`want_int` 拒绝「数字字符串」误伤既有前端** | 低 | 〔R4 已定论〕`assign` 的 `assignee_id` **保持既有 `_validate_assignee`（容忍数字串）不改**；仅 `project_id`/`related_requirement_id` 走 `want_int`——前端表单以数字发送（已核对 `RequirementForm`/`BugForm`），无回退风险。query-param 侧数字仍走独立 `want_int_arg`（`request.args` 恒字符串）|
| **Agents 页负载计数被 `MAX_LIMIT=200` 截断** | 低 | 〔R2 已定论〕已核验：`assignee_type=agent` 可单独过滤、`limit` 上限为 200；取 `limit=200`，>200 个 agent 指派单为已知可接受截断（`# TODO(agent-workload-count)`）。**不**上调全站共享的 `MAX_LIMIT` |
| **无效 JWT 422→401 影响依赖 422 的既有测试** | 低 | 全仓检索断言 `422` 的用例（`test_auth.py`）随之更新为 401；这是**有意的对外错误码修正**，须在评审结论与 README 诚实标注 |
| ~~单步 advance 改为 409/200 影响既有断言~~（〔R1〕**已撤销**）| — | 本轮**不改** `agent-advance`：既有「有动作→200 / 无动作→409」全部保持，零断言变更。真正的并发 500（SQLite 写锁）接受为 dev-only 风险，`# TODO(advance-concurrency)` |
| **TicketDrawer 门禁把某些「本应可用」的按钮藏了** | 低 | `canManage` 判据与后端 `can_manage_ticket`（reporter / 人类 assignee / pm / admin）逐字对齐；后端仍是权威，前端只做一致的收敛 |
| **`_next_position` 在 `threaded=True` 下并发相等**（`requirements.py:38-41`）| 低（仅排序 tie）| 本轮**接受**，不改；排序以 `id` 兜底，非崩溃。记入 `# TODO(position-race)` |
| **`assign` 可对终态工单改派**（语义怪但不违法）| 低 | 本轮**接受**（无状态变更、不违反状态机）；如评审要求，可加 `is_terminal` 守卫，非阻断 |

---

## 8. Out of Scope（本轮刻意不做，诚实标注）

- **新业务功能 / 新页面 / 新端点**：本轮是稳健化收官，不加功能面。
- **数据库 schema 变更 / Alembic 迁移**：无列级变更，延续 `# TODO(migrations-alembic)`。
- **WebSocket / SSE 实时推送**：通知仍 SWR 轮询近实时，延续 `# TODO(phase4-realtime)`。
- **真实 LLM 深度接入**：LLM 层只做「decode 异常归一」的健壮性补丁，不改执行策略，延续双模降级。
- **前端单测 / CI 流水线**：前端仍以 `tsc --noEmit` + `next build` 把关，延续 `# TODO(phase4-ci)`；本轮的「可靠」以后端 pytest 扩充兑现。
- **分布式限流 / 多副本一致性**：延续 `# TODO(ratelimit-distributed)` / `# TODO(notifications-scale)`。
- **`_next_position` 并发精确化、单步 advance 并发写锁、终态改派守卫、users 邮箱可见性**：〔评审裁定〕全部**接受/保留**，不纳入本轮（见 §7、§2.3-B2、R8）；分别记 `# TODO(position-race)` / `# TODO(advance-concurrency)` / `# TODO(users-email-visibility)`。

---

> **交接说明**：本文档现为 **v2**——Subtask #1「方案评审与修复」已逐节做四维评审（可行性 / 完备性 / 一致性 / 合理规模）、对所有 `file:line` 引用与行为断言在现网代码上逐一核验，并就地修复全部 P0/P1（见文首「## 评审记录」R1–R9 与文末「## 评审结论」）。Subtask #2 严格按 §3「文件变更计划」逐项落地（**注意 §2.3-B2 已定为「不改码」、§2.5-A1 已定 `limit=200`、`assign` 保持 `_validate_assignee`**）；Subtask #3 对照本文档逐项 Review 后以 `feat:` 前缀精确提交。实现时若发现引用漂移（上游又有小改动），以「§2 描述的语义 + 定位关键字」为准并同步回填。

---

## 评审结论（Review Verdict · Subtask #1）

**结论：有条件通过（Approved with conditions）。**

v1 方案的两个核心判断——前端「SWR 同键异形」崩溃（§2.5）与后端「JSON 边界类型失守」500（§2.2）——经在现网代码上逐一核验，**完全属实、定位精确、修复方向正确**；范围克制、零新表零新依赖、严格向后兼容，**合理规模、无过度设计**。评审发现的 9 项偏差（R1–R9）中，4 项 P1、4 项 P2 均已在本 v2 正文就地修复，1 项为正向确认；**无 P0 遗留、无 P1 遗留**。

**放行条件（Subtask #2 落地时必须遵守，逐条可验收）**：

1. **〔R1〕`agent-advance` 不改码**：`do_agent_advance` 的 `NoAgentAction` 保持既有 **409**；**不得**改为 200，**不得**新增 `except RuntimeError`（既有即正确，改动会破坏 `test_agent_*` 断言且违反 CLAUDE.md 防御性 try/except 红线）。并发写锁 500 接受为 dev-only 风险。
2. **〔R2〕Agents 页负载用 `limit=200`**（非 500）：`limit=500` 会被 `MAX_LIMIT=200` 静默钳制；**不得**上调全站共享的 `MAX_LIMIT`。`revalidateAll()` 的 `mutate` key 必须同步改为带 `?assignee_type=agent&limit=200` 的新 key。
3. **〔R3〕测试取真会 500 的字段**：`test_validation.py` 的「500→400」负例只针对 `.strip()`/主键/密码类字段；枚举 `choices` 字段（tuple，现已 400）仅作归一回归，不作「500→400」断言。
4. **〔R4〕`assign` 保持 `_validate_assignee`**：仅体层加 `json_body()`，**不**对 `assignee_id` 强加 `want_int`（避免回退数字串容忍、违反向后兼容不变量）。
5. **〔R5〕`Activity.log` 截断保 None**：用 `message[:255] if isinstance(message, str) else message`，**不得**用 `(message or "")[:255]`（会把 `None` 变 `""`）。
6. **〔R6〕JWT 只改 `invalid_token_loader`**（422→401）；`revoked/expired/needs_fresh` 已是 401，不动。
7. **DoD 量化基线更新为 179**（〔R7〕）；`GET /api/users` 邮箱可见性为**有意保留**（〔R8〕），本轮不做。

**验收对齐**：满足 §6.4 Definition of Done 且遵守上述 7 条放行条件即视为达成本轮「每个功能都不报错、每个客户端页面都能正确使用」的目标。**批准进入实现（Subtask #2）。**

---

## 实施过程发现的方案缺陷（Issues Found During Implementation · Subtask #2）

> 落地时严格按 §3「文件变更计划」实现。下面两处为**方案表述与既有代码/UI 交互的细微不完整**，已按「保持设计意图、修正实现细节」处理，未偏离任何主线设计；一并如实记录供 Subtask #3 复核。

- **I1 · 枚举 `choices` 归一改变了 1 处既有测试断言的错误 message 文案（已同步订正测试）**。§2.2.3 将枚举字段（`severity`/`priority`/`role`/`kind`）改走 `want_str(choices=…)` 做「错误体归一」，其 message 由 `"invalid severity"` 变为归一后的 `"severity is invalid"`、`detail` 由 `{allowed:[…]}` 变为统一的 `{field,expected}`。这命中了既有 `tests/test_bugs.py::test_create_bug_rejects_bad_severity` 对**旧 message 字面量**的强断言。按 §6.1「枚举 choices 字段…仅作归一回归」的既定口径，此为**预期的归一回归**，已把该断言由「等于旧 message」放宽为「400 且 `detail.field=="severity"`」，语义不变、仍 400。前端仅在 toast 展示 `error` 文案且枚举字段均为下拉受限输入，无实际影响。**未**改动任何成功路径。
- **I2 · §2.7-C5 `ProfileCard` 的 `initialColor` 需以「初始展示色」为基准（而非裸 `user.avatar_color`）**。方案原文「记录 `initialColor = user.avatar_color`」在 `avatar_color` 为 `null` 时不足以修复「无操作也写色」：因色块 state 会回落 `PALETTE[0]` 用于高亮，若基准取裸 `null`，则 `PALETTE[0] !== null` 恒成立、diff 仍会纳入 `avatar_color`，缺陷不消。已按意图修正为 `initialColor = user?.avatar_color ?? PALETTE[0]`（初始展示色），`buildDiff()` 仅当 `color !== initialColor` 时纳入——完全达成「无任何操作直接保存不写 `avatar_color`」的既定目标。
