"use client";

import useSWR from "swr";
import { useCallback } from "react";
import { api, swrFetcher } from "@/lib/api";
import type { NotificationPreferences, NotificationType } from "@/lib/types";

// 缓存信封统一为 { preferences }〔评审 P2-7〕：GET 响应、optimisticData、PATCH 返回体
// 三者同形，避免 SWR 缓存 shape 漂移。
interface PrefsEnvelope {
  preferences: NotificationPreferences;
}

// 通知偏好数据 + 乐观写（account-settings §7）。
// - 读：SWR GET /me/notification-preferences（缺省全 true，被存量行覆盖）；
// - 写：setPreference 乐观置位 → PATCH 部分更新 → 以返回的权威 effective_map 收敛；
//   失败 rollbackOnError 自动回滚，调用方负责 toast。
export function useNotificationPreferences() {
  const { data, error, isLoading, mutate } = useSWR<PrefsEnvelope>(
    "/me/notification-preferences",
    swrFetcher
  );

  const setPreference = useCallback(
    async (type: NotificationType, next: boolean) => {
      if (!data) return;
      const optimistic: PrefsEnvelope = {
        preferences: { ...data.preferences, [type]: next },
      };
      // patchThunk resolve 出 PATCH 返回的权威 {preferences} 作为最终缓存值。
      const patchThunk = () =>
        api.patch<PrefsEnvelope>("/me/notification-preferences", {
          preferences: { [type]: next },
        });
      // 【§2.7-C6】throwOnError:true —— 失败时 rollbackOnError 回滚乐观态后**向上抛出**，
      // 让卡片的 try/catch 触发 toast（此前不抛，失败静默回滚、零反馈）。
      await mutate(patchThunk, {
        optimisticData: optimistic,
        rollbackOnError: true,
        throwOnError: true,
        revalidate: false,
      });
    },
    [data, mutate]
  );

  return {
    preferences: data?.preferences ?? null,
    loading: isLoading,
    error,
    setPreference,
  };
}
