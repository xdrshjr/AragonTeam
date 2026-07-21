"use client";

// 成员管理弹窗（admin-console §2.2）：建 / 改 / 重置密码三态。
// 【C4】按模式拆分为三个子表单组件，各自持有独立 state 与提交分支，
// 单函数守住 CLAUDE.md 阈值（≤50 行 / 圈复杂度 ≤10 / 嵌套 ≤4）。

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { useAuth } from "@/lib/auth";
import type { User, Role, UserCreate, UserUpdate } from "@/lib/types";
import { ROLE_LABELS } from "@/lib/constants";
import Modal from "@/components/ui/Modal";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import Button from "@/components/ui/Button";

export type MemberFormState =
  | { mode: "create" }
  | { mode: "edit"; user: User }
  | { mode: "reset"; user: User };

interface Props {
  state: MemberFormState | null; // null → 关闭
  onClose: () => void;
  onSaved: () => void; // 成功后：关闭 + mutate("/users")
}

interface SubProps {
  onClose: () => void;
  onSaved: () => void;
}

const ROLE_OPTIONS = (["admin", "pm", "member"] as Role[]).map((r) => ({
  value: r,
  label: ROLE_LABELS[r],
}));

// 邮箱软校验（§2.2 C2）：非空时基本格式检查，与自助路径 /me/profile 对齐；后端契约不变。
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const TITLES: Record<MemberFormState["mode"], string> = {
  create: "新增成员",
  edit: "编辑成员",
  reset: "重置密码",
};

function errText(err: unknown): string {
  return err instanceof ApiError ? err.message : "操作失败";
}

function FormActions({ onClose, onSubmit, submitting, submitLabel }: {
  onClose: () => void;
  onSubmit: () => void;
  submitting: boolean;
  submitLabel: string;
}) {
  return (
    <div className="mt-1 flex justify-end gap-2">
      <Button variant="ghost" onClick={onClose} disabled={submitting}>
        取消
      </Button>
      <Button onClick={onSubmit} disabled={submitting}>
        {submitting ? "提交中…" : submitLabel}
      </Button>
    </div>
  );
}

