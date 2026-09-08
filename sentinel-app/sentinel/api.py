"""SENTINEL HTTP API and static dashboard host."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .data import DATASET
from .engine import (
    build_relationships,
    case_overview,
    entity_dna,
    explain_relationship,
    generate_leads,
    investigation_brief,
    match_historical,
    replay_events,
)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="SENTINEL", description="From scattered data to actionable intelligence.")


@app.get("/api/case")
def get_case() -> dict:
    return case_overview(DATASET)


@app.get("/api/graph")
def get_graph() -> dict:
    leads = {l.entity_id: l for l in generate_leads(DATASET, limit=len(DATASET.entities))}
    rels = build_relationships(DATASET)
    nodes = [
        {
            "id": eid,
            "name": e.name,
            "risk": leads[eid].confidence if eid in leads else 0,
            "domains": leads[eid].domains if eid in leads else [],
        }
        for eid, e in DATASET.entities.items()
    ]
    edges = [
        {
            "source": rel.source,
            "target": rel.target,
            "strength": rel.strength,
            "domains": rel.domains,
        }
        for rel in rels.values()
        if rel.strength >= 15
    ]
    return {"nodes": nodes, "edges": edges}


@app.get("/api/leads")
def get_leads(limit: int = 5) -> dict:
    leads = generate_leads(DATASET, limit=limit)
    return {
        "leads": [
            {
                **{k: v for k, v in asdict(l).items() if k != "signals"},
                "signals": [asdict(s) for s in l.signals],
            }
            for l in leads
        ]
    }


@app.get("/api/relationship")
def get_relationship(source: str, target: str) -> dict:
    result = explain_relationship(DATASET, source, target)
    if not result["exists"]:
        raise HTTPException(status_code=404, detail="No recorded relationship between these entities")
    return result


@app.get("/api/replay")
def get_replay(entity: str | None = None) -> dict:
    return {"events": replay_events(DATASET, entity)}


@app.get("/api/brief/{entity_id}")
def get_brief(entity_id: str) -> dict:
    if entity_id not in DATASET.entities:
        raise HTTPException(status_code=404, detail="Unknown entity")
    return investigation_brief(DATASET, entity_id)


@app.get("/api/dna/{entity_id}")
def get_dna(entity_id: str) -> dict:
    if entity_id not in DATASET.entities:
        raise HTTPException(status_code=404, detail="Unknown entity")
    dna = entity_dna(DATASET, entity_id)
    return {"entity_id": entity_id, "dna": dna, "historical_matches": match_historical(dna)}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
