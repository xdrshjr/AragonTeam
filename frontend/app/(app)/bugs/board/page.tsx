"use client";

import { useState } from "react";
import Link from "next/link";
import { useBoard } from "@/hooks/useBoard";
import type { Card } from "@/lib/types";
import Header from "@/components/layout/Header";
import Button from "@/components/ui/Button";
import KanbanBoard from "@/components/kanban/KanbanBoard";
import TicketDrawer from "@/components/TicketDrawer";
import { SkeletonBoard } from "@/components/ui/Skeleton";

export default function BugsBoardPage() {
  const { board, isLoading, move, mutate } = useBoard("bugs");
  const [openId, setOpenId] = useState<number | null>(null);

  return (
    <>
      <Header
        title="BUG 看板"
        subtitle="拖拽卡片以流转状态 / 同列重排 · 点击卡片查看详情与协作"
        action={
          <Link href="/bugs">
            <Button variant="ghost" size="sm">
              列表视图
            </Button>
          </Link>
        }
      />
      <main className="flex-1 overflow-hidden p-6">
        {isLoading || !board ? (
          <SkeletonBoard columns={5} />
        ) : (
          <KanbanBoard
            board={board}
            entity="bugs"
            onMove={move}
            onOpen={(card: Card) => setOpenId(card.id)}
          />
        )}
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
