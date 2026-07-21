"use client";

import useSWR from "swr";
import { REGISTRATION_META_KEY, swrFetcher } from "@/lib/api";
import type { RegistrationMeta } from "@/lib/types";

/** 网络抖动 / 后端未升级时的兜底：**按开放处理**。 */
const OPTIMISTIC: RegistrationMeta = {
  enabled: true,
  invite_required: true,
  password_min_length: 8,
};

/**
 * 公开注册元信息（self-service-registration §2.2 B-3）。登录页与注册页共用。
 *
 * **失败时按「开放」降级**（§6.1 第 6 条）：把人挡在门外的裁决权属于后端，
 * 一次 502 不该让新同事以为公司关掉了注册。后端会在 `POST /auth/signup` 上做最终裁决，
 * 界面乐观一点的代价只是「填完表单才被告知未开放」，反过来的代价是「本可以注册的人
 * 看到一堵墙就走了」。
 *
 * 该页是**真正的公开路由**（全仓库无 middleware.ts），故本 hook 必须容忍 401 与网络失败，
 * 不得假设「能打开这个页面 = 有会话」（§6.1 第 9 条）。
 */
export function useRegistrationMeta() {
  const { data, error, isLoading } = useSWR<RegistrationMeta>(
    REGISTRATION_META_KEY,
    swrFetcher,
    { shouldRetryOnError: false, revalidateOnFocus: false }
  );

  return {
    meta: data ?? OPTIMISTIC,
    /** 真正拿到过服务端答复时为 true；用于区分「确认关闭」与「还不知道」。 */
    resolved: data !== undefined,
    loading: isLoading,
    error,
  };
}
