"use client";

import { useRouter } from "next/navigation";
import useSWR from "swr";
import { api, listFetcher, ApiError } from "@/lib/api";
import { useToast } from "@/lib/toast";
import type { Notification } from "@/lib/types";
import { notificationIcon, notificationLabel } from "@/lib/constants";
import Header from "@/components/layout/Header";
import Button from "@/components/ui/Button";
import EmptyState from "@/components/ui/EmptyState";
import ErrorState from "@/components/ui/ErrorState";
import { SkeletonRows } from "@/components/ui/Skeleton";
import { AuthorAvatar } from "@/components/ui/Avatar";

function shortTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

export default function NotificationsPage() {
  const router = useRouter();
  const toast = useToast();
  const { data, error, mutate } = useSWR("/notifications?limit=100", listFetcher<Notification>);
  const items = data?.items;

  async function openItem(n: Notification) {
    if (!n.is_read) {
      try {
        await api.post(`/notifications/${n.id}/read`);
        mutate();
      } catch {
        /* 忽略：不阻断跳转 */
      }
    }
    if (n.entity_type && n.entity_id != null) {
      const seg = n.entity_type === "bug" ? "bugs" : "requirements";
      router.push(`/${seg}/board?ticket=${n.entity_id}`);
      // 已在目标看板时同路由 push 不重挂载；派发事件即时打开抽屉（与铃铛一致）。
      window.dispatchEvent(
        new CustomEvent("aragon:open-ticket", { detail: { entity: seg, id: n.entity_id } })
      );
    }
  }

  async function readAll() {
    try {
      await api.post("/notifications/read-all");
      mutate();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "操作失败，请重试");
    }
  }

  return (
    <>
      <Header
        title="通知"
        subtitle={data ? `共 ${data.total} 条` : "与你相关的一切"}
        action={
          items && items.some((n) => !n.is_read) ? (
            <Button size="sm" variant="ghost" onClick={readAll}>
              全部已读
            </Button>
          ) : undefined
        }
      />
      <main className="flex-1 overflow-y-auto p-6">
        <div className="mx-auto max-w-2xl overflow-hidden rounded-xl border border-border bg-surface shadow-card">
          {error && !items ? (
            <ErrorState message="无法加载通知" onRetry={() => mutate()} />
          ) : !items ? (
            <SkeletonRows rows={6} />
          ) : items.length === 0 ? (
            <EmptyState title="暂无通知" hint="被指派、被评论、被提及或工单被推进时，都会出现在这里。" />
          ) : (
            <ul>
              {items.map((n) => (
                <li key={n.id}>
                  <button
                    onClick={() => openItem(n)}
                    className={[
                      "flex w-full items-start gap-3 border-b border-border px-4 py-3.5 text-left last:border-0 hover:bg-black/[0.02]",
                      n.is_read ? "" : "bg-clay-soft/20",
                    ].join(" ")}
                  >
                    <span className="mt-0.5 shrink-0">
                      <AuthorAvatar author={n.actor} size={28} fallback={notificationIcon(n.type)} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="text-xs font-medium text-clay-dark">
                          {notificationLabel(n.type)}
                        </span>
                        {!n.is_read && (
                          <span className="inline-block h-1.5 w-1.5 rounded-full bg-[#B23B1E]" />
                        )}
                      </span>
                      <span className="mt-0.5 block text-sm text-ink">{n.message}</span>
                      <span className="mt-0.5 block text-xs text-ink-muted/70">
                        {shortTime(n.created_at)}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </main>
    </>
  );
}
