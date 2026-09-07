from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import DrugCache, MedicationInfoCache
from app.services.medication_directory import LOCAL_MEDICATION_DIRECTORY
from app.services.medication_interactions import LOCAL_INTERACTION_RULES, SECONDARY_INTERACTION_NOTES


def _extract_first(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return [str(value)]


def normalize_dosage_text(value: str | None) -> dict | None:
    if not value:
        return None
    match = re.search(r"(?P<amount>\d+(?:[.,]\d+)?)\s*(?P<unit>мг|г|мкг|ml|мл)", value.lower())
    if not match:
        return {"raw": value}
    return {
        "raw": value,
        "amount": float(match.group("amount").replace(",", ".")),
        "unit": match.group("unit"),
    }


def _normalize_query(query: str) -> str:
    return query.strip().lower()


def _join_text_lines(parts: list[str | None]) -> str | None:
    lines = [part.strip() for part in parts if part and part.strip()]
    return "\n".join(lines) if lines else None


def _build_alias_index() -> dict[str, str]:
    alias_map: dict[str, str] = {}
    for canonical_name, item in LOCAL_MEDICATION_DIRECTORY.items():
        for alias in item.get("aliases", []):
            alias_map[alias.strip().lower()] = canonical_name
    return alias_map


ALIAS_INDEX = _build_alias_index()


def resolve_medication_query(query: str) -> str:
    normalized = _normalize_query(query)
    return ALIAS_INDEX.get(normalized, normalized)


def _build_local_results(canonical_query: str) -> list[dict]:
    item = LOCAL_MEDICATION_DIRECTORY.get(canonical_query)
    if not item:
        return []
    return [
        {
            "brand_name": item["brand_name"],
            "generic_name": item["generic_name"],
            "manufacturer": "Локальный российский справочник Family PHR",
            "purpose": item.get("purpose"),
            "indications": item.get("indications"),
            "warnings": item.get("warnings"),
            "contraindications": item.get("contraindications"),
            "instructions": item.get("instructions"),
            "dosage_forms": item.get("dosage_forms", []),
            "common_dosages": item.get("common_dosages", []),
            "pediatric_forms": item.get("pediatric_forms", []),
            "common_combinations": item.get("common_combinations", []),
            "normalized_common_dosages": [normalize_dosage_text(dose) for dose in item.get("common_dosages", [])],
            "interactions": item.get("interactions", []),
            "trade_names": item.get("trade_names", []),
            "source": "local_ru_directory",
        }
    ]


def _build_openfda_search(canonical_query: str) -> str:
    local_item = LOCAL_MEDICATION_DIRECTORY.get(canonical_query, {})
    aliases = [alias for alias in local_item.get("aliases", []) if alias]
    search_terms = {canonical_query, *aliases}
    exact_terms = [term.strip() for term in sorted(search_terms) if term.strip()]
    return " OR ".join([f'openfda.generic_name:"{term}" OR openfda.brand_name:"{term}"' for term in exact_terms])


def _build_fallback_searches(canonical_query: str, original_query: str) -> list[str]:
    local_item = LOCAL_MEDICATION_DIRECTORY.get(canonical_query, {})
    aliases = [alias.strip() for alias in local_item.get("aliases", []) if alias and alias.strip()]
    terms: list[str] = []
    for term in [original_query.strip(), canonical_query.strip(), *aliases]:
        if term and term not in terms:
            terms.append(term)

    searches: list[str] = []
    for term in terms:
        searches.append(f'openfda.generic_name:"{term}"')
        searches.append(f'openfda.brand_name:"{term}"')
    return searches


def _request_openfda(search: str) -> dict:
    params = {"search": search, "limit": 5}
    if settings.openfda_api_key:
        params["api_key"] = settings.openfda_api_key
    url = f"https://api.fda.gov/drug/label.json?{urlencode(params)}"
    request = Request(url, headers={"User-Agent": "family-phr-mvp/1.0"})
    try:
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            return {"results": []}
        raise RuntimeError("openFDA API error") from exc
    except URLError as exc:
        raise RuntimeError("openFDA unavailable") from exc


def _parse_openfda_result(item: dict, fallback_name: str) -> dict:
    openfda = item.get("openfda") or {}
    brand_names = _as_list(openfda.get("brand_name"))
    generic_names = _as_list(openfda.get("generic_name"))
    purpose = _extract_first(item.get("purpose"))
    indications = _extract_first(item.get("indications_and_usage"))
    return {
        "brand_name": _extract_first(brand_names) or fallback_name,
        "generic_name": _extract_first(generic_names),
        "manufacturer": _extract_first(openfda.get("manufacturer_name")),
        "purpose": purpose,
        "indications": indications,
        "warnings": _extract_first(item.get("warnings")) or _extract_first(item.get("boxed_warning")),
        "contraindications": _extract_first(item.get("contraindications")),
        "instructions": _extract_first(item.get("dosage_and_administration")),
        "dosage_forms": _as_list(item.get("dosage_forms_and_strengths")),
        "common_dosages": _as_list(item.get("dosage_and_administration")),
        "normalized_common_dosages": [normalize_dosage_text(dose) for dose in _as_list(item.get("dosage_and_administration"))],
        "interactions": _as_list(item.get("drug_interactions")),
        "trade_names": brand_names,
        "source": "openfda",
    }


def _fetch_openfda_results(query: str, canonical_query: str) -> list[dict]:
    searches = [_build_openfda_search(canonical_query), *_build_fallback_searches(canonical_query, query)]
    seen_searches: set[str] = set()
    for search in searches:
        normalized_search = search.strip()
        if not normalized_search or normalized_search in seen_searches:
            continue
        seen_searches.add(normalized_search)
        payload = _request_openfda(normalized_search)
        results = payload.get("results") or []
        if not results:
            continue
        return [_parse_openfda_result(item, canonical_query) for item in results if isinstance(item, dict)]
    return []


def _merge_results(primary: list[dict], secondary: list[dict]) -> list[dict]:
    items: list[dict] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()
    for item in [*primary, *secondary]:
        key = (
            (item.get("brand_name") or "").strip().lower() or None,
            (item.get("generic_name") or "").strip().lower() or None,
            item.get("source"),
        )
        if key in seen:
            continue
        seen.add(key)
        items.append(item)
    return items


def _normalize_drug_cache_name(name: str | None) -> str:
    return (name or "").strip().lower()


def _drug_cache_to_result(item: DrugCache) -> dict:
    return {
        "brand_name": item.raw_name,
        "generic_name": item.name,
        "dosage_forms": [part.strip() for part in (item.dosage_forms or "").split(",") if part.strip()],
        "purpose": item.description,
        "indications": item.description,
        "instructions": item.instructions,
        "source": item.source or "drug_cache",
        "from_cache": True,
    }


def lookup_drug_cache(db: Session | None, query: str, limit: int = 10) -> list[dict]:
    if db is None:
        return []
    normalized = _normalize_drug_cache_name(query)
    if not normalized:
        return []
    exact = db.scalars(select(DrugCache).where(DrugCache.name == normalized).limit(limit)).all()
    if exact:
        return [_drug_cache_to_result(item) for item in exact]
    items = db.scalars(
        select(DrugCache)
        .where(or_(DrugCache.name.ilike(f"%{normalized}%"), DrugCache.raw_name.ilike(f"%{normalized}%")))
        .order_by(DrugCache.updated_at.desc())
        .limit(limit)
    ).all()
    if not items:
        items = [
            item
            for item in db.scalars(select(DrugCache).order_by(DrugCache.updated_at.desc())).all()
            if normalized in _normalize_drug_cache_name(item.name) or normalized in _normalize_drug_cache_name(item.raw_name)
        ][:limit]
    return [_drug_cache_to_result(item) for item in items]


def suggest_drug_cache(db: Session | None, query: str, limit: int = 8) -> list[dict]:
    if db is None:
        return []
    normalized = _normalize_drug_cache_name(query)
    if not normalized:
        return []
    items = db.scalars(
        select(DrugCache)
        .where(or_(DrugCache.name.ilike(f"%{normalized}%"), DrugCache.raw_name.ilike(f"%{normalized}%")))
        .order_by(DrugCache.updated_at.desc())
        .limit(limit)
    ).all()
    if not items:
        items = [
            item
            for item in db.scalars(select(DrugCache).order_by(DrugCache.updated_at.desc())).all()
            if normalized in _normalize_drug_cache_name(item.name) or normalized in _normalize_drug_cache_name(item.raw_name)
        ][:limit]
    return [
        {
            "name": item.raw_name,
            "normalized_name": item.name,
            "instructions": item.instructions,
            "description": item.description,
            "dosage_forms": item.dosage_forms,
            "source": item.source or "drug_cache",
        }
        for item in items
    ]


def _upsert_drug_cache_item(db: Session | None, item: dict, raw_query: str) -> None:
    if db is None:
        return
    candidate_name = item.get("generic_name") or item.get("brand_name") or raw_query
    normalized_name = _normalize_drug_cache_name(candidate_name)
    if not normalized_name:
        return
    dosage_forms_text = ", ".join(item.get("dosage_forms") or [])
    description = _join_text_lines([item.get("purpose"), item.get("indications")])
    instructions = item.get("instructions")
    cached = db.scalar(select(DrugCache).where(DrugCache.name == normalized_name))
    if cached is None:
        cached = DrugCache(
            name=normalized_name,
            raw_name=(item.get("brand_name") or raw_query).strip(),
            dosage_forms=dosage_forms_text or None,
            description=description,
            instructions=instructions,
            source=item.get("source") or "openfda",
        )
        db.add(cached)
        return
    cached.raw_name = (item.get("brand_name") or cached.raw_name or raw_query).strip()
    cached.dosage_forms = dosage_forms_text or cached.dosage_forms
    cached.description = description or cached.description
    cached.instructions = instructions or cached.instructions
    cached.source = item.get("source") or cached.source
    cached.updated_at = datetime.now(UTC).replace(tzinfo=None)


def cache_drug_results(db: Session | None, query: str, results: list[dict]) -> None:
    if db is None or not results:
        return
    for item in results:
        _upsert_drug_cache_item(db, item, query)
    db.commit()


def get_drug_cache_summary(db: Session | None) -> dict:
    if db is None:
        return {"count": 0}
    items = db.scalars(select(DrugCache).order_by(DrugCache.updated_at.desc())).all()
    return {
        "count": len(items),
        "latest": items[0].updated_at if items else None,
    }


def get_drug_cache_maintenance_report(db: Session | None) -> dict:
    if db is None:
        return {"count": 0, "missing_instructions": 0, "local_sources": 0, "remote_sources": 0, "duplicate_groups": 0, "stale_entries": 0}
    items = db.scalars(select(DrugCache).order_by(DrugCache.updated_at.desc())).all()
    duplicate_groups = len([group for group in _group_drug_cache_duplicates(items).values() if len(group) > 1])
    stale_before = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=settings.medication_cache_ttl_hours)
    return {
        "count": len(items),
        "missing_instructions": len([item for item in items if not (item.instructions or "").strip()]),
        "local_sources": len([item for item in items if (item.source or "").startswith("local")]),
        "remote_sources": len([item for item in items if not (item.source or "").startswith("local")]),
        "duplicate_groups": duplicate_groups,
        "stale_entries": len([item for item in items if item.updated_at < stale_before]),
    }


