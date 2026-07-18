"use client";

import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { ROLE_LABELS } from "@/lib/constants";
import Header from "@/components/layout/Header";
import Button from "@/components/ui/Button";
import Avatar from "@/components/ui/Avatar";

export default function SettingsPage() {
  const { user, logout } = useAuth();
  const router = useRouter();

  function onLogout() {
    logout();
    router.replace("/login");
  }

  return (
    <>
      <Header title="设置" subtitle="账号信息与登录状态" />
      <main className="flex-1 overflow-y-auto p-6">
        <div className="max-w-lg rounded-xl border border-border bg-surface p-6 shadow-card">
          <div className="flex items-center gap-4">
            <Avatar
              name={user?.display_name || user?.username || "?"}
              color={user?.avatar_color}
              size={56}
            />
            <div>
              <div className="font-serif text-xl text-ink">
                {user?.display_name || user?.username}
              </div>
              <div className="text-sm text-ink-muted">
                {user ? ROLE_LABELS[user.role] : ""}
              </div>
            </div>
          </div>

          <dl className="mt-6 divide-y divide-border">
            <div className="flex justify-between py-3 text-sm">
              <dt className="text-ink-muted">用户名</dt>
              <dd className="text-ink">{user?.username}</dd>
            </div>
            <div className="flex justify-between py-3 text-sm">
              <dt className="text-ink-muted">邮箱</dt>
              <dd className="text-ink">{user?.email || "—"}</dd>
            </div>
            <div className="flex justify-between py-3 text-sm">
              <dt className="text-ink-muted">角色</dt>
              <dd className="text-ink">{user ? ROLE_LABELS[user.role] : ""}</dd>
            </div>
          </dl>

          <div className="mt-6">
            <Button variant="danger" onClick={onLogout}>
              退出登录
            </Button>
          </div>
        </div>

        <p className="mt-4 max-w-lg text-xs text-ink-muted">
          MVP 阶段设置项为占位；后续将支持修改资料、密码与通知偏好。
        </p>
      </main>
    </>
  );
}
