"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { useBoard } from "@/hooks/useBoard";
import type { Requirement, Bug, Card } from "@/lib/types";
import Header from "@/components/layout/Header";
import Button from "@/components/ui/Button";
import KanbanBoard from "@/components/kanban/KanbanBoard";
import TicketDrawer from "@/components/TicketDrawer";
import { SkeletonBoard } from "@/components/ui/Skeleton";

export default function RequirementsBoardPage() {
  const router = useRouter();
  const toast = useToast();
  const { board, isLoading, move, mutate } = useBoard("requirements");
  const [converting, setConverting] = useState(false);
  const [openId, setOpenId] = useState<number | null>(null);

  async function onConvert(req: Requirement) {
    if (converting) return;
    setConverting(true);
    try {
      const bug = await api.post<Bug>(`/requirements/${req.id}/convert-to-bug`, {});
      toast.success(`已转为 BUG-${bug.id}`);
      mutate();
      // 跳转到 BUG 看板并高亮新卡片（U6）。
      router.push(`/bugs/board?highlight=${bug.id}`);
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
        {isLoading || !board ? (
          <SkeletonBoard columns={7} />
        ) : (
          <KanbanBoard
            board={board}
            entity="requirements"
            onMove={move}
            onConvert={onConvert}
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
