"use client";

// 版本卡展开后的计划列表容器（version-plan-console §5.4）。
//
// 【本组件存在的唯一理由是懒加载边界，§3.4】：折叠态**根本不挂载**它，展开时它内部的
// `usePlansOfVersion` 才发出那一个请求。20 张版本卡的首屏于是只有 1 个请求，而不是 21 个。
// 把 `useSWR` 写进 VersionCard 里就做不到这件事——hook 不能条件调用。

import { usePlansOfVersion } from "@/hooks/usePlans";
import Button from "@/components/ui/Button";
import ErrorState from "@/components/ui/ErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import PlanRow from "@/components/planning/PlanRow";
import type { Plan } from "@/lib/types";

interface Props {
  versionId: number;
  canManage: boolean;
  /** 页面级筛选条透传：两级用同一套「状态 / 显示已归档」判据。 */
  status: string;
  includeArchived: boolean;
  onCreatePlan: () => void;
  onEditPlan: (plan: Plan) => void;
  onToggleArchivePlan: (plan: Plan) => void;
  onDeletePlan: (plan: Plan) => void;
}

export default function VersionPlans({
  versionId, canManage, status, includeArchived,
  onCreatePlan, onEditPlan, onToggleArchivePlan, onDeletePlan,
}: Props) {
  const { plans, isLoading, error, refresh } =
    usePlansOfVersion(versionId, { status, includeArchived });

  return (
    <div className="border-t border-border bg-black/[0.012]">
      {error && !plans.length ? (
        <ErrorState message="无法加载该版本的计划" onRetry={() => refresh()} />
      ) : isLoading ? (
        <div className="space-y-2 px-4 py-3" aria-hidden="true">
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-4 w-1/2" />
        </div>
      ) : plans.length === 0 ? (
        <p className="px-4 py-4 text-sm text-ink-muted">
          这个版本下还没有计划。
          {canManage ? "先排一轮计划，再把需求 / BUG 挂到它上面。" : "计划由项目经理或管理员创建。"}
        </p>
      ) : (
        <div className="divide-y divide-border">
          {plans.map((plan) => (
            <PlanRow
              key={plan.id}
              plan={plan}
              canManage={canManage}
              onEdit={onEditPlan}
              onToggleArchive={onToggleArchivePlan}
              onDelete={onDeletePlan}
            />
          ))}
        </div>
      )}

      {canManage && (
        <div className="flex justify-end border-t border-border px-4 py-2.5">
          <Button variant="ghost" size="sm" onClick={onCreatePlan}>
            + 在此版本下新建计划
          </Button>
        </div>
      )}
    </div>
  );
}
