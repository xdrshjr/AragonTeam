"use client";

import { useState } from "react";
import { ApiError } from "@/lib/api";
import { useToast } from "@/lib/toast";
import Button from "@/components/ui/Button";
import MentionTextarea from "@/components/collab/MentionTextarea";

interface Props {
  onSubmit: (body: string) => Promise<void>;
}

// 评论输入框 + 发送（§2.4 协作区底部）。
// @ 触发成员补全（MentionTextarea）；下拉关闭时 Cmd/Ctrl+Enter 快捷发送；发送中禁用；成功后清空。
export default function CommentComposer({ onSubmit }: Props) {
  const toast = useToast();
  const [body, setBody] = useState("");
  const [sending, setSending] = useState(false);

  async function send() {
    const text = body.trim();
    if (!text) {
      toast.error("请输入评论内容");
      return;
    }
    setSending(true);
    try {
      await onSubmit(text);
      setBody("");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "评论失败");
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <MentionTextarea
        value={body}
        onChange={setBody}
        onKeyDown={(e) => {
          if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
            e.preventDefault();
            send();
          }
        }}
        rows={2}
        aria-label="评论输入框"
        placeholder="写下评论，与团队和 Agent 协作…（@用户名 可提醒对方 · ⌘/Ctrl + Enter 发送）"
      />
      <div className="flex justify-end">
        <Button size="sm" onClick={send} disabled={sending}>
          {sending ? "发送中…" : "发送评论"}
        </Button>
      </div>
    </div>
  );
}
