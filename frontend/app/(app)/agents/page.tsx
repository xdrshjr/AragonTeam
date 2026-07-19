"use client";

import { useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import Link from "next/link";
import { AGENTS_KEY, api, swrFetcher, listFetcher, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/lib/toast";
import { useProjectScope } from "@/lib/project-scope";
import type {
  Agent,
  Requirement,
  Bug,
  Stats,
  AutorunResult,
  TickResult,
  ClaimResult,
  AutorunAllResult,
} from "@/lib/types";
import { AGENT_KIND_LABELS, AGENT_STATUS_LABELS, actionLabel, autopilotSummary } from "@/lib/constants";
import Header from "@/components/layout/Header";
import Button from "@/components/ui/Button";
import Avatar from "@/components/ui/Avatar";
import ErrorState from "@/components/ui/ErrorState";
import AgentFormModal, { AgentFormState } from "@/components/admin/AgentFormModal";

const STATUS_DOT: Record<string, string> = {
  idle: "#3E7A4F",
  busy: "#9A7420",
  offline: "#6E6A62",
};

export default function AgentsPage() {
  const { user } = useAuth();
  const toast = useToast();
  const { mutate } = useSWRConfig();
  const { scopeLabel } = useProjectScope();
  const { data: agents, error: agentsError } = useSWR<Agent[]>(AGENTS_KEY, swrFetcher);
  // 【§2.5-A1】不变量：一个 SWR key 只对应一种 fetcher 形状。此处**绝不**复用列表页的
  // "/requirements"/"/bugs" 裸 key（listFetcher 回 {items,total} 对象），否则 Agents 页拿到
  // 对象、workload() 对其 .filter 崩溃。改用带 assignee_type=agent 的专用 key + listFetcher，
  // 并以 limit=200（= 后端 MAX_LIMIT）缓解负载被默认 50 截断。
  const { data: reqData } = useSWR(
    "/requirements?assignee_type=agent&limit=200", listFetcher<Requirement>);
  const { data: bugData } = useSWR(
    "/bugs?assignee_type=agent&limit=200", listFetcher<Bug>);
  const reqs = reqData?.items ?? [];
  const bugs = bugData?.items ?? [];
  const { data: stats } = useSWR<Stats>("/stats", swrFetcher);

  // 只有 pm/admin 能触发自主编排（后端仍是权威）。
  const canOrchestrate = user?.role === "admin" || user?.role === "pm";
  const [busyId, setBusyId] = useState<number | null>(null);
  const [teamBusy, setTeamBusy] = useState(false);
  // 建 / 改 Agent 弹窗（后端 POST/PATCH 限 pm/admin，member 隐藏所有写入口）。
  const [form, setForm] = useState<AgentFormState | null>(null);

  // 自主运行后刷新看板 / 列表 / Agent / 仪表盘 / 未读数。
  // 【§2.5-A1】负载用的 key 已换成带过滤的专用 key，mutate 必须同步，否则运行后负载不刷新。
  function revalidateAll() {
    // 用**前缀函数式 key** 而非字面量清单：这些 key 现在都可能带 ?project_id= / ?limit= 等
    // 后缀（scale-and-project-scope §2.4），逐条写死会在切换项目后静默漏刷。
    mutate(
      (key) =>
        typeof key === "string" &&
        ["/agents", "/requirements", "/bugs", "/stats", "/board/", "/notifications"].some((p) =>
          key.startsWith(p)
        )
    );
  }

  function workload(agentId: number) {
    const r = reqs.filter(
      (x) => x.assignee_type === "agent" && x.assignee_id === agentId
    ).length;
    const b = bugs.filter(
      (x) => x.assignee_type === "agent" && x.assignee_id === agentId
    ).length;
    return { r, b, total: r + b };
  }

  function recentFor(agentId: number) {
    return (stats?.recent_activities ?? [])
      .filter((a) => a.actor_type === "agent" && a.actor_id === agentId)
      .slice(0, 3);
  }

  async function onClaim(a: Agent) {
    setBusyId(a.id);
    try {
      const res = await api.post<ClaimResult>(`/agents/${a.id}/claim-next`, {});
      if (res.claimed) {
        toast.success(autopilotSummary(a.name, { claimed: 1 }));
      } else {
        toast.info(`${a.name}：暂无可认领工单`);
      }
      revalidateAll();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "认领失败");
    } finally {
      setBusyId(null);
    }
  }

  async function onAutorun(a: Agent) {
    setBusyId(a.id);
    try {
      const res = await api.post<AutorunResult>(`/agents/${a.id}/autorun?run=all`, {});
      toast.success(autopilotSummary(a.name, { advanced: res.advanced.length }));
      revalidateAll();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) toast.info(`${a.name} 正在忙碌`);
      else toast.error(err instanceof ApiError ? err.message : "运行失败");
    } finally {
      setBusyId(null);
    }
  }

  async function onTick(a: Agent) {
    setBusyId(a.id);
    try {
      const res = await api.post<TickResult>(`/agents/${a.id}/tick?run=all`, {
        claim: true,
        claim_count: 1,
      });
      toast.success(
        autopilotSummary(a.name, { claimed: res.claimed.length, advanced: res.advanced.length })
      );
      revalidateAll();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) toast.info(`${a.name} 正在忙碌`);
      else toast.error(err instanceof ApiError ? err.message : "运行失败");
    } finally {
      setBusyId(null);
    }
  }

  async function onRunTeam() {
    setTeamBusy(true);
    try {
      const res = await api.post<AutorunAllResult>(`/agents/autorun-all?run=all`, { claim: true });
      const claimed = res.runs.reduce((s, r) => s + r.claimed.length, 0);
      const advanced = res.runs.reduce((s, r) => s + r.advanced.length, 0);
      toast.success(autopilotSummary("AI 团队", { claimed, advanced }));
      revalidateAll();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "运行失败");
    } finally {
      setTeamBusy(false);
    }
  }

  return (
    <>
      <Header
        title="Agent"
        // Agent 是全局共享的执行者，不隶属项目 → 负载计数**有意不随项目筛选**（§2.4⑦'）。
        // 标注只在选了具体项目时出现（验收 C8：切回「全部项目」时消失）。
        subtitle={`AI 执行者 · 可被指派需求与 BUG 的一等公民${
          scopeLabel ? " · 不随项目筛选" : ""
        }`}
        action={
          canOrchestrate ? (
            <div className="flex items-center gap-2">
              <Button size="sm" variant="ghost" onClick={() => setForm({ mode: "create" })}>
                + 新建 Agent
              </Button>
              <Button size="sm" onClick={onRunTeam} disabled={teamBusy}>
                {teamBusy ? "运行中…" : "▶ 运行 AI 团队一轮"}
              </Button>
            </div>
          ) : undefined
        }
      />
      <main className="flex-1 overflow-y-auto p-6">
        {agentsError && !agents ? (
          <ErrorState message="无法加载 Agent 列表" onRetry={() => mutate(AGENTS_KEY)} />
        ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {agents?.map((a) => {
            const load = workload(a.id);
            const recent = recentFor(a.id);
            const running = busyId === a.id || a.status === "busy";
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

                {/* Phase-3：自主编排操作区（仅 pm/admin） */}
                {canOrchestrate && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button size="sm" variant="subtle" onClick={() => onTick(a)} disabled={running}>
                      {running ? "处理中…" : "⚡ 自动一轮"}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => onClaim(a)} disabled={running}>
                      认领下一个
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => onAutorun(a)} disabled={running}>
                      运行队列
                    </Button>
                    {/* 编辑不受 busy 锁限制：busy 时编辑弹窗可切到空闲以安全解锁（§2.3 C1）。 */}
                    <Button size="sm" variant="ghost" onClick={() => setForm({ mode: "edit", agent: a })}>
                      编辑
                    </Button>
                  </div>
                )}

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
          {!agents && !agentsError && (
            <>
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  className="h-56 animate-pulse rounded-xl border border-border bg-black/[0.03]"
                />
              ))}
            </>
          )}
          {agents && agents.length === 0 && (
            <div className="col-span-full rounded-xl border border-dashed border-border p-10 text-center text-ink-muted">
              暂无 Agent。
            </div>
          )}
        </div>
        )}
      </main>

      <AgentFormModal
        state={form}
        onClose={() => setForm(null)}
        onSaved={() => {
          setForm(null);
          mutate(AGENTS_KEY);
        }}
      />
    </>
  );
}
