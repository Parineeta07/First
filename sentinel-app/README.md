# SENTINEL

From scattered data to actionable intelligence.

SENTINEL correlates telecom (CDR), network (IPDR) and financial records for a single
incident window and turns the correlated evidence into **investigative leads** — not verdicts.

## Features

- **Investigation Copilot** — fuses weak single-domain signals (call spike, new counterparty,
  rapid transfers, unusual amounts, new IP session) into a ranked cross-domain lead with a
  hypothesis, why-it-matters evidence and recommended next steps.
- **Incident Replay** — plays the incident window chronologically, highlighting the entities
  and relationships involved in the graph as each event fires.
- **Explainable Relationship Graph** — click any link to see *why* two entities are connected:
  call count and last contact, transfer count and totals, shared IP sessions, temporal proximity
  to the incident, and the resulting classification.
- **Investigation Brief** — one click produces WHO → WHAT → WHEN → HOW → CONNECTIONS →
  WHY SUSPICIOUS → WHAT NEXT, plus the entity's activity DNA and the closest historical case.

Every generated statement carries the record IDs it was derived from. The system is decision
support: it identifies evidence-backed leads and keeps the investigator in control.

## Run

```bash
pip install -r requirements.txt
uvicorn sentinel.api:app --reload --port 8000
```

Open http://localhost:8000.

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /api/case` | Case and dataset summary |
| `GET /api/leads?limit=N` | Ranked copilot leads |
| `GET /api/graph` | Entity nodes and correlated edges |
| `GET /api/relationship?source=P007&target=P014` | Relationship explainability |
| `GET /api/replay?entity=P007` | Chronological incident events |
| `GET /api/brief/P007` | Full investigation brief |
| `GET /api/dna/P007` | Activity DNA + historical case match |

## Data

`sentinel/data.py` generates a deterministic synthetic dataset (seed 42) for `CASE-0042`:
baseline traffic across 18 entities for the 12 hours before the incident, plus a planted
cross-domain pattern around the incident window. Swap this module for real ingestion —
the engine only depends on the `Dataset` dataclass.

## Tests

```bash
python -m pytest
```
