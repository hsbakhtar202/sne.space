# Step 1 status

**Updated:** 2026-09-24

## Running locally

| Service | URL |
| --- | --- |
| Catalog UI + IA + resolver | http://127.0.0.1:8080/ |
| OACAPI | http://127.0.0.1:8090/ |

```bash
python3 serve/server.py
# other terminal:
cd vendor/OACAPI && OSC_AC_PATH="$(pwd)/../astrocats/astrocats" OSC_API_CATALOGS=sne \
  .venv/bin/flask --app api:app run --host 127.0.0.1 --port 8090
```

## Done

- **S1.1** webcat aggregates: `catalog.min.json` / `names.min.json` (55,449 events)
- **S1.2** Transient Table on `/` over historical `/astrocats/.../output/` paths
- **S1.3** native `/sne/` + `/event/` resolver (SN prepend, aliases, SN↔AT, Levenshtein)
- **S1.4** OACAPI on same corpus
- **S1.5** thin IA pages at historical slugs; dupes/conflicts tables live
- **Event HTML** via webcat from JSON (not hand-written): growing set under `output/html/`
- **Fallback event pages** from event JSON when Bokeh HTML not yet generated
- **Proof:** `serve/test_resolver.py`, `serve/proof_suite.py`, `serve/crawl_resolve_sweep.py`

## Corpus notes

- ~7.3k crawl `/sne/` names resolve into the GitHub catalog; ~1.7k crawl names are not in corpus (post-cutoff, ranges, junk)
- Full Bokeh HTML for all 7k+ is large; prioritized by photometry/spectra richness + crawl linkage

## Next

- Continue batch HTML for remaining crawl-heavy events
- Drive proof suite toward full ~14.4k URL inventory (IA + `/astrocats/` static + query variants)
- S1.7 production DNS when suite is green enough
