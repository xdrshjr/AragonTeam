"use client";

// 治理审计页的筛选条（login-hardening-and-audit-console §5.3）——实体 / 动作 / 施动者 / 起始时间。
// 与 MemberFilterBar 同构：空值一律省略（后端「空串等价于不传」），任一变化交出完整筛选值。

import type { AuditFilters, GovernanceAction } from "@/lib/types";
import { AUDIT_ENTITY_LABELS, governanceActionLabel } from "@/lib/constants";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";

// 全部治理动作（账号 + 站点设置）。顺序与后端 ALL_ACTIONS 一致，供筛选下拉。
const ALL_GOVERNANCE_ACTIONS: GovernanceAction[] = [
  "user_created",
  "user_registered",
  "role_changed",
  "activated",
  "deactivated",
  "password_reset",
  "password_changed",
  "account_locked",
  "account_unlocked",
  "registration_updated",
  "invite_code_rotated",
];

const ENTITY_OPTIONS = (["user", "app_setting"] as const).map((v) => ({
  value: v,
  label: AUDIT_ENTITY_LABELS[v],
}));

const ACTION_OPTIONS = ALL_GOVERNANCE_ACTIONS.map((a) => ({
  value: a,
  label: governanceActionLabel(a),
}));

interface Props {
  filters: AuditFilters;
  onChange: (next: AuditFilters) => void;
}

export default function AuditFilterBar({ filters, onChange }: Props) {
  return (
    <div className="mb-4 flex flex-wrap items-end gap-3">
      <Select
        label="实体"
        name="audit_entity"
        value={filters.entity_type}
        placeholder="全部实体"
        options={ENTITY_OPTIONS}
        onChange={(e) =>
          onChange({ ...filters, entity_type: e.target.value as AuditFilters["entity_type"] })
        }
      />
      <Select
        label="动作"
        name="audit_action"
        value={filters.action}
        placeholder="全部动作"
        options={ACTION_OPTIONS}
        onChange={(e) =>
          onChange({ ...filters, action: e.target.value as AuditFilters["action"] })
        }
      />
      <Input
        label="施动者 ID"
        name="audit_actor"
        type="number"
        min={1}
        className="w-32"
        placeholder="用户 ID"
        value={filters.actor_id}
        onChange={(e) => onChange({ ...filters, actor_id: e.target.value })}
      />
      <Input
        label="起始时间"
        name="audit_since"
        type="datetime-local"
        className="min-w-[13rem]"
        value={filters.since}
        onChange={(e) => onChange({ ...filters, since: e.target.value })}
      />
    </div>
  );
}
