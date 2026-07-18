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

  // 把某卡移动到 toStatus 列的 toIndex 位置（乐观更新，失败回滚 + toast）。
  // toIndex 缺省 = 追加列尾；支持同列精确重排（Phase-2 §2.6）。
  const move = useCallback(
    async (cardId: number, toStatus: string, toIndex?: number) => {
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
      if (!card) return;
      // 同列且未指定插入索引 → 无操作（整列拖放且无重排意图）。
      if (fromStatus === toStatus && toIndex === undefined) return;

      const snapshot = data; // 回滚快照
      // 【Phase-3 §2.5】携拖拽起点卡片的 updated_at 做乐观并发守卫。
      const expectedUpdatedAt = card.updated_at;

      // 乐观：先从所在列移除该卡，再插入目标列 toIndex（缺省列尾）。
      const optimistic: Board<Card> = {
        columns: data.columns.map((col) => {
          const items = col.items.filter((c) => c.id !== cardId);
          if (col.key === toStatus) {
            // 覆盖 status 后整体断言为 Card（联合类型无法逐字段收窄）。
            const moved = { ...card!, status: toStatus } as Card;
            const idx = toIndex == null ? items.length : Math.min(toIndex, items.length);
            return { ...col, items: [...items.slice(0, idx), moved, ...items.slice(idx)] };
          }
          return { ...col, items };
        }),
      };

      try {
        await mutate(
          async () => {
            await api.patch(`/${entity}/${cardId}/move`, {
              status: toStatus,
              position: toIndex,
              expected_updated_at: expectedUpdatedAt,
            });
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
        if (err instanceof ApiError && err.status === 409 && err.allowed) {
          // 状态机 409：非法迁移（体含 allowed）。
          const allowed = err.allowed.length ? `（可迁移至：${err.allowed.join(", ")}）` : "";
          toast.error(`非法状态迁移${allowed}`);
        } else if (err instanceof ApiError && err.status === 409) {
          // 并发 409：他人已更新（体无 allowed）——回滚并拉最新〔§2.5〕。
          toast.error("该工单已被他人更新，请刷新");
          mutate();
        } else {
          toast.error(err instanceof ApiError ? err.message : "移动失败，已回滚");
        }
        // 兜底：确保回滚到快照（并发分支已 revalidate，此处不覆盖最新）。
        if (!(err instanceof ApiError && err.status === 409 && !err.allowed)) {
          mutate(snapshot, { revalidate: false });
        }
      }
    },
    [data, entity, key, mutate, toast]
  );

  return { board: data, error, isLoading, move, mutate };
}
