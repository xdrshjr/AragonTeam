"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { useAuth } from "@/lib/auth";
import { useBoard } from "@/hooks/useBoard";
import type { Requirement, Bug, Card } from "@/lib/types";
import Header from "@/components/layout/Header";
import Button from "@/components/ui/Button";
import KanbanBoard from "@/components/kanban/KanbanBoard";
import TicketDrawer from "@/components/TicketDrawer";
import { SkeletonBoard } from "@/components/ui/Skeleton";
import ErrorState from "@/components/ui/ErrorState";

export default function RequirementsBoardPage() {
  const router = useRouter();
  const toast = useToast();
  const { board, error, isLoading, move, mutate } = useBoard("requirements");
  const { user } = useAuth();
  // 【§2.9-C2】转 BUG 后端限 pm/admin；member 不应看到点了必 403 的「转 BUG」按钮。
  const canConvert = user?.role === "admin" || user?.role === "pm";
  const [converting, setConverting] = useState(false);
  const [openId, setOpenId] = useState<number | null>(null);

  // 【Phase-3 §2.3.3】通知直达：读 ?ticket=<id> 自动打开对应工单抽屉。
  // 用 window.location + 事件而非 useSearchParams，规避静态预渲染的 Suspense 约束：
  // 跨页导航走 mount 读取；已在本看板时同路由 push 不重挂载，靠事件即时打开。
  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("ticket");
    if (t && !Number.isNaN(Number(t))) setOpenId(Number(t));
    function onOpen(e: Event) {
      const d = (e as CustomEvent<{ entity: string; id: number }>).detail;
      if (d?.entity === "requirements" && d.id != null) setOpenId(d.id);
    }
    window.addEventListener("aragon:open-ticket", onOpen);
    return () => window.removeEventListener("aragon:open-ticket", onOpen);
  }, []);

  async function onConvert(req: Requirement) {
    if (converting) return;
    setConverting(true);
    try {
      const bug = await api.post<Bug>(`/requirements/${req.id}/convert-to-bug`, {});
      toast.success(`已转为 BUG-${bug.id}`);
      mutate();
      // 【§2.7-C2】直达新 BUG 卡：看板只监听 ?ticket= 与 aragon:open-ticket 事件；
      // 此前用死参 ?highlight= 会落到空看板、不自动打开抽屉。
      router.push(`/bugs/board?ticket=${bug.id}`);
      window.dispatchEvent(
        new CustomEvent("aragon:open-ticket", { detail: { entity: "bugs", id: bug.id } })
      );
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "转 BUG 失败");
    } finally {
      setConverting(false);
    }
  }

  return (
    <>
      <Header
        title="需求看板"
        subtitle="拖拽卡片以流转状态 / 同列重排 · 点击卡片查看详情与协作"
        action={
          <Link href="/requirements">
            <Button variant="ghost" size="sm">
              列表视图
            </Button>
          </Link>
        }
      />
      <main className="flex-1 overflow-hidden p-6">
        {error && !board ? (
          <ErrorState message="无法加载看板" onRetry={() => mutate()} />
        ) : isLoading || !board ? (
          <SkeletonBoard columns={7} />
        ) : (
          <KanbanBoard
            board={board}
            entity="requirements"
            onMove={move}
            onConvert={canConvert ? onConvert : undefined}
            onOpen={(card: Card) => setOpenId(card.id)}
          />
        )}
      </main>

      <TicketDrawer
        entity="requirements"
        id={openId}
        onClose={() => setOpenId(null)}
        onChanged={() => mutate()}
      />
    </>
  );
}
