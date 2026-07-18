"use client";

import useSWR from "swr";
import Link from "next/link";
import { swrFetcher } from "@/lib/api";
import type { Stats } from "@/lib/types";
import { statusStyle, REQUIREMENT_COLUMNS, BUG_COLUMNS } from "@/lib/constants";
import Header from "@/components/layout/Header";

function actionLabel(a: string): string {
  return (
    {
      created: "创建",
      assigned: "指派",
      moved: "流转",
      converted: "转 BUG",
    }[a] || a
  );
}

export default function DashboardPage() {
  const { data: stats } = useSWR<Stats>("/stats", swrFetcher);

  const cards = [
    { label: "需求总数", value: stats?.requirements.total ?? "—", href: "/requirements" },
    { label: "BUG 总数", value: stats?.bugs.total ?? "—", href: "/bugs" },
    {
      label: "Agent（空闲 / 总）",
      value: stats ? `${stats.agents.idle} / ${stats.agents.total}` : "—",
      href: "/agents",
    },
    { label: "团队成员", value: stats?.members ?? "—", href: "/team" },
  ];

  return (
    <>
      <Header title="仪表盘" subtitle="团队与 Agent 协作全景" />
      <main className="flex-1 overflow-y-auto p-6">
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
          {/* 需求分布 */}
          <div className="rounded-xl border border-border bg-surface p-5 shadow-card">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="font-serif text-lg text-ink">需求分布</h2>
              <Link href="/requirements/board" className="text-xs text-clay-dark hover:underline">
                看板 →
              </Link>
            </div>
            <div className="space-y-2">
              {REQUIREMENT_COLUMNS.map((col) => {
                const n = stats?.requirements.by_status[col.key] ?? 0;
                return (
                  <div key={col.key} className="flex items-center justify-between text-sm">
                    <span className="text-ink-muted">{col.title}</span>
                    <span className="font-medium text-ink">{n}</span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* BUG 分布 */}
          <div className="rounded-xl border border-border bg-surface p-5 shadow-card">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="font-serif text-lg text-ink">BUG 分布</h2>
              <Link href="/bugs/board" className="text-xs text-clay-dark hover:underline">
                看板 →
              </Link>
            </div>
            <div className="space-y-2">
              {BUG_COLUMNS.map((col) => {
                const n = stats?.bugs.by_status[col.key] ?? 0;
                return (
                  <div key={col.key} className="flex items-center justify-between text-sm">
                    <span className="text-ink-muted">{col.title}</span>
                    <span className="font-medium text-ink">{n}</span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* 最近活动（人 / Agent 混合协作轨迹） */}
          <div className="rounded-xl border border-border bg-surface p-5 shadow-card">
            <h2 className="mb-3 font-serif text-lg text-ink">最近活动</h2>
            <div className="space-y-3">
              {stats?.recent_activities?.length ? (
                stats.recent_activities.map((a) => (
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
      </main>
    </>
  );
}
