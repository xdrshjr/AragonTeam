"use client";

import useSWR from "swr";
import { listFetcher, GOVERNANCE_AUDIT_PREFIX } from "@/lib/api";
import type { AuditFilters, GovernanceActivity } from "@/lib/types";

/** 审计一页多少条。治理事件是低频动作，50 条覆盖绝大多数场景，超出走分页。 */
export const AUDIT_PAGE_SIZE = 50;

/**
 * 站点治理审计流（login-hardening-and-audit-console §3.4）。
 *
 * 页面 key 由前缀 + 筛选串内联拼出（**不复用任何 `*_KEY`**，见 lib/api.ts 的不变量）：
 * 空串筛选自动省略，与后端「空串等价于不传」对齐；筛选或翻页改变即换 key、SWR 自动重取。
 *
 * @param filters 四个筛选（实体 / 动作 / 施动者 / 起始时间），空串 = 不过滤。
 * @param offset 分页偏移。
 * @param enabled 仅根管理员页面挂载后才为 true——非根管理员根本不发这个必然 403 的请求。
 */
export function useGovernanceAudit(filters: AuditFilters, offset: number, enabled: boolean) {
  const params = new URLSearchParams();
  if (filters.entity_type) params.set("entity_type", filters.entity_type);
  if (filters.action) params.set("action", filters.action);
  if (filters.actor_id.trim()) params.set("actor_id", filters.actor_id.trim());
  // since 来自 <input type="datetime-local">，是**本地**时刻——转成 UTC ISO（带 Z）再发，
  // 否则会有时区偏移；后端 want_query_datetime 容忍尾部 Z（§2.3 / R-14）。
  const since = filters.since.trim();
  if (since) {
    const d = new Date(since);
    if (!Number.isNaN(d.getTime())) params.set("since", d.toISOString());
  }
  params.set("limit", String(AUDIT_PAGE_SIZE));
  params.set("offset", String(offset));

  const key = enabled ? `${GOVERNANCE_AUDIT_PREFIX}?${params.toString()}` : null;
  const { data, error, isLoading, mutate } = useSWR(key, listFetcher<GovernanceActivity>);

  return {
    items: data?.items ?? [],
    total: data?.total ?? 0,
    loading: enabled && isLoading,
    error,
    refresh: mutate,
  };
}
