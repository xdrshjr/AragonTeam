"use client";

import useSWR from "swr";
import Link from "next/link";
import { swrFetcher } from "@/lib/api";
import { useProjectScope } from "@/lib/project-scope";
import type { Stats } from "@/lib/types";
import {
  statusStyle,
  actionLabel,
  REQUIREMENT_COLUMNS,
  BUG_COLUMNS,
} from "@/lib/constants";
import Header from "@/components/layout/Header";
import ErrorState from "@/components/ui/ErrorState";

// 单行占比条（纯 CSS，零图表依赖，§2.7）：宽度 = count / total。
function DistRow({
  title,
  count,
  total,
  color,
}: {
  title: string;
  count: number;
  total: number;
  color: string;
}) {
  const pct = total > 0 ? Math.round((count / total) * 100) : 0;
  return (
    <div className="flex items-center gap-3">
      <span className="w-14 shrink-0 text-xs text-ink-muted">{title}</span>
      <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-black/[0.05]">
        <div
          className="h-full rounded-full transition-[width] duration-500"
          style={{ width: `${pct}%`, backgroundColor: color, minWidth: count > 0 ? 6 : 0 }}
        />
      </div>
      <span className="w-6 text-right text-xs font-medium text-ink">{count}</span>
    </div>
  );
}

/** 不受项目作用域约束的区块标注（§2.4⑦'）：只在用户确实选了具体项目时出现。 */
function GlobalHint({ show }: { show: boolean }) {
  if (!show) return null;
  return <span className="text-xs font-normal text-ink-muted">（全部项目）</span>;
}

