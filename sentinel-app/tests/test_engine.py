from sentinel.data import BRIDGE_ENTITY, DATASET, PARTNER_ENTITY
from sentinel.engine import (
    entity_dna,
    explain_relationship,
    generate_leads,
    investigation_brief,
    match_historical,
    replay_events,
)


def test_bridge_entity_is_top_lead_and_cross_domain():
    leads = generate_leads(DATASET)
    top = leads[0]
    assert top.entity_id == BRIDGE_ENTITY
    assert set(top.domains) == {"communication", "financial", "network"}
    assert top.evidence_count > 0
    assert top.next_steps


def test_cross_domain_lead_outranks_single_domain_lead():
    leads = generate_leads(DATASET, limit=len(DATASET.entities))
    multi = [l for l in leads if len(l.domains) >= 2]
    single = [l for l in leads if len(l.domains) == 1]
    assert multi and single
    assert min(l.score for l in multi) > max(l.score for l in single)


def test_relationship_explanation_cites_every_domain():
    r = explain_relationship(DATASET, BRIDGE_ENTITY, PARTNER_ENTITY)
    assert r["exists"]
    assert r["communication"]["calls"] > 0
    assert r["financial"]["transfers"] > 0
    assert r["network"]["shared_ips"]
    assert r["temporal_correlation"]["records_in_window"] > 0
    assert 0 < r["strength"] <= 100


def test_replay_is_chronological_and_windowed():
    events = replay_events(DATASET, BRIDGE_ENTITY)
    assert events
    assert events == sorted(events, key=lambda e: e["timestamp"])
    assert {e["kind"] for e in events} == {"communication", "financial", "network"}


def test_brief_has_all_sections():
    b = investigation_brief(DATASET, BRIDGE_ENTITY)
    assert b["primary_entity"]["entity_id"] == BRIDGE_ENTITY
    assert b["timeline"] and b["anomalies"] and b["correlation"]
    assert b["lead"]["confidence"] > 0
    assert sum(b["dna"].values()) == 100
    assert b["historical_matches"][0]["match"] >= b["historical_matches"][-1]["match"]


def test_dna_sums_to_100_for_every_entity():
    for eid in DATASET.entities:
        dna = entity_dna(DATASET, eid)
        assert sum(dna.values()) == 100
        assert all(0 <= v <= 100 for v in match_historical(dna)[0]["dna"].values())
