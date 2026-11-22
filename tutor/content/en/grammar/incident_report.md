---
provenance:
  source: ai_adapted
  model: claude-sonnet-5-5
  prompt_version: adapt.v1
  created_at: '2026-11-22'
  refs:
  - src: twe
    loc: p233.1
    sha: dcd16966a67386415c6327c4a1a4f732340c16d1dab309d992ea2fba5aead702
review:
  status: draft
  reviewer: null
  reviewed_at: null
structure: v2
license: CC-BY-4.0
---
# Raport incydentu (angielski zawodowy)

## Zasada
Raport opisuje fakty neutralnie i chronologicznie: kiedy, co się stało, jaki był skutek, co zrobiono. Używamy czasu przeszłego, strony biernej i godzin; unikamy potocznych wtrąceń.

## Formy
At 14:05 the database became unavailable. The issue was detected at 14:10. The root cause turned out to be… Service was restored at 14:45. Before the client called, the team had fixed the bug.

## Poprawnie
- At 14:05 the database became unavailable.
- The issue was detected at 14:10.
- The outage lasted about forty minutes.
- Service was restored at 14:45.

## Błędnie → poprawnie
- The server crash at 10:15 → The server crashed at 10:15 [tense.past_simple]
- The issue is detected yesterday → The issue was detected yesterday [tense.past_simple]
- Before the client called, the team fixed the bug → Before the client called, the team had fixed the bug [tense.past_perfect]
- The database went down lol → The database became unavailable [register]

## Typowe błędy Polaków
- `tense.past_perfect` — Po polsku kolejność zdarzeń wynika z kontekstu; po angielsku wcześniejsze zdarzenie często oznaczamy had + III forma.
- `register` — W raporcie nie używamy potocznych słów; piszemy neutralnie i konkretnie.

## Źródła
Adaptacja i tłumaczenie na polski (własne przykłady): twe (p233.1). Szczegóły w ATTRIBUTION.md.
