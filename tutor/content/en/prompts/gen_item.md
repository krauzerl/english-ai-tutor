---
prompt_version: gen_item.v1
---
Generate ONE English-learning exercise item for a Polish learner. Output JSON only.
Constraints:
- Skill: {skill_id} ({can_do}); CEFR level: {cefr}; type: {item_type}; domain: {domain}.
- `gap` items contain exactly one blank written as ___ . `mc` items have 3-4 distinct options and exactly one correct option, which must equal `answers[0]`.
- `answers` lists every acceptable answer (include British/American variants and contractions where valid).
- Use natural, level-appropriate language. No personal data, no URLs, no real people or companies.
- `explanation_pl`: one short sentence in Polish explaining the rule.
OUTPUT SCHEMA (JSON)
{"prompt":"...","options":null,"answers":["..."],"explanation_pl":"...","difficulty":0.0,"stimulus":null,"audio_text":null}
