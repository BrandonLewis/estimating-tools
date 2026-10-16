"""Canonical historicals models — the MCP interchange format (Phase 5).

HistoricalRecord mirrors the BidSheet.ai historical-record schema (#972)
field for field; JSONL of `to_payload()` dicts is the interchange format
consumed by ``bulk_create_historical_records``. CanonicalBidTab is the
parsed award tabulation that fans out into records.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

OUTCOMES = ("estimated", "bid", "awarded", "actualized", "competitor_bid")


@dataclass
class HistoricalRecord:
    outcome: str
    agency: str = ""
    bid_item_code: str = ""
    project_ref: str = ""
    bid_date: str | None = None
    region: str = ""
    bidder: str = ""
    bid_item: dict | None = None
    quantity: float | None = None
    unit: str = ""
    unit_price_bid: float | None = None
    unit_cost_estimated: float | None = None
    unit_cost_actual: float | None = None
    breakdown: list[dict] | None = None
    production: dict | None = None
    source: dict | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if self.outcome not in OUTCOMES:
            raise ValueError(f"outcome must be one of {OUTCOMES}, got {self.outcome!r}")

    def to_payload(self) -> dict:
        """Kwargs for create_historical_record / one JSONL line.

        Drops unset fields (None / "" / empty containers) but keeps 0 —
        a zero quantity is a valid observation per the MCP contract.
        """
        out = {}
        for k, v in asdict(self).items():
            if v is None or (isinstance(v, str) and v == ""):
                continue
            if isinstance(v, (list, dict)) and not v:
                continue
            out[k] = v
        return out


@dataclass
class Bidder:
    name: str
    rank: int | None = None          # 1 = low/awarded
    total_bid: float | None = None


@dataclass
class TabItem:
    item_number: str
    bid_item_code: str = ""          # as published, string, leading zeros kept
    description: str = ""
    quantity: float | None = None
    unit: str = ""
    unit_prices: dict = field(default_factory=dict)   # bidder name -> unit price
    extensions: dict = field(default_factory=dict)    # bidder name -> extension


@dataclass
class CanonicalBidTab:
    agency: str
    project_ref: str
    bid_date: str | None = None
    region: str = ""
    contract: str = ""
    bidders: list[Bidder] = field(default_factory=list)
    items: list[TabItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict) -> "CanonicalBidTab":
        return cls(
            agency=data.get("agency", ""),
            project_ref=data.get("project_ref", ""),
            bid_date=data.get("bid_date"),
            region=data.get("region", ""),
            contract=data.get("contract", ""),
            bidders=[Bidder(**b) for b in data.get("bidders", [])],
            items=[TabItem(**it) for it in data.get("items", [])],
            warnings=list(data.get("warnings", [])),
        )

    @classmethod
    def from_json(cls, text: str) -> "CanonicalBidTab":
        return cls.from_dict(json.loads(text))

    def low_bidder(self) -> str | None:
        ranked = [b for b in self.bidders if b.rank is not None]
        if ranked:
            return min(ranked, key=lambda b: b.rank).name
        totaled = [b for b in self.bidders if b.total_bid is not None]
        if totaled:
            return min(totaled, key=lambda b: b.total_bid).name
        return None

    def to_records(self) -> list[HistoricalRecord]:
        """One record per (item x bidder) with a price; low bidder = awarded."""
        low = self.low_bidder()
        records = []
        for item in self.items:
            for bidder in self.bidders:
                price = item.unit_prices.get(bidder.name)
                if price is None:
                    continue
                records.append(HistoricalRecord(
                    outcome="awarded" if bidder.name == low else "competitor_bid",
                    agency=self.agency,
                    bid_item_code=item.bid_item_code,
                    project_ref=self.project_ref,
                    bid_date=self.bid_date,
                    region=self.region,
                    bidder=bidder.name,
                    bid_item={"item_number": item.item_number,
                              "description": item.description},
                    quantity=item.quantity,
                    unit=item.unit,
                    unit_price_bid=price,
                    source={"kind": "bid_tab", "ref": self.contract or self.project_ref},
                ))
        return records
