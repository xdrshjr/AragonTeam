"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { ROLE_LABELS } from "@/lib/constants";
import Avatar from "@/components/ui/Avatar";
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
  const [query, setQuery] = useState("");
  const menuRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  // 全局搜索键盘可达（§2.7）：`/` 聚焦搜索（非输入框内时），Esc 清空并失焦。
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const tag = (e.target as HTMLElement)?.tagName;
      const typing = tag === "INPUT" || tag === "TEXTAREA";
      if (e.key === "/" && !typing) {
        e.preventDefault();
        searchRef.current?.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  function runSearch() {
    const q = query.trim();
    if (!q) return;
    router.push(`/requirements?q=${encodeURIComponent(q)}`);
    // 若已在需求列表页，同路由 push 不会重挂载页面、其 mount 读取不触发；
    // 派发事件让已挂载的列表页即时刷新过滤条（§2.6，与看板 window.location 同为「不引 Suspense」策略）。
    window.dispatchEvent(new CustomEvent<string>("aragon:search", { detail: q }));
  }

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
        {/* 全局搜索框 */}
        <div className="relative hidden md:block">
          <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted/70">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="8" />
              <path d="m21 21-4.3-4.3" />
            </svg>
          </span>
          <input
            ref={searchRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") runSearch();
              if (e.key === "Escape") {
                setQuery("");
                searchRef.current?.blur();
              }
            }}
            placeholder="搜索需求 / BUG…（/）"
            aria-label="全局搜索"
            className="h-9 w-56 rounded-lg border border-border bg-bg pl-9 pr-3 text-sm text-ink placeholder:text-ink-muted/60 focus:border-clay focus:outline-none focus:ring-2 focus:ring-clay/20"
          />
        </div>

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
