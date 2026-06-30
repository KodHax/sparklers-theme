import json
import sys

name = sys.argv[1] if len(sys.argv) > 1 else None
if not name:
    print("Uso: python remove_order.py #1351")
    exit(1)

orders = json.load(open('data/orders.json', encoding='utf-8'))
to_remove = next((o for o in orders if o['name'] == name), None)
if to_remove:
    orders = [o for o in orders if o['name'] != name]
    json.dump(orders, open('data/orders.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f'Removida: {name} | Restam: {len(orders)}')
else:
    print(f'Order {name} nao encontrada (ja processada ou nao existe)')
