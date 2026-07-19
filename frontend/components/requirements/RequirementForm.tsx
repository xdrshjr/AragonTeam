"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { useProjectScope } from "@/lib/project-scope";
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
  const { scope, projects } = useProjectScope();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState<Priority>("medium");
  // 【§2.4⑧-3】默认继承当前作用域，使「选了项目之后新建的单」自然落进该项目；
  // 作用域是「全部 / 未归属」时默认不归属，与今天的行为一致。
  const [projectId, setProjectId] = useState(typeof scope === "number" ? String(scope) : "");
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
    // 【§2.10-D3】create 与 assign 分别处理结果：create 成功即视为成功；若随后指派失败
    // （如所选 assignee 被删 → 404），单已创建（未指派、new），仍刷新列表+关闭弹窗并精确提示，
    // 避免笼统误报「创建失败」且留下不刷新的孤单。
    let created: Requirement;
    try {
      created = await api.post<Requirement>("/requirements", {
        title: title.trim(),
        description: description.trim() || undefined,
        priority,
        // undefined 经 JSON.stringify 自动省略 → 后端 want_int 得 None，语义与今天一致。
        project_id: projectId ? Number(projectId) : undefined,
      });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "创建失败");
      setSubmitting(false);
      return;
    }
    let result = created;
    if (assignee.assignee_type && assignee.assignee_id) {
      try {
        result = await api.patch<Requirement>(`/requirements/${created.id}/assign`, assignee);
        toast.success("需求已创建");
      } catch (err) {
        toast.info(`已创建，但指派失败：${err instanceof ApiError ? err.message : "未知原因"}`);
      }
    } else {
      toast.success("需求已创建");
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
        <Select
          label="项目"
          name="project_id"
          value={projectId}
          onChange={(e) => setProjectId(e.target.value)}
          options={[
            { value: "", label: "不归属项目" },
            ...(projects ?? []).map((p) => ({ value: String(p.id), label: `${p.key} · ${p.name}` })),
          ]}
        />
      </div>
      <AssigneePicker value={assignee} onChange={setAssignee} />
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
