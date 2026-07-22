"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useBoard } from "@/hooks/useBoard";
import { useHierarchyOptions } from "@/hooks/useHierarchyOptions";
import { EMPTY_HIERARCHY } from "@/lib/hierarchy";
import type { HierarchyFilterValue } from "@/lib/hierarchy";
import { useProjectScope } from "@/lib/project-scope";
import type { Card } from "@/lib/types";
import Header from "@/components/layout/Header";
import Button from "@/components/ui/Button";
import HierarchySelects from "@/components/planning/HierarchySelects";
import KanbanBoard from "@/components/kanban/KanbanBoard";
import TicketDrawer from "@/components/TicketDrawer";
import { SkeletonBoard } from "@/components/ui/Skeleton";
import ErrorState from "@/components/ui/ErrorState";

export default function BugsBoardPage() {
  const { scope, scopeLabel } = useProjectScope();
  // 【version-plan-console §7.4】与需求看板同构的「版本 → 计划」筛选行。
  const [hierarchy, setHierarchy] = useState<HierarchyFilterValue>(EMPTY_HIERARCHY);
  const hierarchyOptions = useHierarchyOptions();
  const { board, error, isLoading, move, mutate } = useBoard("bugs", scope, hierarchy);
  const [openId, setOpenId] = useState<number | null>(null);

  // 【Phase-3 §2.3.3】通知直达：读 ?ticket=<id> 自动打开对应工单抽屉。
  // 跨页导航走 mount 读取；已在本看板时同路由 push 不重挂载，靠事件即时打开（同需求看板策略）。
  useEffect(() => {
    // 【H1】只接受正整数 id（?ticket=0 此前 → 抽屉永久骨架 + 全屏遮罩，看板不可用）。
    const t = Number(new URLSearchParams(window.location.search).get("ticket"));
    if (Number.isInteger(t) && t > 0) setOpenId(t);
    function onOpen(e: Event) {
      const d = (e as CustomEvent<{ entity: string; id: number }>).detail;
      if (d?.entity === "bugs" && d.id != null) setOpenId(d.id);
    }
    window.addEventListener("aragon:open-ticket", onOpen);
    return () => window.removeEventListener("aragon:open-ticket", onOpen);
  }, []);

  return (
    <>
      <Header
        title="BUG 看板"
        subtitle={`拖拽卡片以流转状态 / 同列重排 · 点击卡片查看详情与协作${
          scopeLabel ? ` · ${scopeLabel}` : ""
        }`}
        action={
          <Link href="/bugs">
            <Button variant="ghost" size="sm">
              列表视图
            </Button>
          </Link>
        }
      />
      <main className="flex flex-1 flex-col overflow-hidden p-6">
        <HierarchySelects
          className="mb-4 shrink-0"
          value={hierarchy}
          onChange={setHierarchy}
          versions={hierarchyOptions.versions}
          plans={hierarchyOptions.plans}
          loading={hierarchyOptions.isLoading}
          versionsTruncated={hierarchyOptions.versionsTruncated}
          plansTruncated={hierarchyOptions.plansTruncated}
        />
        {/* min-h-0 是 flex 子项能真正滚动的前提（否则内容会把容器撑破）。 */}
        <div className="min-h-0 flex-1">
          {error && !board ? (
            <ErrorState message="无法加载看板" onRetry={() => mutate()} />
          ) : isLoading || !board ? (
            <SkeletonBoard columns={5} />
          ) : (
            <KanbanBoard
              board={board}
              entity="bugs"
              onMove={move}
              onOpen={(card: Card) => setOpenId(card.id)}
            />
          )}
        </div>
      </main>

      <TicketDrawer
        entity="bugs"
        id={openId}
        onClose={() => setOpenId(null)}
        onChanged={() => mutate()}
      />
    </>
  );
}
