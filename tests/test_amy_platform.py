"""Exercise AMY without downloading a model or touching the real user profile."""

import json
import os
import subprocess
import sys
import threading
import unittest
from contextlib import contextmanager, nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.util import find_spec
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import amy_windows
import mitan_jarvis as amy


APP = Path(amy.__file__).resolve()
HTML = "<!doctype html>\r\n<html><body>Hello</body></html>\r\n"


class LocalOllama(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        self.assert_chat()
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if isinstance(request.get("format"), dict):
            project = json.loads(request["messages"][-1]["content"])
            edits = ([{"before": "", "after": HTML}] if project["mode"] == "create"
                     else [{"before": "Hello", "after": "Updated"}])
            plan = {"files": [{"path": project["target"], "edits": edits}]}
            data = json.dumps({"message": {"content": json.dumps(plan)}, "done": True}).encode()
            content_type = "application/json"
        else:
            events = [
                {"message": {"content": "Local test reply."}, "done": False},
                {"message": {"content": ""}, "done": True, "done_reason": "stop"},
            ]
            data = "".join(json.dumps(event) + "\n" for event in events).encode()
            content_type = "application/x-ndjson"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def assert_chat(self):
        if self.path != "/api/chat":
            raise AssertionError(f"Unexpected test endpoint: {self.path}")


@contextmanager
def ollama_fixture():
    with ThreadingHTTPServer(("127.0.0.1", 0), LocalOllama) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server.server_port
        finally:
            server.shutdown()
            thread.join()


def run_amy(home, port, *lines):
    local = home / "AppData" / "Local"
    environment = os.environ.copy()
    environment.update({"HOME": str(home), "USERPROFILE": str(home), "LOCALAPPDATA": str(local), "PYTHONUTF8": "1"})
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(APP), "--port", str(port), "--model", "qwen3.5:4b"],
        input="\n".join((*lines, "/quit", "")), capture_output=True, encoding="utf-8", env=environment, timeout=20,
    )


class TerminalTests(unittest.TestCase):
    def test_offline_chat_clock_and_persistent_memory(self):
        with TemporaryDirectory(prefix="amy-test-") as temporary, ollama_fixture() as port:
            home = Path(temporary)
            result = run_amy(home, port, "/web off", "What time is it?", "What is 12 * 8?",
                             "Give a short greeting.", "/remember I prefer brief answers.", "y")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertRegex(result.stdout, r"AMY: It's [^\n]+\(Asia/Taipei, UTC\+08:00\)")
            self.assertIn("12 * 8 = 96", result.stdout)
            self.assertIn("Local test reply.", result.stdout)
            self.assertIn("Saved and checked.", result.stdout)
            again = run_amy(home, port, "/memories")
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertIn("I prefer brief answers.", again.stdout)

    def test_cancel_create_edit_and_locate_a_file(self):
        with TemporaryDirectory(prefix="amy-test-") as temporary, ollama_fixture() as port:
            home = Path(temporary)
            path = home / "Projects" / "surprise.html"
            request = "Create me an HTML file that can surprise me"
            cancelled = run_amy(home, port, request, "n")
            self.assertEqual(cancelled.returncode, 0, cancelled.stderr)
            self.assertIn("Edit cancelled.", cancelled.stdout)
            self.assertFalse(path.exists())
            created = run_amy(home, port, request, "y", "/where surprise.html")
            self.assertEqual(created.returncode, 0, created.stderr)
            self.assertIn("Saved and verified:", created.stdout)
            self.assertIn("(verified on disk)", created.stdout)
            self.assertEqual(path.read_bytes(), HTML.encode())
            edited = run_amy(home, port, "/file surprise.html Update Hello to Updated", "y")
            self.assertEqual(edited.returncode, 0, edited.stderr)
            self.assertIn("Updated and verified:", edited.stdout)
            self.assertEqual(path.read_bytes(), HTML.replace("Hello", "Updated").encode())
            if sys.platform == "win32":
                backups = list((home / "AMY" / "dump").glob("*-original-1.txt"))
                self.assertEqual([item.read_bytes() for item in backups], [HTML.encode()])


