"""Text normalization, DTC parsing, chunking, and near-duplicate checks."""

import hashlib
import re
from collections import Counter

DTC_RE = re.compile(r"\b([PCBU])[\s\-]?(\d{4})\b", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(19[8-9]\d|20[0-3]\d)\b")
TOKEN_RE = re.compile(r"[a-z0-9]+")

STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with", "at",
    "is", "was", "were", "be", "by", "from", "that", "this", "it", "as", "not",
}

MAKE_ALIASES = {
    "honda": "Honda",
    "toyota": "Toyota",
    "ford": "Ford",
    "chevrolet": "Chevrolet",
    "chevy": "Chevrolet",
    "bmw": "BMW",
    "nissan": "Nissan",
    "hyundai": "Hyundai",
    "kia": "Kia",
    "subaru": "Subaru",
    "acura": "Acura",
    "lexus": "Lexus",
    "volkswagen": "Volkswagen",
    "vw": "Volkswagen",
    "jeep": "Jeep",
    "ram": "Ram",
    "gmc": "GMC",
    "mazda": "Mazda",
    "audi": "Audi",
    "mercedes": "Mercedes-Benz",
    "mercedes-benz": "Mercedes-Benz",
}

# Explicit make/model pairs. Matching is literal, not fuzzy.
MODEL_PAIRS: list[tuple[str, str, str]] = [
    ("Honda", "civic", "Civic"),
    ("Honda", "accord", "Accord"),
    ("Honda", "cr-v", "CR-V"),
    ("Honda", "crv", "CR-V"),
    ("Toyota", "camry", "Camry"),
    ("Toyota", "corolla", "Corolla"),
    ("Toyota", "rav4", "RAV4"),
    ("Toyota", "rav-4", "RAV4"),
    ("Ford", "escape", "Escape"),
    ("Ford", "f-150", "F-150"),
    ("Ford", "f150", "F-150"),
    ("Chevrolet", "malibu", "Malibu"),
    ("Chevrolet", "silverado", "Silverado"),
    ("Nissan", "altima", "Altima"),
    ("Jeep", "wrangler", "Wrangler"),
    ("Hyundai", "elantra", "Elantra"),
    ("Subaru", "outback", "Outback"),
    ("BMW", "328i", "328i"),
]

COMPONENT_ALIASES = {
    "cat converter": "catalytic converter",
    "cat. converter": "catalytic converter",
    "catalyst": "catalytic converter",
    "catalytic converter": "catalytic converter",
    "o2 sensor": "oxygen sensor",
    "oxygen sensor": "oxygen sensor",
    "front brake pads": "front brake pads",
    "brake pads": "brake pads",
    "rotors": "brake rotors",
    "brake rotors": "brake rotors",
    "wheel speed sensor": "wheel speed sensor",
    "shift solenoid": "shift solenoid",
    "thermostat": "thermostat",
    "radio": "radio",
    "spark plug": "spark plug",
    "ignition coil": "ignition coil",
}

REPAIR_VERBS = (
    "replaced",
    "repaired",
    "installed",
    "adjusted",
    "flushed",
    "bled",
    "resurfaced",
    "reprogrammed",
    "tightened",
    "cleaned",
)


def normalize_whitespace(text: str) -> str:
    text = text.replace("\u00a0", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def checksum(text: str) -> str:
    return hashlib.sha256(normalize_whitespace(text).encode("utf-8")).hexdigest()


def normalize_dtc(raw: str) -> str:
    match = DTC_RE.search(raw.strip())
    if not match:
        compact = re.sub(r"[^A-Za-z0-9]", "", raw).upper()
        match = re.fullmatch(r"([PCBU])(\d{4})", compact)
        if not match:
            return raw.strip().upper()
        return f"{match.group(1)}{match.group(2)}"
    return f"{match.group(1).upper()}{match.group(2)}"


def find_dtcs(text: str) -> list[str]:
    found: list[str] = []
    for match in DTC_RE.finditer(text):
        code = f"{match.group(1).upper()}{match.group(2)}"
        if code not in found:
            found.append(code)
    return found


def tokenize(text: str) -> list[str]:
    return [tok for tok in TOKEN_RE.findall(text.lower()) if tok not in STOPWORDS and len(tok) > 1]


def jaccard(a: str, b: str) -> float:
    ta, tb = set(tokenize(a)), set(tokenize(b))
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(tb | ta)


def find_span(text: str, quote: str) -> tuple[int, int] | None:
    if not quote:
        return None
    idx = text.find(quote)
    if idx >= 0:
        return idx, idx + len(quote)
    lower = text.lower()
    idx = lower.find(quote.lower())
    if idx >= 0:
        return idx, idx + len(quote)
    return None


def chunk_text(text: str, *, size: int = 700, overlap: int = 80) -> list[tuple[int, int, str]]:
    cleaned = text.strip()
    if not cleaned:
        return []
    if len(cleaned) <= size:
        return [(0, len(cleaned), cleaned)]
    chunks: list[tuple[int, int, str]] = []
    start = 0
    while start < len(cleaned):
        end = min(len(cleaned), start + size)
        if end < len(cleaned):
            window = cleaned.rfind(". ", start, end)
            if window > start + size // 2:
                end = window + 1
        piece = cleaned[start:end].strip()
        if piece:
            lead = cleaned.find(piece, start)
            if lead < 0:
                lead = start
            chunks.append((lead, lead + len(piece), piece))
        if end >= len(cleaned):
            break
        start = max(end - overlap, start + 1)
    return chunks


def term_highlights(text: str, query: str) -> list[dict[str, int]]:
    spans: list[dict[str, int]] = []
    lower = text.lower()
    for token in sorted(set(tokenize(query)), key=len, reverse=True):
        if len(token) < 3 and not re.fullmatch(r"[pcbu]\d{4}", token):
            continue
        pattern = re.compile(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])")
        for match in pattern.finditer(lower):
            spans.append({"start": match.start(), "end": match.end()})
            if len(spans) >= 12:
                return _merge_spans(spans)
    return _merge_spans(spans)


def _merge_spans(spans: list[dict[str, int]]) -> list[dict[str, int]]:
    if not spans:
        return []
    ordered = sorted(spans, key=lambda item: item["start"])
    merged = [ordered[0]]
    for span in ordered[1:]:
        if span["start"] <= merged[-1]["end"]:
            merged[-1]["end"] = max(merged[-1]["end"], span["end"])
        else:
            merged.append(span)
    return merged


def histogram(lengths: list[int]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for length in lengths:
        if length < 200:
            counts["0-199"] += 1
        elif length < 800:
            counts["200-799"] += 1
        else:
            counts["800+"] += 1
    return dict(counts)
