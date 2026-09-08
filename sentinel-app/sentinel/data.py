"""Synthetic multi-source investigation dataset: CDR, IPDR and financial transactions.

The generator is deterministic (fixed seed) so demos and tests are reproducible.
One case (CASE-0042) contains a planted cross-domain pattern: a bridge entity
that spikes in call activity, opens a new IP session and moves money rapidly
around the incident window.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

CASE_ID = "CASE-0042"
INCIDENT_TIME = datetime(2026, 3, 14, 18, 0)
INCIDENT_WINDOW = timedelta(minutes=45)

ENTITY_COUNT = 18
BRIDGE_ENTITY = "P007"
PARTNER_ENTITY = "P014"
SECONDARY_ENTITY = "P011"


@dataclass(frozen=True)
class Entity:
    entity_id: str
    name: str
    msisdn: str
    account: str
    devices: tuple[str, ...]


@dataclass(frozen=True)
class CallRecord:
    record_id: str
    caller: str
    callee: str
    timestamp: datetime
    duration_s: int
    cell_site: str


@dataclass(frozen=True)
class IpSession:
    record_id: str
    entity_id: str
    timestamp: datetime
    duration_s: int
    ip_address: str
    device_id: str
    bytes_out: int


@dataclass(frozen=True)
class Transaction:
    record_id: str
    sender: str
    receiver: str
    timestamp: datetime
    amount: float
    channel: str


@dataclass
class Dataset:
    entities: dict[str, Entity]
    calls: list[CallRecord] = field(default_factory=list)
    sessions: list[IpSession] = field(default_factory=list)
    transactions: list[Transaction] = field(default_factory=list)

    def records_for(self, entity_id: str) -> tuple[list[CallRecord], list[IpSession], list[Transaction]]:
        calls = [c for c in self.calls if entity_id in (c.caller, c.callee)]
        sessions = [s for s in self.sessions if s.entity_id == entity_id]
        txns = [t for t in self.transactions if entity_id in (t.sender, t.receiver)]
        return calls, sessions, txns


def _entity_id(index: int) -> str:
    return f"P{index:03d}"


FIRST_NAMES = [
    "Arjun", "Meera", "Rohit", "Kavya", "Imran", "Divya", "Sanjay", "Nisha",
    "Vikram", "Pooja", "Farhan", "Anita", "Rahul", "Sneha", "Ajay", "Ritu",
    "Zoya", "Manish",
]


def _build_entities() -> dict[str, Entity]:
    entities: dict[str, Entity] = {}
    for i in range(1, ENTITY_COUNT + 1):
        eid = _entity_id(i)
        entities[eid] = Entity(
            entity_id=eid,
            name=FIRST_NAMES[(i - 1) % len(FIRST_NAMES)],
            msisdn=f"+9198{i:08d}",
            account=f"AC{40000 + i * 7}",
            devices=(f"IMEI-{100000 + i * 13}",),
        )
    return entities


def _baseline_activity(rng: random.Random, ds: Dataset, ids: list[str]) -> None:
    """Ordinary traffic across the 12 hours preceding the incident."""
    seq = 0
    for hour in range(12, 0, -1):
        base = INCIDENT_TIME - timedelta(hours=hour)
        for _ in range(rng.randint(4, 9)):
            a, b = rng.sample(ids, 2)
            seq += 1
            ds.calls.append(
                CallRecord(
                    record_id=f"CDR-{seq:04d}",
                    caller=a,
                    callee=b,
                    timestamp=base + timedelta(minutes=rng.randint(0, 59)),
                    duration_s=rng.randint(20, 600),
                    cell_site=f"CELL-{rng.randint(1, 12):02d}",
                )
            )
        for _ in range(rng.randint(2, 5)):
            e = rng.choice(ids)
            seq += 1
            ds.sessions.append(
                IpSession(
                    record_id=f"IPDR-{seq:04d}",
                    entity_id=e,
                    timestamp=base + timedelta(minutes=rng.randint(0, 59)),
                    duration_s=rng.randint(60, 3600),
                    ip_address=f"10.24.{rng.randint(0, 8)}.{rng.randint(2, 254)}",
                    device_id=ds.entities[e].devices[0],
                    bytes_out=rng.randint(10_000, 900_000),
                )
            )
        for _ in range(rng.randint(1, 4)):
            a, b = rng.sample(ids, 2)
            seq += 1
            ds.transactions.append(
                Transaction(
                    record_id=f"TXN-{seq:04d}",
                    sender=a,
                    receiver=b,
                    timestamp=base + timedelta(minutes=rng.randint(0, 59)),
                    amount=float(rng.randrange(500, 25_000, 500)),
                    channel=rng.choice(["UPI", "IMPS", "NEFT"]),
                )
            )


def _planted_pattern(ds: Dataset) -> None:
    """The cross-domain signal the copilot is expected to surface."""
    t = INCIDENT_TIME

    def at(minutes: int) -> datetime:
        return t + timedelta(minutes=minutes)

    calls = [
        (2, BRIDGE_ENTITY, PARTNER_ENTITY, 41),
        (4, BRIDGE_ENTITY, PARTNER_ENTITY, 63),
        (6, PARTNER_ENTITY, BRIDGE_ENTITY, 28),
        (9, BRIDGE_ENTITY, SECONDARY_ENTITY, 95),
        (14, BRIDGE_ENTITY, PARTNER_ENTITY, 22),
        (16, BRIDGE_ENTITY, PARTNER_ENTITY, 34),
        (19, BRIDGE_ENTITY, SECONDARY_ENTITY, 51),
        (21, PARTNER_ENTITY, BRIDGE_ENTITY, 18),
        (24, BRIDGE_ENTITY, "P003", 77),
        (27, BRIDGE_ENTITY, PARTNER_ENTITY, 30),
        (31, PARTNER_ENTITY, SECONDARY_ENTITY, 44),
        (35, BRIDGE_ENTITY, "P003", 26),
    ]
    for i, (minute, a, b, dur) in enumerate(calls, start=1):
        ds.calls.append(
            CallRecord(
                record_id=f"CDR-INC-{i:03d}",
                caller=a,
                callee=b,
                timestamp=at(minute),
                duration_s=dur,
                cell_site="CELL-07",
            )
        )

    sessions = [
        (7, BRIDGE_ENTITY, "203.0.113.44", 1450),
        (8, PARTNER_ENTITY, "203.0.113.44", 1180),
        (18, BRIDGE_ENTITY, "203.0.113.44", 940),
        (23, SECONDARY_ENTITY, "198.51.100.9", 610),
    ]
    for i, (minute, e, ip, dur) in enumerate(sessions, start=1):
        ds.sessions.append(
            IpSession(
                record_id=f"IPDR-INC-{i:03d}",
                entity_id=e,
                timestamp=at(minute),
                duration_s=dur,
                ip_address=ip,
                device_id=ds.entities[e].devices[0],
                bytes_out=1_400_000 + i * 30_000,
            )
        )

    txns = [
        (11, BRIDGE_ENTITY, PARTNER_ENTITY, 45_000.0, "IMPS"),
        (14, BRIDGE_ENTITY, PARTNER_ENTITY, 42_000.0, "IMPS"),
        (17, BRIDGE_ENTITY, SECONDARY_ENTITY, 38_500.0, "UPI"),
        (20, PARTNER_ENTITY, "P003", 40_000.0, "IMPS"),
        (26, BRIDGE_ENTITY, PARTNER_ENTITY, 40_000.0, "UPI"),
        (33, BRIDGE_ENTITY, "P003", 36_000.0, "UPI"),
    ]
    for i, (minute, a, b, amount, channel) in enumerate(txns, start=1):
        ds.transactions.append(
            Transaction(
                record_id=f"TXN-INC-{i:03d}",
                sender=a,
                receiver=b,
                timestamp=at(minute),
                amount=amount,
                channel=channel,
            )
        )


def build_dataset(seed: int = 42) -> Dataset:
    rng = random.Random(seed)
    entities = _build_entities()
    ds = Dataset(entities=entities)
    _baseline_activity(rng, ds, list(entities))
    _planted_pattern(ds)
    ds.calls.sort(key=lambda r: r.timestamp)
    ds.sessions.sort(key=lambda r: r.timestamp)
    ds.transactions.sort(key=lambda r: r.timestamp)
    return ds


DATASET = build_dataset()
