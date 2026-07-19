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
    // 【§2.10-D3】create 与 assign 分别处理结果：create 成功即视为成功；若随后指派失败，
    // 单已创建（未指派、open），仍刷新列表+关闭弹窗并精确提示，避免误报「创建失败」+孤单不刷新。
    let created: Bug;
    try {
      created = await api.post<Bug>("/bugs", {
        title: title.trim(),
        description: description.trim() || undefined,
        severity,
      });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "创建失败");
      setSubmitting(false);
      return;
    }
    let result = created;
    if (assignee.assignee_type && assignee.assignee_id) {
      try {
        result = await api.patch<Bug>(`/bugs/${created.id}/assign`, assignee);
        toast.success("BUG 已创建");
      } catch (err) {
        toast.info(`已创建，但指派失败：${err instanceof ApiError ? err.message : "未知原因"}`);
      }
    } else {
      toast.success("BUG 已创建");
    }
    setSubmitting(false);
    onCreated(result);
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
