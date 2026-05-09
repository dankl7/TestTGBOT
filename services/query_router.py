import re
from typing import Dict, Any, Optional

from schemas.search import ProductSearchRequest


class QueryRouter:
    def route(self, normalized_query: str, limit: int = 10, offset: int = 0) -> ProductSearchRequest:
        category_id: Optional[str] = None
        brand: Optional[str] = None
        min_price: Optional[float] = None
        max_price: Optional[float] = None
        attributes: Dict[str, Any] = {}

        query_text = normalized_query

        # Извлечение максимальной цены ("до 90000", "до 90 000")
        max_price_match = re.search(r'\bдо\s+(\d+(?:[\s\.,_]\d+)*)\b', query_text, re.IGNORECASE)
        if max_price_match:
            try:
                max_price = float(re.sub(r'[\s\.,_]', '', max_price_match.group(1)))
                query_text = query_text[:max_price_match.start()] + query_text[max_price_match.end():]
            except ValueError:
                pass

        # Извлечение минимальной цены ("от 50000", "от 50 000")
        min_price_match = re.search(r'\bот\s+(\d+(?:[\s\.,_]\d+)*)\b', query_text, re.IGNORECASE)
        if min_price_match:
            try:
                min_price = float(re.sub(r'[\s\.,_]', '', min_price_match.group(1)))
                query_text = query_text[:min_price_match.start()] + query_text[min_price_match.end():]
            except ValueError:
                pass

        # Извлечение процессора (например, M1, M2 Pro, M3 Max)
        processor_match = re.search(r'\b(M[1-4](?:\s+(?:Pro|Max|Ultra))?)\b', query_text, re.IGNORECASE)
        if processor_match:
            # Нормализуем пробелы и регистр
            proc_val = " ".join([p.capitalize() if len(p) > 2 else p.upper() for p in processor_match.group(1).split()])
            attributes['processor'] = proc_val
            query_text = query_text[:processor_match.start()] + query_text[processor_match.end():]

        tokens = query_text.split()
        model_tokens = []

        for token in tokens:
            # Память (128GB, 1TB)
            if bool(re.match(r'^\d+(GB|TB)$', token, re.IGNORECASE)):
                attributes['storage'] = token.upper()
            # Связь (Cellular, Wi-Fi)
            elif token.lower() in ["cellular", "wi-fi", "wifi"]:
                attributes['connectivity'] = "Cellular" if token.lower() == "cellular" else "Wi-Fi"
            # Тип SIM
            elif token.lower() in ["sim+esim", "esim", "physical"]:
                if token.lower() == "physical":
                    attributes['sim_type'] = "Physical"
                elif token.lower() == "sim+esim":
                    attributes['sim_type'] = "SIM+ESIM"
                elif token.lower() == "esim":
                    attributes['sim_type'] = "ESIM"
            else:
                model_tokens.append(token)

        model_str = " ".join(model_tokens).strip()
        model_str_lower = model_str.lower()

        # Определение категории и бренда на основе названия модели
        if "iphone" in model_str_lower:
            brand = "Apple"
            category_id = "smartphones"
        elif "samsung" in model_str_lower:
            brand = "Samsung"
            category_id = "smartphones"
        elif "macbook" in model_str_lower:
            brand = "Apple"
            category_id = "laptops"
        elif "ipad" in model_str_lower:
            brand = "Apple"
            category_id = "tablets"

        return ProductSearchRequest(
            category_id=category_id,
            brand=brand,
            model=model_str if model_str else None,
            min_price=min_price,
            max_price=max_price,
            attributes=attributes if attributes else None,
            limit=limit,
            offset=offset
        )


query_router = QueryRouter()
