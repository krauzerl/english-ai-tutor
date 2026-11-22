# Security Policy

## Supported versions

Only the latest commit on `main` is supported (version 0.x, early development).

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private reporting:
<https://github.com/krauzerl/english-ai-tutor/security/advisories/new>.

Include affected version or commit, reproduction steps and impact. Expect an acknowledgement within about a week.

## Scope and design notes

- The app is local-first. It listens on no network port.
- Secrets (for example `GEMINI_API_KEY`) belong in the environment or in `~/.config/english-ai-tutor/.env`, never in the repository.
- The config directory is created with mode 0700 and `config.toml` with 0600.
- The LanguageTool adapter accepts only `http(s)` URLs on localhost, without credentials, and does not follow redirects.
- Learner data is stored in a local SQLite database; profiles can be exported and deleted.
- Do not expose Ollama or LanguageTool to untrusted networks.
