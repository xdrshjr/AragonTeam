"use client";

// 强制改密页（account-security-and-governance §6.1）。
//
// 它在 `(app)` 路由组**之外**（与 `/login`、`/register` 同级），因此**拿不到**
// `(app)/layout.tsx` 那条登录守卫——本页必须自带**两条反向守卫**，否则会出两种坏状态：
// 未登录直接敲这个地址会渲染一个空表单；标记已清的人敲它会被永久停在一个没有出口的页面。
//
// **不渲染侧边栏**：此刻用户不能去任何别的地方，给他看导航是残忍的假象。

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/lib/toast";
import { useRegistrationMeta } from "@/hooks/useRegistrationMeta";
import AuthSplitLayout from "@/components/auth/AuthSplitLayout";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import PasswordStrength, { isPasswordAcceptable } from "@/components/auth/PasswordStrength";

/** 错误文案容器：`role="alert"` + `aria-live` 让读屏能读到刚出现的校验错误（与 RegisterForm 同款）。 */
function FieldError({ message }: { message?: string }) {
  return (
    <div role="alert" aria-live="polite" className="min-h-[1rem] text-xs text-[#B23B1E]">
      {message}
    </div>
  );
}

export default function ForcePasswordPage() {
  const router = useRouter();
  const { user, loading, logout, refresh } = useAuth();
  const toast = useToast();
  const { policy } = useRegistrationMeta();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | undefined>();
  const [submitting, setSubmitting] = useState(false);

  // 两条反向守卫。形状与 app/login/page.tsx:29-31 的既有守卫一致，不发明第二套写法。
  useEffect(() => {
    if (loading) return;
    if (!user) router.replace("/login");
    else if (!user.must_change_password) router.replace("/dashboard");
  }, [user, loading, router]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!current) return setError("请填写当前密码（管理员发给你的那个）");
    if (!isPasswordAcceptable(next, user?.username ?? "", policy)) {
      return setError("新密码不满足下方的强度要求");
    }
    if (next !== confirm) return setError("两次输入的新密码不一致");
    setSubmitting(true);
    try {
      await api.post("/me/password", { current_password: current, new_password: next });
      // 先刷新登录态：标记清掉之后本页的第二条守卫才不会跟这一跳打架。
      await refresh();
      toast.success("密码已设置，欢迎使用");
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "修改失败，请稍后重试");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center text-ink-muted">
        正在加载…
      </div>
    );
  }

  return (
    <AuthSplitLayout
      title="请先设置你的新密码"
      subtitle="当前密码由管理员设置，仅用于首次登录"
      footer={
        // 一个不想现在改的人必须能走开，否则这个页面就是一个死循环。
        <button
          type="button"
          onClick={() => {
            logout();
            router.replace("/login");
          }}
          className="text-ink-muted hover:text-ink hover:underline"
        >
          退出登录
        </button>
      }
    >
      <p className="mt-4 text-sm text-ink-muted">设置完成后会自动进入工作台。</p>
      <form onSubmit={onSubmit} className="mt-6 flex flex-col gap-3" noValidate>
        <Input label="当前密码" name="current_password" type="password"
               autoComplete="current-password" value={current}
               onChange={(e) => setCurrent(e.target.value)} placeholder="管理员发给你的一次性密码" />
        <div className="flex flex-col gap-2">
          <Input label="新密码" name="new_password" type="password" autoComplete="new-password"
                 value={next} onChange={(e) => setNext(e.target.value)} placeholder="••••••••" />
          <PasswordStrength password={next} username={user.username} policy={policy} />
        </div>
        <Input label="确认新密码" name="confirm_password" type="password"
               autoComplete="new-password" value={confirm}
               onChange={(e) => setConfirm(e.target.value)} placeholder="再输入一次" />
        <FieldError message={error} />
        <Button type="submit" disabled={submitting} className="mt-1 w-full">
          {submitting ? "提交中…" : "设置新密码并进入"}
        </Button>
      </form>
    </AuthSplitLayout>
  );
}
