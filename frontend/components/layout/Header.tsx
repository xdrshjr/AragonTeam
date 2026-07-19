"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { ROLE_LABELS } from "@/lib/constants";
import Avatar from "@/components/ui/Avatar";
import GlobalSearch from "@/components/layout/GlobalSearch";
import ProjectSwitcher from "@/components/layout/ProjectSwitcher";
import NotificationBell from "@/components/notifications/NotificationBell";

interface Props {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
}

export default function Header({ title, subtitle, action }: Props) {
  const { user, logout } = useAuth();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  function onLogout() {
    logout();
    router.replace("/login");
  }

  return (
    <header className="flex h-16 shrink-0 items-center justify-between border-b border-border bg-surface px-6">
      <div className="min-w-0">
        <h1 className="font-serif text-xl text-ink">{title}</h1>
        {subtitle && <p className="truncate text-sm text-ink-muted">{subtitle}</p>}
      </div>

      <div className="flex items-center gap-3">
        {/* 阅读顺序：项目 → 搜索 → 页面动作 → 通知 → 头像。 */}
        <ProjectSwitcher />

        <GlobalSearch />

        {action}

        <NotificationBell />

        <div className="relative" ref={menuRef}>
          <button
            onClick={() => setOpen((v) => !v)}
            className="flex items-center gap-2 rounded-lg px-1.5 py-1 hover:bg-black/[0.04]"
          >
            <Avatar
              name={user?.display_name || user?.username || "?"}
              color={user?.avatar_color}
              size={30}
            />
            <div className="hidden text-left sm:block">
              <div className="text-sm font-medium text-ink">
                {user?.display_name || user?.username}
              </div>
              <div className="text-xs text-ink-muted">
                {user ? ROLE_LABELS[user.role] : ""}
              </div>
            </div>
          </button>

          {open && (
            <div className="absolute right-0 mt-2 w-48 rounded-xl border border-border bg-surface p-1.5 shadow-lift">
              <div className="px-3 py-2">
                <div className="text-sm font-medium text-ink">
                  {user?.display_name || user?.username}
                </div>
                <div className="text-xs text-ink-muted">{user?.email || "—"}</div>
              </div>
              <div className="my-1 h-px bg-border" />
              <button
                onClick={() => {
                  setOpen(false);
                  router.push("/settings");
                }}
                className="w-full rounded-lg px-3 py-2 text-left text-sm text-ink hover:bg-black/[0.04]"
              >
                账号设置
              </button>
              <button
                onClick={onLogout}
                className="w-full rounded-lg px-3 py-2 text-left text-sm text-[#B23B1E] hover:bg-[#F3D2C7]/40"
              >
                退出登录
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
