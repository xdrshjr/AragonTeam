"use client";

// 计划增改弹窗（version-plan-console §7.2）。与 VersionFormModal 同型。
//
// 编辑态可**改挂**到同项目的其他版本。前端先按 project_id 过滤版本选项，能把跨项目
// 的 400 挡在提交前——但**绝不因此省掉**对后端 400 的错误提示：并发下版本可能刚被改。

import { useState } from "react";
import { ApiError } from "@/lib/api";
import { PLAN_STATUS_OPTIONS } from "@/lib/constants";
import { useToast } from "@/lib/toast";
import type { Plan, PlanCreate, PlanStatus, PlanUpdate, Version } from "@/lib/types";
import Modal from "@/components/ui/Modal";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import Textarea from "@/components/ui/Textarea";
import Button from "@/components/ui/Button";

export type PlanFormState =
  | { mode: "create"; version: Version }
  | { mode: "edit"; plan: Plan };

interface Props {
  state: PlanFormState | null;
  onClose: () => void;
  onSaved: () => void;
  /** 供「所属版本」下拉；调用方只传当前作用域内的版本。 */
  versions: Version[];
  onCreate: (body: PlanCreate) => Promise<unknown>;
  onUpdate: (planId: number, body: PlanUpdate) => Promise<unknown>;
}

const TITLES: Record<PlanFormState["mode"], string> = {
  create: "新建计划",
  edit: "编辑计划",
};

function errText(err: unknown): string {
  return err instanceof ApiError ? err.message : "操作失败";
}

/** 只列同项目的版本；当前版本恒保留（它可能已归档而不在默认列表里）。 */
function versionOptions(versions: Version[], projectId: number, currentVersionId: number) {
  const list = versions
    .filter((v) => v.project_id === projectId)
    .map((v) => ({ value: String(v.id), label: v.name }));
  if (!list.some((o) => o.value === String(currentVersionId))) {
    const hit = versions.find((v) => v.id === currentVersionId);
    list.unshift({
      value: String(currentVersionId),
      label: hit ? `${hit.name}（当前）` : `版本 #${currentVersionId}（当前）`,
    });
  }
  return list;
}

function FormActions({ onClose, onSubmit, submitting, label }: {
  onClose: () => void;
  onSubmit: () => void;
  submitting: boolean;
  label: string;
}) {
  return (
    <div className="mt-1 flex justify-end gap-2">
      <Button variant="ghost" onClick={onClose} disabled={submitting}>取消</Button>
      <Button onClick={onSubmit} disabled={submitting}>
        {submitting ? "提交中…" : label}
      </Button>
    </div>
  );
}

function CreatePlanForm({ version, onCreate, onClose, onSaved }: {
  version: Version;
  onCreate: Props["onCreate"];
  onClose: () => void;
  onSaved: () => void;
}) {
  const toast = useToast();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState<PlanStatus>("planning");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit() {
    if (!name.trim()) return toast.error("名称为必填");
    setSubmitting(true);
    try {
      await onCreate({
        name: name.trim(),
        version_id: version.id,
        description: description.trim() || undefined,
        status,
        start_date: startDate || null,
        end_date: endDate || null,
      });
      toast.success("计划已创建");
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
             maxLength={128} placeholder="如 迭代 1：打通主流程" />
      <Textarea label="描述" value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="这一轮要做什么（选填）" />
      <Select label="状态" value={status}
              onChange={(e) => setStatus(e.target.value as PlanStatus)}
              options={PLAN_STATUS_OPTIONS} />
      <div className="grid grid-cols-2 gap-3">
        <Input label="开始日期" type="date" value={startDate}
               onChange={(e) => setStartDate(e.target.value)} />
        <Input label="结束日期" type="date" value={endDate}
               onChange={(e) => setEndDate(e.target.value)} />
      </div>
      <p className="text-xs text-ink-muted">所属版本：{version.name}</p>
      <FormActions onClose={onClose} onSubmit={onSubmit} submitting={submitting} label="创建" />
    </div>
  );
}

function EditPlanForm({ plan, versions, onUpdate, onClose, onSaved }: {
  plan: Plan;
  versions: Version[];
  onUpdate: Props["onUpdate"];
  onClose: () => void;
  onSaved: () => void;
}) {
  const toast = useToast();
  const [name, setName] = useState(plan.name);
  const [description, setDescription] = useState(plan.description ?? "");
  const [status, setStatus] = useState<PlanStatus>(plan.status);
  const [versionId, setVersionId] = useState(String(plan.version_id));
  const [startDate, setStartDate] = useState(plan.start_date ?? "");
  const [endDate, setEndDate] = useState(plan.end_date ?? "");
  const [submitting, setSubmitting] = useState(false);

  function buildDiff(): PlanUpdate {
    const diff: PlanUpdate = {};
    if (name.trim() !== plan.name) diff.name = name.trim();
    if (description.trim() !== (plan.description ?? "")) diff.description = description.trim();
    if (status !== plan.status) diff.status = status;
    if (Number(versionId) !== plan.version_id) diff.version_id = Number(versionId);
    const nextStart = startDate || null;
    if (nextStart !== plan.start_date) diff.start_date = nextStart;
    const nextEnd = endDate || null;
    if (nextEnd !== plan.end_date) diff.end_date = nextEnd;
    return diff;
  }

  async function onSubmit() {
    if (!name.trim()) return toast.error("名称不能为空");
    const diff = buildDiff();
    if (Object.keys(diff).length === 0) return toast.info("没有需要保存的改动");
    setSubmitting(true);
    try {
      await onUpdate(plan.id, diff);
      toast.success("计划已保存");
      onSaved();
    } catch (err) {
      // 跨项目改挂的 400 中文来自后端「plan and version must be in the same project」——
      // 前端过滤只是把它挡在提交前的**大多数**情况下，并发下仍会真的打回来。
      toast.error(errText(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Input label="名称" value={name} onChange={(e) => setName(e.target.value)} maxLength={128} />
      <Textarea label="描述" value={description}
                onChange={(e) => setDescription(e.target.value)} />
      <Select label="状态" value={status}
              onChange={(e) => setStatus(e.target.value as PlanStatus)}
              options={PLAN_STATUS_OPTIONS} />
      <Select label="所属版本" value={versionId}
              onChange={(e) => setVersionId(e.target.value)}
              options={versionOptions(versions, plan.project_id, plan.version_id)} />
      <div className="grid grid-cols-2 gap-3">
        <Input label="开始日期" type="date" value={startDate}
               onChange={(e) => setStartDate(e.target.value)} />
        <Input label="结束日期" type="date" value={endDate}
               onChange={(e) => setEndDate(e.target.value)} />
      </div>
      <p className="text-xs text-ink-muted">
        只能改挂到<strong className="text-ink">同项目</strong>的版本；跨项目会被后端拒绝。
      </p>
      <FormActions onClose={onClose} onSubmit={onSubmit} submitting={submitting} label="保存" />
    </div>
  );
}

export default function PlanFormModal({
  state, versions, onCreate, onUpdate, onClose, onSaved,
}: Props) {
  return (
    <Modal open={!!state} onClose={onClose} title={state ? TITLES[state.mode] : undefined}>
      {state?.mode === "create" && (
        <CreatePlanForm key={state.version.id} version={state.version}
                        onCreate={onCreate} onClose={onClose} onSaved={onSaved} />
      )}
      {state?.mode === "edit" && (
        <EditPlanForm key={state.plan.id} plan={state.plan} versions={versions}
                      onUpdate={onUpdate} onClose={onClose} onSaved={onSaved} />
      )}
    </Modal>
  );
}
