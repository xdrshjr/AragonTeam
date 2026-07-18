"use client";

import useSWR from "swr";
import { useCallback } from "react";
import { api, swrFetcher, listFetcher } from "@/lib/api";
import type { Notification } from "@/lib/types";

// 通知中心数据 + 操作（Phase-3 §2.3.3）。
// - unread-count 轮询（默认 20s，近实时；不引 WebSocket）；
// - 列表按需拉取（listEnabled=false 时不请求，避免关闭下拉时空转）；
// - 单条 / 全部已读后 mutate 未读数与列表。
export function useNotifications(listEnabled: boolean) {
  const countSWR = useSWR<{ count: number }>(
    "/notifications/unread-count",
    swrFetcher,
    { refreshInterval: 20000, revalidateOnFocus: true }
  );

  const listSWR = useSWR(
    listEnabled ? "/notifications?limit=15" : null,
    listFetcher<Notification>
  );

  const refresh = useCallback(() => {
    countSWR.mutate();
    listSWR.mutate();
  }, [countSWR, listSWR]);

  const markRead = useCallback(
    async (id: number) => {
      await api.post(`/notifications/${id}/read`);
      countSWR.mutate();
      listSWR.mutate();
    },
    [countSWR, listSWR]
  );

  const markAllRead = useCallback(async () => {
    await api.post(`/notifications/read-all`);
    countSWR.mutate();
    listSWR.mutate();
  }, [countSWR, listSWR]);

  return {
    count: countSWR.data?.count ?? 0,
    items: listSWR.data?.items ?? [],
    loading: listEnabled && !listSWR.data,
    refresh,
    markRead,
    markAllRead,
  };
}
