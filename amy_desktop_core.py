"""Local services for AMY's Linux desktop app."""

import fcntl
import hashlib
import json
import os
import re
import shutil
import socket
import stat
import struct
import subprocess
import threading
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass, fields
from http.client import HTTPConnection
from pathlib import Path
from tempfile import TemporaryFile
from time import monotonic

import mitan_jarvis as amy

DATA_PARTS = (".local", "share", "mitan-jarvis")
PREFERENCES = "desktop-settings.json"
REPLY_STYLES = {
    "Balanced": "Give a direct answer in plain language. Add examples when they help.",
    "Concise": "Start with the answer. Use a few short sentences unless more detail is requested.",
    "Detailed": "Explain the reasoning in plain language. Use clear steps and a concrete example when useful.",
    "Short, Simple, and Listed": (
        "Use short sentences and simple words. Lead with the answer, then use bullets (•) for key points. "
        "Use numbered lists for ordered steps and short paragraphs where they help explain an idea. "
        "Keep enough detail to answer the question."
    ),
}
OCR_NAMES = {
    "eng": "English", "chi_tra": "Traditional Chinese", "chi_sim": "Simplified Chinese",
    "ind": "Indonesian", "jpn": "Japanese", "kor": "Korean", "vie": "Vietnamese", "tha": "Thai",
    "fra": "French", "spa": "Spanish", "deu": "German", "ita": "Italian", "por": "Portuguese",
    "ara": "Arabic", "hin": "Hindi", "rus": "Russian", "msa": "Malay",
}
TRANSLATION_LANGUAGES = tuple(dict.fromkeys(OCR_NAMES.values()))
MEDIA_TYPES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".wav", ".mp3", ".flac",
               ".ogg", ".m4a", ".mp4", ".webm", ".mkv"}
MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,179}")
REGION = re.compile(r"(-?\d{1,6}),(-?\d{1,6}) (\d{1,5})x(\d{1,5})")
DURABLE_NOTE = re.compile(r"^(?:/remember\s+|(?:please )?remember(?: that)?\s+|"
                         r"(?=i prefer\b|from now on\b)|請記住[：:，, ]*)", re.I)
PRIVATE_NOTE = re.compile(r"\b(?:password|passphrase|private key|api key|access token|seed phrase)\b|密碼|密钥|金鑰", re.I)


class Cancelled(Exception):
    pass


class Cancellation:
    def __init__(self):
        self.event = threading.Event()
        self.lock = threading.Lock()
        self.socket = None

    def stop(self):
        with self.lock:
            self.event.set()
            if self.socket is not None:
                try:
                    self.socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def check(self):
        if self.event.is_set():
            raise Cancelled

    @contextmanager
    def interrupt_socket(self, sock):
        with self.lock:
            self.check()
            self.socket = sock
        try:
            yield
        finally:
            with self.lock:
                self.socket = None


@dataclass(frozen=True)
class Preferences:
    model: str = ""
    style: str = "Balanced"
    style_details: str = ""
    language: str = "en"
    chinese: bool = False
    theme: str = "Dark"
    font: str = ""
    size: int = 11
    web: bool = True
    auto_web: bool = False
    speak: bool = True

    def __post_init__(self):
        if not isinstance(self.model, str) or (self.model and not local_model_name(self.model)):
            raise ValueError("Choose an installed local Ollama model.")
        if self.style not in REPLY_STYLES or self.theme not in ("Dark", "Light"):
            raise ValueError("Unknown reply style or theme.")
        if (self.language not in ("en", "zh") or (self.language == "zh" and not self.chinese)
                or any(type(value) is not bool for value in (self.chinese, self.web, self.auto_web, self.speak))):
            raise ValueError("Choose a language and valid on/off settings.")
        if not isinstance(self.font, str) or len(self.font) > 120 or type(self.size) is not int or not 9 <= self.size <= 24:
            raise ValueError("Choose a font size between 9 and 24.")
        if not isinstance(self.style_details, str) or len(self.style_details) > 500:
            raise ValueError("Keep custom reply preferences within 500 characters.")

    @property
    def reply_style(self):
        return (REPLY_STYLES[self.style] + " " + self.style_details).strip()


def load_preferences():
    try:
        with amy.home_directory(DATA_PARTS) as directory:
            content, _ = amy.snapshot(directory, PREFERENCES, 65_536)
    except FileNotFoundError:
        return Preferences()
    if content is None:
        return Preferences()
    values = json.loads(content)
    if not isinstance(values, dict):
        raise ValueError("Desktop settings must contain a JSON object.")
    return Preferences(**{field.name: values[field.name] for field in fields(Preferences) if field.name in values})


