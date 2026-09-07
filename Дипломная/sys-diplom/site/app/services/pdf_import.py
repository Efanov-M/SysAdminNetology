from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
import re
from typing import Any

from sqlalchemy.orm import Session

from app.models import Document, LabResult, Observation, Patient
from app.services.document_processing import build_uploaded_document, queue_document_processing
from app.utils import save_import_source_bytes


LAB_TEST_PATTERNS = [
    ("Гемоглобин", r"гемоглобин[:\s]+(\d+(?:[.,]\d+)?)", "г/л"),
    ("Глюкоза", r"глюкоза[:\s]+(\d+(?:[.,]\d+)?)", "ммоль/л"),
    ("Общий холестерин", r"общий холестерин[:\s]+(\d+(?:[.,]\d+)?)", "ммоль/л"),
    ("Лейкоциты", r"лейкоциты[:\s]+(\d+(?:[.,]\d+)?)", "10^9/л"),
]

LAB_PANEL_BY_TEST = {
    "Гемоглобин": "ОАК",
    "Лейкоциты": "ОАК",
    "Глюкоза": "Биохимия",
    "Общий холестерин": "Липиды",
    "АЛТ": "Биохимия",
    "АСТ": "Биохимия",
    "Креатинин": "Биохимия",
}

KNOWN_TEST_ALIASES = {
    "гемоглобин": "Гемоглобин",
    "hb": "Гемоглобин",
    "hgb": "Гемоглобин",
    "глюкоза": "Глюкоза",
    "glucose": "Глюкоза",
    "лейкоциты": "Лейкоциты",
    "wbc": "Лейкоциты",
    "общий холестерин": "Общий холестерин",
    "алт": "АЛТ",
    "ast": "АСТ",
    "аст": "АСТ",
    "креатинин": "Креатинин",
    "ттг": "ТТГ",
    "аст алт": "АСТ/АЛТ",
}

OCR_TEXT_REPLACEMENTS = {
    "Гемогпобин": "Гемоглобин",
    "Гпюкоза": "Глюкоза",
    "Лейкоциты:": "Лейкоциты ",
    "Обший": "Общий",
    "ммопь/л": "ммоль/л",
    "ммoль/л": "ммоль/л",
    "10^9л": "10^9/л",
    "10*9/л": "10^9/л",
    "ед/ n": "Ед/л",
    "ед\\л": "Ед/л",
}

HANDWRITING_MARKERS = [
    "испр.",
    "от руки",
    "ручкой",
    "подпись",
]

TABLE_HEADER_ALIASES = {
    "показатель": "test_name",
    "анализ": "test_name",
    "test": "test_name",
    "значение": "value",
    "результат": "value",
    "value": "value",
    "единицы": "unit",
    "ед.": "unit",
    "unit": "unit",
    "реф.": "reference",
    "норма": "reference",
    "референс": "reference",
    "референтные значения": "reference",
}

UNIT_ALIASES = {
    "ммоль л": "ммоль/л",
    "ммоль/л": "ммоль/л",
    "мкмоль л": "мкмоль/л",
    "мкмоль/л": "мкмоль/л",
    "г л": "г/л",
    "г/л": "г/л",
    "ед л": "Ед/л",
    "ед/л": "Ед/л",
    "10^9 л": "10^9/л",
    "10^9/л": "10^9/л",
    "10*9/л": "10^9/л",
}

LAB_FORM_TEMPLATES = [
    {
        "name": "Инвитро",
        "markers": ["инвитро", "invitro", "результаты исследований"],
        "header_aliases": {
            "показатель": "test_name",
            "результат": "value",
            "ед. изм.": "unit",
            "референсные значения": "reference",
        },
    },
    {
        "name": "Гемотест",
        "markers": ["гемотест", "gemotest", "лабораторные исследования"],
        "header_aliases": {
            "исследование": "test_name",
            "результат": "value",
            "единицы измерения": "unit",
            "норма": "reference",
        },
    },
    {
        "name": "KDL",
        "markers": ["kdl", "кдл", "клинико-диагностическая лаборатория"],
        "header_aliases": {
            "параметр": "test_name",
            "значение": "value",
            "единицы": "unit",
            "референтный интервал": "reference",
        },
    },
]


def _method_confidence(method: str) -> float:
    if method == "pypdf":
        return 0.92
    if method == "ocr":
        return 0.76
    if method == "image_ocr":
        return 0.73
    return 0.58


