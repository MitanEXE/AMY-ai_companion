"""Local conversation history and model-proposed choices."""

import fcntl
import json
from dataclasses import dataclass, field
from uuid import uuid4

import mitan_jarvis as amy

DATA_PARTS = (".local", "share", "mitan-jarvis")
FILENAME = "desktop-chats.json"
LIMIT = 24 * 1024 * 1024
CHOICE_TAG = "[[AMY_CHOICES]]"
CHOICE_HINT = (
    "When the user would benefit from making a choice, write a brief explanation and end with "
    '[[AMY_CHOICES]] followed by a JSON array such as [{"title":"First option","reason":"Why it fits and its trade-off"},'
    '{"title":"Second option","reason":"Why it fits and its trade-off"}]. Give 2 to 5 distinct choices. '
    "For ordinary replies omit the marker and JSON. The user can keep chatting without choosing."
)
OPTION_SCHEMA = {
    "type": "array", "maxItems": 5,
    "items": {
        "type": "object", "additionalProperties": False, "required": ["title", "reason"],
        "properties": {"title": {"type": "string", "maxLength": 100},
                       "reason": {"type": "string", "maxLength": 360}},
    },
}
CODING_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["message", "options"],
    "properties": {"message": {"type": "string", "maxLength": 3000}, "options": OPTION_SCHEMA},
}


def validate_choices(options, minimum):
    if not isinstance(options, list) or not minimum <= len(options) <= 5:
        raise ValueError(f"AMY needs {minimum} or more valid options to show a choice card.")
    cleaned = []
    titles = set()
    reasons = set()
    for option in options:
        if not isinstance(option, dict) or set(option) != {"title", "reason"}:
            raise ValueError("AMY returned an incomplete choice.")
        title, reason = option["title"], option["reason"]
        if (not isinstance(title, str) or not isinstance(reason, str)
                or not 1 <= len(title.strip()) <= 100 or not 8 <= len(reason.strip()) <= 360
                or "```" in title + reason or "\n" in title or "\n" in reason
                or title.strip().casefold() in titles or reason.strip().casefold() in reasons):
            raise ValueError("AMY needs distinct options with a short reason for each.")
        titles.add(title.strip().casefold())
        reasons.add(reason.strip().casefold())
        cleaned.append({"title": title.strip(), "reason": reason.strip()})
    return cleaned


class ChoiceStream:
    """Keep the optional choice payload out of streamed visible text."""

    def __init__(self, publish):
        self.publish = publish
        self.buffer = ""
        self.has_choices = False

    def feed(self, chunk):
        self.buffer += chunk
        if self.has_choices:
            return
        before, marker, after = self.buffer.partition(CHOICE_TAG)
        if marker:
            if before:
                self.publish(before)
            self.has_choices = True
            self.buffer = after
            return
        # Hold only a possible marker prefix when it is split across stream chunks.
        keep = next((i for i in range(len(CHOICE_TAG) - 1, 0, -1)
                     if self.buffer.endswith(CHOICE_TAG[:i])), 0)
        ready = self.buffer[:-keep] if keep else self.buffer
        if ready:
            self.publish(ready)
        self.buffer = self.buffer[-keep:] if keep else ""

    def finish(self, answer):
        if not self.has_choices:
            if self.buffer:
                self.publish(self.buffer)
            return answer, []
        prose, _, _ = answer.partition(CHOICE_TAG)
        try:
            choices = validate_choices(json.loads(self.buffer), 2)
        except (ValueError, TypeError):
            return prose.rstrip() or "Try asking for the options again.", []
        return prose.rstrip(), choices


@dataclass
class Conversation:
    id: str = field(default_factory=lambda: uuid4().hex)
    title: str = "New chat"
    workspace: str = ""
    messages: list = field(default_factory=list)
    context: list = field(default_factory=list)

    def record(self, role, text, attachments=(), choices=()):
        if role in ("You", "Heard") and not self.messages and text:
            title = " ".join(text.split())
            self.title = title[:60] + ("…" if len(title) > 60 else "")
        self.messages.append({"role": role, "text": text, "attachments": list(attachments),
                              "choices": list(choices)})

    def remember(self, question, answer):
        self.context = (self.context + [
            {"role": "user", "content": question[-2200:]},
            {"role": "assistant", "content": answer[-2200:]},
        ])[-8:]

    def prompt_context(self, budget=4500):
        selected = []
        for item in reversed(self.context):
            size = len(item["content"])
            if size > budget:
                break
            selected.append(item)
            budget -= size
        selected.reverse()
        if selected and selected[0]["role"] == "assistant":
            selected.pop(0)
        return selected

    def recent_attachments(self):
        for message in reversed(self.messages):
            if message["attachments"]:
                return message["attachments"]
        return []


class ChatStore:
    def __init__(self):
        self.chats = {}
        self.active = ""
        self.original = (None, None)
        self.writable = True

    def load(self):
        try:
            with amy.home_directory(DATA_PARTS) as directory:
                self.original = amy.snapshot(directory, FILENAME, LIMIT)
        except FileNotFoundError:
            return
        if self.original[0] is None:
            return
        try:
            document = json.loads(self.original[0])
            if document["version"] != 1 or not isinstance(document["chats"], list):
                raise ValueError("Unsupported conversation format.")
            chats = {}
            for record in document["chats"]:
                chat = Conversation(**record)
                if not all(isinstance(value, str) for value in (chat.id, chat.title, chat.workspace)):
                    raise ValueError("Invalid chat metadata.")
                if not isinstance(chat.messages, list) or not isinstance(chat.context, list):
                    raise ValueError("Invalid chat history.")
                for item in chat.messages:
                    if (not isinstance(item["role"], str) or not isinstance(item["text"], str)
                            or not isinstance(item["attachments"], list) or not isinstance(item["choices"], list)):
                        raise ValueError("Invalid chat message.")
                    if item["choices"]:
                        validate_choices(item["choices"], 3 if chat.workspace else 2)
                for item in chat.context:
                    if item["role"] not in ("user", "assistant") or not isinstance(item["content"], str):
                        raise ValueError("Invalid model history.")
                if chat.id in chats:
                    raise ValueError("Duplicate chat.")
                chats[chat.id] = chat
            self.chats = chats
            self.active = document.get("active", "")
        except (KeyError, TypeError, ValueError) as error:
            self.writable = False
            raise ValueError("Saved chats could not be read. The existing file was preserved.") from error

    def new(self, workspace=""):
        chat = Conversation(workspace=workspace)
        self.chats[chat.id] = chat
        return chat

    def save(self):
        if not self.writable:
            raise RuntimeError("Chat history is unavailable until its saved file can be read.")
        data = json.dumps({"version": 1, "active": self.active,
                           "chats": [vars(chat) for chat in self.chats.values()]},
                          ensure_ascii=False, separators=(",", ":")).encode()
        with amy.home_directory(DATA_PARTS, created=[]) as directory:
            fcntl.flock(directory, fcntl.LOCK_EX | fcntl.LOCK_NB)
            amy.replace_snapshot(directory, FILENAME, self.original, data, LIMIT)
            self.original = amy.snapshot(directory, FILENAME, LIMIT)
