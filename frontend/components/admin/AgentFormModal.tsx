"use client";

// Agent 管理弹窗（admin-console §2.3）：建 / 改 Agent。
// 【C1】编辑态 status 只提供「空闲 / 离线」——busy 是自主编排的运行时软锁，
// 系统托管、不可人工设置（人工设 busy 将永久锁出编排）。子组件拆分守阈值（C4）。

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useToast } from "@/lib/toast";
import type { Agent, AgentKind, AgentStatus, AgentInput } from "@/lib/types";
import { AGENT_KIND_LABELS, AGENT_STATUS_LABELS } from "@/lib/constants";
import Modal from "@/components/ui/Modal";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import Textarea from "@/components/ui/Textarea";
import Button from "@/components/ui/Button";

export type AgentFormState = { mode: "create" } | { mode: "edit"; agent: Agent };

interface Props {
  state: AgentFormState | null; // null → 关闭
  onClose: () => void;
  onSaved: () => void; // 成功后：关闭 + mutate("/agents")
}

interface SubProps {
  onClose: () => void;
  onSaved: () => void;
}

const KIND_OPTIONS = (["dev", "qa", "generic"] as AgentKind[]).map((k) => ({
  value: k,
  label: AGENT_KIND_LABELS[k],
}));

// 【C1】人工可选状态仅 idle/offline；busy 不在选项内。
const STATUS_OPTIONS = (["idle", "offline"] as AgentStatus[]).map((s) => ({
  value: s,
  label: AGENT_STATUS_LABELS[s],
}));

const TITLES: Record<AgentFormState["mode"], string> = {
  create: "新建 Agent",
  edit: "编辑 Agent",
};

function errText(err: unknown): string {
  return err instanceof ApiError ? err.message : "操作失败";
}

function FormActions({ onClose, onSubmit, submitting }: {
  onClose: () => void;
  onSubmit: () => void;
  submitting: boolean;
}) {
  return (
    <div className="mt-1 flex justify-end gap-2">
      <Button variant="ghost" onClick={onClose} disabled={submitting}>
        取消
      </Button>
      <Button onClick={onSubmit} disabled={submitting}>
        {submitting ? "提交中…" : "保存"}
      </Button>
    </div>
  );
}

// 【C1】状态字段：busy 时只读展示「忙碌」并仅允许切到 idle/offline（提交即安全解锁）。
function StatusField({ busy, status, onChange }: {
  busy: boolean;
  status: AgentStatus | "";
  onChange: (s: AgentStatus | "") => void;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Select
        label="状态"
        value={status}
        onChange={(e) => onChange(e.target.value as AgentStatus | "")}
        options={STATUS_OPTIONS}
        placeholder={busy ? "保持忙碌（系统托管）" : undefined}
      />
      {busy && (
        <span className="text-xs text-ink-muted">
          当前「忙碌」由自主编排托管、不可手动设置；如需解锁可切到「空闲 / 离线」。
        </span>
      )}
    </div>
  );
}

function CreateAgentForm({ onClose, onSaved }: SubProps) {
  const toast = useToast();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<AgentKind>("generic");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit() {
    if (!name.trim()) return toast.error("名称为必填");
    setSubmitting(true);
    try {
      const payload: AgentInput = {
        name: name.trim(),
        kind,
        description: description.trim() || undefined,
      };
      await api.post<Agent>("/agents", payload);
      toast.success("Agent 已保存");
      onSaved();
    } catch (err) {
      toast.error(errText(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Input label="名称" value={name} onChange={(e) => setName(e.target.value)}
             maxLength={64} placeholder="Agent 名称（唯一）" />
      <Select label="类型" value={kind} onChange={(e) => setKind(e.target.value as AgentKind)}
              options={KIND_OPTIONS} />
      <Textarea label="描述" value={description} onChange={(e) => setDescription(e.target.value)}
                placeholder="职责 / 能力说明（选填）" />
      <FormActions onClose={onClose} onSubmit={onSubmit} submitting={submitting} />
    </div>
  );
}

function EditAgentForm({ agent, onClose, onSaved }: SubProps & { agent: Agent }) {
  const toast = useToast();
  const busy = agent.status === "busy";
  const [name, setName] = useState(agent.name);
  const [kind, setKind] = useState<AgentKind>(agent.kind);
  const [description, setDescription] = useState(agent.description ?? "");
  const [status, setStatus] = useState<AgentStatus | "">(busy ? "" : agent.status);
  const [submitting, setSubmitting] = useState(false);

  function buildDiff(): AgentInput {
    const diff: AgentInput = {};
    if (name.trim() !== agent.name) diff.name = name.trim();
    if (kind !== agent.kind) diff.kind = kind;
    if (description.trim() !== (agent.description ?? "")) diff.description = description.trim();
    if (status !== "" && status !== agent.status) diff.status = status;
    return diff;
  }

  async function onSubmit() {
    if (!name.trim()) return toast.error("名称不能为空");
    const diff = buildDiff();
    if (Object.keys(diff).length === 0) return toast.info("没有需要保存的改动");
    setSubmitting(true);
    try {
      await api.patch<Agent>(`/agents/${agent.id}`, diff);
      toast.success("Agent 已保存");
      onSaved();
    } catch (err) {
      toast.error(errText(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Input label="名称" value={name} onChange={(e) => setName(e.target.value)} maxLength={64} />
      <Select label="类型" value={kind} onChange={(e) => setKind(e.target.value as AgentKind)}
              options={KIND_OPTIONS} />
      <Textarea label="描述" value={description} onChange={(e) => setDescription(e.target.value)}
                placeholder="职责 / 能力说明（选填）" />
      <StatusField busy={busy} status={status} onChange={setStatus} />
      <FormActions onClose={onClose} onSubmit={onSubmit} submitting={submitting} />
    </div>
  );
}

export default function AgentFormModal({ state, onClose, onSaved }: Props) {
  return (
    <Modal open={!!state} onClose={onClose} title={state ? TITLES[state.mode] : undefined}>
      {state?.mode === "create" && <CreateAgentForm onClose={onClose} onSaved={onSaved} />}
      {state?.mode === "edit" && (
        <EditAgentForm key={state.agent.id} agent={state.agent} onClose={onClose} onSaved={onSaved} />
      )}
    </Modal>
  );
}
