"use client";

// 单条计划行（version-plan-console §5.4 / §7.1）：
// 名称 + 状态徽章 + 周期 + 需求/BUG 计数（同时是深链）+ 进度条 + 行内动作。

import Link from "next/link";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import ProgressBar from "@/components/ui/ProgressBar";
import RowMenu from "@/components/planning/RowMenu";
import { PLAN_STATUS_STYLES } from "@/lib/constants";
import type { Plan } from "@/lib/types";

interface Props {
  plan: Plan;
  canManage: boolean;
  onEdit: (plan: Plan) => void;
  onToggleArchive: (plan: Plan) => void;
  onDelete: (plan: Plan) => void;
}

function period(plan: Plan): string {
  if (!plan.start_date && !plan.end_date) return "未设周期";
  return `${plan.start_date ?? "—"} ~ ${plan.end_date ?? "—"}`;
}

/** 计数即深链。**必须带 `project_id`**：工单列表页的作用域来自全局 ProjectSwitcher，
 *  在「全部项目」视图里点了项目 B 的计划、而当前作用域停在项目 A，落地后两个条件
 *  AND 起来就是空表——用户会以为「刚才明明写着 4 条需求，怎么一条都没有」。 */
function ticketHref(entity: "requirements" | "bugs", plan: Plan): string {
  return `/${entity}?plan_id=${plan.id}&project_id=${plan.project_id}`;
}

export default function PlanRow({
  plan, canManage, onEdit, onToggleArchive, onDelete,
}: Props) {
  const total = plan.requirement_count + plan.bug_count;
  const archived = plan.status === "archived";

  return (
    <div className="flex flex-col gap-2 px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-medium text-ink">{plan.name}</span>
        <Badge style={PLAN_STATUS_STYLES[plan.status]} />
        <span className="text-xs text-ink-muted">{period(plan)}</span>
        <div className="ml-auto flex items-center gap-1">
          {canManage && (
            <>
              <Button variant="ghost" size="sm" onClick={() => onEdit(plan)}>
                编辑
              </Button>
              <RowMenu
                ariaLabel={`计划 ${plan.name} 的更多操作`}
                items={[
                  {
                    label: archived ? "取消归档" : "归档",
                    onSelect: () => onToggleArchive(plan),
                  },
                  { label: "删除", danger: true, onSelect: () => onDelete(plan) },
                ]}
              />
            </>
          )}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-muted">
        {/* `total === 0` 时**不画进度条**：给 `value={null}` 会进入 ProgressBar 的
            **不确定**模式（脉冲动画 + 读屏播报「进度未知」），那语义是「还在传但不知道
            剩多少」，与「这里一张单都没有」南辕北辙；给 0 又与「0% 完成」混淆。
            这是第三种事实，用文字说清楚。 */}
        {total === 0 ? (
          <span>暂无工单</span>
        ) : (
          <>
            <div className="w-40">
              <ProgressBar
                value={Math.round((plan.done_count / total) * 100)}
                label={`计划进度 ${plan.done_count}/${total}`}
              />
            </div>
            <span>{plan.done_count} / {total} 已完成</span>
          </>
        )}
        <Link
          href={ticketHref("requirements", plan)}
          className="hover:text-clay-dark hover:underline"
        >
          需求 {plan.requirement_count}
        </Link>
        <Link href={ticketHref("bugs", plan)} className="hover:text-clay-dark hover:underline">
          BUG {plan.bug_count}
        </Link>
      </div>
    </div>
  );
}
