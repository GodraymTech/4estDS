import json
import pytest

from forestds.api.routers.blackboard import (
    get_blackboard_note,
    update_blackboard_note,
    reset_blackboard_note,
)
from forestds.api.schemas import BlackboardNoteUpdate
from forestds.db.schema import init_db


@pytest.fixture
def test_db(tmp_path):
    db_file = tmp_path / "test_blackboard.db"
    db_url = str(db_file)
    init_db(db_url)
    return db_url


def test_blackboard_get_creates_default_template(test_db):
    note = get_blackboard_note(note_id="default", db_url=test_db)
    assert note.note_id == "default"
    assert note.title == "团队公共备忘录"
    assert "📝" in note.content_json
    blocks = json.loads(note.content_json)
    assert isinstance(blocks, list)
    assert len(blocks) > 0


def test_blackboard_update_and_persistence(test_db):
    new_blocks = [
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "测试备忘录更新内容", "styles": {}}],
        }
    ]
    update_data = BlackboardNoteUpdate(
        title="修改后的标题",
        content_json=json.dumps(new_blocks, ensure_ascii=False),
        plain_text="测试备忘录更新内容",
        updated_by="张工",
    )
    saved = update_blackboard_note(note_id="default", body=update_data, db_url=test_db)
    assert saved.title == "修改后的标题"
    assert saved.updated_by == "张工"
    assert saved.plain_text == "测试备忘录更新内容"

    # 重新读取确认持久化成功
    reloaded = get_blackboard_note(note_id="default", db_url=test_db)
    assert reloaded.title == "修改后的标题"
    assert "测试备忘录更新内容" in reloaded.content_json


def test_blackboard_reset(test_db):
    # 先修改
    update_data = BlackboardNoteUpdate(
        title="暂存草稿",
        content_json="[]",
        plain_text="",
        updated_by="临时用户",
    )
    update_blackboard_note(note_id="default", body=update_data, db_url=test_db)

    # 重置
    res = reset_blackboard_note(note_id="default", db_url=test_db)
    assert res["ok"] is True

    # 重新读取
    note = get_blackboard_note(note_id="default", db_url=test_db)
    assert note.title == "团队公共备忘录"
    assert note.updated_by == "系统重置"
    assert "📝" in note.content_json
