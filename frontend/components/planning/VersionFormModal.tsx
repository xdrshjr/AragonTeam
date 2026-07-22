"use client";

// 版本增改弹窗（version-plan-console §7.2）。
// 形状照抄 admin/ProjectFormModal：判别联合 state + 双子组件 + buildDiff 三件套。
//
// **没有 released_at 输入框**：它是服务端托管的（随 status 进出 released 由后端
// stamp / 清空），给一个永远不生效的输入框比不给更糟。
// **编辑态不能改项目**：后端 PATCH 静默忽略 project_id，故以只读文本呈现。

import { useState } from "react";
import { ApiError } from "@/lib/api";
import { VERSION_STATUS_OPTIONS } from "@/lib/constants";
import { useToast } from "@/lib/toast";
import type {
  Project, User, Version, VersionCreate, VersionStatus, VersionUpdate,
} from "@/lib/types";
import Modal from "@/components/ui/Modal";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import Textarea from "@/components/ui/Textarea";
import Button from "@/components/ui/Button";

export type VersionFormState =
  | { mode: "create"; projectId: number }
  | { mode: "edit"; version: Version };

interface Props {
  state: VersionFormState | null;        // null → 关闭
  onClose: () => void;
  onSaved: () => void;
  users?: User[];
  projects?: Project[];
  /** 由页面注入（走 useVersions 的 create / update，好让失效编排只有一处）。 */
  onCreate: (body: VersionCreate) => Promise<unknown>;
  onUpdate: (versionId: number, body: VersionUpdate) => Promise<unknown>;
}

const TITLES: Record<VersionFormState["mode"], string> = {
  create: "新建版本",
  edit: "编辑版本",
};

function errText(err: unknown): string {
  return err instanceof ApiError ? err.message : "操作失败";
}

/** 负责人下拉：已停用成员不出现，但**当前负责人恒保留**，否则下拉会静默错位
 *  （手法与 ProjectFormModal.ownerOptions 逐字一致）。 */
function ownerOptions(users: User[] | undefined, currentOwnerId: number | null) {
  return (users ?? [])
    .filter((u) => u.is_active !== false || u.id === currentOwnerId)
    .map((u) => ({
      value: String(u.id),
      label: `${u.display_name || u.username}${u.is_active === false ? "（已停用）" : ""}`,
    }));
}

