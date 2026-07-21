"use client";

// 团队页筛选条（self-service-registration §2.3 C-3）：搜索 + 角色 + 状态 + 来源。
//
// 搜索框 300ms 防抖（复用 `components/layout/GlobalSearch.tsx` 的同一手法与同一常量值）：
// 不防抖会让每敲一个字符都打一次 `/users`，在几十人的团队里就是几十次无谓请求。
// 防抖只在**本组件内部**发生，对外恒以 `onChange` 交出一份完整筛选值——调用方不需要
// 知道有防抖这回事，也就不会有人在别处再写一份。

import { useEffect, useState } from "react";
import { ROLE_LABELS, USER_SOURCE_LABELS } from "@/lib/constants";
import type { Role, UserSource } from "@/lib/types";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";

const DEBOUNCE_MS = 300;

export interface MemberFilters {
  q: string;
  role: Role | "";
  isActive: "" | "true" | "false";
  source: UserSource | "";
}

export const EMPTY_FILTERS: MemberFilters = { q: "", role: "", isActive: "", source: "" };

const ROLE_OPTIONS = (["admin", "pm", "member"] as Role[]).map((r) => ({
  value: r,
  label: ROLE_LABELS[r],
}));

const STATUS_OPTIONS = [
  { value: "true", label: "在职" },
  { value: "false", label: "已停用" },
];

// 只放两个来源：`admin` / `seed` 是绝大多数行，作为筛选项没有区分度。
const SOURCE_OPTIONS = (["signup", "admin"] as UserSource[]).map((s) => ({
  value: s,
  label: USER_SOURCE_LABELS[s],
}));

interface Props {
  filters: MemberFilters;
  onChange: (next: MemberFilters) => void;
}

export default function MemberFilterBar({ filters, onChange }: Props) {
  const [keyword, setKeyword] = useState(filters.q);

  // 外部重置筛选（如「清空」）时把本地输入拉回一致，避免输入框显示一个已失效的词。
  useEffect(() => {
    setKeyword(filters.q);
  }, [filters.q]);

  useEffect(() => {
    if (keyword === filters.q) return;
    const timer = setTimeout(() => onChange({ ...filters, q: keyword }), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [keyword, filters, onChange]);

  return (
    <div className="mb-4 flex flex-wrap items-end gap-3">
      <div className="min-w-[200px] flex-1">
        <Input
          label="搜索"
          name="member_q"
          type="search"
          value={keyword}
          placeholder="用户名 / 显示名称 / 邮箱"
          onChange={(e) => setKeyword(e.target.value)}
        />
      </div>
      <Select
        label="角色"
        name="member_role"
        value={filters.role}
        placeholder="全部角色"
        options={ROLE_OPTIONS}
        onChange={(e) => onChange({ ...filters, role: e.target.value as Role | "" })}
      />
      <Select
        label="状态"
        name="member_status"
        value={filters.isActive}
        placeholder="全部状态"
        options={STATUS_OPTIONS}
        onChange={(e) =>
          onChange({ ...filters, isActive: e.target.value as MemberFilters["isActive"] })
        }
      />
      <Select
        label="来源"
        name="member_source"
        value={filters.source}
        placeholder="全部来源"
        options={SOURCE_OPTIONS}
        onChange={(e) => onChange({ ...filters, source: e.target.value as UserSource | "" })}
      />
    </div>
  );
}

/** 把筛选值拼成后端查询串（空值一律省略——空串在后端等价于不传）。 */
export function toQuery(filters: MemberFilters): string {
  const parts: string[] = [];
  if (filters.q.trim()) parts.push(`q=${encodeURIComponent(filters.q.trim())}`);
  if (filters.role) parts.push(`role=${filters.role}`);
  if (filters.isActive) parts.push(`is_active=${filters.isActive}`);
  if (filters.source) parts.push(`source=${filters.source}`);
  return parts.join("&");
}
