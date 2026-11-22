# Contributing

Thanks for helping. The project is in early development; small, focused changes are easiest to review.

## Setup

```bash
git clone https://github.com/krauzerl/english-ai-tutor.git
cd english-ai-tutor
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Before opening a pull request

```bash
pytest          # live tests (real Ollama or API) are excluded by default
ruff check .
python main.py content validate en
```

All three must pass. Run `pytest -m live` only if you have Ollama running; Gemini live tests may cost money.

## Guidelines

- Branch from `main`, one topic per pull request. Do not rewrite shared history.
- Add or update tests with every behaviour change.
- Keep the teaching engine (`tutor/pedagogy/`) deterministic and free of LLM calls.
- Reach the LLM only through `LLMProvider`; validate structured replies.
- Never commit secrets, databases, audio, model files or source textbooks (see `.gitignore`).
- Keep dependencies minimal and declared in `pyproject.toml`. Note the licence of any new dependency.

## Teaching content

- Content lives in `tutor/content/<lang>/`. Run `python main.py content validate <lang>` after edits.
- Content must be original or adapted from a source with a compatible open licence. Add the source to
  `sources.yaml` with author, URL, licence and a change notice. Do not paste text from copyrighted or
  non-commercial sources, and do not copy passages verbatim.
- A review status of `human_reviewed` is set only by a human through `python main.py content review`.
  Contributors must not edit it by hand.

## Licence of contributions

The project has no licence yet (see README). Open an issue before large contributions so the terms are clear.
