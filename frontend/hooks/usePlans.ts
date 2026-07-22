"use client";

// 计划列表 + CRUD（version-plan-console §5.3）。与 useVersions 同型。

import { useCallback, useMemo } from "react";
import useSWR, { useSWRConfig } from "swr";
import { ApiError, PLANS_PREFIX, api, listFetcher } from "@/lib/api";
import { PLAN_STATUS_STYLES } from "@/lib/constants";
import { invalidateAdminViews, invalidateTicketViews } from "@/lib/swr-keys";
import type { Plan, PlanCreate, PlanUpdate } from "@/lib/types";

/** 一个版本下的计划数远小于工单数；200 是后端 MAX_LIMIT，一次取完即可。 */
const PLANS_OF_VERSION_LIMIT = 200;

export function usePlanMutations() {
  const { mutate } = useSWRConfig();

  const settle = useCallback(() => {
    invalidateAdminViews(mutate);       // `/versions`、`/plans` 均在该前缀表里
    invalidateTicketViews(mutate);      // 工单侧的计划徽章与下拉
  }, [mutate]);

  const create = useCallback(async (body: PlanCreate) => {
    const created = await api.post<Plan>(PLANS_PREFIX, body);
    settle();
    return created;
  }, [settle]);

  const update = useCallback(async (planId: number, body: PlanUpdate) => {
    const updated = await api.patch<Plan>(`${PLANS_PREFIX}/${planId}`, body);
    settle();
    return updated;
  }, [settle]);

  const remove = useCallback(async (planId: number) => {
    try {
      await api.del(`${PLANS_PREFIX}/${planId}`);
    } catch (err) {
      // 与版本侧同款就地翻译。**这句话可以照译**：移走或删除工单确实能让
      // `plan_references` 的计数下降，两条出路都是真的有效。
      if (err instanceof ApiError && err.status === 409) {
        const detail = err.detail as { requirements?: number; bugs?: number } | undefined;
        const reqs = detail?.requirements ?? 0;
        const bugs = detail?.bugs ?? 0;
        throw new ApiError(
          409,
          `该计划下还有 ${reqs} 个需求、${bugs} 个 BUG，请先把它们移到其他计划或删除。`,
          err.detail,
        );
      }
      throw err;
    }
    settle();
  }, [settle]);

  return { create, update, remove, refresh: settle };
}

export interface PlansOfVersionFilters {
  status?: string;
  includeArchived?: boolean;
}

/** 某个版本下的计划（**懒加载**：`versionId` 为 null 时 key 为 null，SWR 根本不发请求）。
 *
 *  这就是 §3.4 说的懒加载边界：版本卡折叠时**不挂载**使用本 hook 的组件，
 *  20 张卡的首屏于是只有 1 个请求而不是 21 个。
 *
 *  筛选条的「状态」/「显示已归档」**一并透传下来**：两级用同一套判据，
 *  否则「显示已归档」勾上之后版本露出来了、它下面的归档计划却还藏着。 */
export function usePlansOfVersion(
  versionId: number | null,
  filters: PlansOfVersionFilters = {},
) {
  const { status = "", includeArchived = false } = filters;
  const key = useMemo(() => {
    if (versionId == null) return null;
    // 版本与计划的状态枚举**不是同一个集合**（版本有 released、计划有 completed）。
    // 后端 `/plans?status=` 走 `choices=PLAN_STATUSES`，塞一个 `released` 进去是**400**，
    // 不是「筛不出东西」。故这里只透传两个枚举的交集，其余按「不筛状态」处理。
    const planStatus = status in PLAN_STATUS_STYLES ? status : "";
    const params = new URLSearchParams();
    params.set("version_id", String(versionId));
    // 后端是 `if status: … elif include_archived …`，两者互斥，故这里也照此拼。
    if (planStatus) params.set("status", planStatus);
    else if (includeArchived) params.set("include_archived", "1");
    params.set("limit", String(PLANS_OF_VERSION_LIMIT));
    return `${PLANS_PREFIX}?${params.toString()}`;
  }, [versionId, status, includeArchived]);

  const { data, error, isLoading, mutate } =
    useSWR<{ items: Plan[]; total: number }>(key, listFetcher);

  return {
    plans: data?.items ?? [],
    total: data?.total ?? 0,
    isLoading,
    error,
    refresh: mutate,
  };
}
