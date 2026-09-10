"""
Universal block-aware parser for Telegram resale-channel posts.

Designed to handle two real-world formats observed in the source channels:

  Top re:sale style (header with colon, followed by flagged price lines)
      iPhone 17 Pro:

      🇪🇺 Sim+eSim 17 Pro 256GB  White — 100500₽
      🇭🇰 Sim+eSim 17 Pro 256GB  Blue  — 101000₽

  Bests re:sale style (header in section header, prices with `.` thousands)
      iPhone 14 Plus

      14 Plus 128GB Yellow — 42.600 🇭🇰
      14 Plus 256GB Black  — 45.200 🇺🇸

Skip rules (per the product owner):
    A line is skipped iff it contains an ASIS/asis/асис marker OR the phrase
    "с коробкой" / "с коробки".  Section headers carrying those markers
    propagate to subsequent product lines until the next non-skip header.

Everything else (any brand, any colour, any flag, any storage) MUST flow
through to the database — there is no other allow/deny logic.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from common.models import ParsedProduct, RawMessage


FLAG_SIM_MAP = {
    # eSIM-only markets
    "🇧🇭": "esim", "🇨🇦": "esim", "🇬🇺": "esim", "🇯🇵": "esim",
    "🇰🇼": "esim", "🇲🇽": "esim", "🇴🇲": "esim", "🇶🇦": "esim",
    "🇸🇦": "esim", "🇦🇪": "esim", "🇺🇸": "esim", "🇻🇮": "esim",
    # SIM + eSIM markets
    "🇪🇺": "sim+esim", "🇮🇳": "sim+esim", "🇻🇳": "sim+esim",
    "🇦🇺": "sim+esim", "🇳🇿": "sim+esim", "🇰🇷": "sim+esim",
    "🇸🇬": "sim+esim", "🇭🇰": "sim+esim", "🇹🇼": "sim+esim",
    "🇷🇺": "sim+esim", "🇰🇿": "sim+esim", "🇮🇩": "sim+esim",
    "🇹🇭": "sim+esim", "🇵🇭": "sim+esim", "🇲🇾": "sim+esim",
    "🇵🇦": "sim+esim", "🇨🇱": "sim+esim", "🇿🇦": "sim+esim",
    "🇬🇧": "sim+esim", "🇮🇱": "sim+esim", "🇹🇷": "sim+esim",
    "🇧🇷": "sim+esim", "🇮🇹": "sim+esim", "🇩🇪": "sim+esim",
    "🇫🇷": "sim+esim", "🇪🇸": "sim+esim", "🇵🇹": "sim+esim",
    "🇵🇱": "sim+esim", "🇸🇪": "sim+esim", "🇳🇴": "sim+esim",
    "🇩🇰": "sim+esim", "🇫🇮": "sim+esim", "🇵🇾": "sim+esim",
    # 2 SIM markets
    "🇨🇳": "2sim",
}
FLAG_REGEX = re.compile("(" + "|".join(re.escape(f) for f in FLAG_SIM_MAP) + ")")

# Numbers like 50.300, 50 300, 50300, 110.400, 1 234 567 (with optional ₽ / руб / rub).
PRICE_REGEX = re.compile(
    r"(\d{1,3}(?:[\.\u202f\xa0\s]\d{3})+|\d{4,7})\s*(?:₽|руб\.?|rub)?",
    re.IGNORECASE,
)

STORAGE_RAM_REGEX = re.compile(r"\b(\d{1,2})\s*/\s*(\d{2,4})\b")  # 8/256, 4/64
STORAGE_REGEX = re.compile(r"\b(\d{1,4})\s*(gb|tb)\b", re.IGNORECASE)

COLORS = (
    "cosmic orange", "deep blue", "rose gold", "jet black", "sky blue",
    "midnight green", "olive green", "graphite gray", "space gray",
    "space black", "mist blue",
    "ultramarine", "starlight", "midnight", "graphite", "lavender", "lavander",
    "natural", "desert", "cosmic", "violet", "purple", "orange", "yellow",
    "silver", "black", "white", "blue", "pink", "green", "red", "gold",
    "olive", "navy", "teal", "sage", "mint", "lime", "gray", "grey",
    "phantom", "cream",
)
COLOR_REGEX = re.compile(
    r"\b(" + "|".join(re.escape(c) for c in COLORS) + r")\b",
    re.IGNORECASE,
)

SIM_TYPE_REGEX = re.compile(
    r"\b(sim\s*\+\s*esim|sim\+esim|esim|2\s*sim|dual\s*sim)\b",
    re.IGNORECASE,
)

# These tokens, when present in a line, force a skip per product policy.
SKIP_PRODUCT_TOKENS = ("asis", "асис", "с коробкой", "с коробки")

# Section markers — when a *header* (no price) carries one of these tokens,
# every product line under it is skipped until a new (clean) header arrives.
SECTION_SKIP_TOKENS = SKIP_PRODUCT_TOKENS

# Lines that should never be considered (channel chrome / disclaimers).
META_TOKENS = (
    "оформление заказа", "менеджер:", "💬менеджер", "условия работы",
    "отзывы клиентов", "👻отправки", "отправки", "faq", "t.me/",
    "https://", "http://",
    "в зависимости от страны", "только esim", "только физическая",
    "esim + физическая", "физическая 2sim",
    "гарантия на обменки", "гарантия на",
    "комплектация", "запак",
    "не активированные обменки", "активированные обменки",
    "предоставляется", "обменки",
    "сюда относятся", "материковом",
    "📱 только", "📱 esim",
    "от 10 шт", "от 100 шт", "от 200 шт", "от 1000 шт",
    "-1 шт", "наша вилка",
)

TOP_RESALE_CHANNELS = {"1963407298", "-1001963407298"}

# Section keywords that imply a brand context even without a brand name.
IMPLICIT_BRAND_HINTS: Tuple[Tuple[re.Pattern, str, str], ...] = (
    (re.compile(r"беспроводн\w*\s+пылесос|проводн\w*\s+пылесос|стайлер|airwrap|airstrait|supersonic|клин\w*\s+воздух\w*", re.IGNORECASE),
     "accessories", "Dyson"),
)

# Patterns that, even on their own, are unmistakably Dyson product codes.
DYSON_INLINE_REGEX = re.compile(
    r"\b(v\d{1,2}s?(?:\s*sv\d{2})?|gen\d|sv\d{2}-?[a-z]?|hd\d{2}|hs\d{2}|pencilvac|big\s*ball|spot\+scrub|clean\+wash|supersonic)\b",
    re.IGNORECASE,
)

# Header recognisers — order matters; first match wins.
HEADER_RULES: Tuple[Tuple[re.Pattern, str, str, str], ...] = (
    # (regex, category_id, brand, model_root_template_format)
    # Apple iPhone family (with optional suffix and optional sub-suffix)
    (re.compile(r"\biphone\s*(\d{1,2}e?)\s*(pro\s*max|pro|plus|mini|air)?\b", re.IGNORECASE),
     "smartphones", "Apple", "iPhone {1}{2}"),
    (re.compile(r"\bipad\s*(pro|air|mini)?\s*(\d{1,2})?\s*(m\d)?\b", re.IGNORECASE),
     "tablets", "Apple", "iPad {1}{2}{3}"),
    (re.compile(r"\bmacbook\s*(air|pro|neo)?\s*(\d{1,2})?\s*(m\d\s*(?:pro|max|ultra)?)?\b", re.IGNORECASE),
     "laptops", "Apple", "MacBook {1}{2}{3}"),
    (re.compile(r"\bimac\s*(m\d)?\b", re.IGNORECASE),
     "laptops", "Apple", "iMac {1}"),
    (re.compile(r"\bairpods\s*(max\s*\d?|pro\s*\d?|\d)?\b", re.IGNORECASE),
     "accessories", "Apple", "AirPods {1}"),
    (re.compile(r"\b(?:apple\s*)?watch\s*(ultra\s*\d?|se\s*\d?|s\d{1,2}|series\s*\d{1,2})?\b", re.IGNORECASE),
     "accessories", "Apple", "Apple Watch {1}"),
    (re.compile(r"\bgalaxy\s*(s\d{2}\s*ultra|s\d{2}\+|s\d{2}\s*fe|s\d{2}|a\d{2}|z\s*fold\s*\d|z\s*flip\s*\d|tab\s*\w*|buds\s*\w*)?\b", re.IGNORECASE),
     "smartphones", "Samsung", "Galaxy {1}"),
    (re.compile(r"\bsamsung\b\s*(s\d{2}\s*ultra|s\d{2}\+|s\d{2}|a\d{2}|z\s*fold\s*\d|z\s*flip\s*\d)?", re.IGNORECASE),
     "smartphones", "Samsung", "Galaxy {1}"),
    (re.compile(r"\b(s\d{2}\s*ultra|s\d{2}\+|s\d{2}\s*fe|s\d{2}|a\d{2})\b", re.IGNORECASE),
     "smartphones", "Samsung", "Galaxy {1}"),
    (re.compile(r"\b(z\s*fold\s*\d|z\s*flip\s*\d)\b", re.IGNORECASE),
     "smartphones", "Samsung", "Galaxy {1}"),
    (re.compile(r"\bgoogle\s*pixel\s*(\d+\s*pro\s*xl|\d+\s*pro|\d+\s*xl|\d+)?\b|\bpixel\s*(\d+\s*pro\s*xl|\d+\s*pro|\d+\s*xl|\d+)\b", re.IGNORECASE),
     "smartphones", "Google", "Pixel {1}{2}"),
    (re.compile(r"\bxiaomi\b|\bredmi\b", re.IGNORECASE),
     "smartphones", "Xiaomi", "Xiaomi"),
    (re.compile(r"\bpoco\s*([a-z]?\s*\d+\s*[a-z]*)?\b", re.IGNORECASE),
     "smartphones", "Poco", "Poco {1}"),
    (re.compile(r"\bhonor\s*([a-z]?\s*\d+\w*)?\b", re.IGNORECASE),
     "smartphones", "Honor", "Honor {1}"),
    (re.compile(r"\b(?:huawei|nova|pura)\b", re.IGNORECASE),
     "smartphones", "Huawei", "Huawei"),
    (re.compile(r"\bdyson\b\s*(\w+)?", re.IGNORECASE),
     "accessories", "Dyson", "Dyson {1}"),
    (re.compile(r"\b(?:dualsense|dualshock)\s*(?:ps5)?\b", re.IGNORECASE),
     "consoles", "Sony", "PS5 DualShock"),
    (re.compile(r"\b(?:sony\s+)?portal\b|\bps\s*portal\b|\bplaystation\s+portal\b", re.IGNORECASE),
     "consoles", "Sony", "PS5 Portal"),
    (re.compile(r"\bps\s*5\s*(pro|slim|digital(?:\s*edition)?)?\b|\bplaystation\s*5", re.IGNORECASE),
     "consoles", "Sony", "PS5 {1}"),
    (re.compile(r"\bxbox\s*(series\s*[xs]|one)?\b", re.IGNORECASE),
     "consoles", "Microsoft", "Xbox {1}"),
    (re.compile(r"\bnintendo\s*switch\s*(oled|lite)?\b|\bswitch\s*(oled|lite)\b", re.IGNORECASE),
     "consoles", "Nintendo", "Switch {1}{2}"),
    (re.compile(r"\bяндекс\s*станц\w*|\byandex\s*station\b", re.IGNORECASE),
     "accessories", "Yandex", "Яндекс Станция"),
    # Apple peripheral accessories (sold without flag, no SIM)
    (re.compile(r"\b(magic\s+(?:mouse|keyboard|trackpad)|airtag|apple\s*tv|magsafe|pencil|power\s*adapter)\b", re.IGNORECASE),
     "accessories", "Apple", "{1}"),
)


@dataclass
class _Context:
    """Mutable state carried across lines while scanning a post."""

    category: Optional[str] = None
    brand: Optional[str] = None
    model_root: Optional[str] = None
    section_skip: bool = False
    history: List[str] = field(default_factory=list)


def _normalise_line(raw: str) -> str:
    """Collapse internal whitespace and strip."""
    return re.sub(r"\s+", " ", raw).strip()


def _looks_like_meta(line_lower: str) -> bool:
    return any(tok in line_lower for tok in META_TOKENS)


def _has_skip_token(line_lower: str) -> bool:
    return any(tok in line_lower for tok in SKIP_PRODUCT_TOKENS)


def _extract_price(line: str) -> Optional[float]:
    """Return the rightmost / largest plausible price as a float, or None."""
    candidates: List[float] = []
    for match in PRICE_REGEX.finditer(line):
        raw = match.group(1)
        digits = re.sub(r"[\s\.\u202f\xa0]", "", raw)
        if not digits.isdigit():
            continue
        value = int(digits)
        if 1_000 <= value <= 9_999_999:
            candidates.append(float(value))
    if not candidates:
        return None
    return candidates[-1]


def _extract_storage(line: str) -> Optional[str]:
    storage_match = STORAGE_REGEX.search(line)
    if storage_match:
        unit = storage_match.group(2).upper()
        return f"{storage_match.group(1)}{unit}"
    ram_match = STORAGE_RAM_REGEX.search(line)
    if ram_match:
        return f"{ram_match.group(2)}GB"
    return None


def _extract_ram(line: str) -> Optional[str]:
    match = STORAGE_RAM_REGEX.search(line)
    if match:
        return f"{match.group(1)}GB"
    return None


def _extract_color(line: str) -> Optional[str]:
    match = COLOR_REGEX.search(line)
    if not match:
        return None
    raw = match.group(1).strip().lower()
    # Title-case multi-word colours (e.g. "cosmic orange" → "Cosmic Orange").
    return " ".join(word.capitalize() for word in raw.split())


def _fix_top_resale_color(
    color: Optional[str],
    brand: str,
    model: str,
    source_channel: str,
) -> Optional[str]:
    """Top re:sale иногда маркирует Silver как White у iPhone Pro-линейки."""
    if not color:
        return color
    if color.lower() != "white":
        return color
    if (source_channel or "").strip() not in TOP_RESALE_CHANNELS:
        return color
    if (brand or "").lower() != "apple":
        return color
    model_lower = (model or "").lower()
    if "iphone" in model_lower and ("pro max" in model_lower or re.search(r"\bpro\b", model_lower)):
        return "Silver"
    return color


def _extract_sim_type(line: str, flag: Optional[str]) -> Optional[str]:
    explicit = SIM_TYPE_REGEX.search(line)
    if explicit:
        token = re.sub(r"\s+", "", explicit.group(1).lower())
        if token in {"sim+esim", "esim", "2sim", "dualsim"}:
            return "sim+esim" if token == "sim+esim" else (
                "2sim" if token in {"2sim", "dualsim"} else "esim"
            )
    if flag:
        return FLAG_SIM_MAP.get(flag)
    return None


def _extract_flag(line: str) -> Optional[str]:
    match = FLAG_REGEX.search(line)
    return match.group(1) if match else None


def _format_root(template: str, match: re.Match) -> str:
    """Apply numbered groups from a header match to the root template."""
    groups = ["", *(match.groups() or ())]
    out = template
    for idx in range(1, len(groups)):
        token = groups[idx] or ""
        token = re.sub(r"\s+", " ", token).strip()
        # Capitalise short tokens; uppercase chip codes (M1, M2 …) and S/A model codes.
        if re.fullmatch(r"m\d(?:\s*(?:pro|max|ultra))?", token, re.IGNORECASE):
            token = token.upper()
        elif re.fullmatch(r"(s|a)\d{2}.*", token, re.IGNORECASE):
            token = token.upper()
        elif re.fullmatch(r"z\s*(fold|flip)\s*\d", token, re.IGNORECASE):
            token = token.title()
        elif token:
            token = " ".join(w.capitalize() for w in token.split())
        out = out.replace("{" + str(idx) + "}", (" " + token) if token else "")
    return re.sub(r"\s+", " ", out).strip()


def _try_parse_header(line: str) -> Optional[Tuple[str, str, str]]:
    """Detect a section header.  Returns (category, brand, model_root) or None."""
    if PRICE_REGEX.search(line):
        return None
    if FLAG_REGEX.search(line):
        return None
    stripped = line.strip().rstrip(":").strip()
    if not stripped:
        return None
    # Drop trailing parens like "(2024)" or "(M1 Pro, 2021)" so the regex can match.
    candidate = re.sub(r"\s*\([^)]*\)\s*$", "", stripped)
    for pattern, category, brand, template in HEADER_RULES:
        match = pattern.search(candidate)
        if not match:
            continue
        model_root = _format_root(template, match) or stripped
        if model_root.lower() == brand.lower():
            model_root = stripped
        return category, brand, model_root
    # Implicit hints (Russian section titles like "Беспроводные пылесосы" → Dyson).
    for pattern, category, brand in IMPLICIT_BRAND_HINTS:
        if pattern.search(candidate):
            return category, brand, ""
    # Bare Dyson product-line model code (V8, Gen5, HD17 …) used as a section header.
    dyson_match = DYSON_INLINE_REGEX.search(candidate)
    if dyson_match and len(candidate) <= 40:
        token = re.sub(r"\s+", " ", dyson_match.group(1)).strip().upper()
        return "accessories", "Dyson", f"Dyson {token}"
    return None


def _merge_model(ctx: _Context, line: str, category: str, brand: str) -> str:
    """Build a final model name combining context root and line specifics."""
    pieces: List[str] = []
    if ctx.model_root:
        pieces.append(ctx.model_root)

    if not ctx.model_root:
        guess = _guess_inline_model(line, category, brand)
        if guess:
            guess_lower = guess.lower().strip()
            if not STORAGE_REGEX.match(guess_lower) and not STORAGE_RAM_REGEX.match(guess_lower):
                pieces.append(guess)

    return _normalise_line(" ".join(p for p in pieces if p))


def _guess_inline_model(line: str, category: str, brand: str) -> Optional[str]:
    """Try to recognise model directly from a flat line (no header context)."""
    line_lower = line.lower()
    if brand == "Apple" and category == "smartphones":
        match = re.search(
            r"(?:iphone\s*)?\b(\d{1,2}e?)\s*(pro\s*max|pro|plus|mini|air)?\b",
            line_lower,
        )
        if match:
            num = match.group(1)
            suffix = " ".join(w.capitalize() for w in (match.group(2) or "").split())
            return _normalise_line(f"iPhone {num} {suffix}")
    if brand == "Apple" and category == "tablets":
        match = re.search(
            r"\bipad\s*(pro|air|mini)?\s*(\d{1,2})?\s*(m\d)?",
            line_lower,
        )
        if match:
            suffix = " ".join(
                _normalise_line(w).title()
                for w in (match.group(1) or "", match.group(2) or "", match.group(3) or "")
                if w
            )
            return _normalise_line(f"iPad {suffix}")
    if brand == "Apple" and category == "laptops":
        match = re.search(
            r"\bmacbook\s*(air|pro|neo)?\s*(\d{1,2})?\s*(m\d\s*(?:pro|max|ultra)?)?",
            line_lower,
        )
        if match:
            kind = (match.group(1) or "").title()
            size = match.group(2) or ""
            chip = (match.group(3) or "").upper()
            return _normalise_line(f"MacBook {kind} {size} {chip}")
    if brand == "Apple" and category == "accessories":
        if "airpods" in line_lower:
            if "max" in line_lower:
                return _normalise_line("AirPods Max " + _grab_after(line_lower, "max"))
            if "pro 3" in line_lower:
                return "AirPods Pro 3"
            if "pro 2" in line_lower:
                return "AirPods Pro 2"
            if "pro" in line_lower:
                return "AirPods Pro"
            digits = re.search(r"airpods\s*(\d)", line_lower)
            return f"AirPods {digits.group(1)}" if digits else "AirPods"
        if "watch" in line_lower:
            sub = re.search(r"watch\s*(ultra\s*\d?|se\s*\d?|s\d{1,2}|series\s*\d{1,2})", line_lower)
            if sub:
                return _normalise_line("Apple Watch " + sub.group(1).upper())
            return "Apple Watch"
        for token in ("magic mouse", "magic keyboard", "magic trackpad",
                       "apple tv", "airtag", "magsafe", "pencil", "power adapter"):
            if token in line_lower:
                return token.title()
    if brand == "Samsung":
        match = re.search(
            r"(s\d{2}\s*ultra|s\d{2}\+|s\d{2}\s*fe|s\d{2}|a\d{2}|z\s*fold\s*\d|z\s*flip\s*\d)",
            line_lower,
        )
        if match:
            token = match.group(1)
            # Preserve a single space between code and suffix (e.g. "S25 Ultra").
            token = re.sub(r"\s+", " ", token).strip()
            if re.match(r"z\s*(fold|flip)", token):
                token = token.title()
            else:
                token = token.upper()
            return f"Galaxy {token}"
    if brand == "Dyson":
        # Try common Dyson identifiers first (V8, V15 SV47, HD16, Gen5, ...).
        inline = DYSON_INLINE_REGEX.search(line_lower)
        if inline:
            token = re.sub(r"\s+", " ", inline.group(1)).strip()
            return _normalise_line("Dyson " + token.upper())
        match = re.search(r"\bdyson\b\s*([a-z]+)?\s*(\d{2,3})?", line_lower)
        if match:
            return _normalise_line("Dyson " + (match.group(1) or "").upper() + (match.group(2) or ""))
        return "Dyson"
    if brand == "Sony":
        if "dualsense" in line_lower or "dualshock" in line_lower:
            return "PS5 DualShock"
        if (
            "portal" in line_lower
            and not re.search(r"\bps\s*5\s+pro\b|\bplaystation\s*5\s+pro\b", line_lower)
        ):
            return "PS5 Portal"
        if "vr2" in line_lower:
            return "PS5 VR2"
        if "ps5" in line_lower or "playstation" in line_lower:
            if "pro" in line_lower:
                if "digital" in line_lower:
                    return "PS5 Pro Digital"
                return "PS5 Pro"
            if "slim" in line_lower:
                if "digital" in line_lower:
                    return "PS5 Slim Digital"
                if "disk" in line_lower or "disc" in line_lower:
                    return "PS5 Slim Disk"
                return "PS5 Slim"
            if "digital" in line_lower:
                return "PS5 Digital"
            return "PS5"
    if brand == "Microsoft":
        if "series x" in line_lower:
            return "Xbox Series X"
        if "series s" in line_lower:
            return "Xbox Series S"
    if brand == "Google":
        match = re.search(r"pixel\s*(\d+\s*pro\s*xl|\d+\s*pro|\d+\s*xl|\d+)", line_lower)
        if match:
            return f"Pixel {match.group(1).title()}"
    return None


def _grab_after(text: str, marker: str) -> str:
    idx = text.find(marker)
    if idx < 0:
        return ""
    tail = text[idx + len(marker):].strip()
    return tail.split()[0].title() if tail else ""


def _line_brand_hint(line_lower: str) -> Optional[Tuple[str, str]]:
    """Best-effort (category, brand) guess from a single product line."""
    for pattern, category, brand, _ in HEADER_RULES:
        if pattern.search(line_lower):
            return category, brand
    if DYSON_INLINE_REGEX.search(line_lower):
        return "accessories", "Dyson"
    return None


def _stable_id(raw_id: str, fingerprint: str) -> str:
    """Deterministic product id derived from message id + product fingerprint."""
    digest = hashlib.sha1(f"{raw_id}::{fingerprint}".encode("utf-8")).hexdigest()[:16]
    return f"prod_{digest}"


def parse_products(raw_message: RawMessage) -> List[ParsedProduct]:
    """Extract every product from a raw Telegram post.

    The function never raises on parse errors — invalid lines are skipped and the
    rest of the post continues to be processed.
    """
    if not raw_message.text:
        return []

    ctx = _Context()
    products: List[ParsedProduct] = []
    seen: set[str] = set()

    for raw_line in raw_message.text.split("\n"):
        line = _normalise_line(raw_line)
        if not line:
            continue

        if line.startswith("[") and re.match(r"\[\d{2}\.\d{2}\.\d{4}", line):
            stripped_prefix = re.sub(
                r"^\[\d{2}\.\d{2}\.\d{4}\s+\d{1,2}:\d{2}\]\s*[^:]*:\s*",
                "",
                line,
            )
            if stripped_prefix and stripped_prefix != line:
                stripped_prefix = re.sub(
                    r"^\d{1,2}/\d{1,2}/\d{1,4}\s*",
                    "",
                    stripped_prefix,
                ).strip()
                if not stripped_prefix:
                    continue
                line = stripped_prefix
            else:
                continue

        # Strip year-like decorations (e.g. "(2024)", "(M1 Pro, 2021)") that
        # would otherwise confuse the price detector when the line is actually
        # a section header.
        cleaned_for_header = re.sub(r"\s*\([^)]{0,40}\)\s*", " ", line).strip()

        line_lower = line.lower()
        if _looks_like_meta(line_lower):
            continue

        has_price = bool(PRICE_REGEX.search(line))
        has_flag = bool(FLAG_REGEX.search(line))
        # If the only price tokens on the line are inside parentheses (years,
        # SKUs, model codes), treat the line as if it had no price for header
        # purposes.
        header_eligible = not has_flag and (
            not has_price or not PRICE_REGEX.search(cleaned_for_header)
        )
        skip_token = _has_skip_token(line_lower)

        if skip_token and not has_price and not has_flag:
            ctx.section_skip = True
            continue

        if header_eligible:
            header = _try_parse_header(cleaned_for_header)
            if header:
                ctx.category, ctx.brand, ctx.model_root = header
                ctx.section_skip = False
                ctx.history.append(cleaned_for_header)
                continue

        if skip_token:
            continue
        if ctx.section_skip:
            continue

        if not has_price:
            continue

        # Resolve category + brand: prefer header context, fall back to line hint.
        category = ctx.category
        brand = ctx.brand
        if not category or not brand:
            hint = _line_brand_hint(line_lower)
            if hint:
                category, brand = hint
        if not category or not brand:
            continue

        price = _extract_price(line)
        if not price:
            continue

        flag = _extract_flag(line)
        sim_type = _extract_sim_type(line, flag)
        color = _extract_color(line)
        storage = _extract_storage(line)
        ram = _extract_ram(line) if STORAGE_RAM_REGEX.search(line) else None

        model = _merge_model(ctx, line, category, brand)
        if not model:
            continue

        attributes: dict = {}
        if storage:
            attributes["storage"] = storage
        if ram and ram != storage:
            attributes["ram"] = ram
        color = _fix_top_resale_color(color, brand, model, raw_message.channel_id)

        if color:
            attributes["color"] = color
        if sim_type and category == "smartphones":
            attributes["sim_type"] = sim_type
        if flag:
            attributes["flag"] = flag

        fingerprint = "|".join(
            [
                category,
                brand,
                model.lower(),
                f"{price:.0f}",
                attributes.get("storage", ""),
                attributes.get("color", ""),
                attributes.get("sim_type", ""),
                attributes.get("flag", ""),
            ]
        )
        if fingerprint in seen:
            continue
        seen.add(fingerprint)

        product = ParsedProduct(
            id=_stable_id(raw_message.id, fingerprint),
            category_id=category,
            brand=brand,
            model=model,
            price=price,
            source_channel=raw_message.channel_id,
            message_link=f"{raw_message.message_link}#p={len(products)+1}",
            timestamp=raw_message.timestamp,
            attributes=attributes,
            raw_message_id=raw_message.id,
        )
        products.append(product)

    return products
