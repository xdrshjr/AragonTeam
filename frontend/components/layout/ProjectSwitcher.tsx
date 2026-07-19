"use client";

import { useProjectScope, type ProjectScope } from "@/lib/project-scope";

// Header 项目切换器（scale-and-project-scope §2.4⑤）。
// 原生 <select>，复用 FilterBar 的样式串（零新依赖）。
const selectCls =
  "h-9 max-w-[15rem] rounded-lg border border-border bg-surface px-2.5 text-sm text-ink focus:border-clay focus:outline-none focus:ring-2 focus:ring-clay/20 disabled:opacity-60";

/** 把 <select> 的字符串值还原成 ProjectScope。 */
function toScope(raw: string): ProjectScope {
  if (raw === "") return null;
  if (raw === "none") return "none";
  return Number(raw);
}

export default function ProjectSwitcher() {
  const { scope, setScope, projects, error } = useProjectScope();

  // 项目列表未到达 / 拉取失败时渲染 disabled 占位（**不渲染 skeleton**：Header 高度固定 h-16，
  // 换骨架会让整条 Header 抖动）；项目拉不到不得阻断整个 Header。
  if (!projects || error) {
    return (
      <select className={selectCls} aria-label="切换项目" disabled>
        <option>{error ? "项目加载失败" : "加载项目…"}</option>
      </select>
    );
  }

  return (
    <select
      className={selectCls}
      aria-label="切换项目"
      value={scope === null ? "" : String(scope)}
      onChange={(e) => setScope(toScope(e.target.value))}
    >
      <option value="">全部项目</option>
      <option value="none">未归属项目</option>
      {projects.map((p) => (
        <option key={p.id} value={p.id}>
          {p.key} · {p.name}
        </option>
      ))}
    </select>
  );
}
