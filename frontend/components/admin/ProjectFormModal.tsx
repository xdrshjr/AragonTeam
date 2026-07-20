"use client";

// 项目管理弹窗（admin-console §2.4 + lifecycle-and-governance §2.6）：新建 / 编辑两态。
// key 输入即大写化并限长 16，对齐 Project.key VARCHAR(16) 与后端 .upper()。
// 归档不放在本弹窗里——它是项目列表行上的独立动作，与「改字段」不同性质（§2.6）。

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useToast } from "@/lib/toast";
import type { Project, ProjectCreate, ProjectUpdate, User } from "@/lib/types";
import Modal from "@/components/ui/Modal";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import Textarea from "@/components/ui/Textarea";
import Button from "@/components/ui/Button";

export type ProjectFormState =
  | { mode: "create" }
  | { mode: "edit"; project: Project };

interface Props {
  state: ProjectFormState | null; // null → 关闭
  onClose: () => void;
  onSaved: () => void; // 成功后：关闭 + mutate(PROJECTS_KEY)（由调用方 projects 页负责）
  /** 供「负责人」下拉；缺省则不渲染该字段（列表未加载完时不放空下拉）。 */
  users?: User[];
}

interface SubProps {
  onClose: () => void;
  onSaved: () => void;
  users?: User[];
}

const TITLES: Record<ProjectFormState["mode"], string> = {
  create: "新建项目",
  edit: "编辑项目",
};

function errText(err: unknown): string {
  return err instanceof ApiError ? err.message : "操作失败";
}

/** 负责人下拉选项：已停用成员不出现（§2.5），但当前负责人恒保留，否则下拉会静默错位。 */
function ownerOptions(users: User[] | undefined, currentOwnerId: number | null) {
  return (users ?? [])
    .filter((u) => u.is_active !== false || u.id === currentOwnerId)
    .map((u) => ({
      value: String(u.id),
      label: `${u.display_name || u.username}${u.is_active === false ? "（已停用）" : ""}`,
    }));
}

function FormActions({ onClose, onSubmit, submitting, label }: {
  onClose: () => void;
  onSubmit: () => void;
  submitting: boolean;
  label: string;
}) {
  return (
    <div className="mt-1 flex justify-end gap-2">
      <Button variant="ghost" onClick={onClose} disabled={submitting}>
        取消
      </Button>
      <Button onClick={onSubmit} disabled={submitting}>
        {submitting ? "提交中…" : label}
      </Button>
    </div>
  );
}

function CreateProjectForm({ onClose, onSaved }: SubProps) {
  const toast = useToast();
  const [name, setName] = useState("");
  const [key, setKey] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit() {
    if (!name.trim() || !key.trim()) return toast.error("名称与标识为必填");
    setSubmitting(true);
    try {
      const payload: ProjectCreate = {
        name: name.trim(),
        key: key.trim(),
        description: description.trim() || undefined,
      };
      await api.post<Project>("/projects", payload);
      toast.success("项目已创建");
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
             maxLength={128} placeholder="项目名称" />
      <Input label="标识（Key）" value={key}
             onChange={(e) => setKey(e.target.value.toUpperCase())}
             maxLength={16} placeholder="如 ARA（大写字母 / 数字）" className="font-mono" />
      <Textarea label="描述" value={description} onChange={(e) => setDescription(e.target.value)}
                placeholder="项目简介（选填）" />
      <FormActions onClose={onClose} onSubmit={onSubmit} submitting={submitting} label="创建" />
    </div>
  );
}

function EditProjectForm({ project, users, onClose, onSaved }: SubProps & { project: Project }) {
  const toast = useToast();
  const [name, setName] = useState(project.name);
  const [key, setKey] = useState(project.key);
  const [description, setDescription] = useState(project.description ?? "");
  const [ownerId, setOwnerId] = useState(
    project.owner_id === null ? "" : String(project.owner_id)
  );
  const [submitting, setSubmitting] = useState(false);

  /** 只提交真正变化的字段——后端对「无任何可更新字段」返 400，空 diff 在此就地拦下。 */
  function buildDiff(): ProjectUpdate {
    const diff: ProjectUpdate = {};
    if (name.trim() !== project.name) diff.name = name.trim();
    if (key.trim().toUpperCase() !== project.key) diff.key = key.trim().toUpperCase();
    if (description.trim() !== (project.description ?? "")) {
      diff.description = description.trim();
    }
    const nextOwner = ownerId === "" ? null : Number(ownerId);
    if (nextOwner !== project.owner_id) diff.owner_id = nextOwner;
    return diff;
  }

  async function onSubmit() {
    if (!name.trim() || !key.trim()) return toast.error("名称与标识不能为空");
    const diff = buildDiff();
    if (Object.keys(diff).length === 0) return toast.info("没有需要保存的改动");
    setSubmitting(true);
    try {
      await api.patch<Project>(`/projects/${project.id}`, diff);
      toast.success("项目已保存");
      onSaved();
    } catch (err) {
      toast.error(errText(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Input label="名称" value={name} onChange={(e) => setName(e.target.value)} maxLength={128} />
      <Input label="标识（Key）" value={key}
             onChange={(e) => setKey(e.target.value.toUpperCase())}
             maxLength={16} className="font-mono" />
      <Textarea label="描述" value={description} onChange={(e) => setDescription(e.target.value)}
                placeholder="项目简介（选填）" />
      <Select label="负责人" value={ownerId} onChange={(e) => setOwnerId(e.target.value)}
              options={ownerOptions(users, project.owner_id)} placeholder="未指定" />
      <FormActions onClose={onClose} onSubmit={onSubmit} submitting={submitting} label="保存" />
    </div>
  );
}

export default function ProjectFormModal({ state, users, onClose, onSaved }: Props) {
  return (
    <Modal open={!!state} onClose={onClose} title={state ? TITLES[state.mode] : undefined}>
      {state?.mode === "create" && <CreateProjectForm onClose={onClose} onSaved={onSaved} />}
      {state?.mode === "edit" && (
        <EditProjectForm key={state.project.id} project={state.project} users={users}
                         onClose={onClose} onSaved={onSaved} />
      )}
    </Modal>
  );
}
