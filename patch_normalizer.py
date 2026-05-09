import re

with open('services/normalizer.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix double replacement for Samsung by adding negative lookbehind
content = content.replace(r'(r"\bs24\b", "Samsung Galaxy S24"),', r'(r"(?<!galaxy\s)\bs24\b", "Samsung Galaxy S24"),')

# Wait, iPhone 17 Pro Max has 17 which could be replaced again if not careful?
# The bare iPhone rule already has: pattern = rf'(?<!iphone\s)\b{model}\b'

# Fix `17 pro` to become `iPhone 17 Pro`
# Actually, the problem is `pro` is not capitalized. 
# In `ru_words`, "про" -> "Pro". If the user types "pro", it stays "pro".
# Let's just add English words to fuzzy_targets or ru_words to capitalize them, 
# OR just add them to `ru_words` mapping? "pro": "Pro", "max": "Max", "ultra": "Ultra"

content = content.replace('"про": "Pro",', '"про": "Pro",\n            "pro": "Pro",')
content = content.replace('"про макс": "Pro Max",', '"про макс": "Pro Max",\n            "pro max": "Pro Max",')
content = content.replace('"ультра": "Ultra",', '"ультра": "Ultra",\n            "ultra": "Ultra",')
content = content.replace('"эйр": "Air",', '"эйр": "Air",\n            "air": "Air",')
content = content.replace('"мини": "Mini"', '"мини": "Mini",\n            "mini": "Mini"')


with open('services/normalizer.py', 'w', encoding='utf-8') as f:
    f.write(content)
