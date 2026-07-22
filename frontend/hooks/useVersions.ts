"use client";

// 版本列表 + CRUD（version-plan-console §5.3）。形状照抄 useDocumentLibrary：
// 一个由筛选拼出的 key + 一个 settle() 收敛全部失效。

import { useCallback, useMemo } from "react";
import useSWR, { useSWRConfig } from "swr";
import { ApiError, VERSIONS_PREFIX, api, listFetcher } from "@/lib/api";
import { invalidateAdminViews, invalidateTicketViews } from "@/lib/swr-keys";
import type { Version, VersionCreate, VersionUpdate } from "@/lib/types";

export interface VersionFilters {
  /** 项目作用域串（`useProjectScope().scopeParam`）；`""` = 全部项目，不发该参数。 */
  projectParam?: string;
  status?: string;
  includeArchived?: boolean;
  limit?: number;
  offset?: number;
}

/** 版本卡比表格行高得多，20 张即一屏半。显式写进 key 是为了「一个 key 一种形状」
 *  在后端改默认上限时仍然成立。 */
export const VERSION_PAGE_SIZE = 20;

export function useVersions(filters: VersionFilters = {}) {
  const { mutate } = useSWRConfig();
  const {
    projectParam = "", status = "", includeArchived = false,
    limit = VERSION_PAGE_SIZE, offset = 0,
  } = filters;

  const key = useMemo(() => {
    const params = new URLSearchParams();
    if (projectParam) params.set("project_id", projectParam);
    if (status) params.set("status", status);
    // 后端是 `if status: … elif include_archived …`——选了具体状态时该参数完全不起作用，
    // 故这里也不发它，免得 key 里留下一个不影响结果的碎片。
    else if (includeArchived) params.set("include_archived", "1");
    params.set("limit", String(limit));
    params.set("offset", String(offset));
    return `${VERSIONS_PREFIX}?${params.toString()}`;
  }, [projectParam, status, includeArchived, limit, offset]);

  const { data, error, isLoading, mutate: mutateList } =
    useSWR<{ items: Version[]; total: number }>(key, listFetcher);

  const settle = useCallback(() => {
    mutateList();
    // 版本 / 计划自身变了 → 所有挂着它们的列表与下拉一起刷（`/versions`、`/plans`
    // 已在 ADMIN_VIEW_PREFIXES 里）。
    invalidateAdminViews(mutate);
    // 工单侧的「计划」徽章列与筛选下拉也读版本名，一并失效。
    invalidateTicketViews(mutate);
  }, [mutate, mutateList]);

  const create = useCallback(async (body: VersionCreate) => {
    const created = await api.post<Version>(VERSIONS_PREFIX, body);
    settle();
    return created;
  }, [settle]);

  const update = useCallback(async (versionId: number, body: VersionUpdate) => {
    const updated = await api.patch<Version>(`${VERSIONS_PREFIX}/${versionId}`, body);
    settle();
    return updated;
  }, [settle]);

  const remove = useCallback(async (versionId: number) => {
    try {
      await api.del(`${VERSIONS_PREFIX}/${versionId}`);
    } catch (err) {
      // 409 的 detail 里带着「还有几个计划」——这正是用户下一步要做的事，必须原样呈现数字。
      //
      // **只说「删除」，不说「或归档」**：后端 hint 逐字是 "delete or archive its plans
      // first"，但 `lifecycle.version_references` 是 `Plan.query.filter_by(version_id=…)
      // .count()`，**不看 status**——归档的计划照样计数。用户照着「或归档」把计划一个个
      // 归档、再回来删版本，仍然 409 且那个数字一个都没少，这是把人送进死循环。
      // 翻译层的职责是说**真话**，不是把后端 hint 转成中文。
      if (err instanceof ApiError && err.status === 409) {
        const plans = (err.detail as { plans?: number } | undefined)?.plans ?? 0;
        throw new ApiError(409, `该版本下还有 ${plans} 个计划，请先删除这些计划。`, err.detail);
      }
      throw err;
    }
    settle();
  }, [settle]);

  return {
    versions: data?.items ?? [],
    total: data?.total ?? 0,
    isLoading,
    error,
    refresh: settle,
    create,
    update,
    remove,
  };
}
