"use client";

import useSWR from "swr";
import { api, swrFetcher, ApiError } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { useAuth } from "@/lib/auth";
import type { User, Role } from "@/lib/types";
import { ROLE_LABELS } from "@/lib/constants";
import Header from "@/components/layout/Header";
import Avatar from "@/components/ui/Avatar";

const ROLE_OPTIONS: Role[] = ["admin", "pm", "member"];

export default function TeamPage() {
  const toast = useToast();
  const { user: me } = useAuth();
  const { data: users, mutate } = useSWR<User[]>("/users", swrFetcher);
  const isAdmin = me?.role === "admin";

  async function changeRole(u: User, role: Role) {
    try {
      await api.patch(`/users/${u.id}`, { role });
      toast.success(`已将 ${u.display_name || u.username} 设为${ROLE_LABELS[role]}`);
      mutate();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "修改失败");
    }
  }

  return (
    <>
      <Header
        title="团队"
        subtitle={isAdmin ? "管理成员与角色" : "团队成员一览"}
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
                  <td className="px-4 py-3">
                    {isAdmin ? (
                      <select
                        value={u.role}
                        onChange={(e) => changeRole(u, e.target.value as Role)}
                        className="h-8 rounded-lg border border-border bg-surface px-2 text-sm text-ink focus:border-clay focus:outline-none focus:ring-2 focus:ring-clay/20"
                      >
                        {ROLE_OPTIONS.map((r) => (
                          <option key={r} value={r}>
                            {ROLE_LABELS[r]}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <span className="text-ink">{ROLE_LABELS[u.role]}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!isAdmin && (
          <p className="mt-3 text-xs text-ink-muted">
            仅管理员可修改成员角色。
          </p>
        )}
      </main>
    </>
  );
}
