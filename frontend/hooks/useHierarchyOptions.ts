"use client";

// 级联下拉 / 计划选择器的数据源（version-plan-console §5.3）。
//
// 【为什么不复用 useVersions】那个 hook 服务 `/versions` 控制台：分页、带状态筛选、
// 带 CRUD 与失效编排。下拉要的是另一件事——「当前作用域内的全部版本与计划，一次取完」。
// 两者共用一个 key 就会违反 lib/api.ts 顶部那条「一个 key 一种形状」的铁律。

import { useMemo } from "react";
import useSWR from "swr";
import { PLANS_PREFIX, VERSIONS_PREFIX, listFetcher } from "@/lib/api";
import { useProjectScope } from "@/lib/project-scope";
import type { Plan, Version } from "@/lib/types";

/** 后端 MAX_LIMIT。取满一页即可覆盖绝大多数项目；超出时**明确告诉用户被截断了**，
 *  绝不静默少几个选项（R-6）。 */
const OPTIONS_LIMIT = 200;

export interface HierarchyOptions {
  versions: Version[];
  plans: Plan[];
  /** 版本数超过 200 —— 下拉少了选项，调用方必须显示提示。 */
  versionsTruncated: boolean;
  plansTruncated: boolean;
  isLoading: boolean;
  error: unknown;
}

/**
 * 取当前项目作用域内的版本与计划（供筛选下拉与 `PlanPicker` 使用）。
 *
 * @param projectIdOverride 指定项目时覆盖全局作用域（建单表单里用户已选了项目，
 *        此时下拉必须跟着那个项目走，而不是跟着 Header 的切换器）。
 *        传 `null` 表示「不覆盖」，走全局作用域。
 */
export function useHierarchyOptions(projectIdOverride?: number | null): HierarchyOptions {
  const { scopeParam } = useProjectScope();
  const projectParam =
    projectIdOverride != null ? String(projectIdOverride) : scopeParam;

  const versionsKey = useMemo(() => {
    const params = new URLSearchParams();
    if (projectParam) params.set("project_id", projectParam);
    params.set("limit", String(OPTIONS_LIMIT));
    return `${VERSIONS_PREFIX}?${params.toString()}`;
  }, [projectParam]);

  const plansKey = useMemo(() => {
    const params = new URLSearchParams();
    if (projectParam) params.set("project_id", projectParam);
    params.set("limit", String(OPTIONS_LIMIT));
    return `${PLANS_PREFIX}?${params.toString()}`;
  }, [projectParam]);

  const versionsResult =
    useSWR<{ items: Version[]; total: number }>(versionsKey, listFetcher);
  const plansResult = useSWR<{ items: Plan[]; total: number }>(plansKey, listFetcher);

  return {
    versions: versionsResult.data?.items ?? [],
    plans: plansResult.data?.items ?? [],
    versionsTruncated: (versionsResult.data?.total ?? 0) > OPTIONS_LIMIT,
    plansTruncated: (plansResult.data?.total ?? 0) > OPTIONS_LIMIT,
    isLoading: versionsResult.isLoading || plansResult.isLoading,
    error: versionsResult.error ?? plansResult.error,
  };
}