def moderate_drug_cache(db: Session | None) -> dict:
    if db is None:
        return {"updated": 0, "merged": 0}
    updated = 0
    items = db.scalars(select(DrugCache)).all()
    merged = 0
    for item in items:
        normalized_name = _normalize_drug_cache_name(item.name)
        normalized_raw = (item.raw_name or "").strip()
        changed = False
        if item.name != normalized_name:
            item.name = normalized_name
            changed = True
        if item.raw_name != normalized_raw:
            item.raw_name = normalized_raw
            changed = True
        if item.description:
            collapsed = re.sub(r"\n{3,}", "\n\n", item.description.strip())
            if collapsed != item.description:
                item.description = collapsed
                changed = True
        if item.instructions:
            cleaned = re.sub(r"\n{3,}", "\n\n", item.instructions.strip())
            if cleaned != item.instructions:
                item.instructions = cleaned
                changed = True
        if changed:
            item.updated_at = datetime.now(UTC).replace(tzinfo=None)
            updated += 1
    duplicate_groups = _group_drug_cache_duplicates(items)
    for group in duplicate_groups.values():
        if len(group) <= 1:
            continue
        keeper = max(group, key=_drug_cache_richness)
        for item in group:
            if item.id == keeper.id:
                continue
            if not (keeper.instructions or "").strip() and (item.instructions or "").strip():
                keeper.instructions = item.instructions
            if not (keeper.description or "").strip() and (item.description or "").strip():
                keeper.description = item.description
            if not (keeper.dosage_forms or "").strip() and (item.dosage_forms or "").strip():
                keeper.dosage_forms = item.dosage_forms
            if not (keeper.raw_name or "").strip() and (item.raw_name or "").strip():
                keeper.raw_name = item.raw_name
            keeper.updated_at = max(keeper.updated_at, item.updated_at)
            db.delete(item)
            merged += 1
        keeper.name = _normalize_drug_cache_name(keeper.name)
        updated += 1
    if updated or merged:
        db.commit()
    return {"updated": updated, "merged": merged}


