"use client";

import { useCallback, useMemo, useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { api, listFetcher } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/lib/toast";
import { invalidateAdminViews } from "@/lib/swr-keys";
import type { User } from "@/lib/types";
import { ROLE_LABELS } from "@/lib/constants";
import Header from "@/components/layout/Header";
import Button from "@/components/ui/Button";
import Avatar from "@/components/ui/Avatar";
import { SkeletonRows } from "@/components/ui/Skeleton";
import ErrorState from "@/components/ui/ErrorState";
import EmptyState from "@/components/ui/EmptyState";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import Pagination from "@/components/ui/Pagination";
import MemberFormModal, {
  MemberFormState,
  type TemporaryPasswordResult,
} from "@/components/admin/MemberFormModal";
import MemberActivityModal from "@/components/admin/MemberActivityModal";
import TemporaryPasswordDialog from "@/components/admin/TemporaryPasswordDialog";
import MemberFilterBar, {
  EMPTY_FILTERS,
  toQuery,
  type MemberFilters,
} from "@/components/admin/MemberFilterBar";

const PAGE_SIZE = 20;

// 根管理员那一行的危险操作**渲染为禁用并带 title 解释**，而不是隐藏：
// 隐藏会让管理员以为是自己权限不够，禁用 + 解释才是诚实的（§2.3 C-3）。
const ROOT_LOCK_HINT = "根管理员由后端配置文件（ROOT_ADMIN_*）定义，不可停用或被他人改密";

function RootBadge() {
  return (
    <span className="rounded-md bg-clay px-1.5 py-0.5 text-xs font-medium text-white">
      根管理员
    </span>
  );
}

function SourceBadge({ source }: { source: User["source"] }) {
  if (source !== "signup") return null;
  return (
    <span className="rounded-md bg-black/[0.05] px-1.5 py-0.5 text-xs font-normal text-ink-muted">
      自助注册
    </span>
  );
}

export default function TeamPage() {
  const { user: me } = useAuth();
  const toast = useToast();
  const { mutate: globalMutate } = useSWRConfig();
  const [filters, setFilters] = useState<MemberFilters>(EMPTY_FILTERS);
  const [offset, setOffset] = useState(0);

  // 【§2.3 C-3 · SWR key 隔离】本页自建 key，**不得**复用 lib/api.ts 的 USERS_KEY
  // （`/users?limit=200`）——那是 AssigneePicker 等选择器的单一 key，被筛选结果污染
  // 会让指派下拉突然只剩几个人。两者都以 `/users` 开头，`invalidateAdminViews` 的
  // 前缀失效因此同时覆盖二者，无需额外接线。
  const query = toQuery(filters);
  const key = `/users?limit=${PAGE_SIZE}&offset=${offset}${query ? `&${query}` : ""}`;
  const { data, error, mutate } = useSWR<{ items: User[]; total: number }>(key, listFetcher);
  const users = data?.items;
  const total = data?.total ?? 0;
  const isAdmin = me?.role === "admin";

  // 任一筛选变化 → 回到第 1 页（与 requirements / bugs 列表页同一约定）：
  // 停在第 3 页看一个只有 2 页的结果集，会显示成「什么都没有」。
  const onFilters = useCallback((next: MemberFilters) => {
    setFilters(next);
    setOffset(0);
  }, []);

  const [editing, setEditing] = useState<MemberFormState | null>(null);
  const [toggling, setToggling] = useState<User | null>(null);
  // 【account-security-and-governance §6.3】账号动态；【§6.2】一次性口令的唯一一次展示。
  const [viewingActivity, setViewingActivity] = useState<User | null>(null);
  const [temporary, setTemporary] = useState<TemporaryPasswordResult | null>(null);
  const hasFilters = useMemo(() => toQuery(filters).length > 0, [filters]);

  async function onToggleActive(u: User) {
    await api.patch<User>(`/users/${u.id}`, { is_active: !u.is_active });
    toast.success(u.is_active ? "成员已停用" : "成员已启用");
    mutate();
    invalidateAdminViews(globalMutate);
  }

  return (
    <>
      <Header
        title="团队"
        subtitle={isAdmin ? "管理成员与角色" : "团队成员一览"}
        action={
          isAdmin ? (
            <Button size="sm" onClick={() => setEditing({ mode: "create" })}>
              + 新增成员
            </Button>
          ) : undefined
        }
      />
      <main className="flex-1 overflow-y-auto p-6">
        <MemberFilterBar filters={filters} onChange={onFilters} />

        <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-card">
          {error && !users ? (
            <ErrorState message="无法加载团队成员" onRetry={() => mutate()} />
          ) : !users ? (
            <SkeletonRows rows={5} />
          ) : users.length === 0 ? (
            <EmptyState
              title={hasFilters ? "没有符合条件的成员" : "还没有成员"}
              hint={hasFilters ? "换一个关键词，或清空筛选条件再看看。" : undefined}
              action={
                hasFilters ? (
                  <Button variant="ghost" size="sm" onClick={() => onFilters(EMPTY_FILTERS)}>
                    清空筛选
                  </Button>
                ) : undefined
              }
            />
          ) : (
            <>
              {/* md 以下折叠为卡片列表：五列表格在手机上必然横向溢出（§6.3）。 */}
              <ul className="divide-y divide-border md:hidden">
                {users.map((u) => (
                  <li key={u.id} className={u.is_active === false ? "p-4 opacity-60" : "p-4"}>
                    <div className="flex items-center gap-2">
                      <Avatar name={u.display_name || u.username} color={u.avatar_color} size={28} />
                      <span className="font-medium text-ink">{u.display_name || u.username}</span>
                      {u.is_root && <RootBadge />}
                      {u.is_active === false && (
                        <span className="rounded-md border border-border px-1.5 py-0.5 text-xs text-ink-muted">
                          已停用
                        </span>
                      )}
                      {!u.is_root && u.is_active !== false && <SourceBadge source={u.source} />}
                    </div>
                    <div className="mt-1 text-xs text-ink-muted">
                      {u.username} · {ROLE_LABELS[u.role]}
                      {u.email ? ` · ${u.email}` : ""}
                    </div>
                    {isAdmin && (
                      <RowActions
                        user={u}
                        onEdit={setEditing}
                        onToggle={setToggling}
                        onActivity={setViewingActivity}
                        className="mt-3 flex-wrap justify-start"
                      />
                    )}
                  </li>
                ))}
              </ul>

              <table className="hidden w-full text-sm md:table">
                <thead>
                  <tr className="border-b border-border text-left text-ink-muted">
                    <th className="px-4 py-3 font-medium">成员</th>
                    <th className="px-4 py-3 font-medium">用户名</th>
                    <th className="px-4 py-3 font-medium">邮箱</th>
                    <th className="px-4 py-3 font-medium">角色</th>
                    {isAdmin && <th className="px-4 py-3 font-medium text-right">操作</th>}
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => (
                    <tr
                      key={u.id}
                      className={[
                        "border-b border-border last:border-0 hover:bg-black/[0.015]",
                        u.is_active === false ? "opacity-60" : "",
                      ].join(" ")}
                    >
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <Avatar name={u.display_name || u.username} color={u.avatar_color} size={28} />
                          <span className="font-medium text-ink">
                            {u.display_name || u.username}
                          </span>
                          {/* 视觉权重依次递减：根管理员 > 已停用 > 自助注册；一行最多两个。 */}
                          {u.is_root && <RootBadge />}
                          {u.is_active === false && (
                            <span className="rounded-md border border-border px-1.5 py-0.5 text-xs font-normal text-ink-muted">
                              已停用
                            </span>
                          )}
                          {!u.is_root && u.is_active !== false && <SourceBadge source={u.source} />}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-ink-muted">{u.username}</td>
                      <td className="px-4 py-3 text-ink-muted">{u.email || "—"}</td>
                      <td className="px-4 py-3 text-ink">{ROLE_LABELS[u.role]}</td>
                      {isAdmin && (
                        <td className="px-4 py-3">
                          <RowActions
                            user={u}
                            onEdit={setEditing}
                            onToggle={setToggling}
                            onActivity={setViewingActivity}
                          />
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>

              {/* total <= limit 时组件自渲染为 null，小团队观感与接分页前完全一致。 */}
              <Pagination
                offset={offset}
                limit={PAGE_SIZE}
                total={total}
                disabled={!users}
                onOffset={setOffset}
              />
            </>
          )}
        </div>
        {isAdmin ? (
          <p className="mt-3 text-xs text-ink-muted">
            成员只能停用、不能删除：他提过的需求与 BUG 需要保留完整的协作轨迹。
            停用会立刻切断登录与被指派的能力，已有工单一律保持原样（由你决定是否改派）。
            带「根管理员」徽章的那一行由后端配置文件定义，不可停用、不可降级。
          </p>
        ) : (
          <p className="mt-3 text-xs text-ink-muted">
            仅管理员可新增成员、修改资料与角色。
          </p>
        )}
      </main>

      <MemberFormModal
        state={editing}
        onClose={() => setEditing(null)}
        onSaved={(result) => {
          setEditing(null);
          mutate();
          // 一次性口令**关掉就再也读不到了**，故先关表单、再把它交给专属对话框。
          if (result) setTemporary(result);
        }}
      />

      <MemberActivityModal user={viewingActivity} onClose={() => setViewingActivity(null)} />

      <TemporaryPasswordDialog
        password={temporary?.password ?? null}
        memberName={temporary?.memberName ?? ""}
        onClose={() => setTemporary(null)}
      />

      <ConfirmDialog
        open={!!toggling}
        title={toggling?.is_active === false ? "启用成员" : "停用成员"}
        danger={toggling?.is_active !== false}
        confirmLabel={toggling?.is_active === false ? "确认启用" : "确认停用"}
        description={
          toggling?.is_active === false ? (
            <>
              「{toggling?.display_name || toggling?.username}」将恢复登录，
              并重新出现在指派选择器里。
            </>
          ) : (
            <>
              「{toggling?.display_name || toggling?.username}」将<strong className="text-ink">
              立即无法登录</strong>，其已签发的令牌下一次请求即失效，也不再出现在指派选择器与
              通知收件人里。他已有的工单<strong className="text-ink">保持原样</strong>，
              历史记录全部保留，随时可以重新启用。
              {toggling?.id === me?.id && (
                <div className="mt-2 text-[#B23B1E]">
                  这是你自己的账号——确认后你将立即退出登录。
                </div>
              )}
            </>
          )
        }
        onConfirm={() => onToggleActive(toggling as User)}
        onClose={() => setToggling(null)}
      />
    </>
  );
}

function RowActions({ user, onEdit, onToggle, onActivity, className = "justify-end" }: {
  user: User;
  onEdit: (s: MemberFormState) => void;
  onToggle: (u: User) => void;
  onActivity: (u: User) => void;
  className?: string;
}) {
  return (
    <div className={`flex gap-2 ${className}`}>
      <Button variant="ghost" size="sm" onClick={() => onEdit({ mode: "edit", user })}>
        编辑
      </Button>
      <span title={user.is_root ? ROOT_LOCK_HINT : undefined}>
        <Button
          variant="ghost"
          size="sm"
          disabled={user.is_root}
          onClick={() => onEdit({ mode: "reset", user })}
        >
          重置密码
        </Button>
      </span>
      {/* 「动态」对根管理员**照常可用**——看治理历史不是危险操作，
          `disabled={user.is_root}` 只作用于「重置密码 / 停用」两项。 */}
      <Button variant="ghost" size="sm" onClick={() => onActivity(user)}>
        动态
      </Button>
      <span title={user.is_root ? ROOT_LOCK_HINT : undefined}>
        <Button
          variant={user.is_active === false ? "ghost" : "danger"}
          size="sm"
          disabled={user.is_root}
          onClick={() => onToggle(user)}
        >
          {user.is_active === false ? "启用" : "停用"}
        </Button>
      </span>
    </div>
  );
}
