"""Data Normalizer Service - Standardizes product data before DB insertion"""
import re
from typing import Optional
from common.models import ParsedProduct

NO_SIM_CATEGORIES = {'accessories', 'tablets', 'laptops', 'computers', 'consoles'}
NO_SIM_BRANDS = {'dyson', 'sony'}
VALID_SIM_TYPES = {'esim', 'sim+esim', '2sim', 'dual-sim'}
STORAGE_RE = re.compile(r'(\d+)\s*(gb|tb|mb)', re.IGNORECASE)
COLOR_MAP = {
    'spacegray': 'space gray', 'spaceblack': 'space black', 'rosegold': 'rose gold',
    'skyblue': 'sky blue', 'midnightgreen': 'midnight green', 'olivegreen': 'olive',
    'graphitegray': 'graphite', 'lavander': 'lavender', 'mistblue': 'mist blue',
    'jetblack': 'jet black', 'cosmic orange': 'orange', 'deep blue': 'blue',
}
CATEGORY_REMAP = {
    'computers': 'laptops',
}

CONSOLE_MODEL_MAP = {
    'dualsense': 'PS5 DualShock',
    'dualshock': 'PS5 DualShock',
    'sony portal': 'PS5 Portal',
    'portal': 'PS5 Portal',
}

PS5_PORTAL_STORAGE_ONLY_RE = re.compile(r'^ps5\s+(128gb|256gb|512gb|1tb)$', re.IGNORECASE)

COLOR_ABBREVIATIONS = {
    'blk': 'black', 'wht': 'white', 'blu': 'blue', 'slv': 'silver',
    'gld': 'gold', 'grn': 'green', 'rd': 'red', 'pnk': 'pink',
    'gry': 'gray', 'prp': 'purple', 'org': 'orange', 'ylw': 'yellow',
}

TOP_RESALE_CHANNELS = {'1963407298', '-1001963407298'}


def _is_iphone_pro_family(model: str) -> bool:
    model_lower = (model or '').lower()
    return 'iphone' in model_lower and ('pro max' in model_lower or re.search(r'\bpro\b', model_lower) is not None)