def _drug_cache_duplicate_key(item: DrugCache) -> str:
    base = _normalize_drug_cache_name(item.raw_name or item.name)
    return re.sub(r"[^a-z0-9а-я]+", "", base, flags=re.IGNORECASE)


def _group_drug_cache_duplicates(items: list[DrugCache]) -> dict[str, list[DrugCache]]:
    groups: dict[str, list[DrugCache]] = {}
    for item in items:
        key = _drug_cache_duplicate_key(item)
        groups.setdefault(key, []).append(item)
    return groups


def _drug_cache_richness(item: DrugCache) -> tuple[int, int, datetime]:
    text_score = sum(
        [
            1 if (item.instructions or "").strip() else 0,
            1 if (item.description or "").strip() else 0,
            1 if (item.dosage_forms or "").strip() else 0,
        ]
    )
    size_score = sum(len((value or "").strip()) for value in [item.instructions, item.description, item.dosage_forms, item.raw_name])
    return (text_score, size_score, item.updated_at)


def clear_drug_cache(db: Session | None) -> int:
    if db is None:
        return 0
    items = db.scalars(select(DrugCache)).all()
    count = len(items)
    for item in items:
        db.delete(item)
    cache_items = db.scalars(select(MedicationInfoCache)).all()
    for item in cache_items:
        db.delete(item)
    db.commit()
    return count


