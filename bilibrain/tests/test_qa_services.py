import asyncio
from types import SimpleNamespace

from bilibrain.services import qa as qa_module


class _FakeChatDb:
    def __init__(self):
        self.created_folder_ids = []
        self.conversations = [
            {
                "conversation_id": 3,
                "folder_id": 99,
                "title": "latest",
            }
        ]
        self.messages = [
            {
                "message_id": 1,
                "conversation_id": 3,
                "role": "user",
                "content": "hello",
                "sources": [],
                "answer_mode": None,
                "route_mode": None,
                "created_at": "2026-03-27 00:00:00",
            }
        ]

    def create_chat_conversation(self, folder_id, title=None):
        self.created_folder_ids.append(folder_id)
        return {
            "conversation_id": 7,
            "folder_id": folder_id,
            "title": title or "",
        }

    def get_latest_chat_conversation(self, folder_id, *, all_scopes=False):
        assert folder_id is None
        assert all_scopes is True
        return self.conversations[0]

    def get_chat_conversation(self, conversation_id):
        if int(conversation_id) == 3:
            return self.conversations[0]
        return None

    def list_chat_messages(self, conversation_id):
        assert int(conversation_id) == 3
        return list(self.messages)

    def list_chat_conversations(self, folder_id, *, all_scopes=False):
        assert folder_id is None
        assert all_scopes is True
        return list(self.conversations)


def test_create_chat_conversation_is_global_scope():
    runtime = SimpleNamespace(db=_FakeChatDb())

    payload = asyncio.run(qa_module.create_chat_conversation(runtime, title="demo"))

    assert payload["conversation"]["conversation_id"] == 7
    assert runtime.db.created_folder_ids == [None]


def test_get_chat_history_uses_global_latest_conversation():
    runtime = SimpleNamespace(db=_FakeChatDb())

    payload = asyncio.run(qa_module.get_chat_history(runtime))

    assert payload["conversation_id"] == 3
    assert payload["folder_id"] == 99
    assert payload["messages"][0]["content"] == "hello"
