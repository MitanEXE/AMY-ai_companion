#!/usr/bin/env python3
"""AMY's Linux desktop companion."""

import argparse
import os
import sys
import threading
from collections import deque
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from time import monotonic

from PySide6.QtCore import QObject, QSize, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontDatabase, QImageReader, QPalette, QPixmap, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QInputDialog, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QStackedWidget, QTextBrowser, QTextEdit, QTreeWidgetItem, QVBoxLayout, QWidget,
)

import amy_desktop_core as desktop
import mitan_jarvis as amy
from amy_desktop_views import DraftDialog, MediaView, MemoryView, ScanPanel, SettingsView, button, label, row

GUIDE = Path(__file__).resolve().parent / "docs" / "LINUX_DESKTOP.md"
IDLE = "Ready"
DARK = dict(base="#11151b", nav="#171d26", surface="#1b222d", border="#344253", text="#edf2fa",
            muted="#a5b1c3", accent="#74dec0", on_accent="#10251f", hover="#263548", danger="#ffacaa")
LIGHT = dict(base="#f5f7fa", nav="#e9eef5", surface="#ffffff", border="#c5d1df", text="#172637",
             muted="#53667c", accent="#167358", on_accent="#ffffff", hover="#dce8f3", danger="#a72f2f")


def apply_theme(application, preferences, default_font):
    colors = DARK if preferences.theme == "Dark" else LIGHT
    font = QFont(preferences.font) if preferences.font else QFont(default_font)
    font.setPointSize(preferences.size)
    application.setFont(font)
    palette = QPalette()
    for role, key in ((QPalette.ColorRole.Window, "base"), (QPalette.ColorRole.Base, "surface"),
                      (QPalette.ColorRole.WindowText, "text"), (QPalette.ColorRole.Text, "text"),
                      (QPalette.ColorRole.Button, "surface"), (QPalette.ColorRole.ButtonText, "text"),
                      (QPalette.ColorRole.Highlight, "accent"), (QPalette.ColorRole.HighlightedText, "on_accent")):
        palette.setColor(role, QColor(colors[key]))
    application.setPalette(palette)
    application.setStyleSheet("""
        QWidget { color: %(text)s; }
        QMainWindow, QDialog { background: %(base)s; }
        QLabel#brand { font-size: 23pt; font-weight: 750; color: %(accent)s; }
        QLabel#pageTitle { font-size: 20pt; font-weight: 700; }
        QLabel#section { font-weight: 700; }
        QLabel#muted { color: %(muted)s; }
        QFrame#nav { background: %(nav)s; border-right: 1px solid %(border)s; }
        QFrame#card { background: %(surface)s; border: 1px solid %(border)s; border-radius: 10px; }
        QPushButton, QComboBox, QSpinBox, QLineEdit {
            background: %(surface)s; border: 1px solid %(border)s; border-radius: 7px; padding: 7px 10px;
        }
        QPushButton:hover { background: %(hover)s; }
        QPushButton:focus, QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus { border-color: %(accent)s; }
        QPushButton:disabled { color: %(muted)s; }
        QPushButton#navButton { text-align: left; border: 1px solid transparent; background: transparent; padding: 11px; }
        QPushButton#navButton:checked, QPushButton#navButton:hover { background: %(hover)s; }
        QPushButton#primary { background: %(accent)s; color: %(on_accent)s; font-weight: 700; }
        QPushButton#primary:disabled { background: %(surface)s; color: %(muted)s; }
        QPushButton#danger:enabled { color: %(danger)s; }
        QTextEdit, QPlainTextEdit, QListWidget, QTreeWidget {
            background: %(surface)s; border: 1px solid %(border)s; border-radius: 10px; padding: 7px;
        }
        QHeaderView::section { background: %(nav)s; color: %(muted)s; padding: 6px; border: 0; }
        QListWidget::item, QTreeWidget::item { padding: 7px 4px; }
        QTabWidget::pane { border: 1px solid %(border)s; border-radius: 8px; }
        QTabBar::tab { padding: 9px 13px; background: %(surface)s; }
        QTabBar::tab:selected { color: %(accent)s; border-bottom: 2px solid %(accent)s; }
        QProgressBar { border: 0; background: %(border)s; border-radius: 2px; max-height: 4px; }
        QProgressBar::chunk { background: %(accent)s; border-radius: 2px; }
    """ % colors)
    return colors


class JobSignals(QObject):
    status = Signal(str)
    chunk = Signal(str)
    done = Signal(object, object)


class Composer(QPlainTextEdit):
    send = Signal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            self.send.emit()
            return
        super().keyPressEvent(event)