function CreateMemberForm({ onClose, onSaved }: SubProps) {
  const toast = useToast();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit() {
    if (!username.trim() || !password) return toast.error("用户名与密码为必填");
    if (password.length < 6) return toast.error("密码至少 6 位");
    if (email.trim() && !EMAIL_RE.test(email.trim())) return toast.error("邮箱格式不正确");
    setSubmitting(true);
    try {
      const payload: UserCreate = {
        username: username.trim(),
        password,
        role,
        display_name: displayName.trim() || undefined,
        email: email.trim() || undefined,
      };
      const u = await api.post<User>("/users", payload);
      toast.success(`已创建成员 ${u.display_name || u.username}`);
      onSaved();
    } catch (err) {
      toast.error(errText(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Input label="用户名" value={username} onChange={(e) => setUsername(e.target.value)}
             maxLength={64} placeholder="登录用户名" />
      <Input label="初始密码" type="password" value={password}
             onChange={(e) => setPassword(e.target.value)} placeholder="至少 6 位" />
      <Input label="显示名称" value={displayName} onChange={(e) => setDisplayName(e.target.value)}
             maxLength={128} placeholder="留空则同用户名" />
      <Input label="邮箱" type="email" value={email} onChange={(e) => setEmail(e.target.value)}
             placeholder="name@example.com（选填）" />
      <Select label="角色" value={role} onChange={(e) => setRole(e.target.value as Role)}
              options={ROLE_OPTIONS} />
      <FormActions onClose={onClose} onSubmit={onSubmit} submitting={submitting} submitLabel="创建" />
    </div>
  );
}

function EditMemberForm({ user, onClose, onSaved }: SubProps & { user: User }) {
  const toast = useToast();
  const { user: me } = useAuth();
  const isSelf = me?.id === user.id;
  const [displayName, setDisplayName] = useState(user.display_name ?? "");
  const [email, setEmail] = useState(user.email ?? "");
  const [role, setRole] = useState<Role>(user.role);
  const [submitting, setSubmitting] = useState(false);

  function buildDiff(): UserUpdate {
    const diff: UserUpdate = {};
    if (displayName.trim() !== (user.display_name ?? "")) diff.display_name = displayName.trim();
    if (email.trim() !== (user.email ?? "")) diff.email = email.trim();
    if (!isSelf && role !== user.role) diff.role = role;
    return diff;
  }

  async function onSubmit() {
    if (email.trim() && !EMAIL_RE.test(email.trim())) return toast.error("邮箱格式不正确");
    const diff = buildDiff();
    if (Object.keys(diff).length === 0) return toast.info("没有需要保存的改动");
    setSubmitting(true);
    try {
      const u = await api.patch<User>(`/users/${user.id}`, diff);
      toast.success(`已更新 ${u.display_name || u.username}`);
      onSaved();
    } catch (err) {
      toast.error(errText(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <span className="text-sm font-medium text-ink">用户名</span>
        <div className="flex h-10 items-center rounded-lg border border-border bg-black/[0.02] px-3 text-sm text-ink-muted">
          {user.username}
        </div>
        <span className="text-xs text-ink-muted">用户名不可修改</span>
      </div>
      <Input label="显示名称" value={displayName} onChange={(e) => setDisplayName(e.target.value)}
             maxLength={128} />
      <Input label="邮箱" type="email" value={email} onChange={(e) => setEmail(e.target.value)}
             placeholder="name@example.com" />
      <div className="flex flex-col gap-1.5">
        {/* 【self-service-registration §2.3 C-3】根管理员的角色由后端配置文件锚定，
            改它会得到 409。禁用 + 解释比让人点下去再吃一个错误诚实得多。 */}
        <Select label="角色" value={role} onChange={(e) => setRole(e.target.value as Role)}
                options={ROLE_OPTIONS} disabled={isSelf || user.is_root} />
        {user.is_root ? (
          <span className="text-xs text-ink-muted">
            根管理员的角色由后端配置文件（<code>ROOT_ADMIN_*</code>）定义，不可修改
          </span>
        ) : (
          isSelf && <span className="text-xs text-ink-muted">不能修改自己的角色</span>
        )}
      </div>
      <FormActions onClose={onClose} onSubmit={onSubmit} submitting={submitting} submitLabel="保存" />
    </div>
  );
}

function ResetPasswordForm({ user, onClose, onSaved }: SubProps & { user: User }) {
  const toast = useToast();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit() {
    if (password.length < 6) return toast.error("新密码至少 6 位");
    if (password !== confirm) return toast.error("两次输入的密码不一致");
    setSubmitting(true);
    try {
      await api.patch<User>(`/users/${user.id}`, { password });
      toast.success(`已重置 ${user.display_name || user.username} 的密码`);
      onSaved();
    } catch (err) {
      toast.error(errText(err));
    } finally {
      setSubmitting(false);
    }
  }

  // 【self-service-registration §2.1 A-4】根管理员的密码只有他本人能改（走设置页的
  // `POST /api/me/password`）。整个表单禁用并说明原因——而不是让人填完再吃一个 409。
  if (user.is_root) {
    return (
      <div className="flex flex-col gap-4">
        <p className="text-sm text-ink-muted">
          <span className="font-medium text-ink">{user.display_name || user.username}</span>{" "}
          是根管理员，其密码不能由他人重置。
        </p>
        <p className="text-sm text-ink-muted">
          请由根管理员本人在「设置 → 修改密码」中更改；若已忘记密码，唯一的恢复路径是修改
          后端配置（<code>ROOT_ADMIN_SYNC_PASSWORD</code>）并重启。
        </p>
        <div className="mt-1 flex justify-end">
          <Button variant="ghost" onClick={onClose}>
            知道了
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-ink-muted">
        为 <span className="font-medium text-ink">{user.display_name || user.username}</span> 设置新密码。
      </p>
      <Input label="新密码" type="password" value={password}
             onChange={(e) => setPassword(e.target.value)} placeholder="至少 6 位" />
      <Input label="确认新密码" type="password" value={confirm}
             onChange={(e) => setConfirm(e.target.value)} />
      <FormActions onClose={onClose} onSubmit={onSubmit} submitting={submitting} submitLabel="重置密码" />
    </div>
  );
}

export default function MemberFormModal({ state, onClose, onSaved }: Props) {
  return (
    <Modal open={!!state} onClose={onClose} title={state ? TITLES[state.mode] : undefined}>
      {state?.mode === "create" && <CreateMemberForm onClose={onClose} onSaved={onSaved} />}
      {state?.mode === "edit" && (
        <EditMemberForm key={state.user.id} user={state.user} onClose={onClose} onSaved={onSaved} />
      )}
      {state?.mode === "reset" && (
        <ResetPasswordForm key={state.user.id} user={state.user} onClose={onClose} onSaved={onSaved} />
      )}
    </Modal>
  );
}
