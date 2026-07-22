"use client";

// 可折叠版本卡（version-plan-console §5.4 / §7.1）：
// 名称 + 状态徽章 + 目标日期 + 负责人 + 计划数 + 聚合进度条 + ⋯ 菜单；展开渲染 <VersionPlans>。

import Badge from "@/components/ui/Badge";
import ProgressBar from "@/components/ui/ProgressBar";
import RowMenu from "@/components/planning/RowMenu";
import VersionPlans from "@/components/planning/VersionPlans";
import { VERSION_STATUS_STYLES } from "@/lib/constants";
import type { Plan, Version } from "@/lib/types";

interface Props {
  version: Version;
  expanded: boolean;
  onToggle: (versionId: number) => void;
  canManage: boolean;
  /** 负责人显示名；映射不中时调用方传 `—`（一个裸 id 对用户没有任何意义）。 */
  ownerName: string;
  /** 「全部项目」作用域下才传：两个项目各有一个「v1.0」是常态，卡上必须能分辨。 */
  projectBadge?: string | null;
  status: string;
  includeArchived: boolean;
  onEdit: (version: Version) => void;
  onToggleArchive: (version: Version) => void;
  onDelete: (version: Version) => void;
  onCreatePlan: (version: Version) => void;
  onEditPlan: (plan: Plan) => void;
  onToggleArchivePlan: (plan: Plan) => void;
  onDeletePlan: (plan: Plan) => void;
}

function dateLine(version: Version): string {
  if (version.status === "released" && version.released_at) {
    return `发布于 ${version.released_at.slice(0, 10)}`;
  }
  return version.target_date ? `目标 ${version.target_date}` : "未设目标日期";
}

export default function VersionCard({
  version, expanded, onToggle, canManage, ownerName, projectBadge,
  status, includeArchived,
  onEdit, onToggleArchive, onDelete,
  onCreatePlan, onEditPlan, onToggleArchivePlan, onDeletePlan,
}: Props) {
  const panelId = `version-plans-${version.id}`;
  const archived = version.status === "archived";

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-card">
      <div className="flex items-start gap-3 px-4 py-3">
        {/* 整个卡头是一个折叠按钮：键盘可达（Enter / Space 由原生 button 提供），
            aria-expanded / aria-controls 让读屏知道它控制着下面那块。 */}
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={panelId}
          onClick={() => onToggle(version.id)}
          className="flex min-w-0 flex-1 flex-col gap-2 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-clay/40"
        >
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span
              aria-hidden="true"
              className={[
                "text-ink-muted transition-transform duration-150",
                expanded ? "rotate-90" : "",
              ].join(" ")}
            >
              ▸
            </span>
            <span className="font-serif text-base text-ink">{version.name}</span>
            <Badge style={VERSION_STATUS_STYLES[version.status]} />
            {projectBadge && (
              <span className="rounded-md bg-clay-soft/60 px-2 py-0.5 font-mono text-xs font-medium text-clay-dark">
                {projectBadge}
              </span>
            )}
            <span className="text-xs text-ink-muted">{dateLine(version)}</span>
            <span className="text-xs text-ink-muted">负责人 {ownerName}</span>
          </div>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 pl-6 text-xs text-ink-muted">
            {/* 进度**只读后端聚合的 total_count / done_count**：plans 是分页的，
                在前端对计划列表求和必然漏算（services/hierarchy 逐字写明了这一条）。 */}
            {version.total_count === 0 ? (
              <span>暂无工单</span>
            ) : (
              <>
                <div className="w-48">
                  <ProgressBar
                    value={Math.round((version.done_count / version.total_count) * 100)}
                    label={`版本进度 ${version.done_count}/${version.total_count}`}
                  />
                </div>
                <span>{version.done_count} / {version.total_count} 已完成</span>
              </>
            )}
            <span>{version.plan_count} 个计划</span>
          </div>
        </button>

        {canManage && (
          <RowMenu
            ariaLabel={`版本 ${version.name} 的更多操作`}
            items={[
              { label: "编辑", onSelect: () => onEdit(version) },
              {
                label: archived ? "取消归档" : "归档",
                onSelect: () => onToggleArchive(version),
              },
              { label: "删除", danger: true, onSelect: () => onDelete(version) },
            ]}
          />
        )}
      </div>

      {/* 折叠即**卸载**——这就是懒加载边界本身（§3.4）。 */}
      {expanded && (
        <div id={panelId}>
          <VersionPlans
            versionId={version.id}
            canManage={canManage}
            status={status}
            includeArchived={includeArchived}
            onCreatePlan={() => onCreatePlan(version)}
            onEditPlan={onEditPlan}
            onToggleArchivePlan={onToggleArchivePlan}
            onDeletePlan={onDeletePlan}
          />
        </div>
      )}
    </div>
  );
}
