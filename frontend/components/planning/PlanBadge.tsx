"use client";

// 列表 / 看板卡上的计划徽章（version-plan-console §5.4）。
//
// 未归属渲染一个浅灰的 `—`，与需求列表「文档」列的未命中态同款——一整列的空白
// 比一整列的「未归属」三个字安静得多，而信息量完全一样。

import Link from "next/link";
import Badge from "@/components/ui/Badge";
import type { PlanContext } from "@/lib/types";

interface Props {
  /** 工单自带的只读概要。**可能是 undefined**（该端点未富化），故按缺省即无渲染。 */
  plan?: PlanContext | null;
  /** 版本段是否渲染成回 `/versions` 的深链（列表里有用，看板卡上太吵故默认关）。 */
  linkVersion?: boolean;
  className?: string;
}

export default function PlanBadge({ plan, linkVersion = false, className = "" }: Props) {
  if (!plan) {
    return <span className={`text-ink-muted/50 ${className}`.trim()}>—</span>;
  }

  const versionName = plan.version_name ?? "—";
  const badge = (
    <Badge
      style={{ label: plan.name, bg: "#EDEAE3", fg: "#5F5B54" }}
      className="max-w-[10rem] truncate"
    />
  );

  if (!linkVersion) {
    return (
      <span className={className} title={`${versionName} · ${plan.name}`}>
        {badge}
      </span>
    );
  }

  // 点计划徽章 → 落到 `/versions` 且该版本已展开，形成「在列表看到归属 → 回到规划树」
  // 的闭环。参数名与工单页的 `?version_id=` 保持一致（全站一个名字表达一件事）。
  return (
    <Link
      href={`/versions?version_id=${plan.version_id}`}
      onClick={(e) => e.stopPropagation()}
      title={`${versionName} · ${plan.name}（点击查看该版本）`}
      className={`inline-flex hover:opacity-80 ${className}`.trim()}
    >
      {badge}
    </Link>
  );
}
