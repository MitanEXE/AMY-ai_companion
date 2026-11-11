# AMY: local training starter

This adds real LoRA training to AMY. You review teaching examples, run a small training job, inspect its results, and decide whether to try the trained model. Your original Ollama model stays available.

AMY handles everyday chat, commands, time and arithmetic locally. It goes online for recognized live requests, such as weather, news and exchange rates, or when you explicitly ask. For an uncommon phrasing, say “look up” followed by the topic or use `/search TOPIC`. If AMY offers to verify a basic explanation, say “yes, check” or “no”. The offer expires after three minutes or when you change topics. `/web off` disables online lookups.

The CPU training profile was designed for a 16 GB laptop. Intel GPU training is an optional experiment with your existing driver.

## 1. Install the two application files

1. Close AMY with `/quit`.
2. Keep `amy_training.py` and `mitan_jarvis.py` together in the project folder.
3. Open a terminal inside that folder.
4. Run:

```bash
python amy_training.py install
```

Read the proposed changes. `yes`, `y`, or Enter approves; `no` or `n` cancels. Capital letters work too.

The installer backs up the previous application files. It copies the new files to `~/.local/share/mitan-jarvis/`. It preserves your notes, profile, language settings, voice files and original Ollama model.

Now start AMY:

```bash
python "$HOME/.local/share/mitan-jarvis/amy.py"
```

### Try a larger local chat model

With your usual local Ollama server running, open another terminal. Start with the 4B model:

```bash
OLLAMA_HOST=127.0.0.1:11435 ollama pull qwen3.5:4b
python "$HOME/.local/share/mitan-jarvis/amy.py" --model qwen3.5:4b
```

Try the same questions with `qwen3.5:9b` if you want to compare quality and speed. Pull that tag first. Close the previous AMY session before switching. Launch without `--model` to return to LFM3 and its training selection. The model flag changes chat for this launch. It does not install models or move a training adapter between models.

### Ask AMY about your screen on Hyprland

Install `grim` once if you don't have it:

```bash
sudo pacman -S --needed grim
```

Download `qwen3.5:4b` using the command above if you haven't already. Open AMY in a terminal on your Hyprland desktop. When you run AMY with LFM3, it uses local Qwen 4B for screen questions. If you launch AMY with Qwen, it uses your selected model.

- Type `/screens` or say “list my screens” to see the numbered displays. The number is the monitor's Hyprland ID plus one.
- Ask “Can you check my screen, what does this text mean?” to use the focused display.
- Ask “On screen 1, what is that?” or type `/screen 1 Explain this message` to choose Screen 1.

AMY captures one frame per request. General visual questions use a smaller image. Use `/screen detail 1 Explain this message` when the display has small text or fine details. Voice starts reading the reply as AMY finishes the first sentence. The terminal shows which step took time.

For faster text and error-message reading, install Tesseract from your Arch terminal:

```bash
sudo pacman -S --needed tesseract tesseract-data-eng
```

Add `tesseract-data-chi_tra` for Traditional Chinese. When the language data is available, AMY tries OCR for questions about visible text and uses your local chat model to explain what it read. Type `/screen text 1` to show the OCR result without waiting for a chat model. If small characters are unclear, zoom in and ask again.

Ordinary checks keep the image in memory. To save a fresh PNG to `~/AMY/screenshots/`, type `/screenshot 1` or say “Save a screenshot of screen 1” and approve in the terminal. Screen checks work with `/web off`.

### Create and edit a project

AMY keeps project files under `~/Projects/`. If you need PHP and Composer on Arch, install them from a normal terminal:

```bash
sudo pacman -S --needed php composer
```

Ask “Create a Laravel project called inventory-app” to prepare a Laravel 13 project. You can also type `/laravel inventory-app` inside AMY. The preview gives you the exact path and Composer command. After you approve, Composer downloads PHP dependencies with plugins and scripts disabled. AMY verifies the installed framework and creates local settings with a generated app key and file-backed sessions and cache. Start the dev server separately when you're ready.

Use `/projects` to list folders and `/project NAME` to select one. A new Laravel project is selected automatically. Ask “Update routes/web.php to add a /hello route that says Hello,” or type `/file PATH REQUEST` for a specific text file. `/edit REQUEST` lets the local model propose a small change within the selected project. Use `/project off` to return to `~/Projects/`.

You can also ask “Create me an HTML file that can surprise me.” AMY proposes a free filename inside the selected project or at the top level of `~/Projects/`. An incomplete draft stops before the approval prompt. Chat replies that hit their token limit show a notice.

Review the exact diff in the terminal before you approve. AMY checks the bytes written and leaves a copy of the diff or creation manifest in `~/AMY/dump/`. The checks confirm the files and changes. Run your project's tests separately to check app behavior.

A successful file creation prints `Saved and verified` followed by the full path. Ask “Where did you save surprise.html?” or type `/where .html`. AMY checks local save reports and verifies the path on disk. `/where` without a name checks the latest save report.

The following commands are typed **at `You >` inside AMY**, not in the normal terminal.

## 2. Check your laptop, then prepare training

```text
/train check
```

This reads CPU, available RAM and free space on the disk holding your home folder. It installs nothing. Close large apps before training. The profile requires at least 6 GiB of currently available RAM.

```text
/train setup
```

Approve this only after reading its description. It creates a separate Python training environment and downloads the official 3.46 GB BF16 LFM3 model. Your existing 1.1 GB Ollama file is for inference and is not the training checkpoint.

Fresh training setups put the environment, examples, runs and cache under `~/AMY/train/`. If you already have training data under `~/.local/share/mitan-jarvis/training/`, AMY keeps using that folder. `/train status` shows the active path.

