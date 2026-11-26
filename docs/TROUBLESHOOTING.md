# Troubleshooting

Each entry below was reproduced or taken from the application's own messages.

| Symptom | Cause and fix |
|---|---|
| ``Ollama nie odpowiada: uruchom `ollama serve`.`` | The Ollama server is not running. Start the service or run `ollama serve`. Check `http://localhost:11434`. |
| Model not found, or the `think` option is rejected | Pull the model (`ollama pull qwen3:8b`). The `think` setting needs Ollama 0.9.0 or newer (`ollama --version`). |
| `Brak profilu. Utwórz: python main.py profile create NAZWA` | No profile yet. Run `python main.py profile create NAME`. |
| `onnxruntime ... NO_SUCHFILE ... kokoro-v1.0.int8.onnx` | The Kokoro files are missing. Put `kokoro-v1.0.int8.onnx` and `voices-v1.0.bin` in `~/.local/share/english-ai-tutor/models/kokoro/` (download links in the README). |
| `Brak biblioteki PortAudio (sudo apt install libportaudio2)` | PortAudio is missing, so no microphone or speaker. Install `libportaudio2`, or keep using `--no-audio`. |
| `[brak mikrofonu: ...] Tryb tekstowy` | No input device was opened. The tutor still speaks; type your answers. List devices with `--list-devices`. |
| `pip install -e ".[dev]"` fails with `ResolutionImpossible` | Seen once, then not reproduced in four clean installs (Python 3.12 and 3.13, no pip cache). Likely a temporary package-index state. Run the command again; if it repeats, report the full pip output. |
| Warnings about a missing local extract (`brehe`, `twe`) from `content validate` | Expected. Source textbooks are not in the repository, so the overlap check is skipped. The command still ends with `OK`. |
| Corrections look wrong | Corrections from conversation are model suggestions and can be mistaken. Lower the intensity with `--correction summary`. |