class NormalizerService:
    @staticmethod
    def normalize_product(product: ParsedProduct) -> ParsedProduct:
        """Normalize product attributes"""
        if product.category_id in CATEGORY_REMAP:
            product.category_id = CATEGORY_REMAP[product.category_id]

        portal_storage_only = (
            product.brand.lower() == 'sony'
            and product.category_id == 'consoles'
            and (product.model or '').strip().lower() == 'ps5'
            and str((product.attributes or {}).get('storage') or '').upper() in {'128GB', '256GB', '512GB', '1TB'}
        )

        clean_attrs = {}
        for key, value in product.attributes.items():
            if key == 'sim_type':
                if product.category_id not in NO_SIM_CATEGORIES and product.brand.lower() not in NO_SIM_BRANDS:
                    if value in VALID_SIM_TYPES:
                        clean_attrs['sim_type'] = value
            elif key == 'storage':
                normalized = NormalizerService.normalize_storage(value)
                if normalized:
                    clean_attrs['storage'] = normalized
            elif key == 'color':
                normalized = NormalizerService._normalize_color(
                    value,
                    brand=product.brand,
                    model=product.model,
                    source_channel=product.source_channel,
                )
                if normalized:
                    clean_attrs['color'] = normalized
            elif key == 'flag':
                clean_attrs['flag'] = value
            else:
                clean_attrs[key] = value

        product.attributes = clean_attrs
        product.model = NormalizerService._normalize_model(product.model, product.brand, product.category_id)
        if portal_storage_only and product.model == 'PS5':
            product.model = 'PS5 Portal'
        return product

    @staticmethod
    def normalize_storage(storage: str) -> Optional[str]:
        """Normalize storage to standard format (e.g., '256GB', '1TB')"""
        if not storage:
            return None
        storage_upper = storage.upper().strip()
        if re.match(r'^\d+(GB|TB)$', storage_upper):
            return storage_upper
        match = STORAGE_RE.search(storage_upper)
        if match:
            value, unit = match.group(1), match.group(2).upper()
            if unit in {'GB', 'TB'}:
                return f"{value}{unit}"
        if storage.isdigit():
            return f"{storage}GB"
        return None

    @staticmethod
    def _normalize_color(
        color: str,
        brand: Optional[str] = None,
        model: Optional[str] = None,
        source_channel: Optional[str] = None,
    ) -> Optional[str]:
        """Normalize color name"""
        if not color:
            return None
        color_lower = color.lower().strip()
        channel = (source_channel or '').strip()
        model_lower = (model or '').lower()
        brand_lower = (brand or '').lower()
        if (
            color_lower == 'white'
            and channel in TOP_RESALE_CHANNELS
            and brand_lower == 'apple'
            and _is_iphone_pro_family(model or '')
        ):
            color_lower = 'silver'
        normalized = COLOR_MAP.get(color_lower, color)
        normalized = COLOR_ABBREVIATIONS.get(normalized.lower().strip(), normalized)
        return normalized.title()

    @staticmethod
    def _normalize_model(model: str, brand: str, category_id: str) -> str:
        """Normalize model name — strip storage/RAM suffixes, fix casing."""
        if not model:
            return "Unknown"
        model = re.sub(r'\s*None\s*', ' ', model).strip()
        model = re.sub(r'\s+', ' ', model).strip()
        model = re.sub(r'[\s\-]+$', '', model)

        if brand.lower() == 'sony' and category_id == 'consoles' and PS5_PORTAL_STORAGE_ONLY_RE.match(model):
            return 'PS5 Portal'

        model = re.sub(r'\s+\d+/\d+(?:GB|TB)$', '', model, flags=re.IGNORECASE)
        model = re.sub(r'\s+\d+(?:GB|TB)$', '', model, flags=re.IGNORECASE)
        model = model.strip()

        if brand.lower() == 'apple':
            model = re.sub(r'\biphone\b', 'iPhone', model, flags=re.IGNORECASE)
            model = re.sub(r'\bipad\b', 'iPad', model, flags=re.IGNORECASE)
            model = re.sub(r'\bmacbook\b', 'MacBook', model, flags=re.IGNORECASE)
            model = re.sub(r'\bairpods\b', 'AirPods', model, flags=re.IGNORECASE)
            model = re.sub(r'\bwatch\b', 'Watch', model, flags=re.IGNORECASE)
            model = re.sub(r'\bimac\b', 'iMac', model, flags=re.IGNORECASE)
        elif brand.lower() == 'samsung':
            model = re.sub(r'\bs\d+\s*ultra\b', lambda m: m.group(0).upper().replace('ULTRA', 'Ultra'), model, flags=re.IGNORECASE)
            model = re.sub(r'\bs\d+\+\b', lambda m: m.group(0).upper(), model, flags=re.IGNORECASE)
        elif brand.lower() == 'sony' and category_id == 'consoles':
            model_lower = model.lower().strip()
            if PS5_PORTAL_STORAGE_ONLY_RE.match(model):
                return 'PS5 Portal'
            if model_lower in CONSOLE_MODEL_MAP:
                return CONSOLE_MODEL_MAP[model_lower]
            if 'dualsense' in model_lower or 'dualshock' in model_lower:
                return 'PS5 DualShock'
            if 'portal' in model_lower:
                return 'PS5 Portal'
            if 'ps5 pro' in model_lower and 'digital' in model_lower:
                return 'PS5 Pro Digital'
            if 'ps5 slim' in model_lower and 'digital' in model_lower:
                return 'PS5 Slim Digital'
            if 'ps5 slim' in model_lower and ('disk' in model_lower or 'disc' in model_lower):
                return 'PS5 Slim Disk'
            if 'ps5 vr2' in model_lower:
                return 'PS5 VR2'
            model = re.sub(r'\bplaystation\b', 'PS5', model, flags=re.IGNORECASE)
            model = re.sub(r'\bps5\s+ps5\b', 'PS5', model, flags=re.IGNORECASE)
            model = re.sub(r'\s+', ' ', model).strip()

        return model if model else "Unknown"
