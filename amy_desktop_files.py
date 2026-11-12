"""Attachment extraction and folder-scoped Coding workspaces."""

import fcntl
import hashlib
import io
import json
import os
import re
import shutil
import stat
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import amy_desktop_core as desktop
import mitan_jarvis as amy

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
TEXT_SUFFIXES = {
    ".txt", ".md", ".rst", ".csv", ".tsv", ".json", ".toml", ".yaml", ".yml", ".xml", ".log",
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".sh", ".bash", ".zsh",
    ".rs", ".go", ".java", ".kt", ".c", ".h", ".cpp", ".hpp", ".cs", ".rb", ".php", ".sql",
    ".swift", ".lua", ".ini", ".cfg", ".conf", ".vue", ".svelte", ".ipynb",
}
TEXT_FILENAMES = {"readme", "license", "makefile", "dockerfile", "gemfile", "cmakelists.txt"}
MAX_ATTACHMENTS = 4
MAX_PROJECT_FILES = 6000
INDEX_LIMIT = 2 * 1024 * 1024
SKIP_DIRECTORIES = {
    "node_modules", "vendor", "dist", "build", "target", "coverage", "__pycache__", ".git", ".venv", "venv",
}


def is_text_file(path):
    return path.suffix.casefold() in TEXT_SUFFIXES or path.name.casefold() in TEXT_FILENAMES


@dataclass(frozen=True)
class Attachment:
    path: Path
    stamp: tuple

    @classmethod
    def select(cls, path):
        path = Path(path).resolve(strict=True)
        info = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"{path.name} is not a regular file.")
        result = cls(path, amy.file_stamp(info))
        if result.stamp[3] > result.limit:
            raise ValueError(f"{path.name} exceeds the {result.limit // (1024 * 1024)} MB attachment limit.")
        return result

    @classmethod
    def from_record(cls, data):
        if (not isinstance(data, dict) or not isinstance(data.get("path"), str)
                or not isinstance(data.get("stamp"), list) or len(data["stamp"]) != 6
                or any(type(value) is not int for value in data["stamp"])):
            raise ValueError("This saved attachment reference could not be read.")
        path = Path(data["path"])
        if not path.is_absolute():
            raise ValueError("The saved attachment location is invalid.")
        return cls(path, tuple(data["stamp"]))

    def record(self):
        return {"path": str(self.path), "stamp": list(self.stamp)}

    @property
    def kind(self):
        suffix = self.path.suffix.casefold()
        if suffix in IMAGE_SUFFIXES:
            return "image"
        if suffix == ".pdf":
            return "pdf"
        if is_text_file(self.path):
            return "text"
        raise ValueError(f"AMY can't read {self.path.name}. Choose an image, PDF, or text file.")

    @property
    def limit(self):
        return (2 if self.kind == "text" else 16) * 1024 * 1024

    def read(self):
        try:
            descriptor = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError as error:
            raise ValueError(f"Reattach {self.path.name}. Its saved location is unavailable.") from error
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or amy.file_stamp(info) != self.stamp
                    or info.st_size > self.limit):
                raise ValueError(f"Reattach {self.path.name}. The file changed after it was selected.")
            data = stream.read(self.limit + 1)
            if len(data) != info.st_size or amy.file_stamp(os.fstat(stream.fileno())) != self.stamp:
                raise ValueError(f"Reattach {self.path.name}. The file changed while AMY was reading it.")
        return data


def decode_text(data, name):
    try:
        text = data.decode("utf-8-sig")
    except UnicodeError as error:
        raise ValueError(f"{name} needs UTF-8 text.") from error
    if "\0" in text:
        raise ValueError(f"{name} doesn't contain readable text.")
    return amy.CONTROL_CHARS.sub("", text)


