"use client";

import useSWR from "swr";
import Link from "next/link";
import { swrFetcher } from "@/lib/api";
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

export default function DashboardPage() {
  const { data: stats, error, mutate } = useSWR<Stats>("/stats", swrFetcher);

  const cards = [
    { label: "需求总数", value: stats?.requirements.total ?? "—", href: "/requirements" },
    { label: "BUG 总数", value: stats?.bugs.total ?? "—", href: "/bugs" },
    {
      label: "Agent（空闲 / 总）",
      value: stats ? `${stats.agents.idle} / ${stats.agents.total}` : "—",
      href: "/agents",
    },
    { label: "本周活动数", value: stats?.activities_this_week ?? "—", href: "/dashboard" },
  ];

  const reqTotal = stats?.requirements.total ?? 0;
  const bugTotal = stats?.bugs.total ?? 0;
  const utilizationPct = stats ? Math.round(stats.agents.utilization * 100) : 0;

  return (
    <>
      <Header title="仪表盘" subtitle="团队与 Agent 协作全景" />
      <main className="flex-1 overflow-y-auto p-6">
        {error && !stats ? (
          <ErrorState message="无法加载仪表盘数据" onRetry={() => mutate()} />
        ) : (
        <>
        {/* 统计卡 */}
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {cards.map((c) => (
            <Link
              key={c.label}
              href={c.href}
              className="rounded-xl border border-border bg-surface p-5 shadow-card transition-shadow hover:shadow-panel"
            >
              <div className="text-sm text-ink-muted">{c.label}</div>
              <div className="mt-2 font-serif text-3xl text-ink">{c.value}</div>
            </Link>
          ))}
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
            <h2 className="mb-4 font-serif text-lg text-ink">Agent 利用率</h2>
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

            <h3 className="mb-2 mt-5 text-sm font-semibold text-ink">最近活动</h3>
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
