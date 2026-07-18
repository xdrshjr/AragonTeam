"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { useBoard } from "@/hooks/useBoard";
import type { Requirement, Bug } from "@/lib/types";
import Header from "@/components/layout/Header";
import Button from "@/components/ui/Button";
import KanbanBoard from "@/components/kanban/KanbanBoard";

export default function RequirementsBoardPage() {
  const router = useRouter();
  const toast = useToast();
  const { board, isLoading, move, mutate } = useBoard("requirements");
  const [converting, setConverting] = useState(false);

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
        subtitle="拖拽卡片以流转状态 · 合法性由后端状态机裁决"
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
          <div className="flex h-full items-center justify-center text-ink-muted">
            加载看板中…
          </div>
        ) : (
          <KanbanBoard
            board={board}
            entity="requirements"
            onMove={move}
            onConvert={onConvert}
          />
        )}
      </main>
    </>
  );
}
