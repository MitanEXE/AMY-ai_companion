# AMY-ai_companion

AMY is a local AI companion for Windows and Linux terminals. It uses Ollama for chat and
supports voice, local tools, screen reading, and project file creation with an
approval preview.

## Install AMY

- **Windows** — [Windows installation guide](docs/WINDOWS.md). Set up Python and
  Ollama, then open `Start-AMY.cmd`.
- **Linux** — [Linux installation and training guide](docs/START_HERE.md).

## Start AMY on Linux

Install Python 3.12 or later and Ollama. From this project folder, run the installer.

```bash
python amy_training.py install
```

Open one terminal for the Ollama server. Use the existing model directory if you
already have an AMY setup.

```bash
OLLAMA_NO_CLOUD=1 OLLAMA_HOST=127.0.0.1:11435 \
  OLLAMA_CONTEXT_LENGTH=4096 \
  OLLAMA_MODELS="$HOME/.local/share/jarvis-models" ollama serve
```

In a second terminal, download the default model and start AMY.

```bash
OLLAMA_HOST=127.0.0.1:11435 ollama pull lfm3:1.7b
python "$HOME/.local/share/mitan-jarvis/amy.py"
```

For Qwen 3.5 4B, pull `qwen3.5:4b` on the same server and add
`--model qwen3.5:4b` to the Python command.

## What you can do

| Task | Example at the AMY prompt |
| --- | --- |
| Read commands | `/help` |
| Check the clock or do arithmetic | “What time is it?” or “What is 12 × 8?” |
| Start a voice session | `/voice on` |
| Read a Hyprland screen | `/screen 1 What does this error mean?` |
| Create an HTML file | “Create me an HTML file that can surprise me.” |
| Look up a saved project file | `/where .html` |
| Turn off web lookups | `/web off` |
| Check local training resources | `/train check` |

Project files go under `~/Projects/`. After approval and a successful write,
AMY shows **Saved and verified** with the full path. Voice, screen reading,
and LoRA training have optional setup steps.

See the [Windows guide](docs/WINDOWS.md), [Linux setup and training guide](docs/START_HERE.md), [command reference](AMY_Commands.txt),
and [validation notes](docs/VALIDATION.md). AMY stores profile data and saved
notes locally. The installer preserves existing profiles and notes.

## License

[MIT](LICENSE). Model weights and downloaded dependencies are governed by their
own licenses.
