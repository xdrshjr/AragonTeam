"use client";

// 项目管理页（admin-console §2.4 + lifecycle-and-governance §2.6）：
// 列表 + 新建 + 行操作「编辑 / 归档 / 删除」。
// 归档优于删除：有工单挂靠的项目删不掉（后端 409），确认框会就地显示还剩多少张单。

import { useState } from "react";
import { useRouter } from "next/navigation";
import useSWR, { useSWRConfig } from "swr";
import { PROJECTS_ALL_KEY, USERS_KEY, api, swrFetcher } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/lib/toast";
import { useProjectScope } from "@/lib/project-scope";
import { invalidateAdminViews } from "@/lib/swr-keys";
import type { Project, User } from "@/lib/types";
import Header from "@/components/layout/Header";
import Button from "@/components/ui/Button";
import { SkeletonRows } from "@/components/ui/Skeleton";
import EmptyState from "@/components/ui/EmptyState";
import ErrorState from "@/components/ui/ErrorState";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import ProjectFormModal, { ProjectFormState } from "@/components/admin/ProjectFormModal";

export default function ProjectsPage() {
  const { user } = useAuth();
  const router = useRouter();
  const toast = useToast();
  const { mutate } = useSWRConfig();
  const { scope, setScope } = useProjectScope();
  // 本页列出全部项目（含归档）；切换器与建单表单仍只读 PROJECTS_KEY（不含归档）。
  const { data: projects, error, mutate: mutateProjects } =
    useSWR<Project[]>(PROJECTS_ALL_KEY, swrFetcher);
  const { data: users } = useSWR<User[]>(USERS_KEY, swrFetcher);
  const canCreate = user?.role === "admin" || user?.role === "pm";
  const canDelete = user?.role === "admin"; // 后端 DELETE 限 admin，比 PATCH 更严
  const [form, setForm] = useState<ProjectFormState | null>(null);
  const [deleting, setDeleting] = useState<Project | null>(null);
  const [archiving, setArchiving] = useState<Project | null>(null);

  // 【§2.4⑦】此前表格行不可点击、无链接——侧边栏把「项目」作为一级导航，点进来却是死胡同。
  function openProject(p: Project) {
    setScope(p.id);
    router.push("/requirements");
  }

  function ownerName(ownerId: number | null): string {
    if (ownerId == null) return "—";
    const owner = users?.find((u) => u.id === ownerId);
    return owner ? owner.display_name || owner.username : "—";
  }

  /** 归档 / 删除都会改变 PROJECTS_KEY 的结果集，两份缓存必须一起失效。 */
  function refreshProjects() {
    mutateProjects();
    invalidateAdminViews(mutate);
  }

  async function onToggleArchive(p: Project) {
    await api.patch<Project>(`/projects/${p.id}`, { archived: !p.archived });
    // 归档当前作用域项目后，切换器读不到它 → project-scope 的失效自愈会回落「全部项目」。
    toast.success(p.archived ? "已取消归档" : "项目已归档");
    refreshProjects();
  }

  async function onDelete(p: Project) {
    await api.del(`/projects/${p.id}`);
    toast.success("项目已删除");
    if (scope === p.id) setScope(null);
    refreshProjects();
  }

  return (
    <>
      <Header
        title="项目"
        subtitle="研发项目容器"
        action={
          canCreate ? (
            <Button size="sm" onClick={() => setForm({ mode: "create" })}>
              + 新建项目
            </Button>
          ) : undefined
        }
      />
      <main className="flex-1 overflow-y-auto p-6">
        <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-card">
          {error && !projects ? (
            <ErrorState message="无法加载项目列表" onRetry={() => mutateProjects()} />
          ) : !projects ? (
            <SkeletonRows rows={4} />
          ) : projects.length === 0 ? (
            <EmptyState
              title="还没有项目"
              hint={canCreate ? "点击右上角「新建项目」创建第一个研发项目。" : "暂无项目。"}
              action={canCreate ? (
                <Button size="sm" onClick={() => setForm({ mode: "create" })}>+ 新建项目</Button>
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
                  {canCreate && <th className="px-4 py-3 font-medium text-right">操作</th>}
                </tr>
              </thead>
              <tbody>
                {projects.map((p) => (
                  <tr
                    key={p.id}
                    onClick={() => openProject(p)}
                    className={[
                      "cursor-pointer border-b border-border last:border-0 hover:bg-black/[0.015]",
                      scope === p.id ? "bg-clay-soft/30" : "",
                      p.archived ? "opacity-60" : "",
                    ].join(" ")}
                  >
                    <td className="px-4 py-3">
                      <span className="rounded-md bg-clay-soft/60 px-2 py-0.5 font-mono text-xs font-medium text-clay-dark">
                        {p.key}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-medium text-ink">
                      {p.name}
                      {scope === p.id && (
                        <span className="ml-2 rounded-md border border-[#E8C9BC] px-1.5 py-0.5 text-xs font-normal text-clay-dark">
                          当前
                        </span>
                      )}
                      {p.archived && (
                        <span className="ml-2 rounded-md border border-border px-1.5 py-0.5 text-xs font-normal text-ink-muted">
                          已归档
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-ink-muted">{p.description || "—"}</td>
                    <td className="px-4 py-3 text-ink-muted">{ownerName(p.owner_id)}</td>
                    {canCreate && (
                      // 行本身是「进入项目」的链接，操作按钮必须阻断冒泡，否则点删除会先跳走。
                      <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                        <div className="flex justify-end gap-2">
                          <Button variant="ghost" size="sm"
                                  onClick={() => setForm({ mode: "edit", project: p })}>
                            编辑
                          </Button>
                          <Button variant="ghost" size="sm" onClick={() => setArchiving(p)}>
                            {p.archived ? "取消归档" : "归档"}
                          </Button>
                          {canDelete && (
                            <Button variant="danger" size="sm" onClick={() => setDeleting(p)}>
                              删除
                            </Button>
                          )}
                        </div>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <p className="mt-3 text-xs text-ink-muted">
          归档只切断「未来把新东西放进去」：归档项目不再出现在项目切换器与建单表单里，
          它已有的工单仍可正常查询与流转。删除仅限空项目，且需管理员权限。
        </p>
      </main>

      <ProjectFormModal
        state={form}
        users={users}
        onClose={() => setForm(null)}
        onSaved={() => {
          setForm(null);
          refreshProjects();
        }}
      />

      <ConfirmDialog
        open={!!archiving}
        title={archiving?.archived ? "取消归档" : "归档项目"}
        danger={!archiving?.archived}
        confirmLabel={archiving?.archived ? "取消归档" : "确认归档"}
        description={
          archiving?.archived ? (
            <>项目「{archiving?.name}」将重新出现在项目切换器与建单表单里。</>
          ) : (
            <>
              项目「{archiving?.name}」将从项目切换器与建单表单中隐藏，
              <strong className="text-ink">它已有的工单不受任何影响</strong>，仍可查询与流转。
              需要时可随时取消归档。
            </>
          )
        }
        onConfirm={() => onToggleArchive(archiving as Project)}
        onClose={() => setArchiving(null)}
      />

      <ConfirmDialog
        open={!!deleting}
        title="删除项目"
        requireTypedConfirmation={deleting?.key}
        description={
          <>
            将永久删除项目「{deleting?.name}」，<strong className="text-ink">不可恢复</strong>。
            若它名下仍有需求或 BUG，删除会被拒绝——请先归档，或把工单移到别的项目。
          </>
        }
        onConfirm={() => onDelete(deleting as Project)}
        onClose={() => setDeleting(null)}
      />
    </>
  );
}
