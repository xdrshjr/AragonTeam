"use client";

// 账号动态（account-security-and-governance §6.3）——某个账号的治理时间线。
//
// 【为什么是 Modal 而不是抽屉】仓库里没有通用 `Drawer`：`components/ui/` 的 15 个文件里
// 没有它，唯一的抽屉 `components/TicketDrawer.tsx` 与工单强耦合（useTicket / 评论流 /
// agent-advance），不是可复用的壳。为一条**只读**时间线先造一套抽屉框架，代价明显高于
// 收益——而 `Modal` 已经带了 focus trap、Esc（经 overlay-stack 判定是否为栈顶）、
// role="dialog" / aria-modal，正是这块内容需要的全部东西。
//
// 权限：非 admin 不渲染入口（后端 `require_role("admin")` 才是门禁，前端隐藏只为体验，
// 与 RegistrationCard 的既有取向一致）。

import type { User, UserActivity } from "@/lib/types";
import { useUserActivities } from "@/hooks/useUserActivities";
import { ROLE_LABELS, userActivityIcon, userActivityLabel } from "@/lib/constants";
import Modal from "@/components/ui/Modal";
import EmptyState from "@/components/ui/EmptyState";
import ErrorState from "@/components/ui/ErrorState";
import { SkeletonRows } from "@/components/ui/Skeleton";

interface Props {
  /** null → 关闭。 */
  user: User | null;
  onClose: () => void;
}

// 相对时间（created_at 带 Z，正确解析为本地时间）。形状与 NotificationBell 的同名函数一致。
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
  return d.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
}

/** 角色迁移用中文呈现；`active`/`disabled` 这类非角色取值原样回显。 */
function valueLabel(value: string | null): string | null {
  if (!value) return null;
  return ROLE_LABELS[value] ?? value;
}

function ActivityRow({ item }: { item: UserActivity }) {
  const from = valueLabel(item.from_status);
  const to = valueLabel(item.to_status);
  const showTransition = item.action === "role_changed" && from && to;

  return (
    <li className="flex gap-3 py-3">
      <span aria-hidden="true" className="mt-0.5 w-5 shrink-0 text-center text-ink-muted">
        {userActivityIcon(item.action)}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="text-sm font-medium text-ink">{userActivityLabel(item.action)}</span>
          {showTransition && (
            <span className="text-xs text-ink-muted">
              {from} → {to}
            </span>
          )}
          <span className="ml-auto shrink-0 text-xs text-ink-muted">
            {relTime(item.created_at)}
          </span>
        </div>
        {item.message && <p className="mt-0.5 text-sm text-ink-muted">{item.message}</p>}
      </div>
    </li>
  );
}

export default function MemberActivityModal({ user, onClose }: Props) {
  const { items, total, loading, error, refresh } = useUserActivities(user?.id ?? null, !!user);

  return (
    <Modal
      open={!!user}
      onClose={onClose}
      title={user ? `账号动态 · ${user.display_name || user.username}` : undefined}
      width={640}
    >
      {error ? (
        <ErrorState message="无法加载账号动态" onRetry={() => refresh()} />
      ) : loading ? (
        <SkeletonRows rows={4} />
      ) : items.length === 0 ? (
        <EmptyState title="这个账号还没有治理记录" />
      ) : (
        <>
          <ul className="divide-y divide-border">
            {items.map((item) => (
              <ActivityRow key={item.id} item={item} />
            ))}
          </ul>
          {total > items.length && (
            <p className="mt-3 text-xs text-ink-muted">
              仅显示最近 {items.length} 条，共 {total} 条。
            </p>
          )}
        </>
      )}
    </Modal>
  );
}
