"use client";

// 项目管理弹窗（admin-console §2.4）：仅新建态（后端无 PATCH /projects，不做假编辑）。
// key 输入即大写化并限长 16，对齐 Project.key VARCHAR(16) 与后端 .upper()。

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useToast } from "@/lib/toast";
import type { Project, ProjectCreate } from "@/lib/types";
import Modal from "@/components/ui/Modal";
import Input from "@/components/ui/Input";
import Textarea from "@/components/ui/Textarea";
import Button from "@/components/ui/Button";

interface Props {
  open: boolean;
  onClose: () => void;
  onSaved: () => void; // 成功后：关闭 + mutate(PROJECTS_KEY)（由调用方 projects 页负责）
}

export default function ProjectFormModal({ open, onClose, onSaved }: Props) {
  return (
    <Modal open={open} onClose={onClose} title="新建项目">
      <CreateProjectForm onClose={onClose} onSaved={onSaved} />
    </Modal>
  );
}

function CreateProjectForm({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
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
      toast.error(err instanceof ApiError ? err.message : "操作失败");
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
      <div className="mt-1 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose} disabled={submitting}>
          取消
        </Button>
        <Button onClick={onSubmit} disabled={submitting}>
          {submitting ? "提交中…" : "创建"}
        </Button>
      </div>
    </div>
  );
}
