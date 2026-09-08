"""Correlation, anomaly and lead-generation engine.

Weak single-domain signals are scored independently, then fused: an entity that
trips signals in several domains inside the incident window is promoted to an
investigative lead. Nothing here asserts guilt — every output carries the
evidence record IDs it was derived from so an investigator can verify it.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from .data import (
    CASE_ID,
    DATASET,
    INCIDENT_TIME,
    INCIDENT_WINDOW,
    CallRecord,
    Dataset,
    IpSession,
    Transaction,
)

DOMAINS = ("communication", "financial", "network")
RAPID_TRANSFER_GAP = timedelta(minutes=10)
LARGE_TRANSFER = 35_000.0

# Weight of each signal when fusing into a cross-domain score.
SIGNAL_WEIGHTS = {
    "call_frequency_spike": 0.22,
    "new_counterparty": 0.14,
    "rapid_transfers": 0.24,
    "unusual_transfer_amount": 0.16,
    "new_ip_session": 0.18,
    "incident_window_activity": 0.12,
}


@dataclass
class Signal:
    signal_id: str
    domain: str
    title: str
    detail: str
    strength: float  # 0..1, confidence in this individual weak signal
    evidence: list[str]


@dataclass
class Lead:
    entity_id: str
    score: float
    confidence: int
    domains: list[str]
    signals: list[Signal]
    connected_entities: list[str]
    evidence_count: int
    hypothesis: str
    why_it_matters: list[str]
    next_steps: list[str]


def in_window(ts: datetime) -> bool:
    return INCIDENT_TIME <= ts <= INCIDENT_TIME + INCIDENT_WINDOW


def _before_window(ts: datetime) -> bool:
    return ts < INCIDENT_TIME


def _call_signals(entity_id: str, calls: list[CallRecord]) -> list[Signal]:
    window_calls = [c for c in calls if in_window(c.timestamp)]
    prior = [c for c in calls if _before_window(c.timestamp)]
    signals: list[Signal] = []
    if not window_calls:
        return signals

    hours_before = max(
        1.0, (INCIDENT_TIME - min((c.timestamp for c in prior), default=INCIDENT_TIME)).total_seconds() / 3600
    )
    baseline_rate = len(prior) / hours_before
    window_rate = len(window_calls) / (INCIDENT_WINDOW.total_seconds() / 3600)
    ratio = window_rate / baseline_rate if baseline_rate else float(len(window_calls))
    if ratio >= 2.0 and len(window_calls) >= 3:
        signals.append(
            Signal(
                signal_id="call_frequency_spike",
                domain="communication",
                title="Call frequency spike",
                detail=(
                    f"{len(window_calls)} calls in the incident window vs a baseline of "
                    f"{baseline_rate:.1f}/hour ({ratio:.1f}x increase)"
                ),
                strength=min(1.0, ratio / 6.0),
                evidence=[c.record_id for c in window_calls],
            )
        )

    known = {c.callee if c.caller == entity_id else c.caller for c in prior}
    new_contacts = {
        (c.callee if c.caller == entity_id else c.caller) for c in window_calls
    } - known
    if new_contacts:
        first_contact = [
            c.record_id
            for c in window_calls
            if (c.callee if c.caller == entity_id else c.caller) in new_contacts
        ]
        signals.append(
            Signal(
                signal_id="new_counterparty",
                domain="communication",
                title="New counterparties",
                detail=f"First-ever contact with {', '.join(sorted(new_contacts))} during the window",
                strength=min(1.0, 0.35 + 0.2 * len(new_contacts)),
                evidence=first_contact,
            )
        )
    return signals


def _transaction_signals(entity_id: str, txns: list[Transaction]) -> list[Signal]:
    outgoing = sorted(
        (t for t in txns if t.sender == entity_id and in_window(t.timestamp)),
        key=lambda t: t.timestamp,
    )
    prior = [t for t in txns if t.sender == entity_id and _before_window(t.timestamp)]
    signals: list[Signal] = []
    if not outgoing:
        return signals

    rapid: list[Transaction] = []
    for a, b in zip(outgoing, outgoing[1:]):
        if b.timestamp - a.timestamp <= RAPID_TRANSFER_GAP:
            rapid.extend(x for x in (a, b) if x not in rapid)
    if len(rapid) >= 2:
        total = sum(t.amount for t in rapid)
        span = (rapid[-1].timestamp - rapid[0].timestamp).total_seconds() / 60
        signals.append(
            Signal(
                signal_id="rapid_transfers",
                domain="financial",
                title="Rapid successive transfers",
                detail=f"{len(rapid)} outgoing transfers totalling Rs {total:,.0f} within {span:.0f} minutes",
                strength=min(1.0, 0.4 + 0.15 * len(rapid)),
                evidence=[t.record_id for t in rapid],
            )
        )

    baseline_max = max((t.amount for t in prior), default=0.0)
    unusual = [t for t in outgoing if t.amount >= LARGE_TRANSFER and t.amount > baseline_max]
    if unusual:
        signals.append(
            Signal(
                signal_id="unusual_transfer_amount",
                domain="financial",
                title="Unusual transfer amounts",
                detail=(
                    f"{len(unusual)} transfer{'s' if len(unusual) > 1 else ''} above the entity's "
                    f"historical maximum of Rs {baseline_max:,.0f}"
                ),
                strength=min(1.0, 0.4 + 0.15 * len(unusual)),
                evidence=[t.record_id for t in unusual],
            )
        )
    return signals


def _session_signals(entity_id: str, sessions: list[IpSession]) -> list[Signal]:
    window = [s for s in sessions if in_window(s.timestamp)]
    prior_ips = {s.ip_address for s in sessions if _before_window(s.timestamp)}
    signals: list[Signal] = []
    new_ips = {s.ip_address for s in window} - prior_ips
    if new_ips:
        signals.append(
            Signal(
                signal_id="new_ip_session",
                domain="network",
                title="New IP / session behaviour",
                detail=f"Sessions from previously unseen address(es) {', '.join(sorted(new_ips))}",
                strength=min(1.0, 0.45 + 0.2 * len(new_ips)),
                evidence=[s.record_id for s in window if s.ip_address in new_ips],
            )
        )
    return signals


def entity_signals(ds: Dataset, entity_id: str) -> list[Signal]:
    calls, sessions, txns = ds.records_for(entity_id)
    signals = (
        _call_signals(entity_id, calls)
        + _transaction_signals(entity_id, txns)
        + _session_signals(entity_id, sessions)
    )
    window_records = (
        [c.record_id for c in calls if in_window(c.timestamp)]
        + [s.record_id for s in sessions if in_window(s.timestamp)]
        + [t.record_id for t in txns if in_window(t.timestamp)]
    )
    if len(window_records) >= 5 and len({s.domain for s in signals}) >= 2:
        signals.append(
            Signal(
                signal_id="incident_window_activity",
                domain="temporal",
                title="Concentrated incident-window activity",
                detail=f"{len(window_records)} records inside the {int(INCIDENT_WINDOW.total_seconds() // 60)}-minute incident window",
                strength=min(1.0, len(window_records) / 20),
                evidence=window_records,
            )
        )
    return signals


# --- relationships ----------------------------------------------------------


@dataclass
class Relationship:
    source: str
    target: str
    strength: int
    domains: list[str]
    calls: list[CallRecord]
    transactions: list[Transaction]
    shared_ips: list[str]
    evidence: list[str]


def _pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def build_relationships(ds: Dataset) -> dict[tuple[str, str], Relationship]:
    calls_by_pair: dict[tuple[str, str], list[CallRecord]] = defaultdict(list)
    txns_by_pair: dict[tuple[str, str], list[Transaction]] = defaultdict(list)
    for c in ds.calls:
        calls_by_pair[_pair(c.caller, c.callee)].append(c)
    for t in ds.transactions:
        txns_by_pair[_pair(t.sender, t.receiver)].append(t)

    ips_by_entity: dict[str, set[str]] = defaultdict(set)
    for s in ds.sessions:
        ips_by_entity[s.entity_id].add(s.ip_address)

    rels: dict[tuple[str, str], Relationship] = {}
    for pair in set(calls_by_pair) | set(txns_by_pair):
        a, b = pair
        calls = sorted(calls_by_pair.get(pair, []), key=lambda c: c.timestamp)
        txns = sorted(txns_by_pair.get(pair, []), key=lambda t: t.timestamp)
        shared_ips = sorted(ips_by_entity[a] & ips_by_entity[b])
        domains = []
        if calls:
            domains.append("communication")
        if txns:
            domains.append("financial")
        if shared_ips:
            domains.append("network")

        window_records = [r for r in calls if in_window(r.timestamp)] + [
            r for r in txns if in_window(r.timestamp)
        ]
        strength = (
            min(35, 5 * len(calls))
            + min(30, 8 * len(txns))
            + min(20, 10 * len(shared_ips))
            + min(15, 4 * len(window_records))
        )
        rels[pair] = Relationship(
            source=a,
            target=b,
            strength=strength,
            domains=domains,
            calls=calls,
            transactions=txns,
            shared_ips=shared_ips,
            evidence=[r.record_id for r in calls] + [r.record_id for r in txns],
        )
    return rels


def explain_relationship(ds: Dataset, a: str, b: str) -> dict:
    rel = build_relationships(ds).get(_pair(a, b))
    if rel is None:
        return {"exists": False, "source": a, "target": b}

    window_records = [r for r in rel.calls if in_window(r.timestamp)] + [
        r for r in rel.transactions if in_window(r.timestamp)
    ]
    temporal = None
    if window_records:
        offsets = [
            abs((r.timestamp - INCIDENT_TIME).total_seconds()) / 60 for r in window_records
        ]
        temporal = {
            "records_in_window": len(window_records),
            "closest_minutes_to_incident": round(min(offsets)),
            "spread_minutes": round(max(offsets) - min(offsets)),
        }

    return {
        "exists": True,
        "source": rel.source,
        "target": rel.target,
        "strength": rel.strength,
        "classification": " + ".join(d.title() for d in rel.domains) or "Unclassified",
        "domains": rel.domains,
        "communication": {
            "calls": len(rel.calls),
            "total_duration_s": sum(c.duration_s for c in rel.calls),
            "last_contact": rel.calls[-1].timestamp.isoformat() if rel.calls else None,
            "evidence": [c.record_id for c in rel.calls],
        },
        "financial": {
            "transfers": len(rel.transactions),
            "total_amount": sum(t.amount for t in rel.transactions),
            "evidence": [t.record_id for t in rel.transactions],
        },
        "network": {"shared_ips": rel.shared_ips},
        "temporal_correlation": temporal,
        "evidence_count": len(rel.evidence),
    }


# --- lead generation --------------------------------------------------------


def _connected(ds: Dataset, entity_id: str) -> list[str]:
    """Entities linked to `entity_id`, strongest relationship first."""
    linked = [
        (rel.strength, b if a == entity_id else a)
        for (a, b), rel in build_relationships(ds).items()
        if entity_id in (a, b) and rel.strength >= 20
    ]
    linked.sort(key=lambda item: (-item[0], item[1]))
    return [eid for _, eid in linked]


def _hypothesis(entity_id: str, domains: list[str], connected: list[str]) -> str:
    if len(domains) >= 3:
        return (
            f"{entity_id} appears to act as a bridge across telecom, financial and network activity "
            f"during the incident window, with recurring contact to {', '.join(connected[:3])}."
        )
    if len(domains) == 2:
        return (
            f"{entity_id} shows correlated {' and '.join(domains)} activity concentrated around the "
            f"incident window."
        )
    return f"{entity_id} shows isolated {domains[0]} anomalies around the incident window."


def _next_steps(ds: Dataset, entity_id: str, signals: list[Signal], connected: list[str]) -> list[str]:
    ids = {s.signal_id for s in signals}
    steps: list[str] = []
    if connected:
        steps.append(f"Examine {entity_id} <-> {connected[0]} communication records in full.")
    if "rapid_transfers" in ids or "unusual_transfer_amount" in ids:
        steps.append("Review transactions immediately before and after the incident time.")
    if "new_ip_session" in ids:
        steps.append("Verify the IP / device association for the sessions in the incident window.")
    if "new_counterparty" in ids:
        steps.append("Identify the subscribers behind the new counterparties.")
    steps.append("Compare this activity distribution with historical cases.")
    return steps


def generate_leads(ds: Dataset = DATASET, limit: int = 5) -> list[Lead]:
    leads: list[Lead] = []
    for entity_id in ds.entities:
        signals = entity_signals(ds, entity_id)
        if not signals:
            continue
        domains = sorted({s.domain for s in signals if s.domain in DOMAINS})
        if not domains:
            continue

        base = sum(SIGNAL_WEIGHTS.get(s.signal_id, 0.1) * s.strength for s in signals)
        # Cross-domain fusion: several weak signals in different domains are
        # worth more than the same number of signals in one domain.
        fusion = 1.0 + 0.35 * (len(domains) - 1)
        score = min(0.95, base * fusion)
        connected = _connected(ds, entity_id)
        evidence_count = sum(len(s.evidence) for s in signals)

        leads.append(
            Lead(
                entity_id=entity_id,
                score=round(score, 3),
                confidence=int(round(score * 100)),
                domains=domains,
                signals=signals,
                connected_entities=connected,
                evidence_count=evidence_count,
                hypothesis=_hypothesis(entity_id, domains, connected),
                why_it_matters=[s.detail for s in signals],
                next_steps=_next_steps(ds, entity_id, signals, connected),
            )
        )

    leads.sort(key=lambda l: (-l.score, l.entity_id))
    return leads[:limit]


# --- entity DNA + historical comparison -------------------------------------

HISTORICAL_CASES = [
    {
        "case_id": "CASE-0017",
        "label": "Layered mule network (closed)",
        "dna": {"financial": 35, "communication": 30, "network": 21, "social": 14},
    },
    {
        "case_id": "CASE-0031",
        "label": "SIM-box telecom fraud (closed)",
        "dna": {"financial": 12, "communication": 58, "network": 22, "social": 8},
    },
    {
        "case_id": "CASE-0009",
        "label": "Compromised-account takeover (closed)",
        "dna": {"financial": 41, "communication": 14, "network": 38, "social": 7},
    },
]


def entity_dna(ds: Dataset, entity_id: str) -> dict[str, int]:
    calls, sessions, txns = ds.records_for(entity_id)
    counts = {
        "communication": len(calls),
        "financial": len(txns),
        "network": len(sessions),
        "social": len(_connected(ds, entity_id)),
    }
    total = sum(counts.values()) or 1
    dna = {k: round(v * 100 / total) for k, v in counts.items()}
    drift = 100 - sum(dna.values())
    if drift:
        top = max(dna, key=lambda k: dna[k])
        dna[top] += drift
    return dna


def match_historical(dna: dict[str, int]) -> list[dict]:
    out = []
    for case in HISTORICAL_CASES:
        distance = sum(abs(dna.get(k, 0) - v) for k, v in case["dna"].items())
        out.append({**case, "match": max(0, round(100 - distance / 2))})
    out.sort(key=lambda c: -c["match"])
    return out


# --- incident replay --------------------------------------------------------


def replay_events(ds: Dataset, entity_id: str | None = None) -> list[dict]:
    events: list[dict] = []

    def relevant(*ids: str) -> bool:
        return entity_id is None or entity_id in ids

    for c in ds.calls:
        if in_window(c.timestamp) and relevant(c.caller, c.callee):
            events.append(
                {
                    "timestamp": c.timestamp.isoformat(),
                    "kind": "communication",
                    "icon": "call",
                    "title": f"Call {c.caller} -> {c.callee}",
                    "detail": f"{c.duration_s}s via {c.cell_site}",
                    "entities": [c.caller, c.callee],
                    "record_id": c.record_id,
                }
            )
    for s in ds.sessions:
        if in_window(s.timestamp) and relevant(s.entity_id):
            events.append(
                {
                    "timestamp": s.timestamp.isoformat(),
                    "kind": "network",
                    "icon": "ip",
                    "title": f"IP session {s.entity_id} @ {s.ip_address}",
                    "detail": f"{s.duration_s}s, {s.bytes_out / 1000:.0f} KB out",
                    "entities": [s.entity_id],
                    "record_id": s.record_id,
                }
            )
    for t in ds.transactions:
        if in_window(t.timestamp) and relevant(t.sender, t.receiver):
            events.append(
                {
                    "timestamp": t.timestamp.isoformat(),
                    "kind": "financial",
                    "icon": "money",
                    "title": f"Transfer Rs {t.amount:,.0f} {t.sender} -> {t.receiver}",
                    "detail": t.channel,
                    "entities": [t.sender, t.receiver],
                    "record_id": t.record_id,
                }
            )

    events.sort(key=lambda e: e["timestamp"])
    return events


# --- investigation brief ----------------------------------------------------


def investigation_brief(ds: Dataset, entity_id: str) -> dict:
    calls, sessions, txns = ds.records_for(entity_id)
    leads = {l.entity_id: l for l in generate_leads(ds, limit=len(ds.entities))}
    lead = leads.get(entity_id)
    signals = lead.signals if lead else entity_signals(ds, entity_id)
    connected = _connected(ds, entity_id)
    dna = entity_dna(ds, entity_id)

    rels = build_relationships(ds)
    correlation = []
    for other in connected:
        rel = rels[_pair(entity_id, other)]
        correlation.append({"entity_id": other, "domains": rel.domains, "strength": rel.strength})

    return {
        "case_id": CASE_ID,
        "generated_for": entity_id,
        "primary_entity": {
            "entity_id": entity_id,
            "name": ds.entities[entity_id].name,
            "msisdn": ds.entities[entity_id].msisdn,
            "account": ds.entities[entity_id].account,
        },
        "activity": {
            "communications": len(calls),
            "transactions": len(txns),
            "ip_sessions": len(sessions),
            "connected_entities": len(connected),
        },
        "timeline": replay_events(ds, entity_id),
        "correlation": correlation,
        "anomalies": [
            {"title": s.title, "detail": s.detail, "domain": s.domain, "evidence": s.evidence}
            for s in signals
        ],
        "lead": {
            "hypothesis": lead.hypothesis if lead else "No cross-domain lead generated.",
            "confidence": lead.confidence if lead else 0,
            "next_steps": lead.next_steps if lead else [],
            "evidence_count": lead.evidence_count if lead else 0,
        },
        "dna": dna,
        "historical_matches": match_historical(dna),
        "disclaimer": (
            "Decision support only. Findings are evidence-backed investigative leads, "
            "not determinations of wrongdoing."
        ),
    }


def case_overview(ds: Dataset = DATASET) -> dict:
    kinds = Counter()
    for e in replay_events(ds):
        kinds[e["kind"]] += 1
    return {
        "case_id": CASE_ID,
        "incident_time": INCIDENT_TIME.isoformat(),
        "window_minutes": int(INCIDENT_WINDOW.total_seconds() // 60),
        "totals": {
            "entities": len(ds.entities),
            "cdr": len(ds.calls),
            "ipdr": len(ds.sessions),
            "transactions": len(ds.transactions),
        },
        "window_events": dict(kinds),
    }
