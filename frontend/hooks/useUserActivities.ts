"use client";

import useSWR from "swr";
import { listFetcher } from "@/lib/api";
import type { UserActivity } from "@/lib/types";

/** 一次取多少条治理记录。账号治理是**低频人工动作**，20 条足以覆盖绝大多数账号的全部历史。 */
export const USER_ACTIVITY_PAGE_SIZE = 20;

/**
 * 某个账号的治理时间线（account-security-and-governance §4.3）。
 *
 * `enabled=false` 时**不发请求**（与 useNotifications 的 listEnabled 同一手法）：
 * 团队页上每一行都挂着一个入口，不能因为渲染了按钮就为每个成员各打一次接口。
 *
 * @param userId 目标账号 id；null 表示尚未选中任何人。
 * @param enabled 弹窗是否打开。
 */
export function useUserActivities(userId: number | null, enabled: boolean) {
  const key =
    enabled && userId !== null
      ? `/users/${userId}/activities?limit=${USER_ACTIVITY_PAGE_SIZE}`
      : null;
  const { data, error, isLoading, mutate } = useSWR(key, listFetcher<UserActivity>);

  return {
    items: data?.items ?? [],
    total: data?.total ?? 0,
    loading: enabled && isLoading,
    error,
    refresh: mutate,
  };
}
