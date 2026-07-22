"use client";

// 「版本 / 计划」控制台（version-plan-console §7.1）。
//
// 骨架照抄 app/(app)/projects/page.tsx：角色门禁 → 弹窗状态三件套 → 数据 → refresh()
// → 四段渲染梯（ErrorState / SkeletonRows / EmptyState / 正文）→ 底部弹窗群。
// 页面本体只做「取数 → 编排 → 弹窗挂载」，树的每一层各有自己的组件（R-12 尺寸红线）。

import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { PROJECTS_KEY, USERS_KEY, swrFetcher } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { isHierarchyParam } from "@/lib/hierarchy";
import { useProjectScope } from "@/lib/project-scope";
import { useToast } from "@/lib/toast";
import { useHierarchyOptions } from "@/hooks/useHierarchyOptions";
import { usePlanMutations } from "@/hooks/usePlans";
import { useVersions, VERSION_PAGE_SIZE } from "@/hooks/useVersions";
import type { Plan, Project, User, Version } from "@/lib/types";
import { VERSION_STATUS_OPTIONS } from "@/lib/constants";
import Header from "@/components/layout/Header";
import Button from "@/components/ui/Button";
import Checkbox from "@/components/ui/Checkbox";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import EmptyState from "@/components/ui/EmptyState";
import ErrorState from "@/components/ui/ErrorState";
import Pagination from "@/components/ui/Pagination";
import { SkeletonRows } from "@/components/ui/Skeleton";
import VersionCard from "@/components/planning/VersionCard";
import VersionFormModal, { VersionFormState } from "@/components/planning/VersionFormModal";
import PlanFormModal, { PlanFormState } from "@/components/planning/PlanFormModal";