def normalized_image(data, size=1400):
    from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QSize, Qt
    from PySide6.QtGui import QImageReader

    source = QBuffer()
    source.setData(data)
    source.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(source)
    reader.setAutoTransform(True)
    dimensions = reader.size()
    if not dimensions.isValid() or dimensions.width() * dimensions.height() > 36_000_000:
        raise ValueError("AMY couldn't read this image within its pixel limit.")
    if max(dimensions.width(), dimensions.height()) > size:
        reader.setScaledSize(dimensions.scaled(QSize(size, size), Qt.AspectRatioMode.KeepAspectRatio))
    picture = reader.read()
    encoded = QByteArray()
    output = QBuffer(encoded)
    output.open(QIODevice.OpenModeFlag.WriteOnly)
    if picture.isNull() or not picture.save(output, "PNG"):
        raise ValueError("AMY couldn't decode the selected image.")
    return bytes(encoded)


def extract_pdf(data, cancel):
    raw = desktop.run_local_tool([sys.executable, str(Path(__file__).resolve()), "--extract-pdf"], cancel,
                                 timeout=18, limit=850_000, data=data)
    result = json.loads(raw)
    if not result["pages"]:
        raise ValueError("This PDF has no readable text. Attach a screenshot of a scanned page for OCR.")
    return result["pages"], result["partial"]


def pdf_worker():
    import resource
    from pypdf import PdfReader

    memory = 512 * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    reader = PdfReader(io.BytesIO(sys.stdin.buffer.read(16 * 1024 * 1024 + 1)))
    if reader.is_encrypted:
        raise ValueError("Open a decrypted copy of this PDF before attaching it.")
    pages = []
    budget = 100_000
    partial = len(reader.pages) > 100
    for index, page in enumerate(reader.pages[:100], 1):
        content = (page.extract_text() or "").strip()
        if content:
            pages.append((index, content[:budget]))
            if len(content) >= budget:
                partial = True
                break
            budget -= len(content)
    print(json.dumps({"pages": pages, "partial": partial}, ensure_ascii=False))


@dataclass
class AttachmentReader:
    cache: dict = field(default_factory=dict)

    def read(self, item, ocr, vision, cancel):
        key = item, ocr, vision
        if key in self.cache:
            # Validate the original selection even when the extracted content is cached.
            if amy.file_stamp(item.path.stat(follow_symlinks=False)) != item.stamp:
                raise ValueError(f"Reattach {item.path.name}. It changed after it was selected.")
            return self.cache[key]
        cancel.check()
        data = item.read()
        image = b""
        partial = False
        if item.kind == "pdf":
            pages, partial = extract_pdf(data, cancel)
        elif item.kind == "image":
            picture = normalized_image(data)
            if vision:
                image, pages = picture, []
            else:
                executable = shutil.which("tesseract")
                if not executable or not ocr:
                    raise ValueError(f"Choose a vision model or install OCR language data to read {item.path.name}.")
                text = amy.read_screen_text(picture, (executable, ocr)).strip()
                if not text:
                    raise ValueError(f"OCR found no clear text in {item.path.name}. Try a vision model.")
                pages = [(0, text)]
        else:
            text = decode_text(data, item.path.name)
            partial = len(text) > 100_000
            pages = [(0, text[:100_000])]
        cancel.check()
        if len(self.cache) >= 8:
            self.cache.pop(next(iter(self.cache)))
        self.cache[key] = pages, image, partial
        return self.cache[key]

    def context(self, records, question, ocr, vision, cancel, progress):
        sections, images, warnings = [], [], []
        for record in records[:MAX_ATTACHMENTS]:
            item = Attachment.from_record(record)
            progress(f"Reading {item.path.name} locally…")
            try:
                pages, image, partial = self.read(item, ocr, vision, cancel)
            except (OSError, RuntimeError, ValueError) as error:
                warnings.append(f"{item.path.name} · {error}")
                continue
            if image:
                images.append(image)
                sections.append(f"Image {len(images)} is {item.path.name}.")
            if pages:
                limit = 4200 // max(1, len(records))
                sections.append(excerpts(item.path.name, pages, question, limit))
            if partial:
                warnings.append(f"{item.path.name} was read up to the extraction limit.")
        return "\n\n".join(sections), tuple(images), warnings


