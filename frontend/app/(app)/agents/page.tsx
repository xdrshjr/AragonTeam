"use client";

import useSWR from "swr";
import { swrFetcher } from "@/lib/api";
import type { Agent } from "@/lib/types";
import { AGENT_KIND_LABELS, AGENT_STATUS_LABELS } from "@/lib/constants";
import Header from "@/components/layout/Header";
import Avatar from "@/components/ui/Avatar";

const STATUS_DOT: Record<string, string> = {
  idle: "#3E7A4F",
  busy: "#9A7420",
  offline: "#6E6A62",
};

export default function AgentsPage() {
  const { data: agents } = useSWR<Agent[]>("/agents", swrFetcher);

  return (
    <>
      <Header title="Agent" subtitle="AI 执行者 · 可被指派需求与 BUG 的一等公民" />
      <main className="flex-1 overflow-y-auto p-6">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {agents?.map((a) => (
            <div
              key={a.id}
              className="rounded-xl border border-border bg-surface p-5 shadow-card"
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
            </div>
          ))}
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
