"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/lib/toast";
import { ApiError } from "@/lib/api";
import { useRegistrationMeta } from "@/hooks/useRegistrationMeta";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import AuthSplitLayout from "@/components/auth/AuthSplitLayout";

// 【self-service-registration §7 R-13】此处曾有一个 DEMO_ACCOUNTS 一键填充块
// （admin / admin123）。它在任何真实部署里都是一个**公开页面上的管理员后门**，
// 本轮随自助注册一并删除。信息本身没有丢失：默认账号来自后端配置 `ROOT_ADMIN_*`，
// README 的「快速开始」写明了开发默认值。

/** 把登录错误映射成给人看的中文（login-hardening-and-audit-console §5.4）。
 *  锁定态 403 必须区别于停用态 403：前者可自愈、有明确等待时长。
 *  `retry_after_seconds` 缺失时降级为不带时长的句子——**绝不显示「NaN 分钟」**。 */
function loginErrorMessage(err: unknown): string {
  if (!(err instanceof ApiError)) return "登录失败";
  if (err.status === 403 && err.message === "account is temporarily locked") {
    const secs = (err.detail as { retry_after_seconds?: number } | undefined)
      ?.retry_after_seconds;
    const mins = typeof secs === "number" && secs > 0 ? Math.ceil(secs / 60) : null;
    return mins
      ? `登录尝试过于频繁，账号已临时锁定，请在 ${mins} 分钟后重试，或联系管理员解锁。`
      : "登录尝试过于频繁，账号已临时锁定，请稍后重试，或联系管理员解锁。";
  }
  if (err.status === 403 && err.message === "account is disabled, contact an administrator") {
    return "账号已被停用，请联系管理员。";
  }
  return err.message;
}

export default function LoginPage() {
  const router = useRouter();
  const { login, user, loading } = useAuth();
  const toast = useToast();
  const { meta } = useRegistrationMeta();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  // 已登录直接进入。
  useEffect(() => {
    if (!loading && user) router.replace("/dashboard");
  }, [user, loading, router]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!username || !password) {
      toast.error("请输入用户名与密码");
      return;
    }
    setSubmitting(true);
    try {
      await login(username, password);
      toast.success("登录成功");
      router.replace("/dashboard");
    } catch (err) {
      toast.error(loginErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthSplitLayout
      title="欢迎回来"
      subtitle="登录以进入你的工作台"
      footer={
        // 注册关闭时不渲染入口：给一个点进去只会看到「未开放」的链接是无谓的绕路。
        meta.enabled ? (
          <span className="text-ink-muted">
            还没有账号？
            <Link href="/register" className="ml-1 font-medium text-clay hover:underline">
              立即注册
            </Link>
          </span>
        ) : undefined
      }
    >
      <form onSubmit={onSubmit} className="mt-6 flex flex-col gap-4">
        <Input
          label="用户名"
          name="username"
          value={username}
          autoComplete="username"
          onChange={(e) => setUsername(e.target.value)}
        />
        <Input
          label="密码"
          name="password"
          type="password"
          value={password}
          autoComplete="current-password"
          onChange={(e) => setPassword(e.target.value)}
          placeholder="••••••••"
        />
        <Button type="submit" disabled={submitting} className="mt-2 w-full">
          {submitting ? "登录中…" : "登录"}
        </Button>
      </form>
    </AuthSplitLayout>
  );
}