def excerpts(name, pages, question, budget):
    terms = set(re.findall(r"\w{3,}", question.casefold()))
    chunks = []
    for page, text in pages:
        lines = text.splitlines()
        for start in range(0, len(lines), 12):
            snippet = "\n".join(lines[start:start + 12])[:950]
            words = set(re.findall(r"\w{3,}", snippet.casefold()))
            location = f"page {page}, " if page else ""
            heading = f"{name} · {location}lines {start + 1}–{min(start + 12, len(lines))}"
            chunks.append((len(terms & words), heading, snippet))
    selected = []
    for _, heading, snippet in sorted(chunks, key=lambda item: item[0], reverse=True):
        available = budget - len(heading) - 2
        if available < 100:
            break
        text = heading + "\n" + snippet[:available]
        selected.append(text)
        budget -= len(text) + 2
    return "\n\n".join(selected) or f"{name} has no text."


@dataclass
class Workspace:
    root: Path
    identity: tuple
    files: dict = field(default_factory=dict)
    edits: list = field(default_factory=list)
    sources: dict = field(default_factory=dict)
    indexed: bool = False
    limited: bool = False

    @classmethod
    def authorize(cls, path):
        root = Path(path).resolve(strict=True)
        with amy.open_project_root(root) as directory:
            identity = amy.scope_identity(directory)
        return cls(root, identity)

    @property
    def index_name(self):
        key = hashlib.sha256(os.fsencode(self.root)).hexdigest()
        return f"project-{key[:32]}.json"

    @contextmanager
    def open(self):
        with amy.open_project_root(self.root) as directory:
            if amy.scope_identity(directory) != self.identity:
                raise RuntimeError("The selected folder changed. Choose it again to confirm access.")
            yield directory

    def load_index(self):
        try:
            with amy.home_directory(("AMY", "important-temp")) as folder:
                raw, _ = amy.snapshot(folder, self.index_name, INDEX_LIMIT)
            if raw:
                data = json.loads(raw)
                if (data["root"] == str(self.root) and tuple(data["identity"]) == self.identity
                        and isinstance(data["files"], dict) and isinstance(data["edits"], list)):
                    self.files = data["files"]
                    self.edits = [entry for entry in data["edits"] if isinstance(entry, str)][-12:]
        except (FileNotFoundError, ValueError, TypeError, KeyError):
            pass

    def save_index(self):
        with amy.home_directory(("AMY", "important-temp"), created=[]) as folder:
            fcntl.flock(folder, fcntl.LOCK_EX | fcntl.LOCK_NB)
            original = amy.snapshot(folder, self.index_name, INDEX_LIMIT)
            if original[0]:
                try:
                    previous = json.loads(original[0])
                    if tuple(previous["identity"]) == self.identity and isinstance(previous["edits"], list):
                        prior = [entry for entry in previous["edits"] if isinstance(entry, str)]
                        self.edits = list(dict.fromkeys(prior + self.edits))[-12:]
                except (TypeError, KeyError, ValueError):
                    pass
            data = json.dumps({"root": str(self.root), "identity": self.identity, "files": self.files,
                               "edits": self.edits}, ensure_ascii=False, separators=(",", ":")).encode()
            amy.replace_snapshot(folder, self.index_name, original, data, INDEX_LIMIT)

    def refresh(self, cancel):
        if not self.indexed:
            self.load_index()
        files = {}
        pending = [()]
        seen = 0
        self.limited = False
        with self.open() as root:
            while pending and seen < MAX_PROJECT_FILES:
                cancel.check()
                parts = pending.pop()
                try:
                    with amy.home_directory(parts, parent=root) as directory, os.scandir(directory) as entries:
                        for entry in entries:
                            cancel.check()
                            seen += 1
                            if seen > MAX_PROJECT_FILES:
                                break
                            path = "/".join((*parts, entry.name))
                            try:
                                amy.project_parts(path, ())
                                info = entry.stat(follow_symlinks=False)
                            except (OSError, ValueError):
                                continue
                            if stat.S_ISDIR(info.st_mode) and entry.name not in SKIP_DIRECTORIES and len(parts) < 11:
                                pending.append((*parts, entry.name))
                            elif stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1:
                                files[path] = list(amy.file_stamp(info))
                except (OSError, RuntimeError):
                    if not parts:
                        raise
        self.limited = bool(pending) or seen >= MAX_PROJECT_FILES
        for name in tuple(self.sources):
            if files.get(name) != self.files.get(name):
                self.sources.pop(name)
        changed = files != self.files or not self.indexed
        self.files = files
        self.indexed = True
        if changed:
            self.save_index()

    def relevant(self, question, cancel):
        terms = set(re.findall(r"[\w-]{3,}", question.casefold()))
        explicit = [name for name in self.files if name.casefold() in question.casefold()]

        def score(name):
            path = Path(name)
            words = set(re.findall(r"[\w-]{3,}", name.casefold()))
            matches = sum(any(len(word) >= 4 and (term.startswith(word) or word.startswith(term))
                              for term in terms) for word in words)
            return (name in explicit, len(words & terms) + matches,
                    path.name.casefold() in {"readme.md", "package.json", "pyproject.toml", "requirements.txt"},
                    -len(path.parts))

        known = sorted(self.files, key=score, reverse=True)
        snapshots = {}
        with self.open() as root:
            for name in known:
                cancel.check()
                if len(snapshots) >= 6:
                    break
                if not is_text_file(Path(name)) and name not in explicit:
                    continue
                path = tuple(name.split("/"))
                try:
                    with amy.home_directory(path[:-1], parent=root) as parent:
                        stamp = amy.file_stamp(amy.project_entry_info(parent, path[-1]))
                    cached = self.sources.get(name)
                    if cached is None or cached[1] != stamp:
                        cached = amy.project_snapshot(root, path)
                        if cached[0] is None:
                            continue
                        if len(self.sources) >= 12:
                            self.sources.pop(next(iter(self.sources)))
                        self.sources[name] = cached
                    snapshots[path] = cached
                except (OSError, RuntimeError, UnicodeError):
                    continue
        return snapshots, [tuple(name.split("/")) for name in known[:80]]

    def record_change(self, draft, instruction):
        paths = ", ".join("/".join(change.path) for change in draft.changes)
        self.edits = (self.edits + [f"{instruction[:200]} · {paths}"])[-12:]
        self.save_index()

    def draft(self, port, model, instruction, reference, images, cancel, progress):
        self.refresh(cancel)
        snapshots, known = self.relevant(instruction, cancel)
        plan = amy.project_edit_plan(port, model, instruction, None, "either", snapshots, known,
                                     cancel=cancel, progress=progress, reference_context=reference,
                                     reference_images=images)
        with self.open() as root:
            changes = amy.validated_project_changes(plan, None, "either", snapshots, root)
            if not changes:
                return None
            parents = frozenset(amy.missing_project_parents(root, changes))
            amy.check_project_state(root, self.identity, changes, parents)
        preview = amy.describe_project_diff(changes)
        report = amy.output_name("project-edit", "txt")
        description = f"Apply the reviewed changes in {self.root}.\nSave a report under {amy.AMY_HOME / 'dump'}."
        return amy.ProjectDraft((), self.identity, tuple(changes), report, preview, parents, description, self.root)


if __name__ == "__main__" and sys.argv[1:] == ["--extract-pdf"]:
    try:
        pdf_worker()
    except Exception as error:
        sys.exit(f"PDF text extraction stopped. {error}")
