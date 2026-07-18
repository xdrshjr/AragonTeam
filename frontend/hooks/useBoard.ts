"use client";

import useSWR from "swr";
import { useCallback } from "react";
import { api, swrFetcher, ApiError } from "@/lib/api";
import { useToast } from "@/lib/toast";
import type { Board, Card } from "@/lib/types";

type Entity = "requirements" | "bugs";

// 看板数据拉取 + 乐观移动 + 回滚（§2.2 B / U3 / U4）。
export function useBoard(entity: Entity, projectId?: number) {
  const toast = useToast();
  const key = `/board/${entity}${projectId ? `?project_id=${projectId}` : ""}`;
  const { data, error, isLoading, mutate } = useSWR<Board<Card>>(key, swrFetcher);

  // 把某卡从当前列移动到 toStatus 列（乐观更新，失败回滚 + toast）。
  const move = useCallback(
    async (cardId: number, toStatus: string) => {
      if (!data) return;

      // 定位卡片与源列。
      let card: Card | undefined;
      let fromStatus = "";
      for (const col of data.columns) {
        const found = col.items.find((c) => c.id === cardId);
        if (found) {
          card = found;
          fromStatus = col.key;
          break;
        }
      }
      if (!card || fromStatus === toStatus) return;

      const snapshot = data; // 回滚快照

      // 乐观：从源列移除，追加到目标列尾（与后端 position 语义一致）。
      const optimistic: Board<Card> = {
        columns: data.columns.map((col) => {
          if (col.key === fromStatus) {
            return { ...col, items: col.items.filter((c) => c.id !== cardId) };
          }
          if (col.key === toStatus) {
            // 覆盖 status 后整体断言为 Card（联合类型无法逐字段收窄）。
            const moved = { ...card!, status: toStatus } as Card;
            return { ...col, items: [...col.items, moved] };
          }
          return col;
        }),
      };

      try {
        await mutate(
          async () => {
            await api.patch(`/${entity}/${cardId}/move`, { status: toStatus });
            // 拉取权威数据（后端已算好 position）。
            return await api.get<Board<Card>>(key);
          },
          {
            optimisticData: optimistic,
            rollbackOnError: true,
            revalidate: false,
            populateCache: true,
          }
        );
      } catch (err) {
        // 回滚由 rollbackOnError 保证；这里补错误提示（§2.6 错误契约）。
        if (err instanceof ApiError && err.status === 409) {
          const allowed = err.allowed?.length ? `（可迁移至：${err.allowed.join(", ")}）` : "";
          toast.error(`非法状态迁移${allowed}`);
        } else {
          toast.error(err instanceof ApiError ? err.message : "移动失败，已回滚");
        }
        // 兜底：确保回滚到快照。
        mutate(snapshot, { revalidate: false });
      }
    },
    [data, entity, key, mutate, toast]
  );

  return { board: data, error, isLoading, move, mutate };
}
