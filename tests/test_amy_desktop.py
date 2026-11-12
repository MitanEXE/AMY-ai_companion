"""Exercise the Linux desktop, using local Ollama and device fixtures."""

import json
import os
import sys
import threading
import unittest
from contextlib import ExitStack
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from unittest.mock import patch

HAS_QT = sys.platform == "linux" and find_spec("PySide6") is not None
if HAS_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QPoint, QTimer, Qt
    from PySide6.QtGui import QImage
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QCheckBox, QDialogButtonBox, QLabel, QPushButton

    import amy_desktop as app
    import amy_desktop_core as desktop
    import amy_desktop_files as files
    from amy_desktop_sessions import ChatStore, CHOICE_TAG
    import mitan_jarvis as amy

HTML = "<!doctype html>\n<html><body><button>Surprise</button></body></html>\n"
OPTIONS = [
    {"title": "Email and password", "reason": "Users keep local accounts. Plan for password resets."},
    {"title": "Email sign-in link", "reason": "Users sign in with a link. Requires email delivery."},
    {"title": "Google sign-in", "reason": "Uses an existing Google account. Requires provider setup."},
]


class OllamaFixture(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send_data(self, value):
        data = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.server.metadata.append(self.path)
        if self.path == "/api/version":
            self.send_data({"version": "fixture"})
        elif self.path == "/api/tags":
            self.send_data({"models": self.server.models})
        else:
            self.send_error(404)

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/show":
            self.server.metadata.append(self.path)
            self.send_data({"capabilities": ["completion", "vision"]})
            return
        if self.path != "/api/chat":
            self.send_error(404)
            return
        self.server.requests.append(request)
        schema = request.get("format") or {}
        if "options" in schema.get("properties", {}):
            content = json.dumps({"message": "Choose an approach.", "options": self.server.options})
            self.send_data({"message": {"content": content}, "done": True})
            return
        if schema:
            proposal = json.loads(request["messages"][-1]["content"])
            plan = {"files": [{"path": proposal["target"], "edits": [{"before": "", "after": HTML}]}]}
            content = json.dumps(self.server.draft or plan)
        else:
            content = self.server.answer
        events = [
            {"message": {"content": content[: len(content) // 2]}, "done": False},
            {"message": {"content": content[len(content) // 2 :]}, "done": False},
            {"message": {"content": ""}, "done": True, "done_reason": self.server.finish_reason,
             "load_duration": 50_000_000, "prompt_eval_duration": 20_000_000,
             "eval_duration": 1_000_000_000, "eval_count": 20},
        ]
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        if self.server.stall:
            self.server.release.wait(8)
        try:
            for event in events:
                self.wfile.write((json.dumps(event) + "\n").encode())
        except (BrokenPipeError, ConnectionResetError):
            pass


@unittest.skipUnless(HAS_QT, "Linux Qt desktop dependencies are optional")
class DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")

    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.home = Path(stack.enter_context(TemporaryDirectory(prefix="amy-desktop-")))
        self.data = self.home / ".local/share/mitan-jarvis"
        stack.enter_context(patch.dict(os.environ, {"HOME": str(self.home)}))
        stack.enter_context(patch.multiple(amy, DATA=self.data, AMY_HOME=self.home / "AMY", WORK_DIR=self.data / "tmp",
                                          PROJECTS_ROOT=self.home / "Projects", MEMORY=self.data / "memory.txt",
                                          SETTINGS=self.data / "settings.json", PROFILE=self.data / "profile.json"))
        self.server = stack.enter_context(ThreadingHTTPServer(("127.0.0.1", 0), OllamaFixture))
        self.server.requests = []
        self.server.metadata = []
        self.server.options = OPTIONS
        self.server.draft = None
        self.server.answer = "A local reply."
        self.server.models = [
            {"name": "lfm3:1.7b", "digest": "a" * 64},
            {"name": "someuser/custom:latest", "digest": "b" * 64, "capabilities": ["completion", "vision"]},
            {"name": "remote:cloud"},
            {"name": "remote:alias", "remote_host": "example.com"},
            {"name": "embeddings:latest", "capabilities": ["embedding"]},
            {"name": "image-only:latest", "capabilities": ["image"]},
        ]
        self.server.finish_reason = "stop"
        self.server.stall = False
        self.server.release = threading.Event()
        worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        worker.start()
        stack.callback(self.server.shutdown)
        stack.callback(self.server.release.set)
        self.window = app.AMYWindow(self.server.server_port, desktop.Preferences(), self.app.font(), load_models=False)
        self.window.show()
        stack.callback(self.window.close)
        self.window.refresh_models()
        self.wait_for(lambda: self.window.models_loaded)
        self.window.pick_model("lfm3:1.7b")

    def wait_for(self, condition, seconds=5):
        deadline = monotonic() + seconds
        while not condition() and monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(12)
        self.assertTrue(condition())

    def send(self, question):
        self.window.composer.setPlainText(question)
        QTest.keyClick(self.window.composer, Qt.Key.Key_Return)

    @staticmethod
    def image_bytes(color):
        image = QImage(40, 24, QImage.Format.Format_RGB32)
        image.fill(color)
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        return bytes(data)

    def test_discover_select_and_persist_settings(self):
        self.window.open_models()
        checks = {check.text(): check for check in self.window.settings.model_scroll.widget().findChildren(QCheckBox)}
        self.assertEqual(set(checks), {"lfm3:1.7b", "someuser/custom:latest"})
        checkbox = checks["someuser/custom:latest"]
        QTest.mouseClick(checkbox, Qt.MouseButton.LeftButton, pos=QPoint(8, checkbox.height() // 2))
        self.assertFalse(checks["lfm3:1.7b"].isChecked())
        self.assertTrue(checks["someuser/custom:latest"].isChecked())
        self.assertEqual(desktop.load_preferences().model, "someuser/custom:latest")

        view = self.window.settings
        view.tabs.setCurrentIndex(0)
        self.assertFalse(view.language.isEnabled())
        view.languages.setCurrentIndex(1)
        view.language.setCurrentIndex(1)
        view.style.setCurrentText("Detailed")
        view.details.setText("Use a practical example.")
        view.theme.setCurrentText("Light")
        view.size.setValue(14)
        QTest.mouseClick(view.save_button, Qt.MouseButton.LeftButton)
        saved = desktop.load_preferences()
        self.assertEqual((saved.language, saved.style, saved.size, saved.theme), ("zh", "Detailed", 14, "Light"))
        self.assertTrue(saved.font)
        self.assertEqual(self.window.colors, app.LIGHT)
        self.assertEqual(self.app.font().pointSize(), 14)
        self.window.open_page(0)
        self.send("Tell me a short story.")
        self.wait_for(lambda: self.window.job is None)
        request = self.server.requests[-1]
        self.assertEqual(request["model"], "someuser/custom:latest")
        self.assertIn("Use a practical example.", request["messages"][0]["content"])
        self.assertIn("Taiwanese Traditional Chinese", request["messages"][0]["content"])

        self.server.models.pop(1)
        self.window.refresh_models()
        self.wait_for(lambda: self.window.job is None)
        self.assertIn("unavailable", self.window.settings.model_status.text())
        self.send("Tell me another story.")
        self.wait_for(lambda: self.window.job is None)
        self.assertEqual(len(self.server.requests), 1)

    def test_html_draft_cancel_and_approve_then_read_back(self):
        samples = []

        def choose(dialog, approve):
            def click():
                choices = dialog.findChild(QDialogButtonBox).buttons()
                samples.append((amy.PROJECTS_ROOT.exists(), [item.text() for item in choices]))
                match = next(item for item in choices if item.text() == ("Approve and save" if approve else "Cancel"))
                QTest.mouseClick(match, Qt.MouseButton.LeftButton)
            QTimer.singleShot(0, click)
            return original(dialog)

        original = app.DraftDialog.exec
        question = "Create a complete, interactive HTML surprise page"
        with patch.object(app.DraftDialog, "exec", lambda dialog: choose(dialog, False)):
            self.send(question)
            self.wait_for(lambda: self.window.job is None)
        self.assertFalse(amy.PROJECTS_ROOT.exists())
        self.assertIn("No files were saved", self.window.transcript.toPlainText())

        with patch.object(app.DraftDialog, "exec", lambda dialog: choose(dialog, True)):
            self.send(question)
            self.wait_for(lambda: self.window.job is None)
        expected = amy.PROJECTS_ROOT / "surprise.html"
        self.assertTrue(samples)
        self.assertEqual([sample[0] for sample in samples], [False, False])
        self.assertEqual(expected.read_text(), HTML)
        self.assertIn(str(expected), self.window.transcript.toPlainText())
        self.assertIn("Saved and verified", self.window.transcript.toPlainText())
        self.assertTrue(self.window.last_report.is_file())
        self.assertEqual(self.window.check_saved_path(), expected)
        self.send("Where did you save it?")
        self.assertIn("Verified save", self.window.transcript.toPlainText())

    def test_truncated_or_stopped_draft_cannot_write(self):
        self.server.finish_reason = "length"
        self.send("Create a complete, interactive HTML surprise page")
        self.wait_for(lambda: self.window.job is None)
        self.assertIn("output limit", self.window.transcript.toPlainText())
        self.assertFalse(amy.PROJECTS_ROOT.exists())

        self.server.finish_reason = "stop"
        self.server.stall = True
        self.send("Create a complete, interactive HTML surprise page")
        self.wait_for(lambda: len(self.server.requests) == 2)
        self.window.stop_current()
        self.wait_for(lambda: self.window.job is None, seconds=2)
        self.assertIn("Draft canceled", self.window.transcript.toPlainText())
        self.assertFalse(amy.PROJECTS_ROOT.exists())

    def test_stale_preview_cannot_overwrite_a_new_file(self):
        def collision(_):
            amy.PROJECTS_ROOT.mkdir()
            (amy.PROJECTS_ROOT / "surprise.html").write_text("An external edit.")
            return 1
        with patch.object(app.DraftDialog, "exec", collision):
            self.send("Create a complete, interactive HTML surprise page")
            self.wait_for(lambda: self.window.job is None)
        self.assertEqual((amy.PROJECTS_ROOT / "surprise.html").read_text(), "An external edit.")
        self.assertNotIn("Saved and verified", self.window.transcript.toPlainText())

    def test_saved_notes_and_media_delete_only_after_approval(self):
        desktop.save_notes(desktop.load_notes(), ["Keep this", "Remove this"])
        self.window.open_page(1)
        self.assertEqual(self.window.memory.notes.count(), 2)
        self.window.memory.notes.setCurrentRow(1)
        with patch.object(self.window, "confirm", return_value=False):
            self.window.delete_notes()
        self.assertEqual(desktop.load_notes().lines, ("Keep this", "Remove this"))
        with patch.object(self.window, "confirm", return_value=True):
            self.window.delete_notes()
        self.assertEqual(desktop.load_notes().lines, ("Keep this",))

        directory = self.home / "AMY/screenshots"
        directory.mkdir(parents=True)
        image_path = directory / "saved.png"
        image = QImage(12, 10, QImage.Format.Format_RGB32)
        image.fill(0xFF44DDCC)
        self.assertTrue(image.save(str(image_path)))
        (directory / "link.png").symlink_to(image_path)
        self.window.open_page(2)
        self.assertEqual(self.window.media.items.topLevelItemCount(), 1)
        self.window.media.items.setCurrentItem(self.window.media.items.topLevelItem(0))
        self.assertEqual(self.window.media.path.text(), str(image_path))
        self.assertTrue(self.window.media.preview.isVisible())
        with patch.object(self.window, "confirm", return_value=False):
            self.window.delete_media()
        self.assertTrue(image_path.is_file())
        with patch.object(self.window, "confirm", return_value=True):
            self.window.delete_media()
        self.assertFalse(image_path.exists())
        self.assertEqual(self.window.media.items.topLevelItemCount(), 0)

    def test_local_small_talk_and_voice_noise_do_not_search(self):
        self.send("Hello, what are you doing?")
        self.send("What time is it now?")
        self.assertIn("ready to help", self.window.transcript.toPlainText())
        self.assertIn("Asia/Taipei", self.window.transcript.toPlainText())
        self.assertFalse(self.server.requests)
        self.window.preferences = desktop.Preferences(speak=False)
        heard = []

        def fake_listen(language, *, cancel, progress):
            heard.append(language)
            if len(heard) < 3:
                return ("[wind blowing] [wind blowing]", "What time is it now?")[len(heard) - 1]
            cancel.event.wait(4)
            cancel.check()
            return ""

        with patch.object(amy, "listen", side_effect=fake_listen):
            self.window.toggle_voice()
            self.wait_for(lambda: len(heard) >= 3)
            self.window.stop_current()
            self.wait_for(lambda: self.window.job is None)
        self.assertEqual(heard[:3], ["en", "en", "en"])
        self.assertNotIn("wind blowing", self.window.transcript.toPlainText())
        self.assertFalse(self.server.requests)

    def test_english_only_speech_assets_and_scan_frame_cache(self):
        self.assertIn("voices/af_sol.pt", amy.speech_assets(("en",)))
        self.assertNotIn("voices/zf_090.pt", amy.speech_assets(("en",)))
        self.assertIn("voices/zf_090.pt", amy.speech_assets(("en", "zh")))
        self.assertEqual(desktop.validate_region("-1920,15 200x100"), "-1920,15 200x100")
        token = desktop.Cancellation()
        with patch.object(desktop, "capture_region", return_value=b"same frame"), \
                patch.object(amy, "screen_ocr_tool", return_value=("tesseract", "eng+chi_tra")), \
                patch.object(amy, "read_screen_text", return_value="Hello.") as ocr:
            frame = desktop.scan_frame("0,0 200x100", None, "en", token)
            self.assertIs(frame, desktop.scan_frame("0,0 200x100", frame, "en", token))
            ocr.assert_called_once_with(b"same frame", ("tesseract", "eng"))

    def test_live_translation_is_reused_after_visual_only_change(self):
        self.window.scan.set_languages({"eng": "English", "jpn": "Japanese"})
        self.window.scan_languages_checked = True
        self.window.scan_region = "0,0 200x100"
        self.window.scan.enable_area(True)
        self.window.scan.source.setCurrentIndex(self.window.scan.source.findData("jpn"))
        self.window.scan.target.setCurrentIndex(self.window.scan.target.findData("Indonesian"))
        self.window.open_scan()
        self.window.scan_live = True
        first = desktop.ScanFrame(b"first", "Hello.", self.image_bytes(0xFF234567))
        second = desktop.ScanFrame(b"second", "Hello.", self.image_bytes(0xFF856798))
        frames = iter((first, second))

        def frame(*_, on_image):
            current = next(frames)
            on_image(current.image)
            return current

        self.server.stall = True
        with patch.object(desktop, "scan_frame", side_effect=frame):
            self.window.scan_tick()
            self.wait_for(lambda: len(self.server.requests) == 1)
            self.assertIsNotNone(self.window.job)
            self.window.scan_tick()
            self.wait_for(lambda: self.window.capture_token is None and self.window.scan_frame == second)
            self.assertIsNotNone(self.window.job)
            self.server.release.set()
            self.wait_for(lambda: self.window.job is None)
        self.assertEqual(self.window.scan_frame, second)
        self.assertEqual(len(self.server.requests), 1)
        self.assertEqual(self.window.scan.preview_image.toImage().pixel(0, 0), 0xFF856798)
        self.assertIn("Indonesian", self.server.requests[0]["messages"][0]["content"])
        self.assertIn("Translated to Indonesian", self.window.scan.status.text())
        self.window.scan.close()

    def test_saved_chats_keep_attachments_and_context_separate(self):
        original = self.window.normal_chat
        document = self.home / "meeting-notes.md"
        document.write_text("Notes\nThe workshop starts in April.\n")
        self.window.add_attachments([str(document)])
        self.assertEqual(len(self.window.queued_attachments), 1)
        self.send("Summarize the notes")
        self.wait_for(lambda: self.window.job is None)
        content = self.server.requests[-1]["messages"][-1]["content"]
        self.assertIn("meeting-notes.md", content)
        self.assertIn("lines 1", content)
        self.assertIn("April", content)
        self.send("When does it start?")
        self.wait_for(lambda: self.window.job is None)
        self.assertIn("April", self.server.requests[-1]["messages"][-1]["content"])
        self.window.new_chat()
        self.send("Explain why rain falls.")
        self.wait_for(lambda: self.window.job is None)
        self.assertNotIn("April", json.dumps(self.server.requests[-1]))
        self.assertNotIn("meeting-notes.md", self.window.transcript.toPlainText())
        saved = ChatStore()
        saved.load()
        self.assertEqual(len(saved.chats), 2)
        self.assertEqual(saved.chats[original.id].title, "Summarize the notes")
        self.assertIn("meeting-notes.md", str(saved.chats[original.id].recent_attachments()))
        self.assertEqual(saved.active, self.window.normal_chat.id)
        self.assertEqual(self.server.metadata.count("/api/show"), 1)
        self.assertEqual(self.window.reply_timing["tokens/s"], 20.0)

    def test_images_and_pdf_are_read_locally(self):
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

        pdf = self.home / "notes.pdf"
        writer = PdfWriter()
        page = writer.add_blank_page(width=260, height=180)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                                 NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        content = DecodedStreamObject()
        content.set_data(b"BT /F1 12 Tf 20 90 Td (AMY PDF note) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(content)
        writer.write(pdf)
        photo = self.home / "photo.png"
        photo.write_bytes(self.image_bytes(0xFF224466))
        self.window.add_attachments([str(pdf), str(photo)])
        self.send("Read these attachments")
        self.wait_for(lambda: self.window.job is None)
        request = self.server.requests[-1]["messages"][-1]
        self.assertIn("notes.pdf", request["content"])
        self.assertIn("page 1", request["content"])
        self.assertIn("AMY PDF note", request["content"])
        self.assertEqual(len(request["images"]), 1)
        self.assertGreater(len(request["images"][0]), 30)
        self.assertTrue((self.home / "AMY/dump/temp").is_dir())

    def test_choice_cards_allow_a_followup_without_submitting(self):
        self.server.answer = "There are two ways.\n" + CHOICE_TAG + json.dumps(OPTIONS[:2])
        self.send("Give me two choices.")
        self.wait_for(lambda: self.window.choice_card is not None)
        card = self.window.choice_card
        self.assertEqual(len(card.group.buttons()), 2)
        self.assertFalse(card.submit.isEnabled())
        self.assertNotIn(CHOICE_TAG, self.window.transcript.toPlainText())
        self.assertTrue(self.window.composer.isEnabled())
        self.server.answer = "Let's look at the existing table."
        self.send("Can we use the existing users table?")
        self.wait_for(lambda: self.window.job is None)
        self.assertIsNone(self.window.choice_card)
        self.assertIn("existing table", self.window.transcript.toPlainText())
        self.assertFalse(any(control.isEnabled() for control in card.group.buttons()))

    def test_coding_requires_choices_and_checks_the_authorized_folder(self):
        project = self.home / "Work" / "project"
        project.mkdir(parents=True)
        source = project / "app.py"
        source.write_text("print('old')\n")
        outside = project.parent / "private.txt"
        outside.write_text("outside the project")
        (project / "outside.txt").symlink_to(outside)
        self.window.authorize_workspace(project)
        self.server.options = OPTIONS[:2]
        self.send("Add authentication")
        self.wait_for(lambda: self.window.job is None)
        self.assertIsNone(self.window.choice_card)
        self.assertIn("complete set of coding options", self.window.transcript.toPlainText())
        self.server.options = OPTIONS
        self.send("Add authentication")
        self.wait_for(lambda: self.window.choice_card is not None)
        card = self.window.choice_card
        self.assertEqual(len(card.group.buttons()), 3)
        self.assertEqual(source.read_text(), "print('old')\n")
        self.assertNotIn("outside.txt", self.window.workspace.files)
        self.server.options = []
        self.send("Can we use the existing users table?")
        self.wait_for(lambda: self.window.job is None)
        self.assertIsNone(self.window.choice_card)
        self.assertFalse(any(control.isEnabled() for control in card.group.buttons()))
        self.assertEqual(source.read_text(), "print('old')\n")
        self.server.options = OPTIONS
        self.send("Add authentication using the existing users table")
        self.wait_for(lambda: self.window.choice_card is not None)
        card = self.window.choice_card
        self.server.draft = {"files": [{"path": "app.py", "edits": [
            {"before": "print('old')", "after": "print('reviewed')"},
        ]}]}
        with patch.object(app.DraftDialog, "exec", return_value=1):
            card.group.button(0).setChecked(True)
            card.submit.click()
            self.wait_for(lambda: self.window.job is None)
        self.assertEqual(source.read_text(), "print('reviewed')\n")
        self.assertEqual(outside.read_text(), "outside the project")
        self.assertTrue(self.window.last_report.is_file())
        restored = files.Workspace.authorize(project)
        restored.load_index()
        self.assertIn("Email and password", restored.edits[0])

    def test_workspace_cache_checks_external_changes_and_reuses_unchanged_text(self):
        project = self.home / "other-project"
        project.mkdir()
        source = project / "main.py"
        source.write_text("value = 1\n")
        workspace = files.Workspace.authorize(project)
        token = desktop.Cancellation()
        with patch.object(amy, "project_snapshot", wraps=amy.project_snapshot) as read:
            workspace.refresh(token)
            self.assertEqual(workspace.relevant("Check main.py", token)[0][("main.py",)][0], b"value = 1\n")
            workspace.refresh(token)
            workspace.relevant("Check main.py", token)
            self.assertEqual(read.call_count, 1)
            source.write_text("value = 22\n")
            workspace.refresh(token)
            self.assertEqual(workspace.relevant("Check main.py", token)[0][("main.py",)][0], b"value = 22\n")
            self.assertEqual(read.call_count, 2)

    def test_short_simple_listed_style_is_sent_with_think_disabled(self):
        style = "Short, Simple, and Listed"
        self.window.save_settings(replace(self.window.preferences, style=style))
        self.send("Explain Python lists.")
        self.wait_for(lambda: self.window.job is None)
        request = self.server.requests[-1]
        self.assertFalse(request["think"])
        self.assertIn("use bullets (•) for key points", request["messages"][0]["content"])
        self.assertIn("short paragraphs", request["messages"][0]["content"])
        self.assertEqual(desktop.load_preferences().style, style)

    def test_legacy_image_command_stays_local(self):
        metadata = list(self.server.metadata)
        self.send("/IMAGE A violet mountain")
        self.assertIn("Image generation is unavailable", self.window.transcript.toPlainText())
        self.assertIsNone(self.window.job)
        self.assertEqual(self.server.requests, [])
        self.assertEqual(self.server.metadata, metadata)
        self.assertNotIn("Create image", {item.text() for item in self.window.findChildren(QPushButton)})

    def test_previously_saved_images_reopen_in_chat(self):
        saved = self.home / "AMY/dump/generated-image.png"
        saved.parent.mkdir(parents=True)
        data = self.image_bytes(0xFF8844CC)
        saved.write_bytes(data)
        self.window.message("AMY", "Generated with a previous version.")
        self.window.normal_chat.messages[-1]["image_file"] = files.Attachment.select(saved).record()
        self.window.save_chats()

        restored = app.AMYWindow(self.server.server_port, desktop.Preferences(), self.app.font(), load_models=False)
        self.addCleanup(restored.close)
        preview, = [item for item in restored.transcript.findChildren(QLabel)
                    if item.accessibleName() == "Saved image"]
        self.assertFalse(preview.pixmap().isNull())
        self.assertEqual(saved.read_bytes(), data)

    def test_search_preview_and_opt_in_automatic_search(self):
        evidence = {"direct_answers": {"en": "It is 20 degrees in Taipei."}, "sources": [{
            "id": 1, "title": "Weather provider", "url": "https://api.open-meteo.com/", "status": "fixture",
        }]}
        with patch.object(amy, "collect_web_evidence", return_value=evidence) as web:
            with patch.object(self.window, "confirm", return_value=False):
                self.send("What is the weather in Taipei?")
            web.assert_not_called()
            self.window.save_settings(replace(self.window.preferences, auto_web=True))
            with patch.object(self.window, "confirm", return_value=False) as confirmation:
                self.send("What is the weather in Taipei?")
                self.wait_for(lambda: self.window.job is None)
            confirmation.assert_not_called()
            self.assertIn("It is 20 degrees", self.window.transcript.toPlainText())
            self.assertFalse(self.server.requests)
            with patch.object(self.window, "confirm", return_value=False) as confirmation:
                self.window.request_web("Look up a product name", from_screen=True)
            confirmation.assert_called_once()
            web.assert_called_once()

    def test_training_lesson_and_note_need_review(self):
        import amy_training
        self.send("Remember that I prefer examples.")
        self.assertEqual(desktop.load_notes().lines, ())
        self.assertIn(("Note", "I prefer examples.", "", "en"), self.window.suggestions)
        self.send("How much is an apple?")
        self.wait_for(lambda: self.window.job is None)
        self.send("Correction: Ask which currency and whether I want the current price.")
        self.window.open_page(1)
        self.window.memory.suggestions.setCurrentRow(1)
        dataset = self.home / "AMY/train/approved-examples.json"
        with patch.object(amy_training, "APP_DATA", self.data), patch.object(amy_training, "check_space"), \
                patch.object(self.window, "confirm", return_value=False):
            self.window.review_suggestion()
        self.assertFalse(dataset.exists())
        with patch.object(amy_training, "APP_DATA", self.data), patch.object(amy_training, "check_space"), \
                patch.object(self.window, "confirm", return_value=True):
            self.window.review_suggestion()
        self.assertIn("Ask which currency", dataset.read_text())
