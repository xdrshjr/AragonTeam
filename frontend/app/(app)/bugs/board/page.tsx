"use client";

import Link from "next/link";
import { useBoard } from "@/hooks/useBoard";
import Header from "@/components/layout/Header";
import Button from "@/components/ui/Button";
import KanbanBoard from "@/components/kanban/KanbanBoard";

export default function BugsBoardPage() {
  const { board, isLoading, move } = useBoard("bugs");

  return (
    <>
      <Header
        title="BUG 看板"
        subtitle="拖拽卡片以流转状态 · 合法性由后端状态机裁决"
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
          <div className="flex h-full items-center justify-center text-ink-muted">
            加载看板中…
          </div>
        ) : (
          <KanbanBoard board={board} entity="bugs" onMove={move} />
        )}
      </main>
    </>
  );
}
