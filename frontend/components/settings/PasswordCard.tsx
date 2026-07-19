"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useToast } from "@/lib/toast";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";

// 修改密码卡（account-settings §7）：三密码框；前端先校 new==confirm 与长度，
// 后端校旧密码。成功清空三框并 toast；后端 400 直接 toast 其 error。
export default function PasswordCard() {
  const toast = useToast();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [saving, setSaving] = useState(false);

  async function onSave() {
    if (next.length < 6) {
      toast.error("新密码至少 6 位");
      return;
    }
    if (next !== confirm) {
      toast.error("两次输入的新密码不一致");
      return;
    }
    setSaving(true);
    try {
      await api.post("/me/password", { current_password: current, new_password: next });
      setCurrent("");
      setNext("");
      setConfirm("");
      toast.success("密码已修改");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "修改失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="rounded-xl border border-border bg-surface p-6 shadow-card">
      <h2 className="font-serif text-lg text-ink">修改密码</h2>
      <p className="mt-1 text-sm text-ink-muted">修改后当前会话不受影响，下次登录请使用新密码。</p>

      <div className="mt-5 flex flex-col gap-4">
        <Input
          label="当前密码"
          type="password"
          autoComplete="current-password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
        />
        <Input
          label="新密码（至少 6 位）"
          type="password"
          autoComplete="new-password"
          value={next}
          onChange={(e) => setNext(e.target.value)}
        />
        <Input
          label="确认新密码"
          type="password"
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
        />
      </div>

      <div className="mt-5">
        <Button onClick={onSave} disabled={saving || !current || !next || !confirm}>
          {saving ? "提交中…" : "修改密码"}
        </Button>
      </div>
    </section>
  );
}
