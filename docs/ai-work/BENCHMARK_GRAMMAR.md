# Benchmark korekt gramatycznych — F4.6

> **WSTĘPNY — złoty standard niezrecenzowany, bramy nieotwierane.**

Zestaw: 130 przypadków (0 human_reviewed). LanguageTool: 6.6. Model oceny: SpeakLeash/bielik-11b-v2.3-instruct:Q4_K_M. Data: 2026-11-22.

| miara | A | B | C |
|---|---|---|---|
| przypadki ocenione / nieocenione | 129/1 | 130/0 | 129/1 |
| zgłoszenia liczone | 83 | 21 | 83 |
| trafienia (1:1) | 64/74 | 20/76 | 64/74 |
| precision [Wilson 95%] | 0.771 [0.670; 0.848] | 0.952 [0.773; 0.992] | 0.771 [0.670; 0.848] |
| recall [Wilson 95%] | 0.865 [0.769; 0.925] | 0.263 [0.177; 0.372] | 0.865 [0.769; 0.925] |
| FPR C1+C2+C3 | 0.240 | 0.000 | 0.240 |
| FPR C1 / C2 / C3 | 0.320 / 0.267 / 0.000 | 0.000 / 0.000 / 0.000 | 0.320 / 0.267 / 0.000 |
| akceptacja BrE/AmE (1−FPR C2) | 0.733 | 1.000 | 0.733 |
| S: bez zgłoszeń liczonych | 1.000 | 1.000 | 1.000 |
| D: bez zgłoszeń liczonych | 1.000 | 1.000 | 1.000 |
| poprawność korekty | 0.531 | 0.900 | 0.531 |
| zgodność kategorii | 0.516 | 0.300 | 0.516 |
| strażnik znaczenia: podejrzane poprawki | 3 | 0 | 3 |
| sugestie (p=l, poza zgłoszeniami) | 0 | 0 | 0 |
| LT p50/p95 [ms] | –/– | 27/35 | 21/23 |
| kolejka p50/p95 [s] | 10.78/20.70 | 0.03/0.04 | 10.80/20.73 |

## Brama jakości (07 §5.4 + minimalna czułość)

- **System A**: NIE dopuszczony. Blokery: zrecenzowanych przypadków 0 < 100; zrecenzowanych spanów złotych 0 < 50. Niespełnione: precision>=0.80, precision_wilson_low>=0.70, fpr_c123<0.10, fpr_c2<0.10, correction>=0.85, category_agreement>=0.85, meaning_human>=0.95, explanation_human>=4, queue_p95<=6s.
- **System B**: NIE dopuszczony. Blokery: zrecenzowanych przypadków 0 < 100; zrecenzowanych spanów złotych 0 < 50. Niespełnione: recall>=0.5, recall_wilson_low>=0.4, category_agreement>=0.85, meaning_human>=0.95, explanation_human>=4.
- **System C**: NIE dopuszczony. Blokery: zrecenzowanych przypadków 0 < 100; zrecenzowanych spanów złotych 0 < 50. Niespełnione: precision>=0.80, precision_wilson_low>=0.70, fpr_c123<0.10, fpr_c2<0.10, correction>=0.85, category_agreement>=0.85, meaning_human>=0.95, explanation_human>=4, queue_p95<=6s.

## Rekomendacje kategorii (nie zmieniają konfiguracji)

- System A: preposition (p=1.00, n=8)
- System B: żadna kategoria nie spełnia progu (precision ≥ 0,85, n ≥ 8)
- System C: preposition (p=1.00, n=8)

## Precision per kategoria (zgłoszona kategoria rdzeniowa)

**A**: agreement 6/7, article 6/6, morphology 4/4, omission 11/14, preposition 8/8, punctuation 1/1, tense 22/33, word_choice 2/5, word_order 4/5
**B**: agreement 5/5, collocation 5/5, morphology 2/2, spelling 4/5, word_choice 4/4
**C**: agreement 6/7, article 6/6, morphology 4/4, omission 11/14, preposition 8/8, punctuation 1/1, tense 22/33, word_choice 2/5, word_order 4/5

## Zasoby i wpływ na rozmowę

```json
{
 "lt_rss_mib": 663.64453125,
 "vram_mib": 6970.0,
 "lt_cpu_pct": 1.2569370191633353,
 "ollama_rss_mib": 7401.05078125,
 "wall_s": 1709.7117574199983,
 "ttft": {
  "baseline_s": 0.16851072766803554,
  "after_lt_s": 0.5973703569992116,
  "degradation": 2.544998975827968
 }
}
```

## Sędzia zadań (11 niezgodności F3)

Zgodność Bielika z kluczem w bazie: 0/11; z kluczem człowieka: 0/0 — **wstępnie, brak kluczy człowieka**
