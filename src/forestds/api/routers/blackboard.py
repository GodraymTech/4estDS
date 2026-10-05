"""团队公共备忘录 / 小黑板路由。

提供全员共享小黑板的读取、实时持久化与清空重置接口。
支持 BlockNote 块级协同富文本数据结构。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_db_url
from ..schemas import BlackboardNoteOut, BlackboardNoteUpdate
from ...db.schema import get_db_connection

router = APIRouter(prefix="/blackboard", tags=["blackboard"])

_DEFAULT_NOTE_ID = "default"

_INITIAL_BLOCKS = [
    {
        "type": "heading",
        "props": {"level": 1},
        "content": [{"type": "text", "text": "📝 团队小黑板", "styles": {}}],
    },
    {
        "type": "paragraph",
        "content": [
            {
                "type": "text",
                "text": "欢迎使用红树林生态资产监管平台团队小黑板！所有访问本站的成员都可以随时在此记录、协同编辑与工作交接。",
                "styles": {},
            }
        ],
    },
    {
        "type": "heading",
        "props": {"level": 2},
        "content": [{"type": "text", "text": "📌 近期重点关注项", "styles": {}}],
    },
    {
        "type": "checkListItem",
        "props": {"checked": True},
        "content": [
            {
                "type": "text",
                "text": "珠金平 20260809 时相单木株高与冠幅复核已通过",
                "styles": {},
            }
        ],
    },
    {
        "type": "checkListItem",
        "props": {"checked": False},
        "content": [
            {
                "type": "text",
                "text": "核查新导入的淇澳岛 COG 高分正射影像与点云融合基准",
                "styles": {},
            }
        ],
    },
    {
        "type": "heading",
        "props": {"level": 2},
        "content": [{"type": "text", "text": "💡 提示", "styles": {}}],
    },
    {
        "type": "paragraph",
        "content": [
            {
                "type": "text",
                "text": "输入 / 即可唤起快速排版菜单（支持多级标题、待办清单、表格、引用等），所有修改会自动实时同步保存到云端。",
                "styles": {"italic": True},
            }
        ],
    },
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("", response_model=BlackboardNoteOut, summary="获取默认公共备忘录")
@router.get("/{note_id}", response_model=BlackboardNoteOut, summary="获取指定公共备忘录")
def get_blackboard_note(
    note_id: str = _DEFAULT_NOTE_ID,
    db_url: Annotated[Optional[str], Depends(get_db_url)] = None,
) -> BlackboardNoteOut:
    """获取小黑板内容；若不存在则自动初始化默认模板。"""
    conn = get_db_connection(db_url)
    try:
        row = conn.execute(
            "SELECT note_id, title, content_json, plain_text, updated_by, created_at, updated_at "
            "FROM blackboard_notes WHERE note_id = ?",
            (note_id,),
        ).fetchone()

        if row:
            return BlackboardNoteOut(
                note_id=row["note_id"],
                title=row["title"],
                content_json=row["content_json"],
                plain_text=row["plain_text"],
                updated_by=row["updated_by"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

        # 首次访问自动创建默认记录
        now = _now_iso()
        init_json = json.dumps(_INITIAL_BLOCKS, ensure_ascii=False)
        conn.execute(
            "INSERT INTO blackboard_notes (note_id, title, content_json, plain_text, updated_by, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                note_id,
                "团队公共备忘录",
                init_json,
                "欢迎使用红树林生态资产监管平台团队小黑板！",
                "系统初建",
                now,
                now,
            ),
        )
        conn.commit()

        return BlackboardNoteOut(
            note_id=note_id,
            title="团队公共备忘录",
            content_json=init_json,
            plain_text="欢迎使用红树林生态资产监管平台团队小黑板！",
            updated_by="系统初建",
            created_at=now,
            updated_at=now,
        )
    finally:
        conn.close()


@router.put("/{note_id}", response_model=BlackboardNoteOut, summary="保存/更新公共备忘录")
def update_blackboard_note(
    note_id: str,
    body: BlackboardNoteUpdate,
    db_url: Annotated[Optional[str], Depends(get_db_url)] = None,
) -> BlackboardNoteOut:
    """更新小黑板内容（支持自动保存）。"""
    conn = get_db_connection(db_url)
    try:
        now = _now_iso()
        existing = conn.execute(
            "SELECT created_at, title FROM blackboard_notes WHERE note_id = ?",
            (note_id,),
        ).fetchone()

        title = body.title if body.title is not None else (existing["title"] if existing else "团队公共备忘录")
        plain_text = body.plain_text or ""
        updated_by = body.updated_by or "团队成员"

        if existing:
            conn.execute(
                "UPDATE blackboard_notes SET title = ?, content_json = ?, plain_text = ?, updated_by = ?, updated_at = ? "
                "WHERE note_id = ?",
                (title, body.content_json, plain_text, updated_by, now, note_id),
            )
            created_at = existing["created_at"]
        else:
            conn.execute(
                "INSERT INTO blackboard_notes (note_id, title, content_json, plain_text, updated_by, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (note_id, title, body.content_json, plain_text, updated_by, now, now),
            )
            created_at = now

        conn.commit()

        return BlackboardNoteOut(
            note_id=note_id,
            title=title,
            content_json=body.content_json,
            plain_text=plain_text,
            updated_by=updated_by,
            created_at=created_at,
            updated_at=now,
        )
    finally:
        conn.close()


@router.delete("/{note_id}", summary="重置清空公共备忘录")
def reset_blackboard_note(
    note_id: str,
    db_url: Annotated[Optional[str], Depends(get_db_url)] = None,
):
    """将小黑板重置为初始状态。"""
    conn = get_db_connection(db_url)
    try:
        now = _now_iso()
        init_json = json.dumps(_INITIAL_BLOCKS, ensure_ascii=False)
        conn.execute(
            "UPDATE blackboard_notes SET title = '团队公共备忘录', content_json = ?, plain_text = '', updated_by = '系统重置', updated_at = ? "
            "WHERE note_id = ?",
            (init_json, now, note_id),
        )
        if conn.total_changes == 0:
            conn.execute(
                "INSERT INTO blackboard_notes (note_id, title, content_json, plain_text, updated_by, created_at, updated_at) "
                "VALUES (?, '团队公共备忘录', ?, '', '系统重置', ?, ?)",
                (note_id, init_json, now, now),
            )
        conn.commit()
        return {"ok": True, "message": "已重置小黑板"}
    finally:
        conn.close()
