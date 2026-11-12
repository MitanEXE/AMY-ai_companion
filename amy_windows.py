"""Native Windows file, screen and console operations for AMY."""

import ctypes
import hashlib
import os
import queue
import re
import secrets
import stat
import sys
from contextlib import ExitStack, contextmanager
from ctypes import wintypes
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from time import monotonic


def data_directory():
    local = os.environ.get("LOCALAPPDATA")
    return (Path(local) if local else Path.home() / "AppData" / "Local") / "AMY"


def valid_component(name):
    stem = name.split(".", 1)[0].rstrip().upper()
    return (
        bool(name) and name not in {".", ".."} and not name.endswith((" ", "."))
        and not any(character in '<>:"/\\|?*' or ord(character) < 32 for character in name)
        and stem not in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
        and re.fullmatch(r"(?:COM|LPT)[1-9¹²³]", stem) is None
    )


if os.name == "nt":
    import msvcrt

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)

    def bind(name, result, *arguments):
        function = getattr(kernel, name)
        function.restype = result
        function.argtypes = arguments
        return function

    create_file = bind(
        "CreateFileW", wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    )
    close_handle = bind("CloseHandle", wintypes.BOOL, wintypes.HANDLE)
    get_file_info = bind("GetFileInformationByHandle", wintypes.BOOL, wintypes.HANDLE, wintypes.LPVOID)
    set_file_info = bind(
        "SetFileInformationByHandle", wintypes.BOOL, wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
    )
    create_mutex = bind("CreateMutexW", wintypes.HANDLE, wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    wait_for_handle = bind("WaitForSingleObject", wintypes.DWORD, wintypes.HANDLE, wintypes.DWORD)
    release_mutex = bind("ReleaseMutex", wintypes.BOOL, wintypes.HANDLE)


READ = 0x80000000
WRITE = 0x40000000
DELETE = 0x00010000
READ_ATTRIBUTES = 0x80
SHARE_READ = 1
CREATE_NEW = 1
OPEN_EXISTING = 3
OPEN_REPARSE_POINT = 0x00200000
BACKUP_SEMANTICS = 0x02000000
INVALID_HANDLE = ctypes.c_void_p(-1).value


class HandleInfo(ctypes.Structure):
    _fields_ = [
        ("attributes", wintypes.DWORD),
        ("creation", wintypes.FILETIME),
        ("access", wintypes.FILETIME),
        ("modified", wintypes.FILETIME),
        ("volume", wintypes.DWORD),
        ("size_high", wintypes.DWORD),
        ("size_low", wintypes.DWORD),
        ("links", wintypes.DWORD),
        ("index_high", wintypes.DWORD),
        ("index_low", wintypes.DWORD),
    ]

    @property
    def st_dev(self):
        return self.volume

    @property
    def st_ino(self):
        return (self.index_high << 32) | self.index_low

    @property
    def st_mode(self):
        kind = stat.S_IFDIR if self.attributes & stat.FILE_ATTRIBUTE_DIRECTORY else stat.S_IFREG
        permissions = 0o444 if self.attributes & stat.FILE_ATTRIBUTE_READONLY else 0o666
        return kind | permissions

    @property
    def st_size(self):
        return (self.size_high << 32) | self.size_low

    @property
    def st_mtime_ns(self):
        return ((self.modified.dwHighDateTime << 32) | self.modified.dwLowDateTime) * 100

    @property
    def st_ctime_ns(self):
        return ((self.creation.dwHighDateTime << 32) | self.creation.dwLowDateTime) * 100

    @property
    def st_nlink(self):
        return self.links


class RenameInfo(ctypes.Structure):
    _fields_ = [
        ("replace", wintypes.DWORD),
        ("root", wintypes.HANDLE),
        ("length", wintypes.DWORD),
        ("name", wintypes.WCHAR * 1),
    ]


def _open(path, access, share, disposition=OPEN_EXISTING, *, directory=False):
    flags = OPEN_REPARSE_POINT | (BACKUP_SEMANTICS if directory else 0)
    handle = create_file(str(path), access, share, None, disposition, flags, None)
    if handle == INVALID_HANDLE:
        raise ctypes.WinError(ctypes.get_last_error())
    return handle


def _inspect(handle):
    info = HandleInfo()
    if not get_file_info(handle, ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    return info


@dataclass(frozen=True)
class Directory:
    path: Path
    identity: tuple[int, int]


@contextmanager
def _directory(path):
    # Deny write/delete opens on the directory itself while using its path.
    handle = _open(path, READ_ATTRIBUTES, SHARE_READ, directory=True)
    try:
        info = _inspect(handle)
        if info.attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT or not stat.S_ISDIR(info.st_mode):
            raise NotADirectoryError(f"AMY needs a real directory without links or junctions: {path}")
        yield Directory(path, (info.st_dev, info.st_ino))
    finally:
        close_handle(handle)


@contextmanager
def home_directory(parts, *, parent=None, created=None):
    with ExitStack() as stack:
        if parent is None:
            home = Path.home()
            if not home.is_absolute() or home.drive.startswith("\\\\"):
                raise RuntimeError("AMY needs a Windows home folder on a local drive for project files.")
            current = stack.enter_context(_directory(Path(home.anchor)))
            for part in home.parts[1:]:
                current = stack.enter_context(_directory(current.path / part))
        else:
            current = parent
        walked = []
        for part in parts:
            if not valid_component(part):
                raise ValueError(f"Invalid Windows directory name: {part!r}")
            walked.append(part)
            path = current.path / part
            try:
                current = stack.enter_context(_directory(path))
            except FileNotFoundError:
                if created is None:
                    raise
                try:
                    path.mkdir()
                except FileExistsError:
                    pass
                else:
                    created.append(tuple(walked))
                current = stack.enter_context(_directory(path))
        yield current


def entry_info(directory, name):
    if not valid_component(name):
        raise FileNotFoundError(name)
    path = directory.path / name
    handle = _open(path, READ_ATTRIBUTES, 7, directory=True)
    try:
        info = _inspect(handle)
        if info.attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise NotADirectoryError(f"AMY skips linked files and junctions: {path}")
        return info
    finally:
        close_handle(handle)


def path_exists(directory, name):
    if not valid_component(name):
        raise ValueError(f"Invalid Windows filename: {name!r}")
    try:
        (directory.path / name).lstat()
    except FileNotFoundError:
        return False
    return True


def walk_directory(directory, relative=()):
    children, names = [], []
    for name in os.listdir(directory.path):
        try:
            info = entry_info(directory, name)
        except (FileNotFoundError, NotADirectoryError):
            continue
        (children if stat.S_ISDIR(info.st_mode) else names).append(name)
    yield relative, children, names, directory
    for name in children:
        try:
            with home_directory((name,), parent=directory) as child:
                yield from walk_directory(child, (*relative, name))
        except (FileNotFoundError, NotADirectoryError):
            continue


class LockedFile:
    def __init__(self, handle, stream, path):
        self.handle, self.stream, self.path = handle, stream, path
        self.removed = False

    def info(self):
        info = _inspect(self.handle)
        if info.attributes & (stat.FILE_ATTRIBUTE_REPARSE_POINT | stat.FILE_ATTRIBUTE_DIRECTORY) or info.links != 1:
            raise RuntimeError(f"AMY needs an ordinary, unlinked file: {self.path}")
        return info

    def read(self, limit):
        info = self.info()
        if info.st_size > limit:
            raise RuntimeError(f"File exceeds the size limit: {self.path}")
        self.stream.seek(0)
        data = self.stream.read(limit + 1)
        if len(data) != info.st_size:
            raise RuntimeError(f"Could not read the expected bytes from {self.path}")
        return data, info

    def write_verified(self, data):
        self.info()
        self.stream.seek(0)
        self.stream.write(data)
        self.stream.truncate()
        self.stream.flush()
        os.fsync(self.stream.fileno())
        if self.read(len(data))[0] != data:
            raise RuntimeError(f"Could not verify the bytes written to {self.path}")

    def publish(self, name):
        if not valid_component(name):
            raise ValueError(f"Invalid Windows filename: {name!r}")
        target = self.path.with_name(name)
        encoded = str(target).encode("utf-16-le")
        offset = RenameInfo.name.offset
        buffer = ctypes.create_string_buffer(max(ctypes.sizeof(RenameInfo), offset + len(encoded) + 2))
        info = RenameInfo.from_buffer(buffer)
        info.length = len(encoded)
        ctypes.memmove(ctypes.addressof(buffer) + offset, encoded, len(encoded))
        # FileRenameInfo with ReplaceIfExists false only publishes a new file.
        if not set_file_info(self.handle, 3, buffer, len(buffer)):
            raise ctypes.WinError(ctypes.get_last_error())
        self.path = target

    def discard(self):
        if not self.removed:
            remove = ctypes.c_ubyte(1)
            if not set_file_info(self.handle, 4, ctypes.byref(remove), ctypes.sizeof(remove)):
                raise ctypes.WinError(ctypes.get_last_error())
            self.removed = True


@contextmanager
def _file(path, access, share, disposition=OPEN_EXISTING):
    if not valid_component(path.name):
        raise ValueError(f"Invalid Windows filename: {path.name!r}")
    handle = _open(path, access, share, disposition)
    try:
        writable = bool(access & WRITE)
        flags = os.O_BINARY | (os.O_RDWR if writable else os.O_RDONLY)
        descriptor = msvcrt.open_osfhandle(handle, flags)
    except BaseException:
        close_handle(handle)
        raise
    try:
        stream = os.fdopen(descriptor, "r+b" if writable else "rb")
    except BaseException:
        os.close(descriptor)
        raise
    with stream:
        item = LockedFile(handle, stream, path)
        item.info()
        yield item


def read_owned_bytes(directory, name, limit):
    with _file(directory.path / name, READ, SHARE_READ) as file:
        return file.read(limit)


def lock_existing_file(directory, name):
    return _file(directory.path / name, READ | WRITE, 0)


@contextmanager
def staged_file(directory, data):
    staged = directory.path / (".amy-stage-" + secrets.token_hex(10))
    with _file(staged, READ | WRITE | DELETE, 0, CREATE_NEW) as file:
        try:
            file.write_verified(data)
            yield file
        except BaseException:
            file.discard()
            raise
        finally:
            if file.path == staged:
                file.discard()


def write_output_file(directory, name, data):
    with staged_file(directory, data) as file:
        file.publish(name)
        if file.read(len(data))[0] != data:
            raise RuntimeError(f"Could not verify the bytes written to {file.path}")


@contextmanager
def project_lock(directory):
    identity = hashlib.sha256(repr(directory.identity).encode("ascii")).hexdigest()[:24]
    handle = create_mutex(None, False, "Local\\AMY.Projects." + identity)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    acquired = False
    try:
        status = wait_for_handle(handle, 0)
        acquired = status in (0, 0x80)
        if status == 0x102:
            raise RuntimeError("Another AMY session is updating this Projects folder. Try again shortly.")
        if not acquired:
            raise ctypes.WinError(ctypes.get_last_error())
        if status == 0x80:
            raise RuntimeError("A previous AMY change was interrupted. Check your project and any backup in AMY/dump.")
        yield
    finally:
        if acquired:
            release_mutex(handle)
        close_handle(handle)


@contextmanager
def screen_session():
    try:
        from mss import MSS
        from mss.exception import ScreenShotError
    except ImportError as error:
        raise RuntimeError("Install requirements-windows.txt for Windows screen reading.") from error
    try:
        with MSS() as capture:
            yield capture
    except ScreenShotError as error:
        raise RuntimeError("Windows could not capture the display. Open AMY in your desktop session.") from error


def screens():
    with screen_session() as capture:
        result = {}
        for number, monitor in enumerate(capture.monitors[1:], 1):
            left, top, width, height = (monitor[key] for key in ("left", "top", "width", "height"))
            result[number] = {
                "name": f"Display {number}",
                "width": width, "height": height, "scale": 1,
                "focused": left == 0 and top == 0,
                "region": {"left": left, "top": top, "width": width, "height": height},
            }
    if not result:
        raise RuntimeError("Windows did not report a connected display. Open AMY on your desktop.")
    return result


def capture_screen(monitor, max_side):
    try:
        from PIL import Image
    except ImportError as error:
        raise RuntimeError("Install requirements-windows.txt for Windows screen reading.") from error
    region = monitor["region"]
    width, height = region["width"], region["height"]
    if not (0 < width <= 16384 and 0 < height <= 16384 and width * height <= 33_554_432):
        raise RuntimeError("Windows reported an unsupported display size.")
    with screen_session() as capture:
        shot = capture.grab(region)
    image = Image.frombytes("RGB", (width, height), shot.rgb)
    image.thumbnail((max_side, max_side), Image.Resampling.BILINEAR)
    with BytesIO() as output:
        image.save(output, format="PNG", compress_level=1)
        return output.getvalue()


_keys = []


def poll_keyboard():
    if not sys.stdin.isatty():
        return None
    while msvcrt.kbhit():
        key = msvcrt.getwch()
        if key in {"\x00", "\xe0"}:
            msvcrt.getwch()
        elif key == "\r":
            command = "".join(_keys).strip()
            _keys.clear()
            if command:
                print(flush=True)
            return command
        elif key == "\b":
            if _keys:
                _keys.pop()
                print("\b \b", end="", flush=True)
        elif key == "\x03":
            raise KeyboardInterrupt
        elif key.isprintable():
            _keys.append(key)
            if len(_keys) > 8192:
                _keys.clear()
                raise RuntimeError("Keyboard command is too long. Voice mode stopped.")
            print(key, end="", flush=True)
    return None


def clear_keyboard():
    if _keys:
        _keys.clear()
        print(flush=True)


def record_microphone(destination, segment, vad):
    try:
        import sounddevice
    except ImportError as error:
        raise RuntimeError("Run --setup to install Windows microphone support.") from error
    frames = queue.Queue(maxsize=24)

    def receive(data, count, timing, status):
        try:
            frames.put_nowait(bytes(data))
        except queue.Full:
            pass

    try:
        with sounddevice.RawInputStream(
            samplerate=16000, blocksize=480, channels=1, dtype="int16", callback=receive,
        ):
            destination.with_suffix(".ready").touch()
            finish = destination.with_suffix(".finish")
            last_audio = monotonic()
            while not finish.exists():
                try:
                    frame = frames.get(timeout=0.1)
                except queue.Empty:
                    if monotonic() - last_audio > 10:
                        raise RuntimeError("Windows sent no microphone samples for 10 seconds.")
                    continue
                last_audio = monotonic()
                if len(frame) != 960:
                    raise RuntimeError("Windows returned an unexpected microphone frame size.")
                if segment.feed(frame, vad.is_speech(frame, 16000)):
                    break
    except sounddevice.PortAudioError as error:
        raise RuntimeError(f"Windows microphone error. Check the default input and microphone permissions. {error}") from error