class AMYWindow(QMainWindow):
    def __init__(self, port, preferences, default_font, *, preference_error="", load_models=True):
        super().__init__()
        self.setWindowTitle("AMY")
        self.resize(1100, 750)
        self.setMinimumSize(725, 560)
        self.ollama = desktop.LocalOllama(port)
        self.preferences = preferences
        self.default_font = default_font
        self.colors = apply_theme(QApplication.instance(), preferences, default_font)
        self.history = deque(maxlen=8)
        self.project = ()
        self.models = {}
        self.models_loaded = False
        self.job = None
        self.job_can_stop = False
        self.job_done = None
        self.job_kind = ""
        self.job_started = 0
        self.status_text = IDLE
        self.last_report = None
        self.last_question = ""
        self.pending_verification = ""
        self.verification_deadline = 0
        self.pending_weather = ""
        self.voice_on = False
        self.voice_session = None
        self.suggestions = []
        self.scan_region = ""
        self.scan_frame = None
        self.scan_result_key = None
        self.scan_live = False
        self.closing = False
        self.streaming = False

        central = QWidget()
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setCentralWidget(central)
        navigation = QFrame()
        navigation.setObjectName("nav")
        navigation.setFixedWidth(174)
        nav = QVBoxLayout(navigation)
        nav.setContentsMargins(14, 20, 14, 16)
        nav.setSpacing(9)
        nav.addWidget(label("AMY", "brand"))
        nav.addWidget(label("Local companion", "muted"))
        nav.addSpacing(18)
        self.pages = QStackedWidget()
        self.nav_group = QButtonGroup(self)
        self.nav_buttons = []
        for index, name in enumerate(("Chat", "Memory", "Saved media", "Settings")):
            item = button(name, lambda checked=False, i=index: self.open_page(i), "navButton")
            item.setCheckable(True)
            self.nav_group.addButton(item, index)
            self.nav_buttons.append(item)
            nav.addWidget(item)
        nav.addWidget(button("Screen tools", self.open_scan, "navButton"))
        nav.addStretch()
        nav.addWidget(button("Setup guide", self.show_guide, "navButton"))
        outer.addWidget(navigation)

        content = QWidget()
        self.content = QVBoxLayout(content)
        self.content.setContentsMargins(24, 20, 24, 18)
        self.content.setSpacing(13)
        header = QHBoxLayout()
        self.title = label("Chat", "pageTitle")
        header.addWidget(self.title, 1)
        self.model_label = button("", self.open_models)
        self.model_label.setToolTip("Choose a downloaded Ollama model")
        header.addWidget(self.model_label)
        self.content.addLayout(header)
        self.content.addWidget(self.pages, 1)
        self.build_chat()
        self.memory = MemoryView()
        self.media = MediaView()
        self.settings = SettingsView()
        self.scan = ScanPanel(self)
        self.scan.configure_languages(preferences.chinese)
        for view in (self.memory, self.media, self.settings):
            self.pages.addWidget(view)
        self.bind_views()
        self.settings.load(preferences)
        self.update_model_label()

        footer = QHBoxLayout()
        self.status_label = label(IDLE, "muted")
        footer.addWidget(self.status_label, 1)
        self.stop = button("Stop", self.stop_current)
        self.stop.hide()
        footer.addWidget(self.stop)
        self.content.addLayout(footer)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        self.bar.hide()
        self.content.addWidget(self.bar)
        outer.addWidget(content, 1)

        self.clock = QTimer(self, interval=1000)
        self.clock.timeout.connect(self.update_status)
        self.clock.start()
        self.scan_clock = QTimer(self, interval=850)
        self.scan_clock.timeout.connect(self.scan_tick)
        self.open_page(0)
        if preference_error:
            self.message("AMY", f"Desktop settings could not be read. {preference_error}")
        if load_models:
            QTimer.singleShot(0, self.refresh_models)

    def build_chat(self):
        chat = QWidget()
        layout = QVBoxLayout(chat)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setAcceptRichText(False)
        self.transcript.document().setDocumentMargin(17)
        layout.addWidget(self.transcript, 1)
        self.message("AMY", "Ask a question, or try “Create a complete, interactive HTML surprise page.”")
        self.result = QFrame()
        self.result.setObjectName("card")
        result = QVBoxLayout(self.result)
        result.setContentsMargins(10, 8, 10, 8)
        self.saved_path = QComboBox()
        self.saved_path.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.saved_path.setMinimumContentsLength(35)
        result.addWidget(self.saved_path)
        self.view_report = button("View change report", self.open_report)
        result.addLayout(row(button("Open file", self.open_saved), button("Open folder", self.open_saved_folder),
                             self.view_report))
        self.result.hide()
        layout.addWidget(self.result)
        self.verify = button("Check online", self.verify_online)
        self.verify.hide()
        layout.addLayout(row(self.verify))
        self.composer = Composer()
        self.composer.setPlaceholderText("Message AMY")
        self.composer.setFixedHeight(76)
        self.composer.send.connect(self.send_message)
        layout.addWidget(self.composer)
        controls = QHBoxLayout()
        self.voice = button("Voice on", self.toggle_voice)
        self.think = QCheckBox("Think")
        self.think.setToolTip("Ask the selected local model to think more before it replies.")
        controls.addWidget(self.voice)
        controls.addWidget(self.think)
        controls.addStretch()
        self.send = button("Send", self.send_message, "primary")
        controls.addWidget(self.send)
        layout.addLayout(controls)
        self.pages.addWidget(chat)

    def bind_views(self):
        self.settings.refresh_models.connect(self.refresh_models)
        self.settings.pick_model.connect(self.pick_model)
        self.settings.save.connect(self.save_settings)
        self.settings.setup_guide.connect(self.show_guide)
        self.memory.refresh.clicked.connect(self.refresh_memory)
        self.memory.add_note.clicked.connect(self.add_note)
        self.memory.delete_notes.clicked.connect(self.delete_notes)
        self.memory.delete_profile.clicked.connect(self.delete_profile)
        self.memory.review.clicked.connect(self.review_suggestion)
        self.memory.dismiss.clicked.connect(self.dismiss_suggestion)
        self.media.refresh.clicked.connect(self.refresh_media)
        self.media.filter.currentIndexChanged.connect(self.refresh_media)
        self.media.items.itemSelectionChanged.connect(self.update_media_selection)
        self.media.open.clicked.connect(self.open_media)
        self.media.folder.clicked.connect(self.open_media_folder)
        self.media.delete.clicked.connect(self.delete_media)
        self.scan.select.clicked.connect(self.select_scan_area)
        self.scan.live.clicked.connect(self.toggle_scan)
        self.scan.identify.clicked.connect(self.identify_scan)
        self.scan.search.clicked.connect(self.search_scan)
        self.scan.save.clicked.connect(self.save_scan)
        self.scan.direction.currentIndexChanged.connect(self.reset_scan)
        self.scan.closed.connect(self.pause_scan)

    def open_page(self, index):
        self.nav_buttons[index].setChecked(True)
        self.pages.setCurrentIndex(index)
        self.title.setText(self.nav_buttons[index].text())
        if index == 1:
            self.refresh_memory()
        elif index == 2:
            self.refresh_media()

    def open_models(self):
        self.open_page(3)
        self.settings.tabs.setCurrentIndex(1)

    def message(self, role, text=""):
        cursor = self.transcript.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if not self.transcript.document().isEmpty():
            cursor.insertText("\n\n")
        heading = QTextCharFormat()
        heading.setFontWeight(QFont.Weight.Bold)
        cursor.insertText(role + "\n", heading)
        if text:
            cursor.insertText(text, QTextCharFormat())
        self.transcript.setTextCursor(cursor)
        self.transcript.ensureCursorVisible()

    @Slot(str)
    def append_chunk(self, text):
        if not self.streaming:
            self.message("AMY")
            self.streaming = True
        cursor = self.transcript.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text, QTextCharFormat())
        self.transcript.setTextCursor(cursor)
        self.transcript.ensureCursorVisible()

    @Slot(str)
    def set_status(self, text):
        self.status_text = text
        self.update_status()
        if self.job_kind.startswith("scan"):
            self.scan.status.setText(text)

    def update_status(self):
        elapsed = f"   {int(monotonic() - self.job_started)}s" if self.job is not None else ""
        self.status_label.setText(self.status_text + elapsed)

    def start_job(self, kind, work, on_success, *, can_stop=True, initial="Working…"):
        if self.job is not None or self.closing:
            return False
        token = desktop.Cancellation()
        self.job = token
        self.job_done = on_success
        self.job_kind = kind
        self.job_can_stop = can_stop
        self.job_started = monotonic()
        self.streaming = False
        self.set_status(initial)
        self.bar.show()
        self.stop.setVisible(can_stop)
        self.stop.setEnabled(can_stop)
        self.send.setEnabled(False)
        self.settings.refresh_button.setEnabled(False)
        self.settings.model_scroll.setEnabled(False)
        self.settings.save_button.setEnabled(False)
        self.memory.setEnabled(False)
        self.media.setEnabled(False)
        signals = JobSignals(self)
        signals.status.connect(self.set_status, Qt.ConnectionType.QueuedConnection)
        signals.chunk.connect(self.append_chunk, Qt.ConnectionType.QueuedConnection)
        signals.done.connect(self.finish_job, Qt.ConnectionType.QueuedConnection)
        self.job_signals = signals

        def run():
            result = error = None
            try:
                result = work(token, signals.status.emit, signals.chunk.emit)
                token.check()
            except Exception as caught:
                error = desktop.Cancelled() if token.event.is_set() else caught
            signals.done.emit(result, error)

        threading.Thread(target=run, name="amy-" + kind, daemon=True).start()
        return True

    @Slot(object, object)
    def finish_job(self, result, error):
        kind, done = self.job_kind, self.job_done
        self.job = self.job_done = None
        self.job_kind = ""
        self.job_signals.deleteLater()
        self.bar.hide()
        self.stop.hide()
        self.send.setEnabled(True)
        self.settings.refresh_button.setEnabled(True)
        self.settings.model_scroll.setEnabled(True)
        self.settings.save_button.setEnabled(True)
        self.memory.setEnabled(True)
        self.media.setEnabled(True)
        if self.closing:
            QTimer.singleShot(0, self.close)
            return
        if isinstance(error, desktop.Cancelled):
            if not self.voice_on:
                self.close_voice()
            self.set_status("Stopped.")
            if kind.startswith("scan"):
                if kind == "scan selection":
                    self.open_scan()
                self.scan.status.setText("Stopped.")
            if kind == "draft":
                self.message("AMY", "Draft canceled. No files were saved.")
        elif error is not None:
            self.voice_on = False
            self.voice.setText("Voice on")
            self.close_voice()
            if kind.startswith("scan"):
                self.pause_scan()
                if kind == "scan selection":
                    self.open_scan()
                self.scan.status.setText(str(error))
            elif kind == "models":
                self.settings.model_status.setText(str(error))
            else:
                self.message("AMY", str(error) or type(error).__name__)
            self.set_status("Check the message to continue.")
        else:
            self.set_status(IDLE)
            try:
                done(result)
            except (OSError, RuntimeError, ValueError) as caught:
                self.report_error(caught)
        self.continue_voice()

    def stop_current(self):
        self.voice_on = False
        self.voice.setText("Voice on")
        self.pause_scan()
        if self.job is not None and self.job_can_stop:
            self.job.stop()
            self.stop.setEnabled(False)
            self.set_status("Stopping…")
        elif self.job is None:
            self.close_voice()

    def confirm(self, title, text, approve):
        dialog = QMessageBox(self)
        dialog.setWindowTitle(title)
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(text)
        accept = dialog.addButton(approve, QMessageBox.ButtonRole.AcceptRole)
        cancel = dialog.addButton(QMessageBox.StandardButton.Cancel)
        dialog.setDefaultButton(cancel)
        dialog.exec()
        return dialog.clickedButton() is accept

    def report_error(self, error):
        dialog = QMessageBox(QMessageBox.Icon.Warning, "AMY", str(error) or type(error).__name__, parent=self)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.exec()

    def show_guide(self):
        try:
            instructions = GUIDE.read_text(encoding="utf-8")
        except OSError as error:
            self.report_error(error)
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("AMY setup guide")
        dialog.resize(830, 645)
        layout = QVBoxLayout(dialog)
        guide = QTextBrowser()
        guide.setOpenLinks(False)
        guide.setMarkdown(instructions)
        layout.addWidget(guide)
        layout.addLayout(row(button("Close", dialog.accept)))
        dialog.exec()

    def update_model_label(self):
        self.model_label.setText(self.preferences.model or "Choose model")

    def refresh_models(self):
        self.start_job("models", lambda token, status, _: self.ollama.models(token, status), self.show_models,
                       initial="Checking downloaded models…")

    def show_models(self, models):
        self.models = models
        self.models_loaded = True
        self.settings.set_models(models, self.preferences.model, self.ollama.port)

    @Slot(str)
    def pick_model(self, name):
        if name not in self.models or self.job is not None:
            return
        try:
            preferences = replace(self.preferences, model=name)
            desktop.save_preferences(preferences)
        except (OSError, RuntimeError, ValueError) as error:
            self.show_models(self.models)
            self.report_error(error)
            return
        self.preferences = preferences
        self.settings.preferences = preferences
        self.update_model_label()
        self.history.clear()
        self.reset_scan()
        self.set_status(f"Using {name} for new messages.")

    @Slot(object)
    def save_settings(self, preferences):
        if self.job is not None:
            return
        try:
            desktop.save_preferences(preferences)
        except (OSError, RuntimeError, ValueError) as error:
            self.report_error(error)
            return
        language_changed = preferences.language != self.preferences.language
        self.preferences = preferences
        self.settings.preferences = preferences
        self.colors = apply_theme(QApplication.instance(), preferences, self.default_font)
        self.transcript.document().setDefaultFont(QApplication.font())
        self.scan.configure_languages(preferences.chinese)
        if language_changed:
            self.history.clear()
        if not preferences.web:
            self.clear_verification()
        self.set_status("Settings saved.")

    def send_message(self):
        if self.job is not None:
            return
        question = self.composer.toPlainText().strip()
        if not question:
            return
        if len(question) > 12_000:
            self.set_status("Keep a message within 12,000 characters.")
            return
        self.composer.clear()
        self.handle_message(question)

    def handle_message(self, question, *, voice=False):
        self.open_page(0)
        self.message("Heard" if voice else "You", question)
        try:
            self.route_message(question, voice)
        except (OSError, RuntimeError, ValueError) as error:
            self.message("AMY", str(error))
            self.continue_voice()

    def route_message(self, question, voice):
        previous_weather, self.pending_weather = self.pending_weather, ""
        command, _, argument = question.partition(" ")
        command = command.casefold()
        if (self.pending_verification and monotonic() < self.verification_deadline
                and amy.verification_reply(question) is True):
            self.verify_online(voice=voice)
            return
        self.clear_verification()
        if command in ("/text", "/voice") and argument.casefold() in ("off", "") and (voice or command == "/text"):
            self.stop_current()
            return
        if command == "/voice":
            if argument.casefold() != "on" or not self.voice_on:
                self.toggle_voice()
            return
        if command == "/help":
            self.deliver_local("Use Settings to pick a model, Memory to manage notes and Screen tools to scan an area. "
                               "Say “Create a complete HTML page” or use /file PATH REQUEST. "
                               "Try /screen 1, /screenshot 1, /where, /search TOPIC or /remember NOTE.", voice)
            return
        if command in ("/memories", "/forget", "/profile"):
            self.open_page(1)
            self.memory.tabs.setCurrentIndex(2 if command == "/profile" else 0)
            self.continue_voice()
            return
        note = desktop.suggest_note(question)
        if note:
            self.queue_suggestion(("Note", desktop.validate_note(note), "", self.preferences.language))
            if command == "/remember" or question.casefold().startswith(("remember ", "please remember ", "請記住")):
                self.deliver_local("I put that note in Memory → Suggestions for your review.", voice)
                return
        correction = question.partition(":")
        if correction[0].strip().casefold() in ("correction", "更正") and correction[2].strip() and self.last_question:
            answer = correction[2].strip()
            if len(self.last_question) > 2000 or len(answer) > 2000:
                raise ValueError("Keep the question and corrected answer within 2,000 characters each.")
            self.queue_suggestion(("Lesson", self.last_question, answer, self.preferences.language))
            self.deliver_local("I put the correction in Memory → Suggestions. You can review it before adding it to training.", voice)
            return
        local = (amy.local_clock_answer(question, self.preferences.language, voice=voice)
                 or amy.calculator_answer(question, self.preferences.language, voice=voice)
                 or amy.status_answer(question, self.preferences.language)
                 or amy.identity_answer(question, self.preferences.language))
        if local:
            self.deliver_local(local, voice)
            return
        request = amy.project_request(question, self.project)
        if request:
            self.project_action(*request)
            return
        screenshot = amy.screenshot_request(question)
        if screenshot:
            self.capture_screenshot(*screenshot)
            return
        screen = amy.screen_request(question)
        if screen:
            self.read_monitor(screen, voice)
            return
        if command == "/screens":
            screens = amy.connected_screens()
            self.deliver_local("\n".join(f"Screen {number} · {item['name']}" for number, item in sorted(screens.items()))
                               or "No screens were found.", voice)
            return
        query = argument if command == "/search" else amy.online_request(question)
        if previous_weather:
            location = amy.weather_location_reply(question)
            if query is None and location:
                query = previous_weather + " in " + location
        if query or command == "/search":
            self.request_web(query, voice=voice)
            return
        if command.startswith("/"):
            self.deliver_local("This command is available in the terminal version. Use /help for desktop commands.", voice)
            return
        self.reply(question, voice=voice)

    def deliver_local(self, text, voice=False):
        self.message("AMY", text)
        if voice and self.preferences.speak:
            language = self.preferences.language
            self.start_job("speech", lambda token, status, _: self.speak_text(text, language, token, status),
                           lambda _: None, initial="Preparing local audio…")
        else:
            self.continue_voice()

    def project_action(self, operation, argument):
        if operation == "where":
            reported, entries = amy.find_project_files(argument)
            if entries:
                lines = [("Verified save" if reported else "Matching file") + f" · {path}" if exists
                         else f"Missing · {path}" for path, exists in entries]
                self.message("AMY", "\n".join(lines))
                verified = tuple(path for path, exists in entries if exists)
                if verified:
                    self.show_saved(verified)
            else:
                self.message("AMY", f"I couldn't verify a save under {amy.PROJECTS_ROOT}.")
            self.continue_voice()
            return
        if operation in ("projects", "project"):
            if operation == "projects":
                try:
                    with amy.home_directory(("Projects",)) as directory:
                        names = sorted(name for name in os.listdir(directory)
                                       if amy.PROJECT_COMPONENT.fullmatch(name) and not name.startswith(".")
                                       and name.casefold() not in amy.PROJECT_PRIVATE
                                       and self.is_project(name))
                except FileNotFoundError:
                    names = []
                self.message("AMY", "\n".join(names) if names else "There are no project folders under ~/Projects/ yet.")
            else:
                self.project = amy.select_project(argument, self.project)
                self.message("AMY", "Current project folder\n" + str(amy.PROJECTS_ROOT.joinpath(*self.project)))
            self.continue_voice()
            return
        if operation == "laravel":
            self.message("AMY", "Use /laravel NAME in AMY's terminal version to review the Composer setup. "
                         "This window can draft and review changes to your project files.")
            self.continue_voice()
            return
        scope, target, instruction, mode, options = amy.project_edit_arguments(operation, argument, self.project)
        model = self.preferences.model

        def work(token, status, _):
            self.ollama.require_model(model, token, status)
            return amy.prepare_project_edit(self.ollama.port, model, scope, target, instruction, mode,
                                            cancel=token, progress=status, **options)

        self.start_job("draft", work, self.review_draft, initial="Checking project paths and local model…")

    @staticmethod
    def is_project(name):
        try:
            with amy.home_directory(("Projects", name)):
                return True
        except OSError:
            return False

    def review_draft(self, draft):
        if draft is None:
            self.message("AMY", "I couldn't draft a concrete change. Give me a filename and what you'd like in it.")
            return
        self.set_status("Draft ready for review.")
        dialog = DraftDialog(draft, self)
        if not dialog.exec():
            self.message("AMY", "Canceled. No files were saved.")
            self.set_status("Canceled.")
            return
        self.start_job("save", lambda *_: draft.apply(), lambda _: self.report_saved(draft),
                       can_stop=False, initial="Saving and reading back the approved files…")

    def report_saved(self, draft):
        self.show_saved(draft.paths, draft.report)
        self.message("AMY", "Saved and verified\n" + "\n".join(str(path) for path in draft.paths)
                     + "\n\nChange report\n" + str(draft.report))
        self.set_status("Verified on disk.")
        if any(change.old is None for change in draft.changes):
            self.queue_suggestion((
                "Lesson", "How do you confirm that a project file was created?",
                "I review the draft with you before writing it. I read the approved file back after saving, "
                "then show its full path and the change report.", "en",
            ))

    def show_saved(self, paths, report=None):
        self.last_report = report
        self.saved_path.clear()
        for path in paths:
            self.saved_path.addItem(str(path), path)
        self.view_report.setVisible(report is not None)
        self.result.show()

    def check_saved_path(self):
        path = self.saved_path.currentData()
        if path is None:
            return None
        parts = path.relative_to(amy.PROJECTS_ROOT).parts
        with amy.home_directory(("Projects",)) as directory:
            if not amy.project_file_exists(directory, parts):
                raise RuntimeError("The verified file is missing now. Refresh with /where.")
        return path

    def open_saved(self):
        try:
            path = self.check_saved_path()
            if path is not None:
                self.open_path(path)
        except (OSError, RuntimeError, ValueError) as error:
            self.report_error(error)

    def open_saved_folder(self):
        try:
            path = self.check_saved_path()
            if path is not None:
                self.open_path(path.parent)
        except (OSError, RuntimeError, ValueError) as error:
            self.report_error(error)

    def open_report(self):
        try:
            reports = [item for item in desktop.list_saved_items() if item.path == self.last_report]
            if not reports:
                raise RuntimeError("The change report is no longer available.")
            self.open_path(desktop.verify_item(reports[0]))
        except (OSError, RuntimeError, ValueError) as error:
            self.report_error(error)

    @staticmethod
    def open_path(path):
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            raise RuntimeError(f"Your desktop couldn't open {path}.")

    def reply(self, question, *, voice=False, query="", screen_request=None):
        preferences = self.preferences
        history = list(self.history)
        think = self.think.isChecked()

        def work(token, status, chunk):
            model = preferences.model
            language = preferences.language
            evidence = None
            image = text = None
            answer_prompt = question
            if query:
                evidence = amy.collect_web_evidence(query, cancel=token, approved=True, progress=status)
                direct = evidence.get("direct_answers", {}).get(language)
                if direct:
                    answer = direct
                    if evidence.get("followup") == "weather_city":
                        answer += " 請用「在台北，台灣」這樣的格式回覆。" if language == "zh" else " Reply with “in Taipei, Taiwan”, for example."
                    chunk(answer)
                    warning = ""
                    if voice and preferences.speak:
                        try:
                            self.speak_text(evidence.get("spoken_answers", {}).get(language, answer), language, token, status)
                        except (OSError, RuntimeError, ValueError) as error:
                            warning = "Voice playback stopped. " + str(error)
                    return answer, evidence, warning
                capabilities = self.ollama.require_model(model, token, status)
            elif screen_request:
                number, prompt, mode = screen_request
                number, monitor = amy.find_screen(number)
                status(f"Reading Screen {number} ({monitor['name']}) locally…")
                use_ocr = mode == "text" or (mode == "fast" and amy.screen_text_question(prompt))
                tool = amy.screen_ocr_tool(language, prompt if preferences.chinese else "") if use_ocr else None
                if mode == "text" and tool is None:
                    raise RuntimeError("Install the matching Tesseract language data to read text. See the Linux Desktop guide.")
                if tool and not preferences.chinese:
                    tool = tool[0], "eng"
                image = amy.screen_capture(monitor, max_side=1920 if tool or mode == "detail" else amy.SCREEN_FAST_SIDE)
                token.check()
                if tool:
                    status("Reading visible text…")
                    text = amy.read_screen_text(image, tool).strip()
                if mode == "text":
                    if not text:
                        raise RuntimeError("I couldn't read clear text. Zoom in or select a smaller area.")
                    if not prompt:
                        answer = amy.screen_text_excerpt(text, 6000)
                        chunk(answer)
                        return answer, None, ""
                if not text:
                    model = self.vision_model(model, token, status)
                capabilities = self.ollama.require_model(model, token, status)
                answer_prompt = prompt or "Briefly describe what is visible on this display."
            else:
                capabilities = self.ollama.require_model(model, token, status)
            warning = []
            use_think = think and (not capabilities or "thinking" in capabilities)
            if think and not use_think:
                warning.append(f"{model} used fast mode because it doesn't support Think.")
            audio = None
            audio_error = ""
            if voice and preferences.speak:
                try:
                    audio = self.sentence_stream(language, token, status)
                except (OSError, RuntimeError, ValueError) as error:
                    audio_error = str(error)

            def publish(piece):
                nonlocal audio, audio_error
                chunk(piece)
                if audio is not None:
                    try:
                        audio.feed(piece)
                    except (OSError, RuntimeError, ValueError) as error:
                        audio_error = str(error)
                        audio = None

            status("Thinking locally…" if use_think else f"Waiting for {model}…")
            answer = amy.ask_ollama(
                self.ollama.port, answer_prompt, history, use_think, False, language, model=model,
                on_chunk=publish, web_context=evidence, reply_style=preferences.reply_style,
                screen_image=image if not text else None, screen_text=amy.screen_text_excerpt(text, 3000) if text else None,
                screen_detail=bool(screen_request and screen_request[-1] == "detail"),
                cancel=token, quiet=True, on_limit=warning.append, use_training=False,
            )
            if audio is not None:
                try:
                    audio.finish()
                    status("Speaking…")
                    self.voice_session.finish(cancel=token)
                except (OSError, RuntimeError, ValueError) as error:
                    audio_error = str(error)
            if audio_error:
                warning.append("Voice playback stopped. " + audio_error)
            return answer, evidence, "\n".join(warning)

        def done(result):
            answer, evidence, warning = result
            if warning:
                self.message("AMY", warning)
            if warning.startswith("Voice playback stopped") or "\nVoice playback stopped" in warning:
                self.stop_current()
            if evidence and evidence.get("sources"):
                lines = [f"[{source['id']}] {source['title']}\n{source['url']}" for source in evidence["sources"]]
                coverage = evidence.get("coverage_note")
                self.message("Sources", "\n\n".join(([coverage] if coverage else []) + lines))
            if evidence and evidence.get("followup") == "weather_city":
                self.pending_weather = query
            if not query and not screen_request:
                self.history.extend(({"role": "user", "content": question[-3000:]},
                                     {"role": "assistant", "content": answer[-3000:]}))
                self.last_question = question
                if preferences.web and amy.optional_web_question(question):
                    self.pending_verification = question
                    self.verification_deadline = monotonic() + 180
                    self.verify.show()
                    QTimer.singleShot(180_000, self.expire_verification)

        self.start_job("reply", work, done, initial="Checking the local model…")

    def clear_verification(self):
        self.pending_verification = ""
        self.verify.hide()

    def expire_verification(self):
        if monotonic() >= self.verification_deadline:
            self.clear_verification()

    def verify_online(self, *, voice=False):
        if self.job is not None or not self.pending_verification:
            return
        if monotonic() >= self.verification_deadline:
            self.clear_verification()
            return
        query = self.pending_verification
        self.clear_verification()
        self.request_web(query, voice=voice)

    def request_web(self, query, *, voice=False, from_screen=False):
        if self.job is not None:
            return
        if not self.preferences.web:
            self.deliver_local("Web lookups are off. You can enable them in Settings.", voice)
            return
        query = amy.normalize_search_query(query)
        if not query or len(query) > 500:
            self.deliver_local("Give me a search query between 1 and 500 characters.", voice)
            return
        if amy.live_query_kind(amy.conversational_text(query)) == "weather" and not amy.weather_city(query):
            self.pending_weather = query
            answer = ("要查哪個城市？請回覆「在台北，台灣」之類的地點。" if self.preferences.language == "zh"
                      else "Which city should I check? For example, reply with “in Taipei, Taiwan.”")
            self.deliver_local(answer, voice)
            return
        private = amy.sensitive_search_query(query)
        caution = "\n\nThis query may contain private information. Review it before sending." if private else ""
        review = from_screen or private or not self.preferences.auto_web
        if not review or self.confirm("Review web search", "Send this query to a web search provider?\n\n" + query + caution, "Search"):
            self.reply(query, voice=voice, query=query)
        else:
            self.set_status("Search canceled.")
            self.continue_voice()

    def read_monitor(self, request, voice):
        self.reply(request[1], voice=voice, screen_request=request)

    def vision_model(self, preferred, token, status):
        models = self.ollama.models(token, status)
        for name in dict.fromkeys((preferred, amy.DEFAULT_VISION_MODEL, *models)):
            if name not in models or (models[name] and "vision" not in models[name]):
                continue
            capabilities = self.ollama.require_model(name, token, status)
            if "vision" in capabilities:
                return name
        raise RuntimeError("Install a local vision model, such as qwen3.5:4b, to identify images.")

    def toggle_voice(self):
        if self.voice_on:
            self.stop_current()
            return
        if self.job is not None:
            return
        self.pause_scan()
        self.voice_on = True
        self.voice.setText("Voice off")
        self.continue_voice()

    def continue_voice(self):
        if self.voice_on and self.job is None and not self.closing:
            QTimer.singleShot(140, self.listen_once)

    def listen_once(self):
        if not self.voice_on or self.job is not None or self.closing:
            return
        if QApplication.activeModalWidget() is not None:
            self.continue_voice()
            return
        language = self.preferences.language

        def listen(token, status, _):
            return amy.clean_voice_transcript(amy.listen(language, cancel=token, progress=status))

        def heard(text):
            if text:
                self.handle_message(text, voice=True)
            else:
                self.set_status("No speech detected. Listening again…")

        self.start_job("listen", listen, heard, initial="Starting microphone…")

    def sentence_stream(self, language, token, status):
        if self.voice_session is None:
            if not amy.KOKORO_PYTHON.is_file():
                raise RuntimeError("Install the offline voice with the Linux Desktop guide.")
            self.voice_session = amy.SpeechSession(cancel=token, progress=status)
        return amy.SentenceStream(lambda text: self.voice_session.submit(text, language), skip_code=True)

    def speak_text(self, text, language, token, status):
        stream = self.sentence_stream(language, token, status)
        stream.feed(text)
        stream.finish()
        status("Speaking…")
        self.voice_session.finish(cancel=token)

    def close_voice(self):
        if self.voice_session is not None:
            self.voice_session.close()
            self.voice_session = None

    def refresh_memory(self):
        try:
            self.notes = desktop.load_notes()
            self.profile_item, profile = desktop.load_profile_item()
        except (OSError, RuntimeError, ValueError) as error:
            self.report_error(error)
            return
        self.memory.notes.clear()
        self.memory.notes.addItems(self.notes.lines)
        self.memory.delete_notes.setEnabled(bool(self.notes.lines))
        self.memory.profile.setPlainText(profile or "No profile is saved.")
        self.memory.delete_profile.setEnabled(self.profile_item is not None)
        self.refresh_suggestions()

    def refresh_suggestions(self):
        self.memory.suggestions.clear()
        for kind, text, answer, _ in self.suggestions:
            self.memory.suggestions.addItem(f"{kind} · {text}" + ("\n" + answer if answer else ""))
        self.memory.review.setEnabled(bool(self.suggestions))
        self.memory.dismiss.setEnabled(bool(self.suggestions))

    def queue_suggestion(self, suggestion):
        if suggestion not in self.suggestions:
            self.suggestions.append(suggestion)
            self.refresh_suggestions()

    def add_note(self, *, initial=""):
        text, ok = QInputDialog.getMultiLineText(self, "Review note", "Note to save for future chats", initial)
        if not ok:
            return False
        try:
            note = desktop.validate_note(text)
            before = desktop.load_notes()
            if note in before.lines:
                self.set_status("That note is already saved.")
                return True
            desktop.save_notes(before, (*before.lines, note))
            self.refresh_memory()
            self.set_status("Saved note verified.")
            return True
        except (OSError, RuntimeError, ValueError) as error:
            self.report_error(error)
            return False

    def delete_notes(self):
        before = getattr(self, "notes", None)
        if before is None or self.job is not None:
            return
        indexes = sorted(index.row() for index in self.memory.notes.selectedIndexes())
        if not indexes:
            self.set_status("Select the notes you want to delete.")
            return
        shown = "\n".join("• " + before.lines[index] for index in indexes)
        if not self.confirm("Delete saved notes", "Remove these notes from AMY's active memory?\n\n" + shown, "Delete"):
            return
        try:
            removed = set(indexes)
            desktop.save_notes(before, [note for index, note in enumerate(before.lines) if index not in removed])
            self.history.clear()
            self.refresh_memory()
            self.set_status(f"Deleted {len(indexes)} saved note(s).")
        except (OSError, RuntimeError, ValueError) as error:
            self.report_error(error)

    def delete_profile(self):
        item = getattr(self, "profile_item", None)
        if item is None or self.job is not None:
            return
        if self.confirm("Delete profile", f"Permanently delete the saved profile file?\n\n{item.path}", "Delete profile"):
            try:
                desktop.delete_item(item)
                self.history.clear()
                self.refresh_memory()
                self.set_status("Profile deleted and checked.")
            except (OSError, RuntimeError, ValueError) as error:
                self.report_error(error)

    def review_suggestion(self):
        index = self.memory.suggestions.currentRow()
        if not 0 <= index < len(self.suggestions) or self.job is not None:
            return
        kind, text, answer, language = self.suggestions[index]
        if kind == "Note":
            if self.add_note(initial=text):
                self.suggestions.pop(index)
                self.refresh_suggestions()
            return
        import amy_training
        try:
            record = amy_training.example_record((language, text, answer, ""), "user")
            confirmed = amy_training.save_teaching_example(
                record, lambda preview: self.confirm("Review training lesson", preview, "Save lesson"),
                root=amy_training.training_directory(),
            )
            if confirmed:
                self.suggestions.pop(index)
                self.refresh_suggestions()
                self.set_status("Training lesson saved and checked.")
        except (OSError, RuntimeError, ValueError) as error:
            self.report_error(error)

    def dismiss_suggestion(self):
        index = self.memory.suggestions.currentRow()
        if 0 <= index < len(self.suggestions):
            self.suggestions.pop(index)
            self.refresh_suggestions()

    def refresh_media(self):
        try:
            items = desktop.list_saved_items()
        except (OSError, RuntimeError, ValueError) as error:
            self.report_error(error)
            return
        selected = self.media_selection()
        self.media.items.clear()
        filters = {1: "Screenshot", 2: "Media", 3: "Report"}
        for item in items:
            if self.media.filter.currentIndex() in filters and item.kind != filters[self.media.filter.currentIndex()]:
                continue
            size = item.stamp[3]
            modified = datetime.fromtimestamp(item.stamp[4] / 1_000_000_000).strftime("%Y-%m-%d %H:%M")
            name = QTreeWidgetItem([item.name, item.kind, f"{size / 1024:,.1f} KiB", modified])
            name.setData(0, Qt.ItemDataRole.UserRole, item)
            self.media.items.addTopLevelItem(name)
            if selected == item:
                self.media.items.setCurrentItem(name)
        self.media.items.setColumnWidth(0, 270)
        self.media.items.setColumnWidth(1, 110)
        self.media.items.setColumnWidth(2, 90)
        self.update_media_selection()

    def media_selection(self):
        item = self.media.items.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item is not None and item.isSelected() else None

    def update_media_selection(self):
        item = self.media_selection()
        self.media.path.setText(str(item.path) if item else
                                "Select a saved file." if self.media.items.topLevelItemCount() else "No saved files match this filter.")
        self.media.preview.hide()
        for control in (self.media.open, self.media.folder, self.media.delete):
            control.setEnabled(item is not None)
        if item is not None and item.path.suffix.casefold() in (".png", ".jpg", ".jpeg", ".webp") and item.stamp[3] <= 16_000_000:
            try:
                verified = desktop.verify_item(item)
            except (OSError, RuntimeError):
                return
            reader = QImageReader(str(verified))
            size = reader.size()
            if size.isValid() and max(size.width(), size.height()) <= 8192:
                reader.setScaledSize(size.scaled(QSize(430, 164), Qt.AspectRatioMode.KeepAspectRatio))
                preview = reader.read()
                if not preview.isNull():
                    self.media.preview.setPixmap(QPixmap.fromImage(preview))
                    self.media.preview.show()

    def open_media(self):
        self.open_selected_media(folder=False)

    def open_media_folder(self):
        self.open_selected_media(folder=True)

    def open_selected_media(self, *, folder):
        item = self.media_selection()
        if item is not None:
            try:
                path = desktop.verify_item(item)
                self.open_path(path.parent if folder else path)
            except (OSError, RuntimeError, ValueError) as error:
                self.report_error(error)

    def delete_media(self):
        item = self.media_selection()
        if item is None or self.job is not None:
            return
        if not self.confirm("Delete saved file", f"Permanently delete this file?\n\n{item.path}", "Delete file"):
            return
        try:
            desktop.delete_item(item)
            self.refresh_media()
            self.set_status(f"Deleted and checked · {item.name}")
        except (OSError, RuntimeError, ValueError) as error:
            self.report_error(error)

    def capture_screenshot(self, number):
        number, monitor = amy.find_screen(number)
        filename = amy.output_name(f"screen-{number}", "png")
        path = amy.AMY_HOME / "screenshots" / filename
        if not self.confirm("Save screenshot", f"Capture Screen {number} ({monitor['name']}) and save it here?\n\n{path}", "Capture and save"):
            self.continue_voice()
            return

        def work(token, status, _):
            _, current = amy.find_screen(number)
            if current["name"] != monitor["name"] or current.get("region") != monitor.get("region"):
                raise RuntimeError("The screen changed after review. Select it again.")
            status("Capturing the approved screen…")
            image = amy.screen_capture(current)
            token.check()
            return desktop.save_region_image(image, filename)

        self.start_job("capture", work, self.report_capture, can_stop=False, initial="Checking display…")

    def report_capture(self, path):
        self.message("AMY", f"Screenshot saved and verified\n{path}\n\nOpen Saved media to view it.")
        self.refresh_media()
        self.set_status("Screenshot verified.")

    def open_scan(self):
        self.scan.show()
        self.scan.raise_()
        self.scan.activateWindow()

    def select_scan_area(self):
        if self.job is not None:
            self.scan.status.setText("Stop the current activity before selecting an area.")
            return
        self.stop_current()
        self.scan.hide()

        def selected(region):
            self.scan_region = region
            self.reset_scan()
            self.scan.enable_area(True)
            self.open_scan()
            self.scan.status.setText(f"Selected area · {region}")
            self.set_status("Screen area selected.")

        self.start_job("scan selection", lambda token, *_: desktop.select_region(token), selected,
                       initial="Drag a rectangle on the screen · Esc cancels")

    def reset_scan(self):
        self.scan_frame = None
        self.scan_result_key = None
        self.scan.translation.clear()
        self.scan.original.clear()

    def toggle_scan(self):
        if self.scan_live:
            self.pause_scan()
            return
        if not self.scan_region or self.job is not None:
            return
        self.stop_current()
        self.scan_live = True
        self.scan.live.setText("Pause live")
        self.scan_clock.start()
        self.scan_tick()

    def pause_scan(self):
        was_live = self.scan_live
        self.scan_live = False
        self.scan_clock.stop()
        self.scan.live.setText("Start live")
        if was_live:
            self.scan.status.setText("Live scanning paused.")
        if self.job_kind == "scan live" and self.job is not None:
            self.job.stop()

    def scan_tick(self):
        if not self.scan_live or not self.scan.isVisible() or self.job is not None or QApplication.activeModalWidget() is not None:
            return
        region, previous = self.scan_region, self.scan_frame
        source, target = self.scan.direction.currentData()
        model, prior_key = self.preferences.model, self.scan_result_key

        def scan(token, status, _):
            frame = desktop.scan_frame(region, previous, source, token)
            key = (region, source, target, model, frame.text)
            if key == prior_key:
                return frame, key, None
            if not target or not frame.text:
                return frame, key, frame.text
            self.ollama.require_model(model, token, status)
            status("Translating locally…")
            answer = amy.ask_ollama(
                self.ollama.port, "Translate the extracted text faithfully. Return only the translation. Keep the original line breaks.",
                [], False, False, target, model=model, screen_text=amy.screen_text_excerpt(frame.text, 3000),
                screen_detail=True, cancel=token, quiet=True, use_training=False,
            )
            return frame, key, answer

        def scanned(result):
            frame, key, translation = result
            if key[:4] != (self.scan_region, *self.scan.direction.currentData(), self.preferences.model):
                return
            self.scan_frame, self.scan_result_key = frame, key
            if translation is None:
                self.scan.status.setText("Text unchanged · Waiting for a change")
                return
            self.scan.original.setPlainText(frame.text)
            self.scan.translation.setPlainText(translation)
            self.scan.tabs.setCurrentIndex(0 if target else 1)
            self.scan.status.setText("Watching for changes." if frame.text else "No clear text in the selected area.")

        self.start_job("scan live", scan, scanned, initial="Checking selected area…")

    def identify_scan(self):
        if not self.scan_region or self.job is not None:
            return
        self.pause_scan()
        region, preferences = self.scan_region, self.preferences

        def work(token, status, _):
            model = self.vision_model(preferences.model, token, status)
            image = desktop.capture_region(region, token)
            status(f"Identifying locally with {model}…")
            return amy.ask_ollama(
                self.ollama.port, "Describe what is visible in this selected area.", [], False, False,
                preferences.language, model=model, screen_image=image, cancel=token, quiet=True, use_training=False,
            )

        def done(answer):
            self.scan.translation.setPlainText(answer)
            self.scan.tabs.setCurrentIndex(0)
            self.scan.status.setText("Image analyzed locally.")

        self.start_job("scan identify", work, done, initial="Checking for a local vision model…")

    def search_scan(self):
        if not self.scan_region or self.job is not None:
            return
        self.pause_scan()
        region = self.scan_region
        source, _ = self.scan.direction.currentData()

        def offer(frame):
            if not frame.text:
                self.scan.status.setText("I couldn't read clear text to search for.")
                return
            text, ok = QInputDialog.getText(self.scan, "Review search text", "Query to send after approval",
                                           text=" ".join(frame.text.split())[:500])
            if ok and text.strip():
                self.open_page(0)
                self.request_web(text, from_screen=True)
            self.scan.status.setText("Search preview ready.")

        self.start_job("scan search", lambda token, *_: desktop.scan_frame(region, self.scan_frame, source, token),
                       offer, initial="Reading selected text locally…")

    def save_scan(self):
        if not self.scan_region or self.job is not None:
            return
        self.pause_scan()
        region = self.scan_region
        filename = amy.output_name("region", "png")
        path = amy.AMY_HOME / "screenshots" / filename
        if self.confirm("Save selected area", f"Capture {region} and save a PNG here?\n\n{path}", "Save image"):
            self.start_job("scan save", lambda token, *_: desktop.save_region_image(desktop.capture_region(region, token), filename),
                           self.report_capture, can_stop=False, initial="Saving the approved capture…")

    def closeEvent(self, event):
        self.closing = True
        self.voice_on = False
        self.pause_scan()
        if self.job is not None:
            if self.job_can_stop:
                self.job.stop()
                self.set_status("Stopping…")
            event.ignore()
            return
        self.close_voice()
        self.ollama.close()
        self.scan.hide()
        super().closeEvent(event)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=amy.DEFAULT_OLLAMA_PORT, help="Local Ollama port (default: 11435)")
    arguments = parser.parse_args()
    if sys.platform != "linux":
        parser.error("Use the AMY Linux desktop app on Linux. See docs/WINDOWS.md for the Windows terminal launcher.")
    if not 1 <= arguments.port <= 65535:
        parser.error("The local port must be between 1 and 65535.")
    application = QApplication([sys.argv[0]])
    application.setApplicationName("AMY")
    application.setDesktopFileName("amy")
    application.setStyle("Fusion")
    default_font = QFont(application.font())
    if "Inter" in QFontDatabase.families():
        default_font.setFamily("Inter")
    preference_error = ""
    try:
        preferences = desktop.load_preferences()
    except (OSError, RuntimeError, ValueError, TypeError) as error:
        preferences = desktop.Preferences()
        preference_error = str(error)
    window = AMYWindow(arguments.port, preferences, default_font, preference_error=preference_error)
    window.show()
    return application.exec()


if __name__ == "__main__":
    sys.exit(main())
