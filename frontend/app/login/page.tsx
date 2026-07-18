"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/lib/toast";
import { ApiError } from "@/lib/api";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";

// 默认账号（seed），点击可一键填充。
const DEMO_ACCOUNTS = [
  { username: "admin", password: "admin123", label: "管理员" },
  { username: "pm", password: "pm123", label: "项目经理" },
  { username: "alice", password: "alice123", label: "成员" },
  { username: "bob", password: "bob123", label: "成员" },
];

export default function LoginPage() {
  const router = useRouter();
  const { login, user, loading } = useAuth();
  const toast = useToast();
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
      const msg = err instanceof ApiError ? err.message : "登录失败";
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen">
      {/* 左侧品牌区 */}
      <div className="hidden flex-1 flex-col justify-between bg-clay-soft/40 p-12 lg:flex">
        <div className="font-serif text-2xl text-clay-dark">AragonTeam</div>
        <div className="max-w-md">
          <h1 className="font-serif text-4xl leading-tight text-ink">
            AI 时代的
            <br />
            团队协作平台
          </h1>
          <p className="mt-4 text-ink-muted">
            需求与 BUG 不只指派给人，也能指派给 Agent。人与 AI
            混合协作的每一步流转，都被完整记录。
          </p>
        </div>
        <div className="text-sm text-ink-muted">© AragonTeam · Anthropic 风格设计</div>
      </div>

      {/* 右侧登录表单 */}
      <div className="flex flex-1 items-center justify-center bg-bg p-6">
        <div className="w-full max-w-sm">
          <div className="mb-8 lg:hidden">
            <div className="font-serif text-2xl text-clay-dark">AragonTeam</div>
          </div>
          <h2 className="font-serif text-2xl text-ink">欢迎回来</h2>
          <p className="mt-1 text-sm text-ink-muted">登录以进入你的工作台</p>

          <form onSubmit={onSubmit} className="mt-6 flex flex-col gap-4">
            <Input
              label="用户名"
              name="username"
              value={username}
              autoComplete="username"
              onChange={(e) => setUsername(e.target.value)}
              placeholder="admin"
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

          <div className="mt-8 rounded-xl border border-border bg-surface p-4 shadow-card">
            <div className="mb-2 text-xs font-medium text-ink-muted">
              演示账号（点击填充）
            </div>
            <div className="flex flex-wrap gap-2">
              {DEMO_ACCOUNTS.map((a) => (
                <button
                  key={a.username}
                  type="button"
                  onClick={() => {
                    setUsername(a.username);
                    setPassword(a.password);
                  }}
                  className="rounded-lg border border-border px-2.5 py-1 text-xs text-ink hover:bg-black/[0.04]"
                >
                  {a.username}
                  <span className="ml-1 text-ink-muted">· {a.label}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
