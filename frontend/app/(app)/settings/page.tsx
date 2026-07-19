"use client";

import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { ROLE_LABELS } from "@/lib/constants";
import Header from "@/components/layout/Header";
import Button from "@/components/ui/Button";
import Avatar from "@/components/ui/Avatar";
import ProfileCard from "@/components/settings/ProfileCard";
import PasswordCard from "@/components/settings/PasswordCard";
import NotificationPrefsCard from "@/components/settings/NotificationPrefsCard";

export default function SettingsPage() {
  const { user, logout } = useAuth();
  const router = useRouter();

  function onLogout() {
    logout();
    router.replace("/login");
  }

  return (
    <>
      <Header title="设置" subtitle="账号资料、密码与通知偏好" />
      <main className="flex-1 overflow-y-auto p-6">
        <div className="mx-auto flex max-w-2xl flex-col gap-6">
          {/* 账号概要 + 登出（用户名 / 角色只读；改角色仍须管理员在团队页操作） */}
          <section className="rounded-xl border border-border bg-surface p-6 shadow-card">
            <div className="flex items-center justify-between gap-4">
              <div className="flex min-w-0 items-center gap-4">
                <Avatar
                  name={user?.display_name || user?.username || "?"}
                  color={user?.avatar_color}
                  size={56}
                />
                <div className="min-w-0">
                  <div className="truncate font-serif text-xl text-ink">
                    {user?.display_name || user?.username}
                  </div>
                  <div className="text-sm text-ink-muted">
                    {user?.username} · {user ? ROLE_LABELS[user.role] : ""}
                  </div>
                </div>
              </div>
              <Button variant="danger" onClick={onLogout}>
                退出登录
              </Button>
            </div>
          </section>

          <ProfileCard />
          <PasswordCard />
          <NotificationPrefsCard />
        </div>
      </main>
    </>
  );
}
