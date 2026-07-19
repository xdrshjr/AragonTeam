"use client";

import { useState } from "react";
import useSWR from "swr";
import { swrFetcher } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { User } from "@/lib/types";
import { ROLE_LABELS } from "@/lib/constants";
import Header from "@/components/layout/Header";
import Button from "@/components/ui/Button";
import Avatar from "@/components/ui/Avatar";
import MemberFormModal, { MemberFormState } from "@/components/admin/MemberFormModal";

export default function TeamPage() {
  const { user: me } = useAuth();
  const { data: users, mutate } = useSWR<User[]>("/users", swrFetcher);
  const isAdmin = me?.role === "admin";
  // 建 / 改 / 重置密码三态弹窗（后端写接口限 admin，member 隐藏所有写入口）。
  const [editing, setEditing] = useState<MemberFormState | null>(null);

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
              {users?.map((u) => (
                <tr key={u.id} className="border-b border-border last:border-0 hover:bg-black/[0.015]">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <Avatar name={u.display_name || u.username} color={u.avatar_color} size={28} />
                      <span className="font-medium text-ink">
                        {u.display_name || u.username}
                      </span>
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
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!isAdmin && (
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
    </>
  );
}
