"""Qt views for AMY's desktop preferences, saved data and screen tools."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFontComboBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QTabWidget, QTreeWidget,
    QVBoxLayout, QWidget,
)

from amy_desktop_core import Preferences, REPLY_STYLES


def label(text="", role=None):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    if role:
        widget.setObjectName(role)
    return widget


def button(text, action=None, role=None):
    widget = QPushButton(text)
    if role:
        widget.setObjectName(role)
    if action is not None:
        widget.clicked.connect(action)
    return widget


def row(*widgets):
    layout = QHBoxLayout()
    for widget in widgets:
        layout.addWidget(widget)
    layout.addStretch()
    return layout


def readonly(text=""):
    widget = QPlainTextEdit(text)
    widget.setReadOnly(True)
    return widget


class SettingsView(QWidget):
    refresh_models = Signal()
    pick_model = Signal(str)
    save = Signal(object)
    setup_guide = Signal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        general = QWidget()
        general_layout = QVBoxLayout(general)
        general_layout.setContentsMargins(20, 18, 20, 20)
        general_layout.setSpacing(16)
        general_layout.addWidget(label("Conversation", "section"))
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setVerticalSpacing(10)
        self.style = QComboBox()
        self.style.addItems(REPLY_STYLES)
        self.details = QLineEdit()
        self.details.setMaxLength(500)
        self.details.setPlaceholderText("For example, use simple words and call me sir occasionally")
        self.languages = QComboBox()
        self.languages.addItems(["English only", "English + Traditional Chinese"])
        self.language = QComboBox()
        self.language.addItem("English (US)", "en")
        self.language.addItem("Traditional Chinese (Taiwan)", "zh")
        self.languages.currentIndexChanged.connect(self.update_languages)
        form.addRow("Reply style", self.style)
        form.addRow("Custom preferences", self.details)
        form.addRow("Language support", self.languages)
        form.addRow("Reply and microphone language", self.language)
        general_layout.addLayout(form)
        general_layout.addWidget(label("Traditional Chinese voice and OCR are optional downloads.", "muted"))
        general_layout.addLayout(row(button("Voice and OCR setup", self.setup_guide.emit)))

        general_layout.addWidget(label("Appearance", "section"))
        appearance = QFormLayout()
        appearance.setVerticalSpacing(10)
        self.theme = QComboBox()
        self.theme.addItems(["Dark", "Light"])
        self.font = QFontComboBox()
        self.size = QSpinBox()
        self.size.setRange(9, 24)
        self.size.setSuffix(" pt")
        appearance.addRow("Theme", self.theme)
        appearance.addRow("Font family", self.font)
        appearance.addRow("Font size", self.size)
        general_layout.addLayout(appearance)
        self.web = QComboBox()
        self.web.addItems(["Ask before searching", "Search public queries automatically", "Off"])
        form.addRow("Web lookups", self.web)
        self.speak = QCheckBox("Speak replies during voice mode")
        general_layout.addWidget(self.speak)
        general_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(general)
        general_page = QWidget()
        page_layout = QVBoxLayout(general_page)
        page_layout.setContentsMargins(0, 0, 0, 12)
        page_layout.addWidget(scroll, 1)
        self.save_button = button("Save settings", self.submit, "primary")
        actions = row(self.save_button)
        actions.setContentsMargins(20, 0, 20, 0)
        page_layout.addLayout(actions)
        self.tabs.addTab(general_page, "General")

        models = QWidget()
        model_page = QVBoxLayout(models)
        model_page.setContentsMargins(20, 18, 20, 20)
        model_page.setSpacing(13)
        model_page.addWidget(label("Local Ollama models", "section"))
        self.model_status = label("Refresh to check which models are downloaded.", "muted")
        model_page.addWidget(self.model_status)
        self.model_scroll = QScrollArea()
        self.model_scroll.setWidgetResizable(True)
        self.model_scroll.setFrameShape(QFrame.Shape.NoFrame)
        model_page.addWidget(self.model_scroll, 1)
        self.refresh_button = button("Refresh models", self.refresh_models.emit)
        model_page.addLayout(row(self.refresh_button))
        self.tabs.addTab(models, "Models")

    def load(self, preferences):
        self.preferences = preferences
        self.style.setCurrentText(preferences.style)
        self.details.setText(preferences.style_details)
        self.languages.setCurrentIndex(int(preferences.chinese))
        self.update_languages()
        self.language.setCurrentIndex(self.language.findData(preferences.language))
        self.theme.setCurrentText(preferences.theme)
        self.font.setCurrentFont(QFont(preferences.font) if preferences.font else QApplication.font())
        self.size.setValue(preferences.size)
        self.web.setCurrentIndex(int(preferences.auto_web) if preferences.web else 2)
        self.speak.setChecked(preferences.speak)

    def update_languages(self):
        bilingual = self.languages.currentIndex() == 1
        self.language.setEnabled(bilingual)
        if not bilingual:
            self.language.setCurrentIndex(0)

    def submit(self):
        self.save.emit(Preferences(
            model=self.preferences.model, style=self.style.currentText(), style_details=self.details.text().strip(),
            language=self.language.currentData(), chinese=self.languages.currentIndex() == 1,
            theme=self.theme.currentText(), font=self.font.currentFont().family(), size=self.size.value(),
            web=self.web.currentIndex() != 2, auto_web=self.web.currentIndex() == 1, speak=self.speak.isChecked(),
        ))

    def set_models(self, models, active, port):
        container = QWidget()
        self.model_group = QButtonGroup(container)
        entries = QVBoxLayout(container)
        entries.setContentsMargins(0, 0, 0, 0)
        entries.setSpacing(9)
        if not models:
            self.model_status.setText(f"No local chat models found on port {port}. Pull a model, then refresh.")
        elif active and active not in models:
            self.model_status.setText(f"{active} is unavailable on port {port}. Tick a downloaded model below.")
        else:
            self.model_status.setText(f"Tick the model to use. Showing downloads on port {port}.")
        for model, capabilities in models.items():
            check = QCheckBox(model)
            self.model_group.addButton(check)
            check.setChecked(model == active)
            check.clicked.connect(lambda checked, name=model: self.pick_model.emit(name) if checked else None)
            entry = QFrame()
            entry.setObjectName("card")
            item = QHBoxLayout(entry)
            item.setContentsMargins(13, 10, 13, 10)
            item.addWidget(check, 1)
            if "vision" in capabilities:
                item.addWidget(label("Images", "muted"))
            entries.addWidget(entry)
        entries.addStretch()
        self.model_scroll.setWidget(container)


class MemoryView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        notes = QWidget()
        notes_layout = QVBoxLayout(notes)
        notes_layout.addWidget(label("Saved notes are used in future chats.", "muted"))
        self.notes = QListWidget()
        self.notes.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.notes.setWordWrap(True)
        notes_layout.addWidget(self.notes, 1)
        self.add_note = button("Add note")
        self.delete_notes = button("Delete selected", role="danger")
        self.refresh = button("Refresh")
        notes_layout.addLayout(row(self.add_note, self.delete_notes, self.refresh))
        self.tabs.addTab(notes, "Saved notes")

        suggested = QWidget()
        suggested_layout = QVBoxLayout(suggested)
        suggested_layout.addWidget(label("Review suggestions before AMY can use them in future chats or training.", "muted"))
        self.suggestions = QListWidget()
        self.suggestions.setWordWrap(True)
        suggested_layout.addWidget(self.suggestions, 1)
        self.review = button("Review", role="primary")
        self.dismiss = button("Dismiss")
        suggested_layout.addLayout(row(self.review, self.dismiss))
        self.tabs.addTab(suggested, "Suggestions")

        profile = QWidget()
        profile_layout = QVBoxLayout(profile)
        profile_layout.addWidget(label("Profile details used to answer questions about you.", "muted"))
        self.profile = readonly()
        profile_layout.addWidget(self.profile, 1)
        self.delete_profile = button("Delete profile", role="danger")
        profile_layout.addLayout(row(self.delete_profile))
        self.tabs.addTab(profile, "Profile")


class MediaView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(label("Screenshots and media from ~/AMY/screenshots/ and ~/AMY/dump/.", "muted"))
        self.filter = QComboBox()
        self.filter.addItems(["All files", "Screenshots", "Other media", "Change reports"])
        self.refresh = button("Refresh")
        layout.addLayout(row(self.filter, self.refresh))
        self.items = QTreeWidget()
        self.items.setHeaderLabels(["Name", "Type", "Size", "Modified"])
        self.items.setRootIsDecorated(False)
        self.items.setUniformRowHeights(True)
        layout.addWidget(self.items, 1)
        self.path = label("Select a saved file.", "muted")
        layout.addWidget(self.path)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.hide()
        layout.addWidget(self.preview)
        self.open = button("Open", role="primary")
        self.folder = button("Open folder")
        self.delete = button("Delete", role="danger")
        layout.addLayout(row(self.open, self.folder, self.delete))


class ScanPanel(QDialog):
    closed = Signal()

    def __init__(self, parent):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("AMY · Screen tools")
        self.resize(525, 470)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        self.select = button("Select area", role="primary")
        self.live = button("Start live")
        self.identify = button("Identify")
        self.search = button("Search text")
        self.save = button("Save image")
        layout.addLayout(row(self.select, self.live))
        self.direction = QComboBox()
        self.configure_languages(False)
        layout.addWidget(self.direction)
        self.status = label("Drag a rectangle around text or an image.", "muted")
        layout.addWidget(self.status)
        self.tabs = QTabWidget()
        self.translation = readonly()
        self.original = readonly()
        self.tabs.addTab(self.translation, "Translation")
        self.tabs.addTab(self.original, "Screen text")
        layout.addWidget(self.tabs, 1)
        layout.addLayout(row(self.identify, self.search, self.save))
        self.enable_area(False)

    def configure_languages(self, chinese):
        current = self.direction.currentData()
        self.direction.clear()
        self.direction.addItem("Read English text", ("en", ""))
        if chinese:
            self.direction.addItem("English → Traditional Chinese", ("en", "zh"))
            self.direction.addItem("Traditional Chinese → English", ("zh", "en"))
        index = self.direction.findData(current)
        self.direction.setCurrentIndex(max(index, 0))

    def enable_area(self, enabled):
        for widget in (self.live, self.identify, self.search, self.save):
            widget.setEnabled(enabled)

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)


class DraftDialog(QDialog):
    def __init__(self, draft, parent):
        super().__init__(parent)
        self.setWindowTitle("Review file changes")
        self.resize(840, 600)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(label("Review file changes", "pageTitle"))
        layout.addWidget(label(draft.description.strip(), "muted"))
        diff = readonly(draft.preview)
        diff.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        diff.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        layout.addWidget(diff, 1)
        actions = QDialogButtonBox()
        approve = actions.addButton("Approve and save", QDialogButtonBox.ButtonRole.AcceptRole)
        approve.setObjectName("primary")
        approve.setAutoDefault(False)
        cancel = actions.addButton(QDialogButtonBox.StandardButton.Cancel)
        cancel.setDefault(True)
        actions.accepted.connect(self.accept)
        actions.rejected.connect(self.reject)
        layout.addWidget(actions)
