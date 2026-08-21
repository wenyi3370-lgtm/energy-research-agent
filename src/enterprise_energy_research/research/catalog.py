"""Product Catalog traversal states and coverage (P0-17).

Finding the official product center and scraping ONE page is not product
research. Catalog items move DISCOVERED -> VISITED -> EXTRACTED -> VERIFIED
-> PUBLISHED, and coverage is computed from the real item inventory, never
from "pages we happened to open".
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from enterprise_energy_research.domain.enums import VerificationStatus
from enterprise_energy_research.domain.models import Product

CatalogState = Literal["DISCOVERED", "VISITED", "EXTRACTED", "VERIFIED", "PUBLISHED"]


class CatalogItem(BaseModel):
    item_id: str
    name: str
    level: Literal["family", "series", "model", "detail"] = "model"
    url: str | None = None
    parent_item_id: str | None = None
    entity_id: str | None = None
    product_id: str | None = None
    state: CatalogState = "DISCOVERED"
    source_page: str | None = None

    def transition(self, target: CatalogState) -> "CatalogItem":
        order = {"DISCOVERED": 0, "VISITED": 1, "EXTRACTED": 2, "VERIFIED": 3, "PUBLISHED": 4}
        if order[target] < order[self.state]:
            raise ValueError(f"catalog item cannot move backwards from {self.state} to {target}")
        return self.model_copy(update={"state": target})


class CatalogInventory(BaseModel):
    items: list[CatalogItem] = Field(default_factory=list)
    scope_urls: list[str] = Field(default_factory=list)
    enumeration_method: str | None = None

    def by_state(self) -> dict[str, int]:
        counts = {"DISCOVERED": 0, "VISITED": 0, "EXTRACTED": 0, "VERIFIED": 0, "PUBLISHED": 0}
        for item in self.items:
            counts[item.state] += 1
        return counts

    def coverage(self) -> float:
        """Share of declared items that reached EXTRACTED or beyond."""
        if not self.items:
            return 0.0
        progressed = sum(1 for item in self.items if item.state in {"EXTRACTED", "VERIFIED", "PUBLISHED"})
        return round(progressed / len(self.items), 4)

    def is_complete(self) -> bool:
        return bool(self.items) and all(item.state in {"VERIFIED", "PUBLISHED"} for item in self.items)


class CatalogTraverser:
    """Enumerate catalog items from page link evidence and advance their states.

    The traversal source is deterministic page evidence (official product
    center URLs, per-page link lists from browser DOM) — never an LLM guess.
    """

    def discover(
        self,
        inventory: CatalogInventory,
        pages: list[dict],
    ) -> CatalogInventory:
        """Record newly seen catalog items from visited pages.

        ``pages`` entries: {url, level, name, entity_id, product_id,
        child_urls: [...], source_page}.
        """
        existing = {(item.name, item.level): item for item in inventory.items}
        state_rank = {"DISCOVERED": 0, "VISITED": 1, "EXTRACTED": 2, "VERIFIED": 3, "PUBLISHED": 4}
        for page in pages:
            name = page.get("name") or ""
            if not name:
                continue
            key = (name, page.get("level", "model"))
            if key in existing:
                item = existing[key]
                if not item.url and page.get("url"):
                    existing[key] = item.model_copy(update={"url": page["url"]})
            else:
                item = CatalogItem(
                    item_id=new_catalog_id(),
                    name=name,
                    level=page.get("level", "model"),
                    url=page.get("url"),
                    entity_id=page.get("entity_id"),
                    product_id=page.get("product_id"),
                    source_page=page.get("source_page"),
                )
                existing[key] = item
                inventory.items.append(item)
            current = existing[key]
            # Re-visiting an already-extracted/verified item keeps its state
            # (idempotent traversal); only early states advance to VISITED.
            if state_rank[current.state] <= state_rank["VISITED"]:
                visited = current.transition("VISITED")
                existing[key] = visited
                for index, item in enumerate(inventory.items):
                    if item.item_id == visited.item_id:
                        inventory.items[index] = visited
        return inventory

    def mark_extracted(
        self,
        inventory: CatalogInventory,
        item_names: list[str],
        *,
        product_id_by_name: dict[str, str] | None = None,
    ) -> CatalogInventory:
        product_id_by_name = product_id_by_name or {}
        state_rank = {"DISCOVERED": 0, "VISITED": 1, "EXTRACTED": 2, "VERIFIED": 3, "PUBLISHED": 4}
        for index, item in enumerate(inventory.items):
            if item.name not in item_names:
                continue
            if state_rank[item.state] > state_rank["EXTRACTED"]:
                continue  # already advanced past extraction
            update = {"product_id": product_id_by_name.get(item.name) or item.product_id}
            inventory.items[index] = item.transition("EXTRACTED").model_copy(update=update)
        return inventory

    def reconcile(
        self,
        inventory: CatalogInventory,
        products: list[Product],
    ) -> CatalogInventory:
        """VERIFIED when a verified product record matches; PUBLISHED when a
        formal artifact binding consumed it (set later by the publisher)."""
        product_keys = {
            product.product_id for product in products
            if product.verification_status == VerificationStatus.VERIFIED
        }
        for index, item in enumerate(inventory.items):
            if item.state != "EXTRACTED":
                continue
            if item.product_id and item.product_id in product_keys:
                inventory.items[index] = item.transition("VERIFIED")
        return inventory


def new_catalog_id() -> str:
    from enterprise_energy_research.domain.ids import new_sortable_id
    return new_sortable_id("CAT")
