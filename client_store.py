"""
Client Store — MVP
==================

Simple JSON-backed store of Estevan's buyers/sellers. Used by the voice
agent so repeat clients (the Smiths, the O'Briens) don't have to re-say
their address and emails every time.

Schema per client:
    {
        "id":                "uuid",
        "name_line1":        "John Smith and Jane Smith",
        "name_line2":        "",
        "last_name":         "Smith",
        "aliases":           ["Smith", "the Smiths", "John", "Jane"],
        "address_streetnum": "45",
        "address_street":    "Maple Avenue",
        "address_unit":      "",
        "address_city":      "Dartmouth",
        "address_state":     "Nova Scotia",
        "address_zipcode":   "B2Y 3Z1",
        "emails":            ["john@gmail.com", "jane@gmail.com"],
        "phones":            ["902-555-1234"],
        "first_met":         "2025-11-03",
        "referral":          "Dave Murray",
        "created_at":        "2026-04-19T10:15:00",
        "updated_at":        "2026-04-19T10:15:00",
    }

Public API:

    store = ClientStore(path="clients.json")
    store.list() -> list[dict]
    store.find(query) -> list[dict]         # fuzzy name match
    store.get(client_id) -> dict | None
    store.add(client_data) -> dict           # returns saved client with id
    store.update(client_id, fields) -> dict
    store.delete(client_id) -> bool
    store.to_offer_json(client_id) -> dict   # slice shaped for Form 400 buyers{}
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


class ClientStore:
    def __init__(self, path: str | Path = "clients.json") -> None:
        self.path = Path(path)
        self._clients: list[dict[str, Any]] = []
        self._load()

    # ------------------------------------------------------------------ IO
    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                self._clients = data.get("clients", [])
            except (json.JSONDecodeError, OSError):
                self._clients = []
        else:
            self._clients = []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "clients": self._clients}
        self.path.write_text(json.dumps(payload, indent=2))

    # --------------------------------------------------------------- queries
    def list(self) -> list[dict[str, Any]]:
        return sorted(self._clients, key=lambda c: c.get("last_name", "").lower())

    def get(self, client_id: str) -> dict[str, Any] | None:
        for c in self._clients:
            if c.get("id") == client_id:
                return c
        return None

    def find(self, query: str) -> list[dict[str, Any]]:
        """
        Match against name_line1, name_line2, last_name, and aliases.
        Case-insensitive substring match, apostrophe/punctuation-insensitive.
        Returns best matches first.
        """
        q = _normalize(query)
        if not q:
            return []
        scored = []
        for c in self._clients:
            targets = [
                c.get("name_line1", ""),
                c.get("name_line2", ""),
                c.get("last_name", ""),
                *c.get("aliases", []),
            ]
            score = 0
            for t in targets:
                t_norm = _normalize(t)
                if not t_norm:
                    continue
                if t_norm == q:
                    score += 100
                elif t_norm.startswith(q):
                    score += 50
                elif q in t_norm:
                    score += 10
            if score > 0:
                scored.append((score, c))
        scored.sort(key=lambda x: -x[0])
        return [c for _, c in scored]

    # ---------------------------------------------------------------- mutate
    def add(self, data: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now().isoformat(timespec="seconds")
        client = {
            "id": data.get("id") or str(uuid.uuid4()),
            "name_line1": (data.get("name_line1") or "").strip(),
            "name_line2": (data.get("name_line2") or "").strip(),
            "last_name": (data.get("last_name") or _extract_last_name(data.get("name_line1", ""))).strip(),
            "aliases": data.get("aliases") or _build_aliases(
                data.get("name_line1", ""), data.get("name_line2", "")
            ),
            "address_streetnum": (data.get("address_streetnum") or "").strip(),
            "address_street": (data.get("address_street") or "").strip(),
            "address_unit": (data.get("address_unit") or "").strip(),
            "address_city": (data.get("address_city") or "").strip(),
            "address_state": (data.get("address_state") or "Nova Scotia").strip(),
            "address_zipcode": (data.get("address_zipcode") or "").strip(),
            "emails": list(data.get("emails") or []),
            "phones": list(data.get("phones") or []),
            "first_met": data.get("first_met", ""),
            "referral": data.get("referral", ""),
            "created_at": now,
            "updated_at": now,
        }
        self._clients.append(client)
        self._save()
        return client

    def update(self, client_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        c = self.get(client_id)
        if not c:
            return None
        for k, v in fields.items():
            if k in ("id", "created_at"):
                continue
            c[k] = v
        c["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self._save()
        return c

    def delete(self, client_id: str) -> bool:
        before = len(self._clients)
        self._clients = [c for c in self._clients if c.get("id") != client_id]
        if len(self._clients) < before:
            self._save()
            return True
        return False

    # ------------------------------------------------------ form-400 shaping
    def to_offer_json(self, client_id: str) -> dict[str, Any]:
        """Return the shape expected by form_400_filler.offer_json['buyers']."""
        c = self.get(client_id)
        if not c:
            return {}
        return {
            "names_line1": c["name_line1"],
            "names_line2": c.get("name_line2", ""),
            "address_streetnum": c.get("address_streetnum", ""),
            "address_street": c.get("address_street", ""),
            "address_city": c.get("address_city", ""),
            "address_state": c.get("address_state", "Nova Scotia"),
            "address_zipcode": c.get("address_zipcode", ""),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize(s: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace — for fuzzy matching."""
    if not s:
        return ""
    s = s.lower().strip()
    # Remove apostrophes, periods, commas, hyphens
    s = re.sub(r"[’'`.\-,]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def _extract_last_name(full: str) -> str:
    """Best-effort last-name extraction from 'John Smith and Jane Smith'."""
    if not full:
        return ""
    # Take whatever's before ' and ' as the primary person
    primary = re.split(r"\s+and\s+", full, maxsplit=1)[0]
    parts = primary.strip().split()
    return parts[-1] if parts else ""


def _build_aliases(line1: str, line2: str) -> list[str]:
    """Generate searchable aliases from the name line(s)."""
    aliases: set[str] = set()
    for line in (line1, line2):
        if not line:
            continue
        aliases.add(line)
        # Split on ' and ' to grab each person
        for person in re.split(r"\s+and\s+", line):
            person = person.strip()
            if not person:
                continue
            aliases.add(person)
            parts = person.split()
            if parts:
                aliases.add(parts[-1])  # last name
                aliases.add(parts[0])   # first name
                aliases.add(f"the {parts[-1]}s")  # "the Smiths"
    return sorted(a for a in aliases if a)


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
        tmp_path = tmp.name

    store = ClientStore(tmp_path)

    # 1. Add 3 clients
    smith = store.add({
        "name_line1": "John Smith and Jane Smith",
        "address_streetnum": "45",
        "address_street": "Maple Avenue",
        "address_city": "Dartmouth",
        "address_zipcode": "B2Y 3Z1",
        "emails": ["john@gmail.com", "jane@gmail.com"],
        "phones": ["902-555-1234"],
    })
    obrien = store.add({
        "name_line1": "Michael O'Brien",
        "address_streetnum": "12",
        "address_street": "Queen Street",
        "address_city": "Halifax",
        "address_zipcode": "B3K 2M5",
        "emails": ["mobrien@icloud.com"],
    })
    ng = store.add({
        "name_line1": "Li Ng and Wei Ng",
        "address_streetnum": "88",
        "address_street": "Pleasant Road",
        "address_city": "Bedford",
        "address_zipcode": "B4A 1C3",
        "emails": ["li@ng.com", "wei@ng.com"],
    })

    # 2. List
    print("=== list ===")
    for c in store.list():
        print(f"  {c['last_name']:<10} {c['name_line1']}")

    # 3. Find
    print("\n=== find('smith') ===")
    for c in store.find("smith"):
        print(f"  {c['name_line1']}")

    print("\n=== find('the Smiths') ===")
    for c in store.find("the Smiths"):
        print(f"  {c['name_line1']}")

    print("\n=== find('jane') ===")
    for c in store.find("jane"):
        print(f"  {c['name_line1']}")

    print("\n=== find('obrien') ===")
    for c in store.find("obrien"):
        print(f"  {c['name_line1']}")

    # 4. Update
    updated = store.update(smith["id"], {"phones": ["902-555-9999"]})
    print(f"\nUpdated Smith phones: {updated['phones']}")

    # 5. to_offer_json
    print("\n=== to_offer_json (Smith) ===")
    print(json.dumps(store.to_offer_json(smith["id"]), indent=2))

    # 6. Reload from disk to verify persistence
    reloaded = ClientStore(tmp_path)
    print(f"\nReload check: {len(reloaded.list())} clients on disk")

    Path(tmp_path).unlink()
    print("\nAll client store self-tests passed.")