def save_preferences(preferences):
    data = (json.dumps(asdict(preferences), ensure_ascii=False, indent=2) + "\n").encode()
    with amy.home_directory(DATA_PARTS, created=[]) as directory:
        fcntl.flock(directory, fcntl.LOCK_EX | fcntl.LOCK_NB)
        amy.replace_snapshot(directory, PREFERENCES, amy.snapshot(directory, PREFERENCES, 65_536), data, 65_536)


@dataclass(frozen=True)
class Notes:
    lines: tuple[str, ...]
    original: tuple


def load_notes():
    content, stamp = amy.memory_snapshot()
    return Notes(tuple((content or b"").decode().splitlines()), (content, stamp))


def save_notes(before, lines):
    amy.save_memory_notes(lines, expected=before.original)


def suggest_note(question):
    match = DURABLE_NOTE.match(question)
    if not match:
        return None
    return question[match.end():].strip() or None


def validate_note(text):
    text = " ".join(text.split())
    if not text or len(text) > 500 or amy.CONTROL_CHARS.search(text):
        raise ValueError("Use a note of 1–500 characters.")
    if PRIVATE_NOTE.search(text):
        raise ValueError("Keep passwords, keys and other credentials out of AMY's notes.")
    return text


@dataclass(frozen=True)
class SavedItem:
    folder: tuple[str, ...]
    name: str
    stamp: tuple
    kind: str

    @property
    def path(self):
        return Path.home().joinpath(*self.folder, self.name)


def item_stamp(directory, name):
    info = os.stat(name, dir_fd=directory, follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode) or not amy.project_entry_owned(info) or info.st_nlink != 1:
        raise RuntimeError(f"AMY cannot manage {name!r} as an owned regular file.")
    return amy.file_stamp(info)


def list_saved_items():
    items = []
    for folder in (("AMY", "screenshots"), ("AMY", "dump")):
        try:
            with amy.home_directory(folder) as directory:
                for name in os.listdir(directory):
                    suffix = Path(name).suffix.casefold()
                    if name.startswith(".") or (suffix not in MEDIA_TYPES and not (folder[-1] == "dump" and suffix == ".txt")):
                        continue
                    try:
                        stamp = item_stamp(directory, name)
                    except (FileNotFoundError, RuntimeError):
                        continue
                    kind = "Report" if suffix == ".txt" else "Screenshot" if folder[-1] == "screenshots" else "Media"
                    items.append(SavedItem(folder, name, stamp, kind))
        except FileNotFoundError:
            continue
    return sorted(items, key=lambda item: item.stamp[4], reverse=True)


def load_profile_item():
    try:
        with amy.home_directory(DATA_PARTS) as directory:
            content, stamp = amy.snapshot(directory, "profile.json")
    except FileNotFoundError:
        return None, ""
    if content is None:
        return None, ""
    return SavedItem(DATA_PARTS, "profile.json", stamp, "Profile"), content.decode()


def verify_item(item):
    with amy.home_directory(item.folder) as directory:
        if item_stamp(directory, item.name) != item.stamp:
            raise RuntimeError("This file changed since the list was loaded. Refresh first.")
    return item.path