export default function VersionsPage() {
  const { user } = useAuth();
  const toast = useToast();
  const { scope, scopeParam, scopeLabel } = useProjectScope();
  // §3.7：版本 / 计划的写操作后端恒为 admin|pm。**这与抽屉里那个行级 canManage 不是
  // 同一个判据**——两处同名不同义，勿串。
  const canManage = user?.role === "admin" || user?.role === "pm";

  const [status, setStatus] = useState("");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [offset, setOffset] = useState(0);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  const { versions, total, isLoading, error, refresh, create, update, remove } =
    useVersions({ projectParam: scopeParam, status, includeArchived, offset });
  const { data: users } = useSWR<User[]>(USERS_KEY, swrFetcher);
  const { data: projects } = useSWR<Project[]>(PROJECTS_KEY, swrFetcher);
  // 计划改挂版本的下拉数据源（作用域内的全部版本，不分页）。
  const { versions: allVersions } = useHierarchyOptions();
  const planOps = usePlanMutations();

  const [versionForm, setVersionForm] = useState<VersionFormState | null>(null);
  const [planForm, setPlanForm] = useState<PlanFormState | null>(null);
  const [deletingVersion, setDeletingVersion] = useState<Version | null>(null);
  const [deletingPlan, setDeletingPlan] = useState<Plan | null>(null);

  // 承接 PlanBadge 的「?version_id=<id>」深链：落地即展开那个版本。
  // 同一个白名单守卫（正整数或 none），非法值直接忽略而不是展开一个不存在的版本。
  useEffect(() => {
    const raw = new URLSearchParams(window.location.search).get("version_id") || "";
    if (isHierarchyParam(raw) && raw !== "none") {
      setExpanded(new Set([Number(raw)]));
    }
  }, []);

  // 任一筛选变化 → 回第一页；否则「筛出 2 个却停在 offset=20」会看到空页。
  const filterSignature = `${scopeParam}|${status}|${includeArchived}`;
  useEffect(() => {
    setOffset(0);
  }, [filterSignature]);

  const ownerNameOf = useMemo(() => {
    return (ownerId: number | null): string => {
      if (ownerId == null) return "—";
      const owner = users?.find((u) => u.id === ownerId);
      // 映射不中时渲染 `—` 而不是 id：一个裸数字对用户没有任何意义。
      return owner ? owner.display_name || owner.username : "—";
    };
  }, [users]);

  const projectKeyOf = useMemo(() => {
    return (projectId: number): string | null => {
      // 只在「全部项目」作用域下才标注项目：已选定具体项目时它是屏幕上的噪音
      // （顶部 scopeLabel 已经说过一遍了）。
      if (scope !== null) return null;
      return projects?.find((p) => p.id === projectId)?.key ?? `#${projectId}`;
    };
  }, [scope, projects]);

  function toggleExpanded(versionId: number) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(versionId)) next.delete(versionId);
      else next.add(versionId);
      return next;
    });
  }

  /** 归档后不能让对象凭空消失（R-15）：后端列表默认隐藏 archived，点完「归档」卡片
   *  当场蒸发、而「显示已归档」此刻可能还是灰的，用户会以为自己误删了。
   *  归档成功后**自动打开「显示已归档」**（必要时先清空状态下拉），卡片留在原位、
   *  徽章变「已归档」、「取消归档」就在同一个菜单里——可逆的动作必须看起来可逆。 */
  function revealArchived() {
    setStatus("");
    setIncludeArchived(true);
  }

  async function onToggleArchiveVersion(version: Version) {
    const archiving = version.status !== "archived";
    try {
      await update(version.id, { status: archiving ? "archived" : "planning" });
      if (archiving) {
        revealArchived();
        toast.success("已归档；已为你打开「显示已归档」");
      } else {
        toast.success("已取消归档（状态回到「规划中」）");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "操作失败");
    }
  }

  async function onToggleArchivePlan(plan: Plan) {
    const archiving = plan.status !== "archived";
    try {
      await planOps.update(plan.id, { status: archiving ? "archived" : "planning" });
      if (archiving) {
        revealArchived();
        toast.success("已归档；已为你打开「显示已归档」");
      } else {
        toast.success("已取消归档（状态回到「规划中」）");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "操作失败");
    }
  }

  // 「状态」与「显示已归档」在后端是 `if status: … elif include_archived …`——选了具体
  // 状态后勾选框完全不起作用。故此时把它禁用并说明原因：一个点了没反应的控件就是在说谎。
  const archivedCheckboxDisabled = Boolean(status);
  const hasFilter = Boolean(status) || includeArchived;
  // versions.project_id 是 NOT NULL，`?project_id=none` 的查询恒为空集（R-3）。
  const scopeIsNone = scope === "none";

  return (
    <>
      <Header
        title="版本 / 计划"
        subtitle={
          isLoading && !versions.length
            ? "规划版本、排布计划，再把需求与 BUG 挂到计划上"
            : `共 ${total} 个版本${scopeLabel ? ` · ${scopeLabel}` : ""}`
        }
        action={
          canManage && !scopeIsNone && typeof scope === "number" ? (
            <Button size="sm" onClick={() => setVersionForm({ mode: "create", projectId: scope })}>
              + 新建版本
            </Button>
          ) : undefined
        }
      />

      <main className="flex-1 overflow-y-auto p-6">
        {/* 轻量筛选条：只有「状态」与「显示已归档」。**不复用 FilterBar**——那是工单
            列表的形状（关键字 / 级别 / 指派人），硬塞会把它变成一个什么都做的组件。 */}
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            aria-label="按版本状态过滤"
            className="h-9 rounded-lg border border-border bg-surface px-2.5 text-sm text-ink focus:border-clay focus:outline-none focus:ring-2 focus:ring-clay/20"
          >
            <option value="">全部状态</option>
            {VERSION_STATUS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>

          <label
            className={[
              "inline-flex items-center gap-2 text-sm",
              archivedCheckboxDisabled ? "text-ink-muted/60" : "text-ink-muted",
            ].join(" ")}
            title={
              archivedCheckboxDisabled
                ? "已按具体状态筛选，归档与否由该状态决定"
                : undefined
            }
          >
            <Checkbox
              aria-label="显示已归档的版本与计划"
              checked={includeArchived}
              disabled={archivedCheckboxDisabled}
              onToggleSelected={() => setIncludeArchived((v) => !v)}
            />
            显示已归档
          </label>

          {hasFilter && (
            <button
              onClick={() => {
                setStatus("");
                setIncludeArchived(false);
              }}
              className="h-9 rounded-lg px-3 text-sm text-ink-muted hover:bg-black/[0.04] hover:text-ink"
            >
              清空
            </button>
          )}
        </div>

        {error && !versions.length ? (
          <div className="rounded-xl border border-border bg-surface shadow-card">
            <ErrorState message="无法加载版本列表" onRetry={() => refresh()} />
          </div>
        ) : isLoading && !versions.length ? (
          <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-card">
            <SkeletonRows rows={4} />
          </div>
        ) : versions.length === 0 ? (
          <div className="rounded-xl border border-border bg-surface shadow-card">
            {scopeIsNone ? (
              // R-3：作用域为「未归属项目」时本页恒空——版本必须归属一个项目。
              // 把「不可能有」说成人话，并**隐藏新建按钮**。
              <EmptyState
                title="版本必须归属一个项目"
                hint="请在顶部切换到一个具体项目后再新建版本。"
              />
            ) : typeof scope !== "number" ? (
              <EmptyState
                title="还没有版本"
                hint={
                  canManage
                    ? "请在顶部切换到一个具体项目后新建版本；版本创建后不可更换项目。"
                    : "版本由项目经理或管理员创建。"
                }
              />
            ) : (
              <EmptyState
                title="还没有版本"
                hint={
                  canManage
                    ? "先建一个版本，再在它下面排计划，最后把需求 / BUG 挂到计划上。"
                    : "版本由项目经理或管理员创建。"
                }
                action={
                  canManage ? (
                    <Button size="sm"
                            onClick={() => setVersionForm({ mode: "create", projectId: scope })}>
                      + 新建版本
                    </Button>
                  ) : undefined
                }
              />
            )}
          </div>
        ) : (
          <>
            <div className="space-y-3">
              {versions.map((version) => (
                <VersionCard
                  key={version.id}
                  version={version}
                  expanded={expanded.has(version.id)}
                  onToggle={toggleExpanded}
                  canManage={canManage}
                  ownerName={ownerNameOf(version.owner_id)}
                  projectBadge={projectKeyOf(version.project_id)}
                  status={status}
                  includeArchived={includeArchived}
                  onEdit={(v) => setVersionForm({ mode: "edit", version: v })}
                  onToggleArchive={onToggleArchiveVersion}
                  onDelete={setDeletingVersion}
                  onCreatePlan={(v) => setPlanForm({ mode: "create", version: v })}
                  onEditPlan={(p) => setPlanForm({ mode: "edit", plan: p })}
                  onToggleArchivePlan={onToggleArchivePlan}
                  onDeletePlan={setDeletingPlan}
                />
              ))}
            </div>
            <div className="mt-3 overflow-hidden rounded-xl border border-border bg-surface">
              <Pagination
                offset={offset}
                limit={VERSION_PAGE_SIZE}
                total={total}
                onOffset={setOffset}
                disabled={isLoading}
              />
            </div>
          </>
        )}

        <p className="mt-3 text-xs text-ink-muted">
          层级为「项目 → 版本 → 计划 → 需求 / BUG」。归档只是把对象从默认列表收起，
          它下面的工单不受任何影响；删除则要求先清空下一层——版本要先删掉它的计划，
          计划要先把工单移走或删除。
        </p>
      </main>

      <VersionFormModal
        state={versionForm}
        users={users}
        projects={projects}
        onCreate={create}
        onUpdate={update}
        onClose={() => setVersionForm(null)}
        onSaved={() => {
          setVersionForm(null);
          refresh();
        }}
      />

      <PlanFormModal
        state={planForm}
        versions={allVersions}
        onCreate={planOps.create}
        onUpdate={planOps.update}
        onClose={() => setPlanForm(null)}
        onSaved={() => {
          setPlanForm(null);
          refresh();
        }}
      />

      <ConfirmDialog
        open={!!deletingVersion}
        title="删除版本"
        description={
          <>
            将永久删除版本「{deletingVersion?.name}」，
            <strong className="text-ink">不可恢复</strong>。
            若它下面还有计划，删除会被拒绝——请先删掉那些计划。
          </>
        }
        onConfirm={() => remove((deletingVersion as Version).id)}
        onClose={() => setDeletingVersion(null)}
      />

      <ConfirmDialog
        open={!!deletingPlan}
        title="删除计划"
        description={
          <>
            将永久删除计划「{deletingPlan?.name}」，
            <strong className="text-ink">不可恢复</strong>。
            若它下面还挂着需求或 BUG，删除会被拒绝——请先把它们移到其他计划或删除。
            <strong className="text-ink">工单本身不会被这一步删掉。</strong>
          </>
        }
        onConfirm={() => planOps.remove((deletingPlan as Plan).id)}
        onClose={() => setDeletingPlan(null)}
      />
    </>
  );
}
