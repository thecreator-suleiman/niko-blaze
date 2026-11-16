"""Licensing registry & publishing gate. Nothing is published unless every component is verified."""
from . import db
from .config import licences
from .visual.assets import load_portrait


def components_for(kind: str, lyrics_provider: str | None) -> list[str]:
    comps = ["model:ace-step-1.5", "visual:procedural", "font:system", "samples:none"]
    if lyrics_provider and lyrics_provider != "none":
        comps.append(f"lyrics:{lyrics_provider}")
    _, authorised_file = load_portrait()
    if authorised_file:
        comps.append("visual:portrait")
    return comps


def record(ref_kind: str, ref_id: str, comps: list[str]):
    reg = licences()
    with db.tx() as c:
        for comp in comps:
            st = reg.get(comp, {}).get("status", "unknown")
            c.execute("INSERT INTO rights(ref_kind,ref_id,component,status,note) VALUES(?,?,?,?,?) "
                      "ON CONFLICT(ref_kind,ref_id,component) DO UPDATE SET status=excluded.status",
                      (ref_kind, ref_id, comp, st, reg.get(comp, {}).get("licence", "")))


def blocked(comps: list[str]) -> list[str]:
    """Return components that are not verified (live re-check against config/licenses.yaml)."""
    reg = licences()
    return [c for c in comps if reg.get(c, {}).get("status") != "verified"]


def summary() -> dict:
    reg = licences()
    return {k: {"status": v.get("status"), "licence": v.get("licence"), "commercial": v.get("commercial_use")}
            for k, v in reg.items()}
