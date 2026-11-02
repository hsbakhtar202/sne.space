# Phase 5 — Controlled end-to-end verification

**Constraint:** Audit rules forbid production mutations, backfills, and “fix then claim PASS.”  
No isolated staging volume was provisioned on the audit host. Therefore Phase 5 is **PARTIAL** — composed of read-only live probes and code-path tracing, not a full crash-injection battery.

## Executed (read-only / observational)

| # | Scenario | How tested | Result |
| --- | --- | --- | --- |
| 1 | New TNS AT, weak/no ALeRCE | Live TNS + prod API for AT2026ah\* | Names on API; phot=0; TNS often 1 det |
| 2 | TNS det + non-detection | AT2026agub TNS fetch + local JSON | Upstream 1/1; local 1/1; API phot=0 |
| 3 | TNS + ALeRCE overlap | SN2023ixf | ALeRCE 111; local≈110; API 110 |
| 4 | Dense multiband ALeRCE | SN2023ixf | PASS for historical enrich path |
| 5 | Historical OSC event | SN2011fe, SN1987A, … | Rich local+API match |
| 6 | WISeREP spectra on pull | Code inspection | Disabled (`enrich_wiserep=False`) |
| 7 | No accessible upstream phot | Some historical TNS empty | Distinguish absent vs inaccessible |
| 12 | Homepage SSR vs API | Prod API + prior dual-catalog analysis | Names fresh; phot stubs diverge |

## Not executed (would mutate / needs staging)

| # | Scenario | Why skipped |
| --- | --- | --- |
| 8 | TNS timeout fault injection | Would require mock proxy or live abuse |
| 9 | Duplicate discovery processing | Mutates catalog |
| 10 | Crash mid JSON→SQLite publish | Needs staging + kill |
| 11 | Container restart persistence | Needs prod/staging ops access |
| 13 | Source correction overwrite | Mutates |
| 14 | Failed enrich then retry | Mutates / needs job control |

## Evidence chain template (where observed)

For AT2026agub:

`TNS request → ok response (1 det, 1 lim) → parse/normalize → local event JSON persist → [gap] CatalogStore phot=0 → API FAIL → UI not fully checked`

Raw files: `phase3_raw/AT2026agub_*`.
