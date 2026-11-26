#!/usr/bin/env bash
# Końcowa bramka B-lite: held-out uruchamiany RAZ dla wszystkich wariantów (MANIFEST.md, zasada 2).
# Wymaga: Ollama z qwen3:8b, lokalny LanguageTool na 127.0.0.1:18081 (inaczej C/D = B, odnotowane w JSON).
set -euo pipefail
cd "$(dirname "$0")/../../.."
R=bench/results/b_lite
sha256sum -c <<<"$(grep -o '[0-9a-f]\{64\}' $R/MANIFEST.md | head -1)  bench/cases/control_b_lite.yaml"
python -m bench.b_lite --variant A,B,C,D --split held --repeat 2 --lt-url http://127.0.0.1:18081 --out $R/held_ABCD.json
