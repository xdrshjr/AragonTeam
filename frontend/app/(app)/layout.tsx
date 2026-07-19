"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { ProjectScopeProvider } from "@/lib/project-scope";
import Sidebar from "@/components/layout/Sidebar";

// 应用外壳：Sidebar（左） + 内容区（右，内含各页自己的 Header）。
// 鉴权守卫：未登录重定向 /login（U2）。
export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [user, loading, router]);

  // 会话复原中或未登录（即将跳转）时显示占位，避免闪现未授权内容。
  if (loading || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center text-ink-muted">
        正在加载…
      </div>
    );
  }

  // ProjectScopeProvider 放在鉴权守卫**之后**：这样它内部的 /projects 请求必然携带有效 JWT。
  return (
    <ProjectScopeProvider>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col">{children}</div>
      </div>
    </ProjectScopeProvider>
  );
}