export default function DashboardPage() {
  const { scopeParam, scopeLabel } = useProjectScope();
  const { data: stats, error, mutate } = useSWR<Stats>(
    `/stats${scopeParam ? `?project_id=${scopeParam}` : ""}`,
    swrFetcher
  );
  // Agent / 成员 / 活动是全局维度（后端 §2.4③ 有意不按项目过滤）——必须显式标注，
  // 否则 Header 写着「ARA」而同一屏是跨项目数据，就是本轮立誓要消灭的「静默说谎 UI」。
  const isScoped = scopeLabel !== null;

  const cards: { label: string; value: number | string; href?: string }[] = [
    { label: "需求总数", value: stats?.requirements.total ?? "—", href: "/requirements" },
    { label: "BUG 总数", value: stats?.bugs.total ?? "—", href: "/bugs" },
    {
      label: isScoped ? "Agent（空闲 / 总）· 全部项目" : "Agent（空闲 / 总）",
      value: stats ? `${stats.agents.idle} / ${stats.agents.total}` : "—",
      href: "/agents",
    },
    // 【§2.10-D5】本周活动数无有意义的导航目标 → 纯展示卡（去死链；此前 href:"/dashboard" 原地跳转）。
    // 【§2.4⑦'】Agent 与活动两张卡不随项目筛选，标题上直接注明。
    {
      label: isScoped ? "本周活动数（全部项目）" : "本周活动数",
      value: stats?.activities_this_week ?? "—",
    },
  ];

  const reqTotal = stats?.requirements.total ?? 0;
  const bugTotal = stats?.bugs.total ?? 0;
  const utilizationPct = stats ? Math.round(stats.agents.utilization * 100) : 0;

  return (
    <>
      <Header
        title="仪表盘"
        subtitle={scopeLabel ? `团队与 Agent 协作全景 · ${scopeLabel}` : "团队与 Agent 协作全景"}
      />
      <main className="flex-1 overflow-y-auto p-6">
        {error && !stats ? (
          <ErrorState message="无法加载仪表盘数据" onRetry={() => mutate()} />
        ) : (
        <>
        {/* 统计卡 */}
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {cards.map((c) => {
            const base = "rounded-xl border border-border bg-surface p-5 shadow-card";
            const inner = (
              <>
                <div className="text-sm text-ink-muted">{c.label}</div>
                <div className="mt-2 font-serif text-3xl text-ink">{c.value}</div>
              </>
            );
            // 可导航卡保留 <Link> + hover；纯展示卡（本周活动数）用 <div>，同视觉、无死链。
            return c.href ? (
              <Link
                key={c.label}
                href={c.href}
                className={`${base} transition-shadow hover:shadow-panel`}
              >
                {inner}
              </Link>
            ) : (
              <div key={c.label} className={base}>
                {inner}
              </div>
            );
          })}
        </div>

        <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-3">
          {/* 需求分布（占比条） */}
          <div className="rounded-xl border border-border bg-surface p-5 shadow-card">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="font-serif text-lg text-ink">需求分布</h2>
              <Link href="/requirements/board" className="text-xs text-clay-dark hover:underline">
                看板 →
              </Link>
            </div>
            <div className="space-y-2.5">
              {REQUIREMENT_COLUMNS.map((col) => (
                <DistRow
                  key={col.key}
                  title={col.title}
                  count={stats?.requirements.by_status[col.key] ?? 0}
                  total={reqTotal}
                  color={statusStyle(col.key).fg}
                />
              ))}
            </div>
          </div>

          {/* BUG 分布（占比条） */}
          <div className="rounded-xl border border-border bg-surface p-5 shadow-card">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="font-serif text-lg text-ink">BUG 分布</h2>
              <Link href="/bugs/board" className="text-xs text-clay-dark hover:underline">
                看板 →
              </Link>
            </div>
            <div className="space-y-2.5">
              {BUG_COLUMNS.map((col) => (
                <DistRow
                  key={col.key}
                  title={col.title}
                  count={stats?.bugs.by_status[col.key] ?? 0}
                  total={bugTotal}
                  color={statusStyle(col.key).fg}
                />
              ))}
            </div>
          </div>

          {/* Agent 利用率 + 最近活动 */}
          <div className="rounded-xl border border-border bg-surface p-5 shadow-card">
            <h2 className="mb-4 flex items-center gap-1.5 font-serif text-lg text-ink">
              Agent 利用率
              <GlobalHint show={isScoped} />
            </h2>
            <div className="mb-2 flex items-baseline justify-between">
              <span className="font-serif text-2xl text-ink">{utilizationPct}%</span>
              <span className="text-xs text-ink-muted">
                忙 {stats?.agents.busy ?? 0} · 闲 {stats?.agents.idle ?? 0} · 离线{" "}
                {stats?.agents.offline ?? 0}
              </span>
            </div>
            <div className="h-2.5 overflow-hidden rounded-full bg-black/[0.05]">
              <div
                className="h-full rounded-full bg-clay transition-[width] duration-500"
                style={{ width: `${utilizationPct}%` }}
              />
            </div>

            <h3 className="mb-2 mt-5 flex items-center gap-1.5 text-sm font-semibold text-ink">
              最近活动
              <GlobalHint show={isScoped} />
            </h3>
            <div className="space-y-3">
              {stats?.recent_activities?.length ? (
                stats.recent_activities.slice(0, 6).map((a) => (
                  <div key={a.id} className="flex items-start gap-2 text-sm">
                    <span
                      className="mt-1.5 inline-block h-1.5 w-1.5 shrink-0 rounded-full"
                      style={{ backgroundColor: statusStyle(a.to_status || "new").fg }}
                    />
                    <div>
                      <span className="text-ink">
                        {a.entity_type === "bug" ? "BUG" : "需求"}#{a.entity_id}
                      </span>{" "}
                      <span className="text-ink-muted">
                        {actionLabel(a.action)}
                        {a.message ? ` · ${a.message}` : ""}
                      </span>
                    </div>
                  </div>
                ))
              ) : (
                <div className="text-sm text-ink-muted">暂无活动</div>
              )}
            </div>
          </div>
        </div>
        </>
        )}
      </main>
    </>
  );
}
