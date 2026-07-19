"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth";
import { api, ApiError } from "@/lib/api";
import { useToast } from "@/lib/toast";
import type { User, ProfileUpdate } from "@/lib/types";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";
import Avatar from "@/components/ui/Avatar";

// 头像底色调色板（与 seed / auth 一致的暖色系）。
const PALETTE = ["#C15F3C", "#3B6EA5", "#6E8B3D", "#8A5A9B", "#C99A2E", "#4B8B8B"];

// 个人资料编辑卡（account-settings §7）：display_name / email / 头像底色。
// 仅提交发生变化的字段（diff），保存成功后 applyUser 就地刷新登录态（Header 即时更新）。
export default function ProfileCard() {
  const { user, applyUser } = useAuth();
  const toast = useToast();
  const [displayName, setDisplayName] = useState(user?.display_name ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [color, setColor] = useState(user?.avatar_color ?? PALETTE[0]);
  const [saving, setSaving] = useState(false);

  if (!user) return null;

  function buildDiff(): ProfileUpdate {
    const diff: ProfileUpdate = {};
    if (displayName.trim() !== (user!.display_name ?? "")) diff.display_name = displayName.trim();
    if (email.trim() !== (user!.email ?? "")) diff.email = email.trim();
    if (color !== (user!.avatar_color ?? "")) diff.avatar_color = color;
    return diff;
  }

  async function onSave() {
    const diff = buildDiff();
    if (Object.keys(diff).length === 0) {
      toast.info("没有需要保存的改动");
      return;
    }
    setSaving(true);
    try {
      const { user: updated } = await api.patch<{ user: User }>("/me/profile", diff);
      applyUser(updated);
      toast.success("资料已更新");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="rounded-xl border border-border bg-surface p-6 shadow-card">
      <h2 className="font-serif text-lg text-ink">个人资料</h2>
      <p className="mt-1 text-sm text-ink-muted">修改显示名称、邮箱与头像底色。</p>

      <div className="mt-5 flex items-center gap-4">
        <Avatar name={displayName || user.username} color={color} size={56} />
        <div className="flex flex-wrap gap-2">
          {PALETTE.map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => setColor(c)}
              aria-label={`头像底色 ${c}`}
              aria-pressed={color === c}
              className={[
                "h-7 w-7 rounded-full border-2 transition",
                color === c ? "border-ink" : "border-transparent hover:brightness-95",
              ].join(" ")}
              style={{ backgroundColor: c }}
            />
          ))}
        </div>
      </div>

      <div className="mt-5 flex flex-col gap-4">
        <Input
          label="显示名称"
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          maxLength={128}
          placeholder="你的显示名称"
        />
        <Input
          label="邮箱"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="name@example.com（留空则清除）"
        />
      </div>

      <div className="mt-5">
        <Button onClick={onSave} disabled={saving}>
          {saving ? "保存中…" : "保存资料"}
        </Button>
      </div>
    </section>
  );
}
