# Install AMY on Windows

AMY runs in a Windows terminal. `Start-AMY.cmd` is the launcher you can
double-click after setup.

## 1. Install Python and Ollama

Use an x64 (Intel or AMD) PC with Windows 11 or Windows 10 22H2 and a local user profile.

1. Install 64-bit **Python 3.12** from [python.org](https://www.python.org/downloads/windows/).
   If you use the Python install manager, run `py install 3.12`.
2. Install and open **Ollama** from the [official Windows download](https://ollama.com/download/windows).
   The Ollama app runs in the background on port `11434` by default.
3. Open a new PowerShell window and check both commands.

```powershell
py -3.12 --version
ollama list
```

If `ollama list` reports a connection error, open Ollama from the Start menu.
If either command is missing, reopen PowerShell after installing it.

## 2. Get AMY and install its Windows dependencies

Download and extract the project ZIP, or use Git if you already have it.

```powershell
git clone https://github.com/MitanEXE/AMY-ai_companion.git
cd AMY-ai_companion
```

Open PowerShell in the folder that contains `Start-AMY.cmd`. These commands
create a Python environment in the project and add timezone and screen-capture
support. Run them once.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements-windows.txt
```

## 3. Download a local model and open AMY

With Ollama open, download AMY's default model.

```powershell
ollama pull lfm3:1.7b
ollama list
.\Start-AMY.cmd
```

You can also double-click `Start-AMY.cmd` from File Explorer. At `You >`,
try **What time is it?** or **What is 12 * 8?**. Then send a chat question to
check that AMY can reach the model. Use `/help` to see commands and `/quit` to exit.

If you already downloaded Qwen on this Windows PC, you can start AMY with it
directly. Pull it first if it is missing from `ollama list`.

```powershell
ollama pull qwen3.5:4b
.\Start-AMY.cmd --model qwen3.5:4b
```

AMY talks to Ollama at `127.0.0.1:11434`. For a server on another local port,
start AMY with `.\Start-AMY.cmd --port 11435`, using your server's actual port.
After model download, local chat works offline. Windows AMY starts with web
search off. Use `/web on` after the optional setup if you want online lookups.
[Ollama's Windows guide](https://docs.ollama.com/windows)

## 4. Check files and screens

- Try **Create a text file called hello.txt saying Hello.** Read the preview
  and enter `y` to save it. AMY prints the path after verifying the file.
- Type `/projects` to list projects and `/where hello.txt` to find that file.
- Type `/screens` to list monitors. Use `/screen 1 What does this say?` to
  capture one frame and use local vision. This requires `qwen3.5:4b`. With no
  screen number, Windows AMY uses the primary display.
- Use `/screenshot 1` to preview and approve saving a PNG.
- For `/screen text 1`, install Tesseract and its `eng` or `chi_tra` language
  data, and make sure `tesseract --list-langs` works in PowerShell.
  [Tesseract installation guide](https://tesseract-ocr.github.io/tessdoc/Installation.html)

| Data | Folder |
| --- | --- |
| Project files | `%USERPROFILE%\Projects` |
| Saved screenshots | `%USERPROFILE%\AMY\screenshots` |
| File change reports and original-file backups | `%USERPROFILE%\AMY\dump` |
| Settings, memories and optional voice files | `%LOCALAPPDATA%\AMY` |

AMY asks before writing project files. On Windows it saves a verified backup of
each existing file before editing it. Keep those backups if an edit is
interrupted. Windows file checks require real local folders and regular files,
including at the project root.

## 5. Optional voice and web setup

1. In the AMY folder, run `.\Start-AMY.cmd --setup`. The approval prompt shows
   the data folder. Setup downloads CPU PyTorch, the checked Kokoro model and
   voices, and the web-search tools. The speech models run locally afterward.
2. Run `.\Start-AMY.cmd --voice-test` to hear the English and Mandarin voices.
   If the error specifically reports a missing eSpeak library, see the
   [Kokoro Windows instructions](https://github.com/hexgrad/kokoro#windows-installation).
3. For microphone input, download the Windows x64 zip from the official
   [whisper.cpp releases](https://github.com/ggml-org/whisper.cpp/releases).
   Put `whisper-cli.exe` and the DLLs from its folder together in
   `%LOCALAPPDATA%\AMY\whisper`. Download the multilingual
   [ggml-base.bin](https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin)
   and save it as `%LOCALAPPDATA%\AMY\ggml-base.bin`.

Check the model file in PowerShell. The publisher lists the SHA-1 digest
`465707469ff3a37a2b9b8d8f89f2f99de7299dac`.
[whisper.cpp model list](https://huggingface.co/ggerganov/whisper.cpp)

```powershell
Get-FileHash "$env:LOCALAPPDATA\AMY\ggml-base.bin" -Algorithm SHA1
```

Open AMY and type `/voice`. Speak and pause for a reply. Type `/voice off`
and press Enter to return to text. If Windows reports a microphone error,
check the default input in **Settings → System → Sound** and allow desktop
apps to use the microphone in **Settings → Privacy & security → Microphone**.

The Linux guide covers LoRA training, Laravel scaffolding, the paid Brave API
key, and Hyprland workspace shortcuts. Use `/project` and `/file` to work with an
existing Laravel project on Windows. [Linux guide](START_HERE.md)

## Update AMY

If you cloned the project, close AMY and run these from its folder.

```powershell
git pull --ff-only
.\.venv\Scripts\python.exe -m pip install -r .\requirements-windows.txt
```

If you use a ZIP, extract the new release to a new folder and repeat step 2.
Both launchers read your local data from `%LOCALAPPDATA%\AMY`.
