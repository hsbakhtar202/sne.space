# AUDIT_EVIDENCE — index

Read-only baseline captured during the independent data-integrity audit.  
**Do not overwrite.** Add follow-up evidence under a dated sibling directory if re-auditing after fixes.

| Artifact | Phase | Contents |
| --- | --- | --- |
| `AUDIT_STARTED_UTC.txt` | meta | Audit start timestamp |
| `AUDIT_COMPLETED_UTC.txt` | meta | Audit report pack completion timestamp |
| `phase1_architecture.md` | 1 | Architecture map, subsystem classifications, path:line citations |
| `phase2_catalog_min_scan.json` | 2 | Full `catalog.min.json` aggregate stats (photolink-based) |
| `phase2_local_scan_summary.json` | 2 | Local event JSON array-level scan (n≈2718) |
| `phase2_local_events_sample.csv` | 2 | Sample rows from local scan |
| `phase3_sample_method.json` | 3 | Sampling method + event list (n=22; shortfall vs ≥30 noted) |
| `phase3_reconciliation_rows.json` | 3 | Machine-readable reconciliation |
| `phase3_raw/*` | 3 | Per-event TNS/ALeRCE/API/local phot stats (sanitized) |
| `phase4_prod_api_probes.json` | 4 | Public API probes |
| `phase4_docker_compose_excerpt.txt` | 4 | Volume/scheduler-relevant compose excerpt |
| `phase5_controlled_e2e.md` | 5 | What was / was not executed under no-mutation rules |
| `phase6_scientific.md` | 6 | Scientific accuracy notes (if present) |
| `phase6_scientific_sample.json` | 6 | Peak/maxappmag sample findings |

Parent reports: `../AUDIT_EXECUTIVE_SUMMARY.md`, `../CATALOG_INTEGRITY.csv`, `../UPSTREAM_RECONCILIATION.csv`, `../PIPELINE_EXECUTION_AUDIT.md`, `../SCIENTIFIC_ACCURACY_AUDIT.md`, `../REMEDIATION_PLAN.md`.
