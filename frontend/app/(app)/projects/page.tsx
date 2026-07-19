"use client";

// 项目管理页（admin-console §2.4）：项目列表 + 「+新建项目」。
// 后端仅提供 list/create，本页只做列表 + 新建；编辑 / 删除按 §8 交棒未来，不放假按钮。

import { useState } from "react";
import useSWR from "swr";
import { swrFetcher } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Project, User } from "@/lib/types";
import Header from "@/components/layout/Header";
import Button from "@/components/ui/Button";
import { SkeletonRows } from "@/components/ui/Skeleton";
import EmptyState from "@/components/ui/EmptyState";
import ProjectFormModal from "@/components/admin/ProjectFormModal";

export default function ProjectsPage() {
  const { user } = useAuth();
  const { data: projects, mutate } = useSWR<Project[]>("/projects", swrFetcher);
  const { data: users } = useSWR<User[]>("/users", swrFetcher);
  const canCreate = user?.role === "admin" || user?.role === "pm";
  const [creating, setCreating] = useState(false);

  function ownerName(ownerId: number | null): string {
    if (ownerId == null) return "—";
    const owner = users?.find((u) => u.id === ownerId);
    return owner ? owner.display_name || owner.username : "—";
  }

  return (
    <>
      <Header
        title="项目"
        subtitle="研发项目容器"
        action={
          canCreate ? (
            <Button size="sm" onClick={() => setCreating(true)}>
              + 新建项目
            </Button>
          ) : undefined
        }
      />
      <main className="flex-1 overflow-y-auto p-6">
        <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-card">
          {!projects ? (
            <SkeletonRows rows={4} />
          ) : projects.length === 0 ? (
            <EmptyState
              title="还没有项目"
              hint={canCreate ? "点击右上角「新建项目」创建第一个研发项目。" : "暂无项目。"}
              action={canCreate ? (
                <Button size="sm" onClick={() => setCreating(true)}>+ 新建项目</Button>
              ) : undefined}
            />
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-ink-muted">
                  <th className="px-4 py-3 font-medium">标识</th>
                  <th className="px-4 py-3 font-medium">名称</th>
                  <th className="px-4 py-3 font-medium">描述</th>
                  <th className="px-4 py-3 font-medium">负责人</th>
                </tr>
              </thead>
              <tbody>
                {projects.map((p) => (
                  <tr key={p.id} className="border-b border-border last:border-0 hover:bg-black/[0.015]">
                    <td className="px-4 py-3">
                      <span className="rounded-md bg-clay-soft/60 px-2 py-0.5 font-mono text-xs font-medium text-clay-dark">
                        {p.key}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-medium text-ink">{p.name}</td>
                    <td className="px-4 py-3 text-ink-muted">{p.description || "—"}</td>
                    <td className="px-4 py-3 text-ink-muted">{ownerName(p.owner_id)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </main>

      <ProjectFormModal
        open={creating}
        onClose={() => setCreating(false)}
        onSaved={() => {
          setCreating(false);
          mutate();
        }}
      />
    </>
  );
}
