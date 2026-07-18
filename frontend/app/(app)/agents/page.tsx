"use client";

import useSWR from "swr";
import Link from "next/link";
import { swrFetcher } from "@/lib/api";
import type { Agent, Requirement, Bug, Stats } from "@/lib/types";
import { AGENT_KIND_LABELS, AGENT_STATUS_LABELS, actionLabel } from "@/lib/constants";
import Header from "@/components/layout/Header";
import Avatar from "@/components/ui/Avatar";

const STATUS_DOT: Record<string, string> = {
  idle: "#3E7A4F",
  busy: "#9A7420",
  offline: "#6E6A62",
};

export default function AgentsPage() {
  const { data: agents } = useSWR<Agent[]>("/agents", swrFetcher);
  const { data: reqs } = useSWR<Requirement[]>("/requirements", swrFetcher);
  const { data: bugs } = useSWR<Bug[]>("/bugs", swrFetcher);
  const { data: stats } = useSWR<Stats>("/stats", swrFetcher);

  function workload(agentId: number) {
    const r = (reqs ?? []).filter(
      (x) => x.assignee_type === "agent" && x.assignee_id === agentId
    ).length;
    const b = (bugs ?? []).filter(
      (x) => x.assignee_type === "agent" && x.assignee_id === agentId
    ).length;
    return { r, b, total: r + b };
  }

  function recentFor(agentId: number) {
    return (stats?.recent_activities ?? [])
      .filter((a) => a.actor_type === "agent" && a.actor_id === agentId)
      .slice(0, 3);
  }

  return (
    <>
      <Header title="Agent" subtitle="AI 执行者 · 可被指派需求与 BUG 的一等公民" />
      <main className="flex-1 overflow-y-auto p-6">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {agents?.map((a) => {
            const load = workload(a.id);
            const recent = recentFor(a.id);
            return (
              <div
                key={a.id}
                className="flex flex-col rounded-xl border border-border bg-surface p-5 shadow-card"
              >
                <div className="flex items-start gap-3">
                  <Avatar name={a.name} isAgent size={40} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <h3 className="font-medium text-ink">{a.name}</h3>
                      <span className="flex items-center gap-1.5 text-xs text-ink-muted">
                        <span
                          className="inline-block h-2 w-2 rounded-full"
                          style={{ backgroundColor: STATUS_DOT[a.status] || "#6E6A62" }}
                        />
                        {AGENT_STATUS_LABELS[a.status] || a.status}
                      </span>
                    </div>
                    <div className="mt-0.5 text-xs text-clay-dark">
                      {AGENT_KIND_LABELS[a.kind] || a.kind} Agent
                    </div>
                    <p className="mt-2 text-sm text-ink-muted">{a.description}</p>
                  </div>
                </div>

                {/* 当前工单负载 */}
                <div className="mt-4 flex items-center gap-4 border-t border-border pt-3 text-xs">
                  <Link href="/requirements/board" className="text-ink-muted hover:text-clay-dark">
                    需求 <span className="font-semibold text-ink">{load.r}</span>
                  </Link>
                  <Link href="/bugs/board" className="text-ink-muted hover:text-clay-dark">
                    BUG <span className="font-semibold text-ink">{load.b}</span>
                  </Link>
                  <span className="ml-auto text-ink-muted">
                    进行中 <span className="font-semibold text-ink">{load.total}</span>
                  </span>
                </div>

                {/* 最近该 Agent 的活动 */}
                {recent.length > 0 && (
                  <div className="mt-3 space-y-1.5">
                    {recent.map((act) => (
                      <div key={act.id} className="flex items-start gap-2 text-xs">
                        <span className="mt-1 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-clay" />
                        <span className="text-ink-muted">
                          {act.entity_type === "bug" ? "BUG" : "需求"}#{act.entity_id} ·{" "}
                          {actionLabel(act.action)}
                          {act.message ? ` · ${act.message}` : ""}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
          {agents && agents.length === 0 && (
            <div className="col-span-full rounded-xl border border-dashed border-border p-10 text-center text-ink-muted">
              暂无 Agent。
            </div>
          )}
        </div>
      </main>
    </>
  );
}
