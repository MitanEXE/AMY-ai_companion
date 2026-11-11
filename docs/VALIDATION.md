# What was tested

These results come from the development test environment.

## Real training test

| Item | Result |
| --- | --- |
| Model | Official LiquidAI/LFM3-1.7B, pinned revision |
| Original safetensors size | 3,457,635,448 bytes |
| Checkpoint digest | Matched the publisher's model-file metadata |
| Backend tested | CPU, BF16, PyTorch 2.10.0+cpu |
| Training method | Rank-4 LoRA on query/value projection layers |
| Trainable parameters | 292,864; all base parameters frozen |
| Teaching examples | 36 English/Traditional Chinese scenarios |
| Separate evaluation examples | 12 |
| Full optimizer steps | 48 |
| Optimizer time | About 154 seconds here; not a laptop estimate |
| Peak process RSS | About 4.47 GiB |
| Adapter file | 1,177,192 bytes, about 1.2 MB |
| Held-out loss | 3.4703 before; 2.5216 after |
| Saved-adapter reload | Passed; checked evaluation loss after reload |
| Original model | Preserved; its parameters were frozen |

The held-out-loss reduction was about 27.3%. This is a narrow reference-answer metric, **not a 27.3% increase in intelligence or overall accuracy**.

An initial two-step pilot changed the weights but slightly worsened its small evaluation score. It was not eligible for normal chat. An earlier longer candidate made an unsupported creator claim despite a better loss score. That finding led to clearer teaching context and an additional basic identity guard.

## Example from the revised run

Question: "顯示的時間是什麼？"

Supplied example context: computer clock `2033-01-05 16:30`, `Asia/Jakarta`. This is synthetic evaluation context, not the real present time.

The base answer invented a different date in 2026. The trained candidate used the supplied `2033-01-05 16:30` context. This demonstrates a useful improvement on this one scenario, not reliable behavior on every time-related question. AMY's normal clock questions use the local clock tool directly.

The revised identity answer identified AMY, but phrasing such as "on the Mitan side" was still awkward. The starter run is an experiment, not a polished general assistant model.

## Application checks

- The existing 19 checks for identity, memory approval, local clock/calculator, offline behavior, query privacy, source handling, failed-search recovery and optional search-key controls passed with the training integration.
- Seventeen training-control checks cover declined changes, review-before-save, correction replacement/backups, train/evaluation separation, path and storage guards, verified installation, modified-helper rejection, fixed command dispatch, incompatible-base rejection, pilot activation rejection and rollback. Together with the existing 19 checks, 36 application/control checks passed.
- The exact pinned-source download, digest verification, local-source package installation and BF16 CPU backward probe passed.
- The public approved pilot command completed through its real supervisor, memory/storage checks, worker subprocess and post-run verification in an isolated test layout.
- The real trained local server rejected unauthenticated and browser-origin requests.
- Streamed and non-streamed model replies worked.
- The boolean JSON search router returned constrained valid JSON.
- AMY's actual transport started the trained server, verified its local health, streamed an answer and stopped its own child process.

## Project and screenshot update checks

- Text and simulated voice requests selected the expected project and screen.
- Approved file creation and edits used the requested paths. Read-back checks preserved exact bytes, CRLF line endings and file modes. Tests covered cancellation, a stale preview, path traversal, links, private files and rollback after a simulated failure.
- An isolated local test service supplied edit plans. A mock Composer process exercised staging, version checks, initial settings, the creation report, name collisions and cleanup on failure.
- Screenshot saving required approval and used the requested display. The prior loopback screen checks passed. The app and training helper agreed on fresh and existing training paths.
- Live Composer downloads, real model-generated edits, and screen capture on the laptop were not tested in this update.

## Fast screen checks

- Verified fast and detailed capture scales, OCR routing, the no-model text command, single-frame vision fallback, and streamed voice playback with a local API fixture.
- Real Tesseract recognized a sample English error on a synthetic 1920 × 1200 display in about a third of a second in the development environment. Language selection for Traditional Chinese was checked with a fixture.
- The normal screenshot-save resolution, project and training path checks, and existing chat routing checks passed. Live Hyprland capture, Qwen latency and microphone performance on the laptop were not benchmarked.

## File creation and output limits

- The exact unnamed HTML request went through the project editor. Checks covered approval, cancellation, complete HTML, name collisions, and a verified change report.
- A local Ollama API fixture exercised a chat cutoff, a file draft cut short by the output limit, and a draft missing its closing HTML. The incomplete files never reached approval.
- The code-reply budget and deterministic file capability reply were tested. Real Ollama generation on the laptop was not measured in this update.

## Saved file location checks

- Verified the original spelling error, cancellation, verified saves in nested projects, lookup after restart, missing files, symlink rejection, and file matches without a save report. The lookup used no chat or web requests.

## Limits

No Intel Arc, NPU, Ultra 5 125H, Arch Linux driver or physical microphone benchmark was performed here. The CPU path is tested; optional XPU setup must pass its own probe and pilot. Existing voice functionality was preserved, not re-benchmarked on the user's sound hardware.

Only two generated answer comparisons accompany the reference-loss evaluation. These are small checks, not a broad model benchmark. Manual review is still required before trial selection. No automatic web-based teaching, model self-rating loop or silent retraining is enabled.

The trained trial uses Transformers rather than importing an adapter into the existing quantized Ollama model. Compatibility between an arbitrary LoRA export and Ollama is not assumed. Original Ollama chat remains the normal default and rollback target.
