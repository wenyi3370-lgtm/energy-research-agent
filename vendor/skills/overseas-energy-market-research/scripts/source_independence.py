from __future__ import annotations

import ipaddress
import re
from itertools import combinations
from pathlib import Path
from urllib.parse import urlparse

# FIX round-3 (v2.2): root-domain detection uses the real Public Suffix
# algorithm (prevailing rule: exception > longest exact/wildcard > default *)
# against the FROZEN local snapshot references/public_suffix_list.dat — the
# single deterministic source of truth. No optional package can change
# results (tldextract is intentionally NOT consulted).

_PSL_PATH = Path(__file__).resolve().parent.parent / "references" / "public_suffix_list.dat"


def _load_psl() -> tuple[set[str], set[str], set[str]]:
    exact: set[str] = set()
    wildcard: set[str] = set()
    exceptions: set[str] = set()
    try:
        text = _PSL_PATH.read_text(encoding="utf-8")
    except OSError:
        return exact, wildcard, exceptions
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("!"):
            exceptions.add(line[1:].casefold())
        elif line.startswith("*."):
            wildcard.add(line[2:].casefold())
        else:
            exact.add(line.casefold())
    return exact, wildcard, exceptions


_PSL_EXACT, _PSL_WILDCARD, _PSL_EXCEPTIONS = _load_psl()


def _psl_registrable(hostname: str) -> str:
    """Public-Suffix-List PREVAILING-RULE algorithm (FIX round-3 P1-3/4/5).

    - exceptions win over exact/wildcard for the same label count;
    - otherwise the LONGEST matching rule prevails (exact or wildcard);
    - wildcard `*.ck` matches EXACTLY one label + `.ck` (label-level
      matching, never a string endswith on arbitrary depth);
    - the default `*` rule (single-label suffix) applies when nothing
      matches (unknown TLD);
    - registrable domain = prevailing public suffix + one label to its
      left (deep domains: y.x.a.ck -> x.a.ck; sub.www.ck -> www.ck).
    """
    labels = hostname.split(".")
    n = len(labels)
    public_suffix_labels = 0  # label count of the prevailing public suffix
    for i in range(n):
        candidate = ".".join(labels[i:])
        if candidate in _PSL_EXCEPTIONS:
            # exception label is part of the registrable domain; the public
            # suffix is everything to its right (e.g. !www.ck -> suffix=ck)
            public_suffix_labels = max(n - (i + 1), 1) if i + 1 < n else 1
            break
        if candidate in _PSL_EXACT:
            public_suffix_labels = n - i
            break
        # wildcard `*.w`: candidate must be exactly one label + w
        for w in _PSL_WILDCARD:
            if candidate.count(".") == w.count(".") + 1 and candidate.endswith("." + w):
                public_suffix_labels = n - i
                break
        if public_suffix_labels:
            break
    if not public_suffix_labels:
        public_suffix_labels = 1  # default "*" rule (unknown TLD)
    registrable_labels = public_suffix_labels + 1
    if registrable_labels >= n:
        return hostname
    return ".".join(labels[n - registrable_labels:])


def root_domain_from_url(value: str) -> str:
    hostname = (urlparse(str(value).strip()).hostname or "").strip(".").casefold()
    if not hostname:
        return ""
    try:
        ipaddress.ip_address(hostname)
        return hostname
    except ValueError:
        pass
    # FIX round-3 P1-7: references/public_suffix_list.dat is the ONLY
    # deterministic source of truth — no optional tldextract shortcut, so
    # installed/uninstalled optional packages can never change results.
    registrable = _psl_registrable(hostname)
    # Strip a leading "www." ONLY when it is a subdomain of a 2+ label
    # registrable domain (www.example.com -> example.com). PSL exception
    # domains like !www.ck resolve to www.ck itself and must be preserved
    # (FIX round-2 P2-8: stripping BEFORE PSL resolution corrupted them).
    if registrable.startswith("www.") and registrable.count(".") >= 2:
        return registrable[4:]  # "www." is 4 chars
    return registrable


def normalize_taxonomy(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().casefold()).strip("_")


def normalize_group(value: str) -> str:
    return re.sub(r"[^\w]+", "", str(value).strip().casefold(), flags=re.UNICODE)


def canonical_source_key(source_id: str, ledger: dict[str, dict[str, str]]) -> str:
    current = source_id
    visited: set[str] = set()
    while current and current not in visited:
        visited.add(current)
        row = ledger.get(current, {})
        relation = normalize_taxonomy(row.get("source_relation_type", ""))
        canonical = str(row.get("canonical_source_id", "")).strip()
        if not canonical or canonical == current or relation in {"original", "independent_analysis"}:
            return current
        current = canonical
    return "cycle:" + "->".join(sorted(visited))


def source_signature(source_id: str, ledger: dict[str, dict[str, str]]) -> dict[str, str]:
    row = ledger.get(source_id, {})
    return {
        "source_id": source_id,
        "publisher_group": normalize_group(row.get("publisher_group", "")),
        "root_domain": str(row.get("root_domain", "")).strip().casefold(),
        "canonical_source": canonical_source_key(source_id, ledger),
        "source_type": normalize_taxonomy(row.get("source_type", "")),
    }


def evaluate_claim_independence(
    source_ids: set[str],
    ledger: dict[str, dict[str, str]],
    policy: dict,
) -> tuple[bool, list[str], list[str]]:
    minimum_sources = int(policy["minimum_independent_sources_per_critical_claim"])
    minimum_types = int(policy["minimum_distinct_source_types_per_critical_claim"])
    available = sorted(source_ids & set(ledger))
    if len(available) < minimum_sources:
        return False, [], [f"requires {minimum_sources} ledger-backed sources; found {len(available)}"]

    signatures = {source_id: source_signature(source_id, ledger) for source_id in available}
    for candidate in combinations(available, minimum_sources):
        values = [signatures[source_id] for source_id in candidate]
        if any(not item["publisher_group"] or not item["root_domain"] or not item["source_type"] for item in values):
            continue
        if policy["require_distinct_publisher_groups"] and len({item["publisher_group"] for item in values}) != len(values):
            continue
        if policy["require_distinct_root_domains"] and len({item["root_domain"] for item in values}) != len(values):
            continue
        if policy["require_distinct_canonical_sources"] and len({item["canonical_source"] for item in values}) != len(values):
            continue
        if len({item["source_type"] for item in values}) < minimum_types:
            continue
        return True, list(candidate), []

    all_values = list(signatures.values())
    reasons: list[str] = []
    if len({item["publisher_group"] for item in all_values if item["publisher_group"]}) < minimum_sources:
        reasons.append("insufficient distinct publisher groups")
    if len({item["root_domain"] for item in all_values if item["root_domain"]}) < minimum_sources:
        reasons.append("insufficient distinct root domains")
    if len({item["canonical_source"] for item in all_values if item["canonical_source"]}) < minimum_sources:
        reasons.append("sources resolve to the same original/mirror chain")
    if len({item["source_type"] for item in all_values if item["source_type"]}) < minimum_types:
        reasons.append("insufficient source-type diversity")
    if any(not item["publisher_group"] or not item["root_domain"] or not item["source_type"] for item in all_values):
        reasons.append("source-independence metadata is incomplete")
    if not reasons:
        reasons.append("no source subset satisfies all independence dimensions simultaneously")
    return False, [], reasons
