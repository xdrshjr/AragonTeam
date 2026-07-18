"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useToast } from "@/lib/toast";
import type { Bug, Severity } from "@/lib/types";
import { SEVERITY_STYLES } from "@/lib/constants";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Textarea from "@/components/ui/Textarea";
import Select from "@/components/ui/Select";
import AssigneePicker, { AssigneeValue } from "@/components/AssigneePicker";

interface Props {
  onCreated: (bug: Bug) => void;
  onCancel: () => void;
}

const SEVERITY_OPTIONS = (Object.keys(SEVERITY_STYLES) as Severity[]).map((k) => ({
  value: k,
  label: SEVERITY_STYLES[k].label,
}));

// 新建 BUG 表单。
export default function BugForm({ onCreated, onCancel }: Props) {
  const toast = useToast();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [severity, setSeverity] = useState<Severity>("major");
  const [assignee, setAssignee] = useState<AssigneeValue>({
    assignee_type: null,
    assignee_id: null,
  });
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) {
      toast.error("请填写 BUG 标题");
      return;
    }
    setSubmitting(true);
    try {
      let bug = await api.post<Bug>("/bugs", {
        title: title.trim(),
        description: description.trim() || undefined,
        severity,
      });
      if (assignee.assignee_type && assignee.assignee_id) {
        bug = await api.patch<Bug>(`/bugs/${bug.id}/assign`, assignee);
      }
      toast.success("BUG 已创建");
      onCreated(bug);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "创建失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      <Input
        label="标题"
        name="title"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="例如：拖拽后偶发卡片位置错乱"
        autoFocus
      />
      <Textarea
        label="描述"
        name="description"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="复现步骤、期望结果、实际结果（可选）"
      />
      <div className="grid grid-cols-2 gap-4">
        <Select
          label="严重度"
          name="severity"
          value={severity}
          onChange={(e) => setSeverity(e.target.value as Severity)}
          options={SEVERITY_OPTIONS}
        />
        <AssigneePicker value={assignee} onChange={setAssignee} />
      </div>
      <div className="mt-2 flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          取消
        </Button>
        <Button type="submit" disabled={submitting}>
          {submitting ? "创建中…" : "创建 BUG"}
        </Button>
      </div>
    </form>
  );
}
