import { useEffect, useRef } from "react";
import "@blocknote/core/fonts/inter.css";
import { BlockNoteView } from "@blocknote/mantine";
import "@blocknote/mantine/style.css";
import { useCreateBlockNote } from "@blocknote/react";
import type { PartialBlock } from "@blocknote/core";
import { message } from "antd";
import { endpoints } from "../../shared/api/endpoints";
import type { BlackboardNote } from "../../shared/api/types";
import { useAppTheme } from "../../app/providers";

interface BlackboardEditorProps {
  note: BlackboardNote;
  onSyncStatusChange?: (status: "idle" | "saving" | "saved" | "error", lastSaved?: string) => void;
}

export function BlackboardEditor({ note, onSyncStatusChange }: BlackboardEditorProps) {
  const { dark } = useAppTheme();
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isDirtyRef = useRef(false);

  // 解析初始 Block 列表
  const initialBlocks = (() => {
    try {
      if (note.content_json) {
        const parsed = JSON.parse(note.content_json);
        if (Array.isArray(parsed) && parsed.length > 0) {
          return parsed as PartialBlock[];
        }
      }
    } catch {
      // 容错回退
    }
    return undefined;
  })();

  const editor = useCreateBlockNote({
    initialContent: initialBlocks,
  });

  const saveContent = async () => {
    if (!editor) return;
    try {
      onSyncStatusChange?.("saving");
      const blocks = editor.document;
      const contentJson = JSON.stringify(blocks);

      // 提取简要纯文本用于快照/检索
      const plainText = blocks
        .map((b) => {
          if ("content" in b && Array.isArray(b.content)) {
            return b.content.map((c: any) => c.text || "").join("");
          }
          return "";
        })
        .filter(Boolean)
        .join("\n");

      await endpoints.updateBlackboardNote(note.note_id, {
        title: note.title,
        content_json: contentJson,
        plain_text: plainText,
        updated_by: "团队成员",
      });

      isDirtyRef.current = false;
      const nowStr = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      onSyncStatusChange?.("saved", nowStr);
    } catch (err) {
      console.error("保存备忘录失败", err);
      onSyncStatusChange?.("error");
      message.error("公共备忘录同步失败，请检查网络连接");
    }
  };

  const handleChange = () => {
    isDirtyRef.current = true;
    onSyncStatusChange?.("saving");
    if (timerRef.current) {
      clearTimeout(timerRef.current);
    }
    // 700ms 防抖自动提交
    timerRef.current = setTimeout(() => {
      saveContent();
    }, 700);
  };

  // 卸载前若有未保存改动，立刻触发保存
  useEffect(() => {
    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
      if (isDirtyRef.current) {
        saveContent();
      }
    };
  }, []);

  return (
    <div style={EDITOR_CONTAINER} className="blackboard-bn-root">
      <BlockNoteView
        editor={editor}
        theme={dark ? "dark" : "light"}
        onChange={handleChange}
        style={BN_VIEW_STYLE}
      />
    </div>
  );
}

const EDITOR_CONTAINER: React.CSSProperties = {
  minHeight: "100%",
  padding: "4px 8px 32px 0",
};

const BN_VIEW_STYLE: React.CSSProperties = {
  minHeight: "450px",
  fontFamily: "var(--font-family, inherit)",
};