def _get_cached_results(cache_key: str, db: Session | None = None) -> list[dict] | None:
    if db is None:
        return None
    cached = db.scalar(select(MedicationInfoCache).where(MedicationInfoCache.query == cache_key))
    if not cached:
        return None
    age_limit = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=settings.medication_cache_ttl_hours)
    if cached.fetched_at < age_limit:
        return None
    return cached.payload


def _save_cached_results(cache_key: str, results: list[dict], db: Session | None = None) -> None:
    if db is None:
        return
    cached = db.scalar(select(MedicationInfoCache).where(MedicationInfoCache.query == cache_key))
    if not cached:
        cached = MedicationInfoCache(query=cache_key, payload=results)
        db.add(cached)
    else:
        cached.payload = results
        cached.fetched_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()


def fetch_medication_info(query: str, db: Session | None = None, force_refresh: bool = False) -> list[dict]:
    normalized_query = query.strip()
    if not normalized_query:
        return []

    canonical_query = resolve_medication_query(normalized_query)
    if not force_refresh:
        local_cached_results = lookup_drug_cache(db, canonical_query, limit=10)
        if local_cached_results:
            return local_cached_results
    if not force_refresh:
        cached_results = _get_cached_results(canonical_query, db)
        if cached_results is not None:
            return cached_results

    local_results = _build_local_results(canonical_query)
    remote_results: list[dict] = []

    try:
        remote_results = _fetch_openfda_results(normalized_query, canonical_query)
    except Exception:
        fallback_cached_results = lookup_drug_cache(db, normalized_query, limit=10)
        if fallback_cached_results:
            return fallback_cached_results
        if local_results:
            remote_results = []
        else:
            raise

    merged_results = _merge_results(remote_results, local_results)
    if not merged_results:
        merged_results = lookup_drug_cache(db, normalized_query, limit=10) or local_results

    cache_drug_results(db, canonical_query, merged_results)
    _save_cached_results(canonical_query, merged_results, db)
    return merged_results


def check_local_medication_interactions(names: list[str]) -> list[dict]:
    normalized = {(name or "").strip().lower() for name in names if name}
    hits = []
    for pair, description in LOCAL_INTERACTION_RULES.items():
        if pair.issubset(normalized):
            sources = [{"source": "local_ru_rules", "description": description}]
            if pair in SECONDARY_INTERACTION_NOTES:
                sources.append({"source": "local_family_notes", "description": SECONDARY_INTERACTION_NOTES[pair]})
            hits.append({"pair": sorted(pair), "sources": sources, "source_count": len(sources)})
    return hits