def _method_label(method: str) -> str:
    return {
        "pypdf": "text-extraction",
        "ocr": "ocr",
        "image_ocr": "image-ocr",
        "raw": "raw-fallback",
    }.get(method, "unknown")


def _normalize_ocr_text(text: str) -> str:
    normalized = text
    for source, target in OCR_TEXT_REPLACEMENTS.items():
        normalized = normalized.replace(source, target)
    normalized = re.sub(r"(?<=\d)[OoОо](?=\d)", "0", normalized)
    normalized = re.sub(r"(?<=\d)[IlI|](?=\d)", "1", normalized)
    normalized = normalized.replace("—", "-").replace("–", "-")
    return normalized


def _normalize_unit(unit: str | None) -> str | None:
    if not unit:
        return None
    normalized = re.sub(r"\s+", " ", unit.strip().lower().replace("\\", "/"))
    return UNIT_ALIASES.get(normalized, unit.strip())


def _normalize_test_name(value: str | None) -> str | None:
    if not value:
        return None
    key = re.sub(r"\s+", " ", value.strip().lower())
    return KNOWN_TEST_ALIASES.get(key, value.strip())


def _extract_reference_range(value: str | None) -> tuple[float | None, float | None, str | None]:
    if not value:
        return None, None, None
    match = re.search(r"(-?\d+(?:[.,]\d+)?)\s*[-–]\s*(-?\d+(?:[.,]\d+)?)", value)
    if not match:
        return None, None, value.strip()
    return (
        float(match.group(1).replace(",", ".")),
        float(match.group(2).replace(",", ".")),
        value.strip(),
    )


