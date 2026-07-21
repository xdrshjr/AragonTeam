"use client";

import useSWR from "swr";
import { useCallback } from "react";
import { api, swrFetcher, REGISTRATION_SETTINGS_KEY } from "@/lib/api";
import type { RegistrationSettings } from "@/lib/types";

/** PATCH 的部分更新载荷；三个键均可选，一个都不带后端返 400。 */
export interface RegistrationSettingsPatch {
  enabled?: boolean;
  invite_code?: string;
  default_role?: RegistrationSettings["default_role"];
}

/**
 * 根管理员的注册设置读写（self-service-registration §2.3 C-4）。
 *
 * 写路径全部走「乐观更新 → 以服务端返回的权威值收敛 → 失败自动回滚并向上抛」，
 * 与 `useNotificationPreferences` 同一手法：PATCH / rotate 的响应体与 GET **完全同形**，
 * 因此可以直接替换缓存，省一次往返。
 *
 * `throwOnError: true` 是有意的：失败时回滚之后必须让调用方的 try/catch 拿到错误去 toast，
 * 否则开关会「弹回去」而用户不知道为什么。
 */
export function useRegistrationSettings(enabled: boolean) {
  const { data, error, isLoading, mutate } = useSWR<RegistrationSettings>(
    enabled ? REGISTRATION_SETTINGS_KEY : null,
    swrFetcher
  );

  const update = useCallback(
    async (patch: RegistrationSettingsPatch) => {
      const optimistic = data ? { ...data, ...patch } : undefined;
      await mutate(
        () => api.patch<RegistrationSettings>(REGISTRATION_SETTINGS_KEY, patch),
        {
          optimisticData: optimistic,
          rollbackOnError: true,
          throwOnError: true,
          revalidate: false,
        }
      );
    },
    [data, mutate]
  );

  // rotate 不做乐观更新：新码由服务端的 CSPRNG 生成，客户端无从预测，
  // 编一个假值只会让用户看到一个一闪而过的错误邀请码。
  const rotate = useCallback(async () => {
    await mutate(
      () => api.post<RegistrationSettings>(`${REGISTRATION_SETTINGS_KEY}/rotate-code`, {}),
      { rollbackOnError: true, throwOnError: true, revalidate: false }
    );
  }, [mutate]);

  return { settings: data ?? null, loading: isLoading, error, refresh: mutate, update, rotate };
}