function projectLabel(projects: Project[] | undefined, projectId: number): string {
  const hit = projects?.find((p) => p.id === projectId);
  return hit ? `${hit.key} · ${hit.name}` : `#${projectId}`;
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

function CreateVersionForm({
  projectId, users, projects, onCreate, onClose, onSaved,
}: {
  projectId: number;
  users?: User[];
  projects?: Project[];
  onCreate: Props["onCreate"];
  onClose: () => void;
  onSaved: () => void;
}) {
  const toast = useToast();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState<VersionStatus>("planning");
  const [ownerId, setOwnerId] = useState("");
  const [targetDate, setTargetDate] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit() {
    if (!name.trim()) return toast.error("名称为必填");
    setSubmitting(true);
    try {
      await onCreate({
        name: name.trim(),
        project_id: projectId,
        description: description.trim() || undefined,
        status,
        owner_id: ownerId === "" ? null : Number(ownerId),
        target_date: targetDate || null,
      });
      toast.success("版本已创建");
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
             maxLength={128} placeholder="如 v1.0 首个可用版本" />
      <Textarea label="描述" value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="这个版本要交付什么（选填）" />
      <Select label="状态" value={status}
              onChange={(e) => setStatus(e.target.value as VersionStatus)}
              options={VERSION_STATUS_OPTIONS} />
      <Select label="负责人" value={ownerId} onChange={(e) => setOwnerId(e.target.value)}
              options={ownerOptions(users, null)} placeholder="未指定" />
      {/* 后端 DATE 列序列化为 `YYYY-MM-DD` 且**无 Z**，故用 date 而非 datetime-local。 */}
      <Input label="目标日期" type="date" value={targetDate}
             onChange={(e) => setTargetDate(e.target.value)} />
      <p className="text-xs text-ink-muted">
        所属项目：{projectLabel(projects, projectId)}（版本创建后不可更换项目）
      </p>
      <FormActions onClose={onClose} onSubmit={onSubmit} submitting={submitting} label="创建" />
    </div>
  );
}

function EditVersionForm({
  version, users, projects, onUpdate, onClose, onSaved,
}: {
  version: Version;
  users?: User[];
  projects?: Project[];
  onUpdate: Props["onUpdate"];
  onClose: () => void;
  onSaved: () => void;
}) {
  const toast = useToast();
  const [name, setName] = useState(version.name);
  const [description, setDescription] = useState(version.description ?? "");
  const [status, setStatus] = useState<VersionStatus>(version.status);
  const [ownerId, setOwnerId] = useState(
    version.owner_id === null ? "" : String(version.owner_id)
  );
  const [targetDate, setTargetDate] = useState(version.target_date ?? "");
  const [submitting, setSubmitting] = useState(false);

  /** 只提交真正变化的字段——后端对「无任何可更新字段」返 400，空 diff 在此就地拦下。 */
  function buildDiff(): VersionUpdate {
    const diff: VersionUpdate = {};
    if (name.trim() !== version.name) diff.name = name.trim();
    if (description.trim() !== (version.description ?? "")) {
      diff.description = description.trim();
    }
    if (status !== version.status) diff.status = status;
    const nextOwner = ownerId === "" ? null : Number(ownerId);
    if (nextOwner !== version.owner_id) diff.owner_id = nextOwner;
    const nextDate = targetDate || null;
    if (nextDate !== version.target_date) diff.target_date = nextDate;
    return diff;
  }

  async function onSubmit() {
    if (!name.trim()) return toast.error("名称不能为空");
    const diff = buildDiff();
    if (Object.keys(diff).length === 0) return toast.info("没有需要保存的改动");
    setSubmitting(true);
    try {
      await onUpdate(version.id, diff);
      toast.success("版本已保存");
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
      <Textarea label="描述" value={description}
                onChange={(e) => setDescription(e.target.value)} />
      <Select label="状态" value={status}
              onChange={(e) => setStatus(e.target.value as VersionStatus)}
              options={VERSION_STATUS_OPTIONS} />
      <Select label="负责人" value={ownerId} onChange={(e) => setOwnerId(e.target.value)}
              options={ownerOptions(users, version.owner_id)} placeholder="未指定" />
      <Input label="目标日期" type="date" value={targetDate}
             onChange={(e) => setTargetDate(e.target.value)} />
      <p className="text-xs text-ink-muted">
        所属项目：{projectLabel(projects, version.project_id)}（版本创建后不可更换项目）
        {version.released_at && (
          <> · 实际发布时间 {version.released_at.slice(0, 10)}（由系统在状态转为「已发布」时记录）</>
        )}
      </p>
      <FormActions onClose={onClose} onSubmit={onSubmit} submitting={submitting} label="保存" />
    </div>
  );
}

export default function VersionFormModal({
  state, users, projects, onCreate, onUpdate, onClose, onSaved,
}: Props) {
  return (
    <Modal open={!!state} onClose={onClose} title={state ? TITLES[state.mode] : undefined}>
      {state?.mode === "create" && (
        <CreateVersionForm projectId={state.projectId} users={users} projects={projects}
                           onCreate={onCreate} onClose={onClose} onSaved={onSaved} />
      )}
      {state?.mode === "edit" && (
        <EditVersionForm key={state.version.id} version={state.version} users={users}
                         projects={projects} onUpdate={onUpdate}
                         onClose={onClose} onSaved={onSaved} />
      )}
    </Modal>
  );
}
