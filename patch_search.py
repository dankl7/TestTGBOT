import sys

with open('bot/handlers/search.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace("query = message.text.strip()", "query = message.text.strip() if message.text else ''")

with open('bot/handlers/search.py', 'w', encoding='utf-8') as f:
    f.write(content)
