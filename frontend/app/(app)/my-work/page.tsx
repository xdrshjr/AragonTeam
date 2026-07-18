"use client";

import { useState } from "react";
import useSWR from "swr";
import { swrFetcher } from "@/lib/api";
import type { MeWork, Requirement, Bug } from "@/lib/types";
import { statusStyle, PRIORITY_STYLES, SEVERITY_STYLES } from "@/lib/constants";
import Header from "@/components/layout/Header";
import Badge from "@/components/ui/Badge";
import EmptyState from "@/components/ui/EmptyState";
import { SkeletonRows } from "@/components/ui/Skeleton";
import TicketDrawer from "@/components/TicketDrawer";

type Entity = "requirements" | "bugs";
type OpenTarget = { entity: Entity; id: number } | null;

function TicketRow({
  kind,
  item,
  onOpen,
}: {
  kind: Entity;
  item: Requirement | Bug;
  onOpen: () => void;
}) {
  const isBug = kind === "bugs";
  const prefix = isBug ? "BUG" : "REQ";
  const levelBadge = isBug
    ? SEVERITY_STYLES[(item as Bug).severity]
    : PRIORITY_STYLES[(item as Requirement).priority];
  return (
    <button
      onClick={onOpen}
      className="flex w-full items-center gap-3 border-b border-border px-4 py-3 text-left last:border-0 hover:bg-black/[0.02]"
    >
      <span className="w-16 shrink-0 text-xs text-ink-muted">
        {prefix}-{item.id}
      </span>
      <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink">{item.title}</span>
      <Badge style={levelBadge} />
      <Badge style={statusStyle(item.status)} />
    </button>
  );
}

function Section({
  title,
  reqs,
  bugs,
  onOpen,
}: {
  title: string;
  reqs: Requirement[];
  bugs: Bug[];
  onOpen: (t: OpenTarget) => void;
}) {
  const total = reqs.length + bugs.length;
  return (
    <div className="flex flex-col overflow-hidden rounded-xl border border-border bg-surface shadow-card">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="font-serif text-lg text-ink">{title}</h2>
        <span className="rounded-full bg-clay-soft/50 px-2 py-0.5 text-xs font-medium text-clay-dark">
          {total}
        </span>
      </div>
      {total === 0 ? (
        <EmptyState title="这里空空如也" hint="没有与你相关的工单。" />
      ) : (
        <div>
          {reqs.map((r) => (
            <TicketRow
              key={`r-${r.id}`}
              kind="requirements"
              item={r}
              onOpen={() => onOpen({ entity: "requirements", id: r.id })}
            />
          ))}
          {bugs.map((b) => (
            <TicketRow
              key={`b-${b.id}`}
              kind="bugs"
              item={b}
              onOpen={() => onOpen({ entity: "bugs", id: b.id })}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default function MyWorkPage() {
  const { data, mutate } = useSWR<MeWork>("/me/work", swrFetcher);
  const [open, setOpen] = useState<OpenTarget>(null);

  return (
    <>
      <Header title="我的工作" subtitle="指派给我 / 我提交的单，一处聚合" />
      <main className="flex-1 overflow-y-auto p-6">
        {!data ? (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div className="rounded-xl border border-border bg-surface shadow-card">
              <SkeletonRows rows={4} />
            </div>
            <div className="rounded-xl border border-border bg-surface shadow-card">
              <SkeletonRows rows={4} />
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Section
              title="指派给我"
              reqs={data.assigned.requirements}
              bugs={data.assigned.bugs}
              onOpen={setOpen}
            />
            <Section
              title="我提交的"
              reqs={data.reported.requirements}
              bugs={data.reported.bugs}
              onOpen={setOpen}
            />
          </div>
        )}
      </main>

      <TicketDrawer
        entity={open?.entity ?? "requirements"}
        id={open?.id ?? null}
        onClose={() => setOpen(null)}
        onChanged={() => mutate()}
      />
    </>
  );
}
