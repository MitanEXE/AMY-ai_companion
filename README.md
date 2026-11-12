# AMY

AMY is a local AI companion for Linux and Windows. It chats through Ollama
and previews project file changes for you to approve.

| Your setup | Start here |
| --- | --- |
| Linux desktop | [Install the app on Arch Linux](#linux-desktop) |
| Linux terminal | [Run in a terminal](#linux) |
| Windows | [Run in PowerShell](#windows) |

Get the project from GitHub using **Code → Download ZIP**. Extract it and open
a terminal in the folder containing this README.

## Linux desktop

1. On Arch Linux, install Python, uv, and Ollama if needed.

   ```bash
   sudo pacman -S --needed python uv ollama
   ```

2. From the AMY folder, run the installer.

   ```bash
   python install_amy_desktop.py
   ```

3. Open **AMY Companion** from your app launcher. Go to **Settings → Models** and select
   a downloaded model.

If the list is empty, leave AMY open, download the default model, and click
**Refresh models**.

```bash
OLLAMA_HOST=127.0.0.1:11435 ollama pull lfm3:1.7b
```

If your models are already in Ollama on port `11434`, run the installer with
`--port 11434` to use that server. Use the same port for model downloads.
For voice, screen translation, or troubleshooting, see the
[Linux desktop guide](docs/LINUX_DESKTOP.md).

Use **New chat** for a separate conversation, **Attach** to read local files,
and **Coding** to choose a project folder and review proposed code changes.

## Linux

You need **Python 3.12 or newer** and **Ollama**. [Ollama for Linux](https://ollama.com/download/linux)

1. In **Terminal 1**, start Ollama and leave it running. If your AMY server is
   already running on port `11435`, go to step 2.

   ```bash
   OLLAMA_NO_CLOUD=1 OLLAMA_HOST=127.0.0.1:11435 \
     OLLAMA_CONTEXT_LENGTH=4096 \
     OLLAMA_MODELS="$HOME/.local/share/jarvis-models" ollama serve
   ```

2. In **Terminal 2**, open the AMY folder. Download the default model once,
   then start AMY.

   ```bash
   OLLAMA_HOST=127.0.0.1:11435 ollama pull lfm3:1.7b
   python mitan_jarvis.py
   ```

For voice, Hyprland screen reading, or training, see the
[Linux setup guide](docs/START_HERE.md).

## Windows

You need **64-bit Python 3.12** and **Ollama**. Open Ollama from the Start menu
before running the commands below. [Python download](https://www.python.org/downloads/windows/) ·
[Ollama download](https://ollama.com/download/windows)

1. Open **PowerShell** in the AMY folder and run this setup once.

   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r .\requirements-windows.txt
   ollama pull lfm3:1.7b
   ```

2. Start AMY.

   ```powershell
   .\Start-AMY.cmd
   ```

After setup, you can also double-click `Start-AMY.cmd` in File Explorer.
For voice, screen reading, or troubleshooting, see the
[Windows setup guide](docs/WINDOWS.md).

## First things to try

Enter one of these after AMY opens.

| Try this | What happens |
| --- | --- |
| `What time is it?` | AMY checks your device clock. |
| `Explain why a compass points north.` | AMY asks your local Ollama model. |
| `Create a text file called hello.txt saying Hello.` | AMY previews the file. After you approve, it saves under your **Projects** folder and shows the verified path. |

In the terminal, type `/help` for commands or `/quit` to exit.
See the [command reference](AMY_Commands.txt) and [validation notes](docs/VALIDATION.md).

## License

[MIT](LICENSE). Models and dependencies have their own licenses.