Training has a monitored **30 GiB storage budget**. It also requires at least 8 GiB free disk space beyond each operation's reserved space. The installer initially asks for about 16 GiB free space including that reserve.

The CPU path was tested. `/train setup xpu` is optional: it uses an Intel GPU PyTorch build and checks BF16 forward/backward operations with your existing driver. Arch Linux on your exact Intel driver was not tested here. If that check fails, use `/train setup cpu`, then run a CPU pilot. Changing backends requires a new pilot before full training.

## 3. Approve examples and add a correction

```text
/train init
```

Read the 36 starter examples, then approve saving them. They teach identity, plain language, uncertainty, permission boundaries and English/Traditional Chinese responses. Separate evaluation questions are kept out of training. Synthetic dates and bench indicators are clearly labeled as examples, not current facts or real machine rules.

Your existing corrections take priority over starter answers. No chat history, personal profile or documents are automatically copied into training.

Add something you want AMY to learn:

```text
/teach
```

For example, enter these answers at the prompts:

| Prompt | Example input |
| --- | --- |
| Question | `How should you explain an unfamiliar Linux command?` |
| Correct answer | `Explain what it does, its target and its risks. Ask for missing details before suggesting changes.` |
| Reference context | Leave blank with Enter |
| Answer language | `en` |

Review the example and approve it. If you teach the same question again, the previous dataset is backed up before its answer is replaced.

Saving an example does not immediately change the model. The next training run updates the weights. Passwords and API keys do not belong in teaching examples; models can memorize their training text.

## 4. Run the pilot first

```text
/train pilot
```

This performs **two real LoRA optimizer steps**. It reports speed, memory, whether weights changed, and whether the saved adapter reloaded correctly. It cannot become the normal chat model.

Voice pauses while using the training editor. The original Ollama model is released from RAM for training; its downloaded file is preserved. No extra cloud account or paid API is needed.

AMY waits for training to finish before returning to chat. Press **Ctrl+C** to stop a run. The current application may close too; restart it normally afterward. A stopped run is not automatically accepted or activated.

## 5. Train and inspect the result

```text
/train run
/train review
```

The full run performs at least 48 steps, covering every approved example. The small laptop profile accepts up to 256 curated examples per run. The base model stays frozen; only query/value LoRA weights are trained.

The worker has a 30-minute time guard, an 8 GiB process-RAM guard, an available-system-RAM guard and storage checks. These are monitored safeguards, not OS quotas. A stopped or failed run is not reported as successful or activated automatically.

Review shows:

- Evaluation loss before and after training on separate questions.
- Two base/candidate answer comparisons.
- Whether adapter weights changed and passed a reload check.
- Resource use, file locations and trial eligibility.

Lower loss means the model assigned higher likelihood to the reference answers in this small test. It does **not** mean better general intelligence, reliable coding, or universal factual accuracy. Look at the actual answers.

## 6. Try it, or return to the original

```text
/train use
```

This asks for approval before selecting a completed candidate that passed the basic evaluation guards. Trained trial chat uses a private local Transformers process. It can use more RAM and respond slower than quantized Ollama. The model loads once per AMY session; local clock, calculator and fixed identity answers still bypass the model.

To switch back:

```text
/train base
```

Approve the switch. Your original Ollama model is used again. Examples, adapters and reports stay available. No model or personal memory is deleted.

Use `/voice` to resume voice chat after training. Use `/train status` for the current selection and file status. Use `/web off` when you want offline conversation; training itself runs offline after setup.

## What this version does not claim

This is supervised local training from examples you approve. It does not retrain silently from its own conversations or automatically believe web pages. It does not teach a whole new language from a handful of examples. LFM3 already includes English and Chinese support.

The numerical and current-data tools remain application tools. Training is not a substitute for a clock, calculator, weather service or current source.

CPU training was tested against the real official 1.7B checkpoint. Run a pilot to measure speed and memory on your hardware. Read `VALIDATION.md` for the results and limits.

If your existing voice/web environment has not received the previous update, refresh it once with `python "$HOME/.local/share/mitan-jarvis/amy.py" --setup`. Its existing setup routine checks matching voice assets and preserves notes/profile; it defaults reply language to English. Training uses a separate environment.

## Sources and reproducibility

- [Liquid AI LFM3 model and training information](https://huggingface.co/LiquidAI/LFM3-1.7B)
- [Hugging Face PEFT / LoRA](https://huggingface.co/docs/peft/en/developer_guides/lora)
- [PyTorch Intel GPU support](https://docs.pytorch.org/docs/main/notes/get_start_xpu.html)
- [MSI Prestige 14 AI Evo / Ultra 5 125H specification](https://tw.msi.com/Business-Productivity/Prestige-14-AI-Evo-C1MX/Specification)

The inspected released Transformers package lacked native LFM3 support. The separate training environment therefore uses the official Hugging Face repository at a fixed tested revision and archive checksum. It imports native LFM3 classes; it does not execute Python downloaded from the model repository.

The model revision is `1da06bec6a819da10b54c67e5c90972b46d81871`. Its safetensors SHA-256 is checked before use. The source revisions and digests are included directly in `amy_training.py`.

## FP32 CPU training option

If BF16 is slow, exit AMY and run the installed training helper from your Linux terminal. FP32 requires 10 GiB available RAM.

```bash
python "$HOME/.local/share/mitan-jarvis/amy_training.py" pilot fp32
python "$HOME/.local/share/mitan-jarvis/amy_training.py" train fp32
```

Run the second command after the FP32 pilot succeeds. Review with /train review inside AMY.
