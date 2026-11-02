# P0B Restore Manifest (inventory only)

Drawn: `2026-10-31T16:42:08.196201+00:00`

| Metric | Value |
| --- | ---: |
| Production index names | 110565 |
| Upstream event JSON names (union) | 99710 |
| Local laptop event JSON | 2718 |
| Recoverable from upstream ∩ index | 99672 (90.15%) |
| Index not in upstream | 10893 |
| Conflict candidates (local∩upstream∩index) | 21 |

## Pinned partitions

- `astrocatalogs/sne-pre-1990` @ `5a55865ad5bf` — 5228 JSON (pushed 2022-04-11T19:49:16Z)
- `astrocatalogs/sne-1990-1999` @ `14546f31a5e3` — 2357 JSON (pushed 2022-04-11T19:49:21Z)
- `astrocatalogs/sne-2000-2004` @ `2c1fd645ec1c` — 1924 JSON (pushed 2022-04-11T19:49:27Z)
- `astrocatalogs/sne-2005-2009` @ `d798967beb1d` — 7996 JSON (pushed 2022-04-11T19:49:40Z)
- `astrocatalogs/sne-2010-2014` @ `59ccf91a9cd0` — 10319 JSON (pushed 2022-04-11T19:50:01Z)
- `astrocatalogs/sne-2015-2019` @ `94f5ec15b228` — 27657 JSON (pushed 2022-04-11T19:50:29Z)
- `astrocatalogs/sne-2020-2024` @ `3bbe79d7790d` — 44229 JSON (pushed 2022-04-11T19:51:22Z)

## Next steps (staging only)

1. Sparse-checkout / download only names in `index_not_on_volume` ∩ upstream.
2. Provenance-aware merge for conflict candidates; never blind overwrite enriched files.
3. Verify restored arrays vs advertised photolink/spectralink.
4. Report remaining gaps before any production sync.
