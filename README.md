# 🎬 AI Local Video Dubber Studio

A fully offline, local AI video dubbing pipeline with an interactive subtitle review GUI. 

Extract speech from any video, transcribe it using OpenAI's Whisper, translate lines with a local Ollama model (e.g., Qwen 2.5 / 3.5), review and fine-tune both the source and translated subtitles in a desktop editor, and clone the original speaker's voice into the target language using Coqui XTTS-v2.

---

## ⚡ Features

- **100% Local & Private:** No APIs, cloud subscriptions, or external network requests during inference.
- **Voice Cloning (Zero-Shot):** Extracts the speaker's vocal timbre directly from the video to synthesize the new language.
- **Interactive Two-Stage Editor:** Correct misheard words in the transcript **before** translating, then refine translated lines **before** generating voice tracks.
- **Apple Silicon Optimized:** Native acceleration for M-series chips (M1–M4).
- **Auto Audio Syncing:** Speeds up slightly elongated translated lines to stay within original video subtitle cuts.

---

## 📋 Prerequisites

- **macOS** (Tested on Apple Silicon M-series chips) or **Linux/Windows** with Python 3.10 or 3.11.
  > ⚠️ **Note on Python:** Python 3.10 or 3.11 is strongly recommended. Python 3.12+ has known wheel incompatibilities with Coqui TTS and PyTorch audio backends.
- **Homebrew** (macOS)
- **Ollama** installed and running locally with your desired translation model.

---

## 🚀 Installation

### 1. System Dependencies (macOS)

Install `ffmpeg` for media extraction/remuxing and `python-tk` for the desktop GUI:

```bash
brew install ffmpeg python-tk@3.11
```

---

## License

Notice: This repository contains source code licensed under the MIT License. However, this project relies on XTTS v2 model weights, which are licensed under the Coqui Public Model License (CPML). Because the CPML strictly prohibits any commercial use of the model and its generated audio outputs, this entire project can only be used for non-commercial purposes (research, personal hobby, or testing). Any commercial deployment is strictly forbidden by the underlying model terms.
