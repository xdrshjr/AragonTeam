"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useNotifications } from "@/hooks/useNotifications";
import { ApiError } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { notificationIcon, notificationLabel } from "@/lib/constants";
import type { Notification } from "@/lib/types";
import { AuthorAvatar } from "@/components/ui/Avatar";
import ErrorState from "@/components/ui/ErrorState";

// 相对时间（created_at 带 Z，正确解析为本地时间）。
function relTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const diff = Date.now() - d.getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "刚刚";
  if (m < 60) return `${m} 分钟前`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} 小时前`;
  const day = Math.floor(h / 24);
  if (day < 30) return `${day} 天前`;
  return d.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
}

// Header 通知铃铛（Phase-3 §2.3.3）：未读红点（轮询）+ 下拉列表 + 点击直达工单 + 全部已读。
export default function NotificationBell() {
  const router = useRouter();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const { count, items, loading, error, refresh, markRead, markAllRead } = useNotifications(open);
  const wrapRef = useRef<HTMLDivElement>(null);

  async function onMarkAllRead() {
    try {
      await markAllRead();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "操作失败，请重试");
    }
  }

  // 点击外部 / Esc 关闭（a11y）。
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  async function onOpenItem(n: Notification) {
    setOpen(false);
    if (!n.is_read) {
      try {
        await markRead(n.id);
      } catch {
        /* 已读失败不阻断跳转 */
      }
    }
    if (n.entity_type && n.entity_id != null) {
      const seg = n.entity_type === "bug" ? "bugs" : "requirements";
      router.push(`/${seg}/board?ticket=${n.entity_id}`);
      // 已在目标看板时，同路由 push 不重挂载、其 mount 读取不触发；派发事件即时打开抽屉（与全局搜索同策略）。
      window.dispatchEvent(
        new CustomEvent("aragon:open-ticket", { detail: { entity: seg, id: n.entity_id } })
      );
    }
  }

  const badge = count > 99 ? "99+" : String(count);

  return (
    <div className="relative" ref={wrapRef}>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-label={`通知${count > 0 ? `（${count} 条未读）` : ""}`}
        aria-haspopup="menu"
        aria-expanded={open}
        className="relative flex h-9 w-9 items-center justify-center rounded-lg text-ink-muted hover:bg-black/[0.04] hover:text-ink"
      >
        <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>
        {count > 0 && (
          <span className="absolute -right-0.5 -top-0.5 inline-flex min-w-[16px] items-center justify-center rounded-full bg-[#B23B1E] px-1 text-[10px] font-semibold leading-4 text-white">
            {badge}
          </span>
        )}
      </button>

      {open && (
        <div
          role="menu"
          aria-label="通知列表"
          className="absolute right-0 z-50 mt-2 w-80 overflow-hidden rounded-xl border border-border bg-surface shadow-lift"
        >
          <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
            <span className="text-sm font-semibold text-ink">通知</span>
            {count > 0 && (
              <button
                onClick={onMarkAllRead}
                className="text-xs text-clay-dark hover:underline"
              >
                全部已读
              </button>
            )}
          </div>

          <div className="max-h-[22rem] overflow-y-auto">
            {/* 【§2.8③】error 分支必须在 loading **之前**：此前 error 从不被返回，
                后端一挂下拉就永久停在「加载中…」，既无重试也无提示。 */}
            {error ? (
              <ErrorState message="无法加载通知" onRetry={() => refresh()} />
            ) : loading ? (
              <div className="px-4 py-8 text-center text-sm text-ink-muted">加载中…</div>
            ) : items.length === 0 ? (
              <div className="px-4 py-10 text-center text-sm text-ink-muted">暂无通知</div>
            ) : (
              <ul>
                {items.map((n) => (
                  <li key={n.id}>
                    <button
                      role="menuitem"
                      onClick={() => onOpenItem(n)}
                      className={[
                        "flex w-full items-start gap-3 border-b border-border px-4 py-3 text-left last:border-0 hover:bg-black/[0.03]",
                        n.is_read ? "" : "bg-clay-soft/20",
                      ].join(" ")}
                    >
                      <span className="mt-0.5 shrink-0">
                        <AuthorAvatar author={n.actor} size={26} fallback={notificationIcon(n.type)} />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="flex items-center gap-1.5">
                          <span className="text-[11px] font-medium text-clay-dark">
                            {notificationLabel(n.type)}
                          </span>
                          {!n.is_read && (
                            <span className="inline-block h-1.5 w-1.5 rounded-full bg-[#B23B1E]" />
                          )}
                        </span>
                        <span className="mt-0.5 block text-sm text-ink">{n.message}</span>
                        <span className="mt-0.5 block text-xs text-ink-muted/70">
                          {relTime(n.created_at)}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="border-t border-border px-4 py-2 text-center">
            <Link
              href="/notifications"
              role="menuitem"
              onClick={() => setOpen(false)}
              className="text-xs text-ink-muted hover:text-clay-dark hover:underline"
            >
              查看全部
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