class ProjectSafetyTests(unittest.TestCase):
    def test_windows_disallows_device_names_and_alternate_streams(self):
        for name in ("NUL.txt", "COM1.py", "LPT¹.txt", "a.txt:stream", "x.", "x ", "..", r"a\b", "a/b"):
            with self.subTest(name=name):
                self.assertFalse(amy_windows.valid_component(name))
        self.assertTrue(amy_windows.valid_component("hello world.txt"))

    def test_refuses_a_hard_link(self):
        with TemporaryDirectory(prefix="amy-test-") as temporary:
            home = Path(temporary)
            projects = home / "Projects"
            projects.mkdir()
            original = home / "outside.txt"
            original.write_bytes(b"outside\n")
            os.link(original, projects / "linked.txt")
            with patch.object(Path, "home", return_value=home), amy.home_directory(("Projects",)) as folder:
                with self.assertRaises(RuntimeError):
                    amy.project_snapshot(folder, ("linked.txt",))

    def test_restore_existing_bytes_and_remove_new_file_when_report_fails(self):
        with TemporaryDirectory(prefix="amy-test-") as temporary:
            home = Path(temporary)
            projects = home / "Projects"
            projects.mkdir()
            existing = projects / "existing.txt"
            existing.write_bytes(b"old\r\n")
            output = amy.write_output_file
            report = "20260101-120000-project-edit-0123abcd.txt"

            def fail_report(directory, name, data):
                if name == report:
                    raise OSError("simulated report write failure")
                return output(directory, name, data)

            with patch.object(Path, "home", return_value=home), patch.multiple(
                amy, PROJECTS_ROOT=projects, AMY_HOME=home / "AMY", write_output_file=fail_report,
            ):
                with amy.home_directory(("Projects",)) as folder:
                    identity = amy.scope_identity(folder)
                    old, stamp = amy.project_snapshot(folder, ("existing.txt",))
                changes = [
                    amy.ProjectChange(("existing.txt",), old, stamp, b"new\r\n"),
                    amy.ProjectChange(("created.txt",), None, None, b"new file\r\n"),
                ]
                with self.assertRaisesRegex(OSError, "simulated report"):
                    amy.apply_project_changes((), identity, changes, report, amy.describe_project_diff(changes), set())
            self.assertEqual(existing.read_bytes(), b"old\r\n")
            self.assertFalse((projects / "created.txt").exists())
            self.assertEqual(list(projects.glob(".amy-stage-*")), [])

    @unittest.skipUnless(sys.platform == "win32", "Native Windows filesystem test")
    def test_existing_file_cannot_be_replaced_by_a_new_file_publish(self):
        with TemporaryDirectory(prefix="amy-test-") as temporary:
            home = Path(temporary)
            path = home / "Projects" / "existing.txt"
            path.parent.mkdir()
            path.write_bytes(b"original")
            with patch.object(Path, "home", return_value=home), amy.home_directory(("Projects",)) as folder:
                with self.assertRaises(OSError):
                    amy.write_output_file(folder, "existing.txt", b"replacement")
            self.assertEqual(path.read_bytes(), b"original")
            self.assertEqual(list(path.parent.glob(".amy-stage-*")), [])

    @unittest.skipUnless(sys.platform == "win32", "Native Windows filesystem test")
    def test_windows_project_paths_and_duplicates(self):
        with TemporaryDirectory(prefix="amy-test-") as temporary:
            projects = Path(temporary) / "Projects"
            with patch.object(amy, "PROJECTS_ROOT", projects):
                self.assertEqual(amy.project_parts(str(projects / "notes.txt"), ()), ("notes.txt",))
                for filename in (r"C:notes.txt", r"..\notes.txt", "CON.txt", "notes.txt:hidden"):
                    with self.subTest(filename=filename), self.assertRaises(ValueError):
                        amy.project_parts(filename, ())
                file = {"path": "Notes.txt", "edits": [{"before": "", "after": "test"}]}
                plan = {"files": [file, {**file, "path": "notes.txt"}]}
                with self.assertRaisesRegex(RuntimeError, "duplicate"):
                    amy.validated_project_changes(plan, None, "create", {}, None)


class DeviceFixtureTests(unittest.TestCase):
    @unittest.skipUnless(find_spec("PIL"), "Install Pillow to check image conversion")
    def test_windows_screen_selection_and_resize(self):
        from PIL import Image

        def capture(region):
            return SimpleNamespace(rgb=b"\x30\x60\x90" * (region["width"] * region["height"]))

        display = SimpleNamespace(
            monitors=[
                {"left": -160, "top": 0, "width": 320, "height": 90},
                {"left": -160, "top": 0, "width": 160, "height": 90},
                {"left": 0, "top": 0, "width": 160, "height": 90},
            ],
            grab=capture,
        )
        with patch.object(amy_windows, "screen_session", return_value=nullcontext(display)):
            monitors = amy_windows.screens()
            self.assertFalse(monitors[1]["focused"])
            self.assertTrue(monitors[2]["focused"])
            png = amy_windows.capture_screen(monitors[1], 80)
        with Image.open(BytesIO(png)) as image:
            self.assertEqual((image.format, image.size), ("PNG", (80, 45)))

    def test_windows_microphone_reuses_pause_detector(self):
        class Input:
            def __init__(self, *, callback, **_):
                self.callback = callback

            def __enter__(self):
                for frame in [b"\x01" * 960] * 6 + [bytes(960)] * 3:
                    self.callback(frame, 480, None, None)
                return self

            def __exit__(self, *_):
                pass

        sounddevice = SimpleNamespace(RawInputStream=Input, PortAudioError=OSError)
        vad = SimpleNamespace(is_speech=lambda frame, rate: rate == 16000 and any(frame))
        with TemporaryDirectory(prefix="amy-test-") as temporary, patch.dict(
            sys.modules, {"sounddevice": sounddevice},
        ):
            audio = Path(temporary) / "input.wav"
            segment = amy.SpeechSegment(pause_seconds=0.09)
            amy_windows.record_microphone(audio, segment, vad)
            self.assertTrue(audio.with_suffix(".ready").is_file())
            self.assertTrue(segment.active)
            self.assertEqual(segment.voiced_frames, 6)
            self.assertEqual(segment.silent_frames, 3)


if __name__ == "__main__":
    unittest.main()
