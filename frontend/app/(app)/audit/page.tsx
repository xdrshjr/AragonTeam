"use client";

// 站点治理审计页（login-hardening-and-audit-console §5.3）——**仅根管理员可见**。
//
// 【本仓库第一例「页面级无权限态」，是本轮新立的一条 UI 惯例】
// 既有惯例都是**局部**的：整块隐藏（settings 页的 RegistrationCard）或禁用 + title（团队页）。
// 分工判据（后续同类照办）：
//   - 页面内的一块（卡片 / 按钮 / 列）→ 隐藏，或禁用 + title 解释（用户还有别的事能做）；
//   - 整个页面 → 渲染 EmptyState，**不 redirect**（用户是被一个链接送到这里的，他需要知道
//     为什么到不了；redirect 会闪一下再跳走，还会掩盖「这个链接不该出现在我侧栏里」的 bug）。

import { useMemo, useState } from "react";
import { useAuth } from "@/lib/auth";
import { relTime } from "@/lib/format";
import { governanceActionIcon, governanceActionLabel, ROLE_LABELS } from "@/lib/constants";
import { useGovernanceAudit, AUDIT_PAGE_SIZE } from "@/hooks/useGovernanceAudit";
import type { AuditFilters, GovernanceActivity } from "@/lib/types";
import Header from "@/components/layout/Header";
import Button from "@/components/ui/Button";
import EmptyState from "@/components/ui/EmptyState";
import ErrorState from "@/components/ui/ErrorState";
import { SkeletonRows } from "@/components/ui/Skeleton";
import Pagination from "@/components/ui/Pagination";
import AuditFilterBar from "@/components/admin/AuditFilterBar";

const EMPTY_AUDIT_FILTERS: AuditFilters = {
  entity_type: "",
  action: "",
  actor_id: "",
  since: "",
};

/** 角色迁移用中文呈现；`active`/`disabled`/`locked` 这类非角色取值原样回显。 */
function valueLabel(value: string | null): string | null {
  if (!value) return null;
  return ROLE_LABELS[value] ?? value;
}

function AuditRow({ item }: { item: GovernanceActivity }) {
  const from = valueLabel(item.from_status);
  const to = valueLabel(item.to_status);
  const showTransition = from && to;
  // 施动者：system 事件（如 account_locked）显示「系统」；否则显示解析出的名字。
  const actorName = item.actor ? item.actor.name : item.actor_type === "user" ? "已删除用户" : "系统";
  const targetName = item.target ? item.target.name : null;

  return (
    <li className="flex gap-3 px-4 py-3">
      <span aria-hidden="true" className="mt-0.5 w-5 shrink-0 text-center text-ink-muted">
        {governanceActionIcon(item.action)}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="text-sm font-medium text-ink">
            {governanceActionLabel(item.action)}
          </span>
          {showTransition && (
            <span className="text-xs text-ink-muted">
              {from} → {to}
            </span>
          )}
          <span className="text-xs text-ink-muted">
            {actorName}
            {targetName && <> → {targetName}</>}
          </span>
          <span className="ml-auto shrink-0 text-xs text-ink-muted">
            {relTime(item.created_at)}
          </span>
        </div>
        {item.message && <p className="mt-0.5 text-sm text-ink-muted">{item.message}</p>}
      </div>
    </li>
  );
}

export default function AuditPage() {
  const { user } = useAuth();
  const [filters, setFilters] = useState<AuditFilters>(EMPTY_AUDIT_FILTERS);
  const [offset, setOffset] = useState(0);

  const isRoot = !!user?.is_root;
  const { items, total, loading, error, refresh } = useGovernanceAudit(filters, offset, isRoot);
  const hasFilters = useMemo(
    () => Object.values(filters).some((v) => v !== ""),
    [filters]
  );

  // 任一筛选变化 → 回到第 1 页（与团队页同一约定）。
  function onFilters(next: AuditFilters) {
    setFilters(next);
    setOffset(0);
  }

  // 【§5.3 / 评审 P1-8】非根管理员：渲染 EmptyState，**不 redirect**。
  if (user && !isRoot) {
    return (
      <>
        <Header title="治理审计" subtitle="站点级的账号与配置变更记录" />
        <main className="flex-1 overflow-y-auto p-6">
          <EmptyState
            title="仅根管理员可见"
            hint="站点治理审计包含注册配置的变更记录，只有根管理员可以查看；你可以在团队页查看单个成员的账号动态。"
          />
        </main>
      </>
    );
  }

  return (
    <>
      <Header title="治理审计" subtitle="站点级的账号与配置变更记录" />
      <main className="flex-1 overflow-y-auto p-6">
        <AuditFilterBar filters={filters} onChange={onFilters} />

        <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-card">
          {error ? (
            <ErrorState message="无法加载治理审计" onRetry={() => refresh()} />
          ) : loading && items.length === 0 ? (
            <SkeletonRows rows={6} />
          ) : items.length === 0 ? (
            <EmptyState
              title={hasFilters ? "没有符合条件的记录" : "还没有治理记录"}
              hint={
                hasFilters
                  ? "换一组筛选条件，或清空后再看看。"
                  : "账号角色变更、锁定 / 解锁、注册配置修改都会记录在这里。"
              }
              action={
                hasFilters ? (
                  <Button variant="ghost" size="sm" onClick={() => onFilters(EMPTY_AUDIT_FILTERS)}>
                    清空筛选
                  </Button>
                ) : undefined
              }
            />
          ) : (
            <>
              <ul className="divide-y divide-border">
                {items.map((item) => (
                  <AuditRow key={item.id} item={item} />
                ))}
              </ul>
              <Pagination
                offset={offset}
                limit={AUDIT_PAGE_SIZE}
                total={total}
                disabled={loading}
                onOffset={setOffset}
              />
            </>
          )}
        </div>
      </main>
    </>
  );
}