def delete_item(item):
    with amy.home_directory(item.folder) as directory:
        fcntl.flock(directory, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if item_stamp(directory, item.name) != item.stamp:
            raise RuntimeError("This file changed since the list was loaded. Refresh first.")
        staged = "." + amy.output_name("delete", "pending")
        amy.rename_project_entry(directory, item.name, directory, staged)
        try:
            if item_stamp(directory, staged)[:-1] != item.stamp[:-1]:
                raise RuntimeError("The selected file changed during deletion.")
            os.unlink(staged, dir_fd=directory)
        except BaseException:
            try:
                amy.rename_project_entry(directory, staged, directory, item.name)
            except OSError as error:
                raise RuntimeError(f"An external change blocked restoration. Inspect {item.path.with_name(staged)}.") from error
            raise
        if amy.path_exists(directory, item.name) or amy.path_exists(directory, staged):
            raise RuntimeError("The selected filename reappeared during verification. Refresh the list.")
    return item.path


def local_model_name(name):
    return (isinstance(name, str) and MODEL_NAME.fullmatch(name) is not None
            and not name.casefold().endswith((":cloud", "-cloud")))


class LocalOllama:
    def __init__(self, port):
        self.port = port
        self.process = None
        self.log = None
        self.model_details = {}
        self.model_digests = {}
        self.models_checked = 0.0

    def call(self, path, cancel, payload=None, *, timeout=5):
        with closing(HTTPConnection("127.0.0.1", self.port, timeout=timeout)) as connection:
            cancel.check()
            connection.connect()
            with cancel.interrupt_socket(connection.sock):
                body = json.dumps(payload) if payload is not None else None
                connection.request("POST" if body is not None else "GET", path, body,
                                   {"Content-Type": "application/json"})
                with connection.getresponse() as response:
                    if response.status != 200:
                        raise RuntimeError(f"Ollama {path} returned HTTP {response.status}. Refresh your model list.")
                    data = response.read(2_000_001)
        if len(data) > 2_000_000:
            raise RuntimeError("Ollama returned more model data than AMY can read.")
        result = json.loads(data)
        if not isinstance(result, dict):
            raise RuntimeError("The local port did not return an Ollama response.")
        return result

    def ensure_running(self, cancel, progress):
        try:
            version = self.call("/api/version", cancel)
        except ConnectionRefusedError:
            version = None
        if version is not None:
            if not isinstance(version.get("version"), str):
                raise RuntimeError("This port is occupied by another application. Choose the Ollama port.")
            return
        executable = shutil.which("ollama")
        if not executable:
            raise RuntimeError("Ollama is missing. See the Linux Desktop guide.")
        if self.process is None or self.process.poll() is not None:
            self.close()
            progress("Starting local Ollama…")
            environment = {**os.environ, "OLLAMA_HOST": f"127.0.0.1:{self.port}", "OLLAMA_NO_CLOUD": "1"}
            environment.setdefault("OLLAMA_CONTEXT_LENGTH", "4096")
            existing = Path.home() / ".local/share/jarvis-models"
            if existing.is_dir():
                environment.setdefault("OLLAMA_MODELS", str(existing))
            amy.WORK_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.log = TemporaryFile(dir=amy.WORK_DIR)
            self.process = subprocess.Popen([executable, "serve"], stdin=subprocess.DEVNULL,
                                            stdout=self.log, stderr=subprocess.STDOUT,
                                            env=environment, start_new_session=True)
        deadline = monotonic() + 12
        while monotonic() < deadline:
            cancel.check()
            try:
                version = self.call("/api/version", cancel)
                if isinstance(version.get("version"), str):
                    return
            except ConnectionRefusedError:
                pass
            if self.process.poll() is not None:
                self.log.seek(max(0, self.log.seek(0, os.SEEK_END) - 1800))
                raise RuntimeError("Ollama did not start. " + self.log.read().decode(errors="replace").strip())
            cancel.event.wait(0.15)
        raise RuntimeError("Local Ollama did not become ready. Try Refresh models.")

    def models(self, cancel, progress, *, refresh=True):
        if refresh or monotonic() - self.models_checked >= 30:
            self.ensure_running(cancel, progress)
        try:
            result = self.call("/api/tags", cancel)
        except ConnectionRefusedError:
            self.ensure_running(cancel, progress)
            result = self.call("/api/tags", cancel)
        if not isinstance(result.get("models"), list):
            raise RuntimeError("Ollama's downloaded-model list is unavailable.")
        models = {}
        digests = {}
        for item in result["models"]:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("model")
            capabilities = item.get("capabilities") or ()
            if (local_model_name(name) and not item.get("remote_host") and not item.get("remote_model")
                    and (not capabilities or "completion" in capabilities)):
                models[name] = tuple(capabilities)
                digest = item.get("digest")
                if isinstance(digest, str) and digest:
                    digests[name] = digest
        self.model_details = {
            name: details for name, details in self.model_details.items()
            if not refresh and name in digests and self.model_digests.get(name) == digests[name]
        }
        self.model_digests = digests
        self.models_checked = monotonic()
        return dict(sorted(models.items(), key=lambda pair: pair[0].casefold()))

    def require_model(self, model, cancel, progress, *, vision=False):
        if not model:
            raise RuntimeError("Tick an installed model in Settings → Models, then try again.")
        cancel.check()
        models = self.models(cancel, progress, refresh=False)
        if model not in models:
            raise RuntimeError(f"{model} is unavailable on this Ollama server. Refresh the list and choose a local model.")
        details = self.model_details.get(model)
        if details is None:
            details = self.call("/api/show", cancel, {"model": model})
            self.model_details[model] = details
        if details.get("remote_host") or details.get("remote_model"):
            raise RuntimeError("Choose a downloaded model that runs locally.")
        capabilities = details.get("capabilities") or models[model]
        if capabilities and "completion" not in capabilities:
            raise RuntimeError(f"{model} cannot generate chat replies. Choose a chat model.")
        if vision and "vision" not in capabilities:
            raise RuntimeError(f"{model} cannot read images. Select a local vision model, such as qwen3.5:4b.")
        return capabilities

    def close(self):
        self.model_details.clear()
        self.model_digests.clear()
        self.models_checked = 0.0
        if self.process is not None:
            amy.stop_voice_process(self.process)
            self.process = None
        if self.log is not None:
            self.log.close()
            self.log = None


@contextmanager
def temporary_directory():
    with amy.home_directory(("AMY", "dump", "temp"), created=[]):
        yield amy.AMY_HOME / "dump" / "temp"


def run_local_tool(argv, cancel, *, timeout, limit, data=None):
    executable = shutil.which(argv[0])
    if not executable:
        raise RuntimeError(f"Install {argv[0]} to use screen tools. See the Linux Desktop guide.")
    cancel.check()
    with temporary_directory() as scratch, TemporaryFile(dir=scratch) as output, \
            TemporaryFile(dir=scratch) as errors, TemporaryFile(dir=scratch) as incoming:
        if data is not None:
            incoming.write(data)
            incoming.seek(0)
        with subprocess.Popen([executable, *argv[1:]], stdin=incoming if data is not None else subprocess.DEVNULL, stdout=output,
                              stderr=errors, start_new_session=True) as process:
            deadline = monotonic() + timeout
            try:
                while process.poll() is None:
                    cancel.check()
                    if monotonic() > deadline or output.tell() > limit:
                        raise RuntimeError(f"{argv[0]} exceeded its time or output limit.")
                    cancel.event.wait(0.04)
            finally:
                amy.stop_voice_process(process)
            output.seek(0)
            errors.seek(0)
            if process.returncode:
                if argv[0] == "slurp" and not errors.read(1):
                    raise Cancelled
                errors.seek(0)
                raise RuntimeError(f"{argv[0]}: " + errors.read(600).decode(errors="replace").strip())
            result = output.read(limit + 1)
            if len(result) > limit:
                raise RuntimeError(f"{argv[0]} exceeded its output limit.")
            return result


def validate_region(region):
    match = REGION.fullmatch(region)
    if not match:
        raise ValueError("The screen selector returned an invalid area.")
    x, y, width, height = map(int, match.groups())
    if not 2 <= width <= 8192 or not 2 <= height <= 8192:
        raise ValueError("Drag a region between 2 and 8192 pixels on each side.")
    return f"{x},{y} {width}x{height}"


def select_region(cancel):
    result = run_local_tool(["slurp", "-f", "%x,%y %wx%h"], cancel, timeout=90, limit=120)
    return validate_region(result.decode().strip())


def capture_region(region, cancel, *, max_side=1800):
    region = validate_region(region)
    width, height = (int(value) for value in region.split()[1].split("x"))
    scale = min(1.0, max_side / max(width, height))
    image = run_local_tool(["grim", "-g", region, "-s", f"{scale:.6f}", "-l", "1", "-"],
                           cancel, timeout=8, limit=16_000_000)
    if len(image) < 33 or image[:16] != b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR":
        raise RuntimeError("The compositor did not return a PNG image.")
    if max(struct.unpack(">II", image[16:24])) > max_side + 2:
        raise RuntimeError("The capture exceeded its expected dimensions.")
    return image


@dataclass(frozen=True)
class ScanFrame:
    fingerprint: bytes
    text: str
    image: bytes = b""


def ocr_languages():
    executable = shutil.which("tesseract")
    if executable is None:
        return {}
    try:
        result = subprocess.run([executable, "--list-langs"], capture_output=True, text=True,
                                errors="replace", timeout=2, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if result.returncode:
        return {}
    return {code: OCR_NAMES.get(code, code) for code in result.stdout.splitlines()
            if code not in ("osd", "equ") and re.fullmatch(r"[a-z][a-z0-9_/-]{1,39}", code)}


def scan_frame(region, previous, language, cancel, *, on_image=None):
    image = capture_region(region, cancel)
    fingerprint = hashlib.sha256(image).digest()
    if previous is not None and fingerprint == previous.fingerprint:
        return previous
    if on_image is not None:
        on_image(image)
    if language in ("en", "zh"):
        legacy = amy.screen_ocr_tool(language, "")
        executable = legacy[0] if legacy else None
        language = "chi_tra" if language == "zh" else "eng"
    else:
        executable = shutil.which("tesseract")
    text = amy.read_screen_text(image, (executable, language)).strip() if executable and language else ""
    cancel.check()
    return ScanFrame(fingerprint, text, image)


def save_region_image(image, filename):
    with amy.home_directory(("AMY", "screenshots"), created=[]) as directory:
        amy.write_output_file(directory, filename, image)
    return amy.AMY_HOME / "screenshots" / filename
