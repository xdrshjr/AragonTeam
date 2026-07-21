"use client";

// 公开注册页（self-service-registration §6.1）。
//
// 它是 `(app)` 路由组的**同级兄弟**，与 `/login` 一样天然在登录守卫之外——全仓库无
// `middleware.ts`，唯一的守卫是 `app/(app)/layout.tsx` 里的客户端 useEffect 重定向。
// 因此本页任何请求都必须自己容忍 401 与网络失败，不得假设「能打开这个页面 = 有会话」。

import { useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { useRegistrationMeta } from "@/hooks/useRegistrationMeta";
import AuthSplitLayout from "@/components/auth/AuthSplitLayout";
import RegisterForm from "@/components/auth/RegisterForm";
import Button from "@/components/ui/Button";
import EmptyState from "@/components/ui/EmptyState";

export default function RegisterPage() {
  const router = useRouter();
  const { user, loading } = useAuth();
  const { meta, resolved } = useRegistrationMeta();

  // 已登录访问注册页 → 直接进工作台（与 app/login/page.tsx 同一守卫）。
  useEffect(() => {
    if (!loading && user) router.replace("/dashboard");
  }, [user, loading, router]);

  // meta 请求失败时 `enabled` 恒为乐观的 true（见 useRegistrationMeta 的降级理由），
  // 故这里只有在**确实拿到过服务端答复**且答复为关闭时，才渲染空态。
  const closed = resolved && !meta.enabled;

  return (
    <AuthSplitLayout
      title={closed ? "暂未开放注册" : "创建你的账号"}
      subtitle={closed ? "这台实例当前只接受管理员建号" : "填写邀请码即可加入团队工作区"}
      footer={
        <span className="text-ink-muted">
          已有账号？
          <Link href="/login" className="ml-1 font-medium text-clay hover:underline">
            去登录
          </Link>
        </span>
      }
    >
      {closed ? (
        <div className="mt-6 rounded-xl border border-border bg-surface shadow-card">
          <EmptyState
            icon={<span className="text-2xl">🔒</span>}
            title="当前未开放自助注册"
            hint="请联系管理员为你创建账号；管理员可在「设置 → 注册配置」里重新开放。"
            action={
              <Button variant="ghost" size="sm" onClick={() => router.push("/login")}>
                返回登录
              </Button>
            }
          />
        </div>
      ) : (
        <RegisterForm />
      )}
    </AuthSplitLayout>
  );
}
