"""Agent 执行层：真实 LLM 产物 or 优雅降级（real-agent-execution §3.5）。

`generate_work` 是「评论正文从哪来」的**唯一决策点**：启用且成功 → LLM 真实产物；
测试 / 未配置 / 调用失败 / 空返回 / 超长 / 任何异常 → 回退 `fallback_message`
（= `AGENT_FORWARD` 的确定性模板）。

**关键不变量（P1-2 / 放行条件 C2）**：对 LLM 调用以兜底 `except Exception` 收口——
任何外部 / 解析 / 非预期异常一律降级，**绝不冒泡成 5xx**；恒返回**非空**正文，
既保证「不能有大的报错」，也保证既有断言 `assert body["comment"]["body"]` 恒真。
"""
import logging
import os
from typing import NamedTuple

from flask import current_app

from services import agent_prompts, llm

_LOG = logging.getLogger(__name__)

# 产物字符上限：超过视为异形（撑爆 feed / 网关病态响应），降级到模板（§3.5）。
# 取值远高于 max_tokens=700 的正常产出，仅拦截病态超长响应，不误伤正常长文。
_MAX_BODY_CHARS = 20000

# autopilot 单次调用的 LLM 墙钟预算默认值（秒）；`0` 表示不限（§3.8 P2-1）。
_DEFAULT_WALL_BUDGET = 120


def _llm_active() -> bool:
    """是否走真实 LLM：测试环境恒 False（离线、可复现、绝不触网，R3）。"""
    if current_app.config.get("TESTING"):
        return False
    return llm.is_enabled()


class WorkProduct(NamedTuple):
    """带来源标记的工作产物（document-lifecycle-depth §2.3 C-2）。

    `from_llm` 为真**当且仅当**真实 LLM 返回了被采纳的正文——判据与下方「采纳」的条件
    逐字相同。所有降级路径（未启用 / 空返回 / 超长 / 异常）一律 False。
    Agent 归档以它为第一道前置条件：**降级模板绝不归档**，而 `_llm_active()` 在 TESTING
    下恒 False，因此存量用例的行为逐字节不变。
    """

    text: str
    from_llm: bool


def generate_work_product(entity, ticket, agent, to_status,
                          fallback_message: str) -> WorkProduct:
    """该步骤的正文 + 来源标记——真实产物或降级模板，恒非空、绝不抛给上层。"""
    if not _llm_active():
        return WorkProduct(fallback_message, False)
    try:
        system, user = agent_prompts.build_context(entity, ticket, agent, to_status)
        result = llm.complete(system, user)
        text = (result.text or "").strip()
        if not text:
            _LOG.warning("agent_executor: empty LLM output for %s#%s, using template",
                         entity, ticket.id)
            return WorkProduct(fallback_message, False)
        if len(text) > _MAX_BODY_CHARS:
            _LOG.warning("agent_executor: oversized LLM output (%d chars) for %s#%s, using template",
                         len(text), entity, ticket.id)
            return WorkProduct(fallback_message, False)
        return WorkProduct(text, True)
    except Exception as exc:  # noqa: BLE001 —— 兜底：任何失败一律降级，绝不冒泡成 5xx（P1-2）
        _LOG.warning("agent_executor: LLM generation failed (%s) for %s#%s, using template",
                     exc, entity, ticket.id)
        return WorkProduct(fallback_message, False)


def generate_work(entity, ticket, agent, to_status, fallback_message: str) -> str:
    """薄包装，**保持既有签名与语义逐字节不变**（零破坏，§8 R-9）。

    改动 `generate_work` 的签名会牵动 `real-agent-execution` 一轮的全部叙述与潜在测试桩，
    因此新能力走 `generate_work_product`，本函数只丢掉来源标记。
    """
    return generate_work_product(entity, ticket, agent, to_status,
                                 fallback_message).text


def wall_budget_seconds():
    """autopilot 单次调用的 LLM 墙钟预算（秒）；不启用预算时返回 None（§3.8 P2-1）。

    仅在**真实 LLM 活跃**时生效：离线 / 测试 / 未配置一律 None（预算永不触发，故
    autopilot 离线行为逐字节不变）。env `AGENT_LLM_WALL_BUDGET <= 0` 亦视为不限（None）。
    """
    if not _llm_active():
        return None
    try:
        budget = int(os.environ.get("AGENT_LLM_WALL_BUDGET", _DEFAULT_WALL_BUDGET))
    except (TypeError, ValueError):
        budget = _DEFAULT_WALL_BUDGET
    return budget if budget > 0 else None
