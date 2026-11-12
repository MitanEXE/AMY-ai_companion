# AMY for Linux

Open AMY from your app launcher for chat, voice, file review and screen tools. AMY uses your local Ollama models. The installer creates a Qt environment and a launcher in your home folder. Your existing terminal setup and AMY data are available from the same home folder.

## Install on Arch Linux and Hyprland

1. Extract or clone AMY into a folder you intend to keep, such as `~/AMY/desktop`.
2. Open a terminal in that folder. If you already have Python, uv and Ollama, go to step 3. If you need them, install the Arch packages.

   ```bash
   sudo pacman -S --needed python uv ollama
   ```

3. Run the desktop installer. Review the paths and approve the install.

   ```bash
   python install_amy_desktop.py
   ```

4. Find **AMY** in your app launcher and open it. If the launcher hasn't refreshed, run the app directly once.

   ```bash
   "$HOME/.local/share/mitan-jarvis/desktop-env/bin/python" amy_desktop.py
   ```

AMY defaults to `127.0.0.1:11435`, the port used by the original AMY setup. It connects to a running Ollama there. If the port is free, AMY starts its own local Ollama with cloud features disabled. It uses `~/.local/share/jarvis-models` if that folder exists. AMY shuts down the server it started when it closes.

If your downloaded models are on Ollama's standard service at port `11434`, run `python install_amy_desktop.py --port 11434` in the AMY folder. You can also pass `--port 11434` to `amy_desktop.py` when launching directly.

## Choose your model

1. Click **Choose model** or open **Settings → Models**.
2. Tick the downloaded model you want. AMY remembers the choice for the next launch.
3. Click **Refresh models** after downloading or removing a model. The list comes from the Ollama server shown on the page. Model downloads happen in Ollama.

On the original AMY port, leave AMY open and run one of the following once. Use port `11434` in the command if that's where AMY connects.

```bash
OLLAMA_HOST=127.0.0.1:11435 ollama pull lfm3:1.7b
```

```bash
OLLAMA_HOST=127.0.0.1:11435 ollama pull qwen3.5:4b
```

Start with LFM3 for short text chat or Qwen 4B for text and vision on a 16 GB laptop. Leave **Think** off for quick questions. The model's speed and output vary with the model you choose.

## Try the first file

1. In **Chat**, send **Create a complete, interactive HTML surprise page**.
2. Watch the progress at the bottom. Click **Stop** to cancel a draft.
3. Review the proposed filename, destination and exact diff. Click **Approve and save** when it looks right.
4. Look for **Saved and verified**. Click **Open file** or **Open folder** to find it under `~/Projects/`.

You can specify a name, for example `/file surprise.html Create a small interactive page with a reveal button`. AMY checks for changes to the destination between review and save. It reads the saved file back and writes a change report under `~/AMY/dump/`. Ask **Where did you save it?** to look up a saved path.

## Set up the way AMY replies

In **Settings → General**, choose **Balanced**, **Concise**, or **Detailed**. Add a custom preference, such as “Use simple words and call me sir occasionally.” You can also choose the theme, installed font family, font size, and whether to speak replies or offer web lookups. Click **Save settings**.

**English only** is the default. Choose **English + Traditional Chinese** to enable Chinese replies, Mandarin microphone input and the English/Traditional Chinese screen translation choices. Choose the active reply and microphone language on the same page. Ollama text chat uses your selected model for either language.

## Optional offline voice and web setup

If your existing AMY voice works, try **Voice on** first. Speak and pause. AMY listens again after each reply until you click **Voice off** or **Stop**. Whisper uses the language you selected. The voice engine plays audio locally.

For fresh voice setup, install the mic and playback tools on Arch if you need them.

```bash
sudo pacman -S --needed whisper-cpp pipewire-audio espeak-ng
```

Install speech and web dependencies from the AMY source folder. Pick **one** setup command. They create or update the shared AMY speech environment after you review the install prompt.

| What you want | Command |
| --- | --- |
| English voice AF_SOL | `python mitan_jarvis.py --setup --voice-languages en` |
| English AF_SOL and Mandarin ZF_090 | `python mitan_jarvis.py --setup --voice-languages en,zh` |

For a fresh English-only mic, get [ggml-base.en.bin](https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin) from the official whisper.cpp model repository. Put it in `~/.local/share/mitan-jarvis/`. For Mandarin input, use [ggml-base.bin](https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin) in the same folder. An existing multilingual file works for English too.

| File | Publisher's SHA-1 |
| --- | --- |
| `ggml-base.en.bin` | `137c40403d78fd54d454da0f9bd998f78703390c` |
| `ggml-base.bin` | `465707469ff3a37a2b9b8d8f89f2f99de7299dac` |

Run `sha1sum` on the downloaded file and compare it with the [publisher's model list](https://huggingface.co/ggerganov/whisper.cpp). Turn voice on in AMY. If the mic fails, run `wpctl status` in a terminal and check the selected input.

AMY answers questions about its identity, the device clock and supported arithmetic locally. The default web setting previews the query before sending it. To use searches hands-free, choose **Search public queries automatically**. AMY still asks before sending a query flagged as private or derived from your screen. Try **the weather in Hsinchu** or **Check online** when it appears under a local answer.

## Select and scan part of the screen

On Hyprland, install the capture and English OCR tools when you want this feature.

```bash
sudo pacman -S --needed grim slurp tesseract tesseract-data-eng
```

For Traditional Chinese OCR, also install `tesseract-data-chi_tra` and enable Traditional Chinese in Settings.

1. Open **Screen tools → Select area**. Drag a rectangle around the part of the screen you want AMY to read.
2. Pick a reading or translation direction. Click **Start live**. Identical frames skip OCR. If OCR sees the same text after a visual change, AMY reuses the translation.
3. Click **Pause live** to stop capture, or close the panel. Use **Select area** again to move or resize the captured region. Keep the results panel outside the selected area.
4. Use **Identify** for a local vision description, **Search text** to preview a web query, or **Save image** to write a capture after approval. For images, AMY uses your selected model if it supports vision. Otherwise it looks for a compatible downloaded model and shows which one it uses.

To read a whole monitor, type `/screen 1 What does this error mean?`. Type `/screenshot 1` to preview a screenshot save. Screen reads and translations use temporary data. Images appear in **Saved media** after an approved save.

## Manage memory, media and lessons

- **Memory → Saved notes** reads the same active notes as the terminal app. Select notes and confirm **Delete selected** to remove them from future chats. **Profile** shows the separate profile used by AMY and lets you delete that file.
- Notes deleted in the desktop app are removed from the active notes file. Any backups made by the terminal app are separate files.
- **Saved media** shows captures and other media under `~/AMY/screenshots/` and `~/AMY/dump/`. It also lists change reports. Select an item to see its exact path, open it, or confirm deletion.
- Say **Remember that I prefer short examples** to create a reviewable suggestion. To draft a lesson for the last model answer, say **Correction: ...**. Review both under **Memory → Suggestions**.
- Approved notes take effect in future chats. Approved lessons are saved for a later training run. Follow the [training guide](START_HERE.md) for a pilot, evaluation and trial activation in the terminal app. The desktop model picker uses the Ollama model you ticked.

## Validation

Headless tests exercise the Qt window, local Ollama API requests, settings and deletion, draft review and verified saves, cancellation, and repeated screen frames. On a Hyprland laptop, test real mic playback and region selection using the steps above.
