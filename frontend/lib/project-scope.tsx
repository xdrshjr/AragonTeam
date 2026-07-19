"use client";

// 全局项目作用域（scale-and-project-scope §2.4④）。
// 让「项目」这一维度从 Header 的切换器一路贯通到列表 / 看板 / 仪表盘 / 建单表单 / 抽屉。

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { PROJECTS_KEY, swrFetcher } from "@/lib/api";
import type { Project } from "@/lib/types";

/** 具体项目 | 未归属（后端 `?project_id=none`）| 全部项目。 */
export type ProjectScope = number | "none" | null;

const STORAGE_KEY = "aragon.project";

interface ProjectScopeValue {
  scope: ProjectScope;
  setScope: (next: ProjectScope) => void;
  /** 可直接拼进 query；scope 为 null（全部项目）时返回 ""。 */
  scopeParam: string;
  projects: Project[] | undefined;
  isLoading: boolean;
  error: unknown;
  /** 当前作用域的可读名称；scope 为 null 时返回 null（调用方据此决定是否标注）。 */
  scopeLabel: string | null;
}

const Ctx = createContext<ProjectScopeValue | null>(null);

/** 把 localStorage 里的原始串解析成 ProjectScope；非法值一律回落 null。 */
function parseStored(raw: string | null): ProjectScope {
  if (raw === "none") return "none";
  if (!raw) return null;
  const n = Number(raw);
  return Number.isInteger(n) && n > 0 ? n : null;
}

export function ProjectScopeProvider({ children }: { children: React.ReactNode }) {
  // 初值恒为 null：localStorage 在 SSR 阶段不存在，在 useState 初始化函数里读会造成
  // 首屏 hydration mismatch（§7-R3）。读取一律放进下面的 useEffect。
  const [scope, setScopeState] = useState<ProjectScope>(null);

  useEffect(() => {
    setScopeState(parseStored(window.localStorage.getItem(STORAGE_KEY)));
  }, []);

  const { data: projects, isLoading, error } = useSWR<Project[]>(PROJECTS_KEY, swrFetcher);

  const setScope = useCallback((next: ProjectScope) => {
    setScopeState(next);
    if (next === null) window.localStorage.removeItem(STORAGE_KEY);
    else window.localStorage.setItem(STORAGE_KEY, String(next));
  }, []);

  // 失效自愈：选中的项目已被删 / 换库 / 换环境时静默回落「全部项目」，
  // 否则每一页都会空掉且没有任何线索（§2.4④）。
  useEffect(() => {
    if (!projects || typeof scope !== "number") return;
    if (!projects.some((p) => p.id === scope)) setScope(null);
  }, [projects, scope, setScope]);

  const value = useMemo<ProjectScopeValue>(() => {
    const scopeParam = scope === null ? "" : String(scope);
    let scopeLabel: string | null = null;
    if (scope === "none") scopeLabel = "未归属项目";
    else if (typeof scope === "number") {
      const hit = projects?.find((p) => p.id === scope);
      scopeLabel = hit ? `${hit.key} · ${hit.name}` : `项目 #${scope}`;
    }
    return { scope, setScope, scopeParam, projects, isLoading, error, scopeLabel };
  }, [scope, setScope, projects, isLoading, error]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useProjectScope(): ProjectScopeValue {
  const ctx = useContext(Ctx);
  if (!ctx) {
    throw new Error("useProjectScope 必须在 ProjectScopeProvider 内使用");
  }
  return ctx;
}
