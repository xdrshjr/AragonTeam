"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useToast } from "@/lib/toast";
import type { Requirement, Priority } from "@/lib/types";
import { PRIORITY_STYLES } from "@/lib/constants";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Textarea from "@/components/ui/Textarea";
import Select from "@/components/ui/Select";
import AssigneePicker, { AssigneeValue } from "@/components/AssigneePicker";

interface Props {
  onCreated: (req: Requirement) => void;
  onCancel: () => void;
}

const PRIORITY_OPTIONS = (Object.keys(PRIORITY_STYLES) as Priority[]).map((k) => ({
  value: k,
  label: PRIORITY_STYLES[k].label,
}));

// 新建需求表单（含指派人/Agent 选择）。创建后若选了指派则调用 assign。
export default function RequirementForm({ onCreated, onCancel }: Props) {
  const toast = useToast();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState<Priority>("medium");
  const [assignee, setAssignee] = useState<AssigneeValue>({
    assignee_type: null,
    assignee_id: null,
  });
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) {
      toast.error("请填写需求标题");
      return;
    }
    setSubmitting(true);
    try {
      let req = await api.post<Requirement>("/requirements", {
        title: title.trim(),
        description: description.trim() || undefined,
        priority,
      });
      // 若选择了指派对象，创建后立即指派（触发 new→assigned）。
      if (assignee.assignee_type && assignee.assignee_id) {
        req = await api.patch<Requirement>(`/requirements/${req.id}/assign`, assignee);
      }
      toast.success("需求已创建");
      onCreated(req);
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
        placeholder="例如：接入 dev-agent 自动认领需求"
        autoFocus
      />
      <Textarea
        label="描述"
        name="description"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="补充背景、验收标准等（可选）"
      />
      <div className="grid grid-cols-2 gap-4">
        <Select
          label="优先级"
          name="priority"
          value={priority}
          onChange={(e) => setPriority(e.target.value as Priority)}
          options={PRIORITY_OPTIONS}
        />
        <AssigneePicker value={assignee} onChange={setAssignee} />
      </div>
      <div className="mt-2 flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          取消
        </Button>
        <Button type="submit" disabled={submitting}>
          {submitting ? "创建中…" : "创建需求"}
        </Button>
      </div>
    </form>
  );
}
