"use client";

import useSWR from "swr";
import { AGENTS_KEY, USERS_KEY, swrFetcher } from "@/lib/api";
import type { User, Agent, AssigneeType } from "@/lib/types";
import { AGENT_KIND_LABELS } from "@/lib/constants";

export interface AssigneeValue {
  assignee_type: AssigneeType | null;
  assignee_id: number | null;
}

interface Props {
  label?: string;
  value: AssigneeValue;
  onChange: (v: AssigneeValue) => void;
}

// 统一「指派给 人 or Agent」选择器：一个 select，选项分「成员」与「Agent」两组。
// value 编码为 "user:3" / "agent:1" / ""（未指派）。
export default function AssigneePicker({ label = "指派给", value, onChange }: Props) {
  const { data: users } = useSWR<User[]>(USERS_KEY, swrFetcher);
  const { data: agents } = useSWR<Agent[]>(AGENTS_KEY, swrFetcher);

  const current =
    value.assignee_type && value.assignee_id
      ? `${value.assignee_type}:${value.assignee_id}`
      : "";

  // 【lifecycle-and-governance §2.5】已停用成员不再可被指派；但**当前工单的 assignee
  // 恰为已停用成员时仍须保留该选项**，否则 <select> 的 value 匹配不到任何 option，
  // 浏览器会静默显示成第一项——UI 会说成「未指派」，又是一次说谎。
  const selectableUsers = (users ?? []).filter(
    (u) =>
      u.is_active !== false ||
      (value.assignee_type === "user" && value.assignee_id === u.id)
  );

  function handle(raw: string) {
    if (!raw) {
      onChange({ assignee_type: null, assignee_id: null });
      return;
    }
    const [type, id] = raw.split(":");
    onChange({ assignee_type: type as AssigneeType, assignee_id: Number(id) });
  }

  return (
    <div className="flex flex-col gap-1.5">
      {label ? <label className="text-sm font-medium text-ink">{label}</label> : null}
      <select
        value={current}
        onChange={(e) => handle(e.target.value)}
        className="h-10 rounded-lg border border-border bg-surface px-3 text-sm text-ink focus:border-clay focus:outline-none focus:ring-2 focus:ring-clay/20"
      >
        <option value="">未指派</option>
        {agents && agents.length > 0 && (
          <optgroup label="Agent（AI 执行者）">
            {agents.map((a) => (
              <option key={`agent:${a.id}`} value={`agent:${a.id}`}>
                🤖 {a.name} · {AGENT_KIND_LABELS[a.kind] || a.kind}
              </option>
            ))}
          </optgroup>
        )}
        {selectableUsers.length > 0 && (
          <optgroup label="团队成员">
            {selectableUsers.map((u) => (
              <option key={`user:${u.id}`} value={`user:${u.id}`}>
                {u.display_name || u.username}
                {u.is_active === false ? "（已停用）" : ""}
              </option>
            ))}
          </optgroup>
        )}
      </select>
    </div>
  );
}
