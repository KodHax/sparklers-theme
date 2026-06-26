#!/usr/bin/env python3
"""
Apaga tokens OAuth em cache para forçar re-autenticação com novos scopes.
Uso: python reauth.py
"""
from config import SOURCE, DEST
from utils.oauth import invalidate_cached_token

print("Invalidando tokens em cache...\n")

for label, config in [("SOURCE", SOURCE), ("DEST", DEST)]:
    shop_url = config.shop_url
    print(f"  {label}: {shop_url}")
    invalidate_cached_token(shop_url)

print("\nTokens apagados. Na próxima execução, o OAuth vai pedir nova autorização.")
print("Certifica-te que a App tem os scopes corretos no Partners Dashboard.")
