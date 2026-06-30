import json
import sys

start_name = sys.argv[1] if len(sys.argv) > 1 else None
if not start_name:
    print("Uso: python trim_orders.py #1373")
    exit(1)

orders = json.load(open('data/orders.json', encoding='utf-8'))
idx = next((i for i, o in enumerate(orders) if o['name'] == start_name), None)
if idx is None:
    print(f"Order {start_name} nao encontrada no ficheiro.")
    exit(1)

trimmed = orders[idx:]
json.dump(trimmed, open('data/orders.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print(f"Removidas {idx} orders do inicio.")
print(f"Restam: {len(trimmed)} orders ({trimmed[0]['name']} ate {trimmed[-1]['name']})")
