"""Optional local image generation through a running ComfyUI server."""

import json
import re
from contextlib import closing
from http.client import HTTPConnection
from pathlib import PurePosixPath
from secrets import randbits
from time import monotonic
from urllib.parse import urlencode

import amy_desktop_core as desktop
from amy_desktop_files import normalized_image


class ComfyUI:
    def __init__(self, port=8188):
        self.port = port

    def request(self, path, cancel, payload=None, *, limit=1_000_000, timeout=10):
        try:
            with closing(HTTPConnection("127.0.0.1", self.port, timeout=timeout)) as connection:
                cancel.check()
                connection.connect()
                with cancel.interrupt_socket(connection.sock):
                    body = json.dumps(payload) if payload is not None else None
                    connection.request("POST" if body is not None else "GET", path, body,
                                       {"Content-Type": "application/json"})
                    with connection.getresponse() as response:
                        if response.status != 200:
                            raise RuntimeError(f"ComfyUI returned HTTP {response.status}. Check its workflow and model.")
                        data = response.read(limit + 1)
        except ConnectionRefusedError as error:
            raise RuntimeError(f"Start local ComfyUI on 127.0.0.1:{self.port} to generate images.") from error
        if len(data) > limit:
            raise RuntimeError("The image generator returned more data than AMY can read.")
        return data

    def checkpoints(self, cancel):
        result = json.loads(self.request("/models/checkpoints", cancel))
        if not isinstance(result, list):
            raise RuntimeError("ComfyUI did not return its checkpoint list.")
        names = {item for item in result if isinstance(item, str) and 1 <= len(item) <= 240
                 and item.casefold().endswith(".safetensors") and not any(c in item for c in "\0\r\n")}
        return sorted(names, key=str.casefold)

    def generate(self, prompt, checkpoint, cancel, progress):
        if not 1 <= len(prompt) <= 1600:
            raise ValueError("Use an image prompt between 1 and 1,600 characters.")
        if checkpoint not in self.checkpoints(cancel):
            raise RuntimeError("That checkpoint is no longer available in ComfyUI.")
        workflow = {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
            "2": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": prompt}},
            "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": ""}},
            "4": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
            "5": {"class_type": "KSampler", "inputs": {
                "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0],
                "seed": randbits(63), "steps": 18, "cfg": 7.0, "sampler_name": "euler",
                "scheduler": "normal", "denoise": 1.0,
            }},
            "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
            "7": {"class_type": "PreviewImage", "inputs": {"images": ["6", 0]}},
        }
        result = json.loads(self.request("/prompt", cancel, {"prompt": workflow}))
        prompt_id = result.get("prompt_id")
        if not isinstance(prompt_id, str) or not re.fullmatch(r"[a-zA-Z0-9-]{1,64}", prompt_id):
            raise RuntimeError("ComfyUI did not accept the image job.")
        progress(f"Generating a 512 × 512 image with {checkpoint}…")
        deadline = monotonic() + 900
        try:
            while monotonic() < deadline:
                cancel.check()
                history = json.loads(self.request(f"/history/{prompt_id}", cancel)).get(prompt_id)
                if history:
                    return self.read_result(history, cancel)
                cancel.event.wait(0.8)
        except (desktop.Cancelled, OSError):
            if not cancel.event.is_set():
                raise
            # Delete only this pending job. ComfyUI owns any job already running.
            try:
                self.request("/queue", desktop.Cancellation(), {"delete": [prompt_id]}, timeout=2)
            except (OSError, RuntimeError):
                pass
            raise desktop.Cancelled
        raise RuntimeError("The image job exceeded 15 minutes. Check the job in ComfyUI.")

    def read_result(self, history, cancel):
        if history.get("status", {}).get("status_str") == "error":
            raise RuntimeError("ComfyUI couldn't generate the image. Check its log and checkpoint compatibility.")
        items = history.get("outputs", {}).get("7", {}).get("images", [])
        if not items or not isinstance(items[0], dict):
            raise RuntimeError("ComfyUI finished without an image preview.")
        item = items[0]
        name, subfolder = item.get("filename"), item.get("subfolder", "")
        if (item.get("type") != "temp" or not isinstance(name, str) or PurePosixPath(name).name != name
                or not name.lower().endswith(".png") or not isinstance(subfolder, str)
                or PurePosixPath(subfolder).is_absolute() or ".." in PurePosixPath(subfolder).parts
                or any(char in name + subfolder for char in "\\\"\0\r\n")):
            raise RuntimeError("ComfyUI returned an invalid preview location.")
        query = urlencode({"filename": name, "subfolder": subfolder, "type": "temp"})
        image = self.request("/view?" + query, cancel, limit=16_000_000)
        if not image.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("ComfyUI did not return a PNG preview.")
        return normalized_image(image, size=512)