def _normalize_reference_for_patient(reference_text: str | None, patient: Patient | None) -> tuple[float | None, float | None, str | None]:
    if not reference_text:
        return None, None, None
    age_years = None
    if patient and patient.date_of_birth:
        age_years = max((datetime.now().date() - patient.date_of_birth).days // 365, 0)
    normalized_text = reference_text.strip()
    child_match = re.search(r"(дет[^\d]{0,10}|child[^\d]{0,10})(-?\d+(?:[.,]\d+)?)\s*[-–]\s*(-?\d+(?:[.,]\d+)?)", normalized_text, re.IGNORECASE)
    adult_match = re.search(r"(взросл[^\d]{0,10}|adult[^\d]{0,10})(-?\d+(?:[.,]\d+)?)\s*[-–]\s*(-?\d+(?:[.,]\d+)?)", normalized_text, re.IGNORECASE)
    if age_years is not None:
        if age_years < 18 and child_match:
            return float(child_match.group(2).replace(",", ".")), float(child_match.group(3).replace(",", ".")), normalized_text
        if age_years >= 18 and adult_match:
            return float(adult_match.group(2).replace(",", ".")), float(adult_match.group(3).replace(",", ".")), normalized_text
    return _extract_reference_range(normalized_text)


def _is_probable_table_header(parts: list[str]) -> bool:
    lowered = [part.lower() for part in parts]
    header_hits = sum(1 for value in lowered if value in TABLE_HEADER_ALIASES)
    return header_hits >= 2


def _detect_lab_form_template(text: str) -> dict[str, Any] | None:
    lowered = text.lower()
    for template in LAB_FORM_TEMPLATES:
        if any(marker in lowered for marker in template["markers"]):
            return template
    return None


def _extract_cell_confidence(raw_cells: list[str], extraction_method: str) -> dict[str, float]:
    base = _method_confidence(extraction_method)
    confidence: dict[str, float] = {}
    for index, cell in enumerate(raw_cells):
        score = base
        stripped = cell.strip()
        if not stripped:
            score -= 0.2
        if re.search(r"[|_]{2,}", stripped):
            score -= 0.12
        if any(char in stripped for char in ["?", "~", "*"]):
            score -= 0.08
        if re.search(r"\d", stripped):
            score += 0.03
        confidence[f"cell_{index}"] = round(max(min(score, 0.99), 0.35), 2)
    return confidence


def _normalize_table_cells(line: str) -> list[str]:
    return [part.strip() for part in re.split(r"\s{2,}|\t|\||;", line) if part.strip()]


def _looks_like_cross_table_row(parts: list[str]) -> bool:
    return len(parts) >= 3 and any(re.search(r"-?\d+(?:[.,]\d+)?", part) for part in parts[1:])


def _extract_nested_table_candidates(lines: list[str], extraction_method: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    current_test_name: str | None = None
    for line in lines:
        parts = _normalize_table_cells(line)
        if not parts:
            continue
        if len(parts) == 1 and not re.search(r"-?\d+(?:[.,]\d+)?", parts[0]):
            current_test_name = _normalize_test_name(parts[0]) or parts[0]
            continue
        if current_test_name and _looks_like_cross_table_row(parts):
            value_match = re.search(r"-?\d+(?:[.,]\d+)?", " ".join(parts[1:]))
            if not value_match:
                continue
            unit = None
            reference_text = None
            if len(parts) >= 3:
                unit = _normalize_unit(parts[2])
            if len(parts) >= 4:
                reference_text = parts[3]
            cell_confidence = _extract_cell_confidence(parts, extraction_method)
            candidates.append(
                {
                    "kind": "lab_result",
                    "value": {
                        "test_name": current_test_name,
                        "value": float(value_match.group(0).replace(",", ".")),
                        "unit": unit,
                        "reference_text": reference_text,
                    },
                    "confidence": "medium",
                    "confidence_score": round(sum(cell_confidence.values()) / len(cell_confidence), 2),
                    "cell_confidence": cell_confidence,
                    "source_line": line,
                    "match_mode": "nested_table",
                }
            )
            current_test_name = None
    return candidates


def analyze_image_quality(file_bytes: bytes, original_filename: str) -> dict[str, Any]:
    suffix = Path(original_filename).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png"}:
        return {"is_photo": False, "quality_hint": None}
    try:
        import io

        from PIL import Image, ImageStat  # type: ignore

        image = Image.open(io.BytesIO(file_bytes))
        width, height = image.size
        brightness = None
        quality_hint = "Снимок подходит для OCR"
        suggestions: list[str] = []
        grayscale = image.convert("L")
        brightness = ImageStat.Stat(grayscale).mean[0]
        if min(width, height) < 1200:
            quality_hint = "Снимок лучше сделать ближе и при хорошем освещении"
            suggestions.append("Поднесите телефон ближе к документу")
        if brightness < 75:
            quality_hint = "Фото тёмное, лучше переснять при ярком свете"
            suggestions.append("Добавьте яркий ровный свет без тени")
        ratio = max(width, height) / max(min(width, height), 1)
        if ratio > 2.1:
            quality_hint = "Документ снят под углом или слишком узко кадрирован"
            suggestions.append("Держите телефон ровно и захватывайте весь бланк целиком")
        region_hints = [
            {"name": "верх документа", "action": "проверьте, не обрезаны ли шапка и название лаборатории"},
            {"name": "центр документа", "action": "если строки слиплись, попробуйте переснять без наклона"},
            {"name": "низ документа", "action": "убедитесь, что нижние строки и референсы не ушли в тень"},
        ]
        return {
            "is_photo": True,
            "width": width,
            "height": height,
            "brightness": round(brightness, 1) if brightness is not None else None,
            "quality_hint": quality_hint,
            "suggestions": suggestions,
            "region_hints": region_hints,
        }
    except Exception:
        return {"is_photo": True, "quality_hint": "Не удалось оценить качество фото"}


def extract_text_from_document_bytes(file_bytes: bytes, original_filename: str) -> tuple[str, str]:
    suffix = Path(original_filename).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png"}:
        try:
            import io

            from PIL import Image, ImageEnhance, ImageOps  # type: ignore
            import pytesseract  # type: ignore

            image = Image.open(io.BytesIO(file_bytes))
            image = ImageOps.exif_transpose(image)
            variants = []
            grayscale = ImageOps.grayscale(image)
            variants.append(ImageEnhance.Contrast(grayscale).enhance(1.5))
            variants.append(ImageEnhance.Contrast(grayscale).enhance(2.0).rotate(1.2, expand=True))
            variants.append(ImageEnhance.Contrast(grayscale).enhance(2.0).rotate(-1.2, expand=True))
            texts = [_normalize_ocr_text(pytesseract.image_to_string(variant, lang="rus+eng")) for variant in variants]
            best_text = max(texts, key=lambda value: len(re.findall(r"[A-Za-zА-Яа-яЁё0-9]", value)))
            return best_text, "image_ocr"
        except Exception:
            return _normalize_ocr_text(file_bytes.decode("utf-8", errors="ignore")), "raw"

    try:
        from pypdf import PdfReader  # type: ignore

        import io

        reader = PdfReader(io.BytesIO(file_bytes))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        if text.strip():
            return _normalize_ocr_text(text), "pypdf"
    except Exception:
        pass

    try:
        import io

        import pytesseract  # type: ignore
        from pdf2image import convert_from_bytes  # type: ignore

        images = convert_from_bytes(file_bytes, fmt="png")
        return _normalize_ocr_text("\n".join(pytesseract.image_to_string(image, lang="rus+eng") for image in images)), "ocr"
    except Exception:
        return _normalize_ocr_text(file_bytes.decode("utf-8", errors="ignore")), "raw"


def extract_page_texts(file_bytes: bytes, original_filename: str) -> tuple[list[str], str]:
    suffix = Path(original_filename).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png"}:
        text, method = extract_text_from_document_bytes(file_bytes, original_filename)
        return [text], method
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(io.BytesIO(file_bytes))
        pages = [_normalize_ocr_text(page.extract_text() or "") for page in reader.pages]
        pages = [page for page in pages if page.strip()]
        if pages:
            return pages, "pypdf"
    except Exception:
        pass
    text, method = extract_text_from_document_bytes(file_bytes, original_filename)
    return [text], method


def _extract_table_candidates(lines: list[str]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    known_tests = {
        "гемоглобин": ("Гемоглобин", "г/л"),
        "глюкоза": ("Глюкоза", "ммоль/л"),
        "общий холестерин": ("Общий холестерин", "ммоль/л"),
        "лейкоциты": ("Лейкоциты", "10^9/л"),
        "алт": ("АЛТ", "Ед/л"),
        "аст": ("АСТ", "Ед/л"),
        "креатинин": ("Креатинин", "мкмоль/л"),
    }
    multiline_state: dict[str, Any] | None = None
    for line in lines:
        normalized = re.sub(r"\s+", " ", line.strip().lower())
        if multiline_state and re.fullmatch(r"-?\d+(?:[.,]\d+)?(?:\s+[A-Za-zА-Яа-яЁё/^0-9\\]+)?", line.strip()):
            match = re.search(r"(-?\d+(?:[.,]\d+)?)", line)
            if match:
                multiline_state["value"]["value"] = float(match.group(1).replace(",", "."))
                unit_match = re.search(r"(-?\d+(?:[.,]\d+)?)\s+([A-Za-zА-Яа-яЁё/^0-9\\]+)", line.strip())
                if unit_match:
                    multiline_state["value"]["unit"] = _normalize_unit(unit_match.group(2))
                multiline_state["source_line"] = f"{multiline_state['source_line']} | {line.strip()}"
                multiline_state["match_mode"] = "multiline_row"
                multiline_state["confidence_score"] = 0.74
                candidates.append(multiline_state)
                multiline_state = None
                continue
        for token, (test_name, unit) in known_tests.items():
            if token not in normalized:
                continue
            match = re.search(r"(-?\d+(?:[.,]\d+)?)", normalized)
            if not match:
                multiline_state = {
                    "kind": "lab_result",
                    "value": {"test_name": test_name, "value": None, "unit": unit},
                    "confidence": "medium",
                    "confidence_score": 0.62,
                    "source_line": line,
                }
                continue
            candidates.append(
                {
                    "kind": "lab_result",
                    "value": {"test_name": test_name, "value": float(match.group(1).replace(",", ".")), "unit": unit},
                    "confidence": "medium",
                    "confidence_score": 0.72,
                    "source_line": line,
                }
            )
        row_match = re.search(r"^([A-Za-zА-Яа-яЁё\s]+?)[\s\.:_]{1,}(-?\d+(?:[.,]\d+)?)(?:\s+([A-Za-zА-Яа-яЁё/^0-9\\]+))?$", line.strip())
        if row_match:
            raw_name = row_match.group(1).strip()
            test_name = next((name for name in LAB_PANEL_BY_TEST if name.lower() == raw_name.lower()), _normalize_test_name(raw_name))
            candidates.append(
                {
                    "kind": "lab_result",
                    "value": {
                        "test_name": test_name,
                        "value": float(row_match.group(2).replace(",", ".")),
                        "unit": _normalize_unit(row_match.group(3)),
                    },
                    "confidence": "medium",
                    "confidence_score": 0.68,
                    "source_line": line,
                }
            )
    return candidates


def _extract_structured_table_candidates(lines: list[str], extraction_method: str = "raw", template: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    structured: list[dict[str, Any]] = []
    header_map: dict[int, str] = {}
    pending_row: dict[str, Any] | None = None
    for line in lines:
        parts = _normalize_table_cells(line)
        if len(parts) < 2:
            if pending_row and line.strip():
                numeric_match = re.search(r"(-?\d+(?:[.,]\d+)?)(?:\s+([A-Za-zА-Яа-яЁё/^0-9\\]+))?", line.strip())
                if numeric_match:
                    pending_row["value"]["value"] = float(numeric_match.group(1).replace(",", "."))
                    if numeric_match.group(2):
                        pending_row["value"]["unit"] = _normalize_unit(numeric_match.group(2))
                    pending_row["source_line"] = f"{pending_row['source_line']} | {line.strip()}"
                    structured.append(pending_row)
                    pending_row = None
                else:
                    pending_row["value"]["test_name"] = f"{pending_row['value']['test_name']} {line.strip()}".strip()
            continue
        normalized_parts = [part.lower() for part in parts]
        header_aliases = {**TABLE_HEADER_ALIASES, **((template or {}).get("header_aliases") or {})}
        mapped = {index: header_aliases.get(value) for index, value in enumerate(normalized_parts)}
        if any(mapped.values()) and _is_probable_table_header(parts):
            header_map = {index: value for index, value in mapped.items() if value}
            pending_row = None
            continue
        if not header_map:
            continue
        candidate_value: dict[str, Any] = {}
        for index, key in header_map.items():
            if index >= len(parts):
                continue
            raw_value = parts[index]
            if key == "value":
                match = re.search(r"-?\d+(?:[.,]\d+)?", raw_value)
                if not match:
                    continue
                candidate_value[key] = float(match.group(0).replace(",", "."))
            elif key == "reference":
                low, high, text = _extract_reference_range(raw_value)
                candidate_value["reference_low"] = low
                candidate_value["reference_high"] = high
                candidate_value["reference_text"] = text
            else:
                candidate_value[key] = raw_value
        if "test_name" in candidate_value and "value" not in candidate_value:
            pending_row = {
                "kind": "lab_result",
                "value": {
                    "test_name": _normalize_test_name(str(candidate_value["test_name"])) or str(candidate_value["test_name"]),
                    "value": None,
                    "unit": _normalize_unit(candidate_value.get("unit")),
                    "reference_low": candidate_value.get("reference_low"),
                    "reference_high": candidate_value.get("reference_high"),
                    "reference_text": candidate_value.get("reference_text"),
                },
                "confidence": "medium",
                "confidence_score": 0.66,
                "source_line": line,
                "match_mode": "structured_multiline",
            }
            continue
        if pending_row and "value" in candidate_value and "test_name" not in candidate_value:
            pending_row["value"]["value"] = candidate_value["value"]
            if candidate_value.get("unit"):
                pending_row["value"]["unit"] = _normalize_unit(candidate_value.get("unit"))
            if candidate_value.get("reference_text"):
                pending_row["value"]["reference_low"] = candidate_value.get("reference_low")
                pending_row["value"]["reference_high"] = candidate_value.get("reference_high")
                pending_row["value"]["reference_text"] = candidate_value.get("reference_text")
            pending_row["source_line"] = f"{pending_row['source_line']} | {line}"
            structured.append(pending_row)
            pending_row = None
            continue
        if {"test_name", "value"}.issubset(candidate_value):
            test_name = next(
                (name for name in LAB_PANEL_BY_TEST if name.lower() == str(candidate_value["test_name"]).lower()),
                _normalize_test_name(str(candidate_value["test_name"])) or str(candidate_value["test_name"]),
            )
            cell_confidence = _extract_cell_confidence(parts, extraction_method)
            structured.append(
                {
                    "kind": "lab_result",
                    "value": {
                        "test_name": test_name,
                        "value": candidate_value["value"],
                        "unit": _normalize_unit(candidate_value.get("unit")),
                        "reference_low": candidate_value.get("reference_low"),
                        "reference_high": candidate_value.get("reference_high"),
                        "reference_text": candidate_value.get("reference_text"),
                    },
                    "confidence": "medium",
                    "confidence_score": round(sum(cell_confidence.values()) / len(cell_confidence), 2),
                    "cell_confidence": cell_confidence,
                    "source_line": line,
                    "match_mode": "structured_table",
                }
            )
    return structured


def parse_medical_pdf_text(text: str, extraction_method: str = "raw") -> list[dict[str, Any]]:
    normalized = text.replace(",", ".")
    candidates: list[dict[str, Any]] = []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    method_confidence = _method_confidence(extraction_method)
    template = _detect_lab_form_template(text)

    pressure_match = re.search(r"(?:ад|давление|bp)[^\d]{0,10}(\d{2,3})\s*[\/\\]\s*(\d{2,3})(?:[^\d]{0,10}(\d{2,3}))?", normalized, re.IGNORECASE)
    if pressure_match:
        candidates.append(
            {
                "kind": "blood_pressure",
                "value": {
                    "sys": int(pressure_match.group(1)),
                    "dia": int(pressure_match.group(2)),
                    "pulse": int(pressure_match.group(3)) if pressure_match.group(3) else None,
                },
                "confidence": "high",
                "confidence_score": round(min(method_confidence + 0.08, 0.98), 2),
                "source_line": pressure_match.group(0),
                "extraction_method": extraction_method,
            }
        )

    for test_name, pattern, unit in LAB_TEST_PATTERNS:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if not match:
            continue
        candidates.append(
            {
                "kind": "lab_result",
                "value": {
                    "test_name": test_name,
                    "value": float(match.group(1)),
                    "unit": unit,
                    "panel_name": LAB_PANEL_BY_TEST.get(test_name, "Без панели"),
                },
                "confidence": "medium",
                "confidence_score": round(min(method_confidence + 0.03, 0.95), 2),
                "source_line": match.group(0),
                "extraction_method": extraction_method,
            }
        )

    seen_lab_names = {item["value"]["test_name"] for item in candidates if item["kind"] == "lab_result"}
    for item in _extract_table_candidates(lines):
        if item["value"]["test_name"] in seen_lab_names:
            continue
        item["confidence_score"] = round(min(item["confidence_score"], method_confidence), 2)
        item["extraction_method"] = extraction_method
        item["value"]["panel_name"] = LAB_PANEL_BY_TEST.get(item["value"]["test_name"], "Без панели")
        if template:
            item["lab_form_template"] = template["name"]
        candidates.append(item)

    for item in _extract_structured_table_candidates(lines, extraction_method=extraction_method, template=template):
        test_name = item["value"]["test_name"]
        if test_name in seen_lab_names:
            continue
        item["confidence_score"] = round(min(item["confidence_score"], method_confidence), 2)
        item["extraction_method"] = extraction_method
        item["value"]["panel_name"] = LAB_PANEL_BY_TEST.get(test_name, "Без панели")
        if template:
            item["lab_form_template"] = template["name"]
        candidates.append(item)
        seen_lab_names.add(test_name)

    for item in _extract_nested_table_candidates(lines, extraction_method=extraction_method):
        test_name = item["value"]["test_name"]
        if test_name in seen_lab_names:
            continue
        item["confidence_score"] = round(min(item["confidence_score"], method_confidence), 2)
        item["extraction_method"] = extraction_method
        item["value"]["panel_name"] = LAB_PANEL_BY_TEST.get(test_name, "Без панели")
        if template:
            item["lab_form_template"] = template["name"]
        candidates.append(item)
        seen_lab_names.add(test_name)

    return candidates


def build_page_level_analysis(page_texts: list[str], extraction_method: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    page_summaries = []
    comparisons: list[dict[str, Any]] = []
    values_by_test: dict[str, list[dict[str, Any]]] = {}
    for index, page_text in enumerate(page_texts, start=1):
        candidates = parse_medical_pdf_text(page_text, extraction_method=extraction_method)
        lab_count = len([item for item in candidates if item.get("kind") == "lab_result"])
        pressure_count = len([item for item in candidates if item.get("kind") == "blood_pressure"])
        page_summaries.append({"page": index, "lab_results": lab_count, "blood_pressure": pressure_count, "candidate_count": len(candidates)})
        for item in candidates:
            if item.get("kind") != "lab_result":
                continue
            value = item.get("value", {})
            test_name = value.get("test_name")
            numeric_value = value.get("value")
            if test_name is None or numeric_value is None:
                continue
            values_by_test.setdefault(str(test_name), []).append({"page": index, "value": numeric_value, "unit": value.get("unit")})
    for test_name, entries in sorted(values_by_test.items()):
        pages = {entry["page"] for entry in entries}
        distinct_values = {entry["value"] for entry in entries}
        if len(pages) > 1:
            comparisons.append(
                {
                    "test_name": test_name,
                    "pages": sorted(pages),
                    "values": entries,
                    "status": "changed" if len(distinct_values) > 1 else "repeated",
                }
            )
    return page_summaries, comparisons


def build_duplicate_review_groups(candidates: list[dict[str, Any]], page_comparisons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for index, item in enumerate(candidates):
        if item.get("kind") != "lab_result":
            continue
        test_name = str(item.get("value", {}).get("test_name") or "").strip()
        if not test_name:
            continue
        grouped.setdefault(test_name, []).append({**item, "candidate_index": index})

    duplicate_groups: list[dict[str, Any]] = []
    comparison_by_test = {item["test_name"]: item for item in page_comparisons}
    for test_name, items in grouped.items():
        if len(items) < 2:
            continue
        recommended = max(items, key=lambda item: float(item.get("confidence_score") or 0))
        duplicate_groups.append(
            {
                "test_name": test_name,
                "items": items,
                "recommended_candidate_index": recommended["candidate_index"],
                "status": comparison_by_test.get(test_name, {}).get("status", "duplicate"),
                "pages": comparison_by_test.get(test_name, {}).get("pages", []),
            }
        )
    return duplicate_groups


def build_region_review_hints(text: str, photo_quality: dict[str, Any] | None = None) -> list[str]:
    hints: list[str] = []
    if photo_quality and photo_quality.get("region_hints"):
        hints.extend(item["action"] for item in photo_quality["region_hints"])
    lowered = text.lower()
    if any(marker in lowered for marker in HANDWRITING_MARKERS) or re.search(r"[A-Za-zА-Яа-яЁё]\s*/\s*[A-Za-zА-Яа-яЁё]", text):
        hints.append("Похоже, на документе есть рукописные пометки. Проверьте строки с исправлениями вручную.")
    if re.search(r"[\/\\]{2,}|_{3,}", text):
        hints.append("Есть признаки шумного скана: проверьте строки, где текст разделён линиями или косыми чертами.")
    return hints


def import_medical_pdf(
    db: Session,
    patient: Patient,
    pdf_bytes: bytes,
    original_filename: str,
    save_results: bool = False,
    store_document: bool = False,
) -> dict:
    page_texts, extraction_method = extract_page_texts(pdf_bytes, original_filename)
    text = "\n".join(page_texts)
    candidates = parse_medical_pdf_text(text, extraction_method=extraction_method)
    page_summaries, page_comparisons = build_page_level_analysis(page_texts, extraction_method)
    photo_quality = analyze_image_quality(pdf_bytes, original_filename)
    created = {"observations": 0, "lab_results": 0, "document": False}

    if save_results:
        for item in candidates:
            if item["kind"] == "blood_pressure":
                db.add(Observation(patient_id=patient.id, type="blood_pressure", value=item["value"]))
                created["observations"] += 1
            elif item["kind"] == "lab_result":
                reference_low, reference_high, reference_text = _normalize_reference_for_patient(item["value"].get("reference_text"), patient)
                db.add(
                    LabResult(
                        patient_id=patient.id,
                        test_name=item["value"]["test_name"],
                        value=item["value"]["value"],
                        unit=item["value"]["unit"],
                        reference_low=reference_low if reference_low is not None else item["value"].get("reference_low"),
                        reference_high=reference_high if reference_high is not None else item["value"].get("reference_high"),
                        reference_text=reference_text if reference_text is not None else item["value"].get("reference_text"),
                    )
                )
                created["lab_results"] += 1
        if store_document:
            stored_path = save_import_source_bytes(original_filename, pdf_bytes, patient.id)
            document = build_uploaded_document(
                patient_id=patient.id,
                stored_path=stored_path,
                original_filename=original_filename,
                description="Импортированный медицинский PDF",
            )
            db.add(document)
            created["document"] = True
        db.commit()
        if store_document:
            db.refresh(document)
            queue_document_processing(document)

    return {
        "candidates": candidates,
        "created": created,
        "text_excerpt": text[:1000],
        "extraction_method": extraction_method,
        "extraction_pipeline": _method_label(extraction_method),
        "document_confidence_score": _method_confidence(extraction_method),
        "candidate_count": len(candidates),
        "page_count": len(page_texts),
        "page_summaries": page_summaries,
        "page_comparisons": page_comparisons,
        "duplicate_review_groups": build_duplicate_review_groups(candidates, page_comparisons),
        "grouped_candidates": build_candidate_groups(candidates),
        "table_review_summary": build_table_review_summary(candidates),
        "candidate_quality_flags": build_candidate_quality_flags(candidates),
        "lab_form_template": template["name"] if (template := _detect_lab_form_template(text)) else None,
        "photo_quality": photo_quality,
        "region_review_hints": build_region_review_hints(text, photo_quality),
        "handwriting_review_hints": build_handwriting_review_hints(text, extraction_method),
        "suspicious_review_fragments": build_suspicious_review_fragments(text),
        "region_review_summary": build_region_review_summary(text),
    }


def build_candidate_groups(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for index, item in enumerate(candidates):
        enriched_item = {**item, "candidate_index": index}
        if item.get("kind") == "lab_result":
            group = item.get("value", {}).get("panel_name") or "Без панели"
        elif item.get("kind") == "blood_pressure":
            group = "Жизненные показатели"
        else:
            group = "Прочее"
        grouped.setdefault(group, []).append(enriched_item)
    return [{"name": name, "items": items} for name, items in grouped.items()]


def build_table_review_summary(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: dict[str, int] = {}
    for item in candidates:
        if item.get("kind") != "lab_result":
            continue
        mode = item.get("match_mode", "pattern")
        summary[mode] = summary.get(mode, 0) + 1
    return [{"mode": mode, "count": count} for mode, count in sorted(summary.items())]


def build_candidate_quality_flags(candidates: list[dict[str, Any]]) -> list[str]:
    flags: list[str] = []
    if any(item.get("match_mode") in {"structured_multiline", "multiline_row"} for item in candidates):
        flags.append("обнаружены многострочные строки анализов")
    if any(item.get("match_mode") in {"nested_table", "structured_table"} for item in candidates):
        flags.append("обнаружены вложенные или перекрёстные табличные структуры")
    if any((item.get("value", {}) or {}).get("unit") in {"Ед/л", "10^9/л"} for item in candidates if item.get("kind") == "lab_result"):
        flags.append("нормализованы нестандартные единицы измерения")
    if any((item.get("value", {}) or {}).get("reference_text") for item in candidates if item.get("kind") == "lab_result"):
        flags.append("извлечены референсные диапазоны из табличного бланка")
    if any(item.get("cell_confidence") for item in candidates):
        flags.append("добавлен confidence по ячейкам для ручной проверки строк")
    if any(item.get("lab_form_template") for item in candidates):
        flags.append("распознан шаблон типового российского лабораторного бланка")
    return flags


def build_handwriting_review_hints(text: str, extraction_method: str) -> list[str]:
    hints: list[str] = []
    lowered = text.lower()
    if extraction_method in {"ocr_image", "ocr_photo", "ocr_fallback"}:
        hints.append("документ прошёл OCR-ветку, рукописные пометки стоит перепроверить вручную")
    if any(marker in lowered for marker in ["испр.", "исправ", "ручн", "от руки"]):
        hints.append("замечены признаки рукописных исправлений рядом с анализами")
    if any(marker in lowered for marker in ["штамп", "печать", "stamp"]):
        hints.append("в тексте есть признаки штампов или печатей, часть значений могла сдвинуться")
    if hints:
        hints.append("смешанные печатно-рукописные области лучше подтверждать по строкам ниже")
    return hints


def build_suspicious_review_fragments(text: str) -> list[str]:
    fragments: list[str] = []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    markers = ("испр", "ручн", "от руки", "штамп", "печать", "подпись", "замазан", "повтор")
    for line in lines:
        lowered = line.lower()
        if any(marker in lowered for marker in markers):
            fragments.append(line[:140])
        if len(fragments) >= 5:
            break
    return fragments


def build_region_review_summary(text: str) -> list[dict]:
    summary: list[dict] = []
    lowered = text.lower()
    if any(token in lowered for token in ["испр", "ручн", "от руки"]):
        summary.append({"region": "строки с анализами", "risk": "high", "note": "Есть признаки рукописных исправлений рядом со значениями."})
    if any(token in lowered for token in ["штамп", "печать", "stamp"]):
        summary.append({"region": "область подписи/печати", "risk": "medium", "note": "Штамп или печать могли сместить часть строк и референсов."})
    if any(token in lowered for token in ["табл", "column", "ед.", "реф"]):
        summary.append({"region": "табличная часть", "risk": "medium", "note": "Подтвердите сомнительные колонки показатель / значение / единицы вручную."})
    return summary
