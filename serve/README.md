# Local sne.space (Step 1)

See [STATUS.md](STATUS.md) for current progress.

## Start

```bash
# Catalog UI + event resolver + IA pages (port 8080)
python3 serve/server.py

# OACAPI (port 8090) — separate terminal
cd vendor/OACAPI
OSC_AC_PATH="$(pwd)/../astrocats/astrocats" OSC_API_CATALOGS=sne \
  .venv/bin/flask --app api:app run --host 127.0.0.1 --port 8090
```

## Routes

| URL | What |
| --- | --- |
| http://127.0.0.1:8080/ | Transient Table |
| http://127.0.0.1:8080/about/ | Thin IA pages (also `/download/`, `/contribute/`, …) |
| http://127.0.0.1:8080/sne/2011fe/ | Event resolver → HTML |
| http://127.0.0.1:8080/sne/SN2011fe.json | Event JSON download |
| http://127.0.0.1:8090/sne/SN2011fe/redshift | OACAPI |

## Proof suite

```bash
python3 serve/proof_suite.py --crawl-limit 150
```

## Regenerate

```bash
cd vendor/astrocats
# Aggregates
uv run python -m astrocats.scripts.webcat -c sne --no-write-html --no-collect-hosts

# Priority event HTML
uv run python -m astrocats.scripts.webcat -c sne \
  --event-list SN2011fe SN1987A SN2014J \
  --no-collect-hosts --no-write-catalog --force-html
```
