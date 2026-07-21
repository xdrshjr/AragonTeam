"use client";

import useSWR from "swr";
import { REGISTRATION_META_KEY, swrFetcher } from "@/lib/api";
import type { PasswordPolicy, RegistrationMeta } from "@/lib/types";
import {
  PASSWORD_MIN_LENGTH,
  PASSWORD_MAX_LENGTH,
  DEFAULT_MIN_CHAR_CLASSES,
} from "@/components/auth/PasswordStrength";

/** 网络抖动 / 后端未升级时的兜底：**按开放处理**。 */
const OPTIMISTIC: RegistrationMeta = {
  enabled: true,
  invite_required: true,
  password_min_length: PASSWORD_MIN_LENGTH,
  password_max_length: PASSWORD_MAX_LENGTH,
  password_min_char_classes: DEFAULT_MIN_CHAR_CLASSES,
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
 *
 * 【account-security-and-governance §2.1 A-3 ①】口令策略从这里下发。**有意不新建
 * `usePasswordPolicy`**：那会是同一个 SWR key 上的第二份真相，正是本产品反复反对的东西。
 */
export function useRegistrationMeta() {
  const { data, error, isLoading } = useSWR<RegistrationMeta>(
    REGISTRATION_META_KEY,
    swrFetcher,
    { shouldRetryOnError: false, revalidateOnFocus: false }
  );

  const meta = data ?? OPTIMISTIC;
  // 派生对象：既有 `meta` / `resolved` 两键逐字不变，现有两个调用点零改动。
  // 编译期回落值 = 后端的 DEFAULT_*，故后端未升级（响应缺两个新键）时行为与本轮之前相同。
  const policy: PasswordPolicy = {
    minLength: meta.password_min_length ?? PASSWORD_MIN_LENGTH,
    maxLength: meta.password_max_length ?? PASSWORD_MAX_LENGTH,
    minCharClasses: meta.password_min_char_classes ?? DEFAULT_MIN_CHAR_CLASSES,
  };

  return {
    meta,
    /** 真正拿到过服务端答复时为 true；用于区分「确认关闭」与「还不知道」。 */
    resolved: data !== undefined,
    /** 当前生效的口令策略（§2.1 A-3）。 */
    policy,
    loading: isLoading,
    error,
  };
}
