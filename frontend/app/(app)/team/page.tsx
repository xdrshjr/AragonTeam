"use client";

import { useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { USERS_KEY, api, swrFetcher } from "@/lib/api";
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
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import MemberFormModal, { MemberFormState } from "@/components/admin/MemberFormModal";

export default function TeamPage() {
  const { user: me } = useAuth();
  const toast = useToast();
  const { mutate: globalMutate } = useSWRConfig();
  // 【§2.7-A3】接 error/加载态：失败不再渲染空表（误读为「无成员」），加载中给骨架。
  const { data: users, error, mutate } = useSWR<User[]>(USERS_KEY, swrFetcher);
  const isAdmin = me?.role === "admin";
  // 建 / 改 / 重置密码三态弹窗（后端写接口限 admin，member 隐藏所有写入口）。
  const [editing, setEditing] = useState<MemberFormState | null>(null);
  // 停用 / 启用二次确认（lifecycle-and-governance §2.5）。
  const [toggling, setToggling] = useState<User | null>(null);

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
        <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-card">
          {error && !users ? (
            <ErrorState message="无法加载团队成员" onRetry={() => mutate()} />
          ) : !users ? (
            <SkeletonRows rows={5} />
          ) : (
            <table className="w-full text-sm">
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
                        {u.is_active === false && (
                          <span className="rounded-md border border-border px-1.5 py-0.5 text-xs font-normal text-ink-muted">
                            已停用
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-ink-muted">{u.username}</td>
                    <td className="px-4 py-3 text-ink-muted">{u.email || "—"}</td>
                    <td className="px-4 py-3 text-ink">{ROLE_LABELS[u.role]}</td>
                    {isAdmin && (
                      <td className="px-4 py-3">
                        <div className="flex justify-end gap-2">
                          <Button variant="ghost" size="sm"
                                  onClick={() => setEditing({ mode: "edit", user: u })}>
                            编辑
                          </Button>
                          <Button variant="ghost" size="sm"
                                  onClick={() => setEditing({ mode: "reset", user: u })}>
                            重置密码
                          </Button>
                          <Button
                            variant={u.is_active === false ? "ghost" : "danger"}
                            size="sm"
                            onClick={() => setToggling(u)}
                          >
                            {u.is_active === false ? "启用" : "停用"}
                          </Button>
                        </div>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        {isAdmin ? (
          <p className="mt-3 text-xs text-ink-muted">
            成员只能停用、不能删除：他提过的需求与 BUG 需要保留完整的协作轨迹。
            停用会立刻切断登录与被指派的能力，已有工单一律保持原样（由你决定是否改派）。
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
        onSaved={() => {
          setEditing(null);
          mutate();
        }}
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
