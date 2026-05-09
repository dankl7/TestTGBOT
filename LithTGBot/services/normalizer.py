import re
from thefuzz import fuzz
from schemas.search import NormalizedQueryDTO


class QueryNormalizer:
    def __init__(self):
        # Exact mapping for Russian words
        self.ru_words = {
            "айфон": "iPhone",
            "самсунг": "Samsung",
            "макбук": "MacBook",
            "айпад": "iPad",
            "про": "Pro",
            "pro": "Pro",
            "про макс": "Pro Max",
            "pro max": "Pro Max",
            "ультра": "Ultra",
            "ultra": "Ultra",
            "эйр": "Air",
            "air": "Air",
            "мини": "Mini",
            "mini": "Mini"
        }

        # Targets for fuzzy matching to fix typos
        self.fuzzy_targets = {
            "iphone": "iPhone",
            "samsung": "Samsung",
            "macbook": "MacBook",
            "ipad": "iPad",
            "apple": "Apple",
            "galaxy": "Galaxy"
        }

        # Regex patterns for storage normalization
        self.storage_patterns = [
            (re.compile(r'\b(128|256|512)(?:g|gb|гб)?\b', re.IGNORECASE), r'\1GB'),
            (re.compile(r'\b1(?:t|tb|тб)\b', re.IGNORECASE), r'1TB')
        ]

        # Abbreviations map (Longest must be first to avoid partial replacements)
        self.abbreviations = [
            # iPhone
            (r"\b17\s*pm\b", "iPhone 17 Pro Max"),
            (r"\b17\s*p\b", "iPhone 17 Pro"),
            (r"\b16\s*pm\b", "iPhone 16 Pro Max"),
            (r"\b16\s*p\b", "iPhone 16 Pro"),
            (r"\b15\s*pm\b", "iPhone 15 Pro Max"),
            (r"\b15\s*p\b", "iPhone 15 Pro"),
            (r"\bse3\b", "iPhone SE 3"),
            (r"\bse2\b", "iPhone SE 2"),
            (r"\bse\b", "iPhone SE"),

            # Samsung
            (r"\bs24\s*ultra\b", "Samsung Galaxy S24 Ultra"),
            (r"\bs24\+\b", "Samsung Galaxy S24+"),
            (r"(?<!galaxy\s)\bs24\b", "Samsung Galaxy S24"),
            (r"\bz\s*fold\b", "Samsung Galaxy Z Fold"),
            (r"\bz\s*flip\b", "Samsung Galaxy Z Flip"),
            (r"\ba56\b", "Samsung Galaxy A56"),
            (r"\ba36\b", "Samsung Galaxy A36"),

            # MacBook
            (r"\bmba\b", "MacBook Air"),
            (r"\bmbp\b", "MacBook Pro"),
            (r"\bmb\b", "MacBook"),

            # iPad
            (r"\bipad\s*pro\b", "iPad Pro"),
            (r"\bipad\s*air\b", "iPad Air"),
            (r"\bipad\s*mini\b", "iPad Mini")
        ]

        # Keywords used to determine if a bare number like '17' refers to an Apple model
        self.apple_context_keywords = {
            "p", "pm", "pro", "max", "iphone", "айфон",
            "sim", "esim", "white", "black", "blue", "natural", "titanium"
        }

    def _apply_fuzzy(self, word: str) -> str:
        """
        Applies fuzzy matching to correct misspelled brands and models (e.g., iphoe -> iPhone).
        """
        if word.isdigit() or len(word) < 3:
            return word

        best_match = word
        best_ratio = 0

        for target, replacement in self.fuzzy_targets.items():
            ratio = fuzz.ratio(word.lower(), target)
            if len(target) <= 5:
                if ratio >= 80 and ratio > best_ratio:
                    best_match = replacement
                    best_ratio = ratio
            else:
                if ratio >= 75 and ratio > best_ratio:
                    best_match = replacement
                    best_ratio = ratio

        return best_match if best_ratio > 0 else word

    def _check_apple_context(self, text: str) -> bool:
        """
        Determines whether the query context implies an Apple device.
        Used to prevent false positives like "17 чехол" -> "iPhone 17 чехол".
        """
        # 1. If query is just model + storage, assume it's valid
        temp = text.lower()
        temp = re.sub(r'\b(15|16|17)\b', '', temp)
        temp = re.sub(r'\b(128gb|256gb|512gb|1tb)\b', '', temp)
        temp = temp.replace(" ", "")
        if not temp:
            return True

        # 2. Check for explicit keywords
        words = set(text.lower().split())
        if words.intersection(self.apple_context_keywords):
            return True

        # 3. Check for presence of storage identifiers indicating a device
        if re.search(r'\b\d{3}gb\b|\b1tb\b', text, re.IGNORECASE):
            return True

        return False

    def normalize(self, query: str) -> NormalizedQueryDTO:
        """
        Normalizes a user search query, expanding abbreviations and correcting typos.
        """
        original = query

        # Initial preparation
        text = query.strip().lower()
        text = text.replace('ё', 'е')
        text = re.sub(r'\s+', ' ', text)

        applied_replacements = []

        def record_replacement(from_s: str, to_s: str):
            if from_s.lower() != to_s.lower():
                applied_replacements.append({"from": from_s, "to": to_s})

        # 1. Fuzzy matching to fix misspelled words
        words = text.split()
        fuzzy_words = []
        for w in words:
            fw = self._apply_fuzzy(w)
            if fw != w:
                record_replacement(w, fw)
            fuzzy_words.append(fw)
        text = " ".join(fuzzy_words)

        # 2. Exact RU translations
        # Sort by length descending to replace compound words (e.g. "про макс") first
        for ru_w, en_w in sorted(self.ru_words.items(), key=lambda x: len(x[0]), reverse=True):
            pattern = re.compile(rf'\b{ru_w}\b', re.IGNORECASE)
            matches = pattern.findall(text)
            for m in matches:
                record_replacement(m, en_w)
            text = pattern.sub(en_w, text)

        # 3. Storage normalization
        for pattern, replacement in self.storage_patterns:
            def replacer(match):
                orig = match.group(0)
                new_val = match.expand(replacement)
                record_replacement(orig, new_val)
                return new_val
            text = pattern.sub(replacer, text)

        # 4. Abbreviations expansion
        for pattern, replacement in self.abbreviations:
            matches = re.findall(pattern, text, flags=re.IGNORECASE)
            for m in matches:
                record_replacement(m, replacement)
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

        # 5. Selective normalization for bare iPhone models (15, 16, 17)
        for model in ["15", "16", "17"]:
            # Negative lookbehind to avoid prepending iPhone if it's already there
            pattern = rf'(?<!iphone\s)\b{model}\b'
            matches = re.findall(pattern, text, flags=re.IGNORECASE)
            if matches and self._check_apple_context(text):
                for m in matches:
                    record_replacement(m, f'iPhone {model}')
                text = re.sub(pattern, f'iPhone {model}', text, flags=re.IGNORECASE)

        # Final cleanup
        text = re.sub(r'\s+', ' ', text).strip()
        confidence = 0.95 if applied_replacements else 1.0

        return NormalizedQueryDTO(
            original_query=original,
            normalized_query=text,
            tokens=text.split(),
            applied_replacements=applied_replacements,
            confidence=confidence
        )


normalizer = QueryNormalizer()
