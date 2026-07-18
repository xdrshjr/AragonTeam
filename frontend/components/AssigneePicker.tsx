"use client";

import useSWR from "swr";
import { swrFetcher } from "@/lib/api";
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
  const { data: users } = useSWR<User[]>("/users", swrFetcher);
  const { data: agents } = useSWR<Agent[]>("/agents", swrFetcher);

  const current =
    value.assignee_type && value.assignee_id
      ? `${value.assignee_type}:${value.assignee_id}`
      : "";

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
      <label className="text-sm font-medium text-ink">{label}</label>
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
        {users && users.length > 0 && (
          <optgroup label="团队成员">
            {users.map((u) => (
              <option key={`user:${u.id}`} value={`user:${u.id}`}>
                {u.display_name || u.username}
              </option>
            ))}
          </optgroup>
        )}
      </select>
    </div>
  );
}
