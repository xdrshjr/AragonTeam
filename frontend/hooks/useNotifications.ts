"use client";

import useSWR, { mutate as globalMutate } from "swr";
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

  // 铃铛与通知整页是两个独立 key；读单后必须**双向**同步，否则另一侧滞留旧状态
  // （停在 /notifications 点铃铛「全部已读」，页面每一行仍显示未读直到刷新）。
  // 只匹配到 "?" 为止：不把页长常量硬编码进匹配串——否则日后改页长，这行会静默失效
  // （匹配不到任何 key 且不报错）。多失效一个铃铛自己的 key 无害。
  const syncPage = useCallback(() => {
    globalMutate((key) => typeof key === "string" && key.startsWith("/notifications?"));
  }, []);

  const markRead = useCallback(
    async (id: number) => {
      await api.post(`/notifications/${id}/read`);
      countSWR.mutate();
      listSWR.mutate();
      syncPage();
    },
    [countSWR, listSWR, syncPage]
  );

  const markAllRead = useCallback(async () => {
    await api.post(`/notifications/read-all`);
    countSWR.mutate();
    listSWR.mutate();
    syncPage();
  }, [countSWR, listSWR, syncPage]);

  return {
    count: countSWR.data?.count ?? 0,
    items: listSWR.data?.items ?? [],
    loading: listEnabled && !listSWR.data && !listSWR.error,
    // 【§2.8③】此前从不返回 error：后端挂掉时下拉永久「加载中…」，无重试无提示。
    error: listSWR.error,
    refresh,
    markRead,
    markAllRead,
  };
}
