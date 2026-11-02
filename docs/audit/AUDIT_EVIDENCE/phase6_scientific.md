# Phase 6 — Scientific accuracy (evidence pointer)

Full narrative: `../SCIENTIFIC_ACCURACY_AUDIT.md`.

Machine sample: `phase6_scientific_sample.json`.

Key confirmed points:

1. Physical peak requires more than a single discovery magnitude; `peak_established` / ≥2 dets gate exists in code intent but index still carries many phot=1 + maxappmag cases.
2. Local sample: derived `maxappmag` with 1 detection on `SN2026aeiv`, `SN2024ggi`.
3. Local scan: 86 possible peak-mislabel cases among 2,718 files (`CATALOG_INTEGRITY.csv`).
4. Catalog.min.json: 65.2% phot=1 — modal product is not a multi-epoch light curve.
5. Distance/extinction/absolute mag only scientifically valid when peak + z + dust inputs are secure — not verified corpus-wide.
