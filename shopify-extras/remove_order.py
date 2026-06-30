import json

orders = json.load(open('data/orders.json', encoding='utf-8'))
to_remove = next((o for o in orders if o['name'] == '#1265'), None)
if to_remove:
    orders = [o for o in orders if o['name'] != '#1265']
    json.dump(orders, open('data/orders.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f'Removida: #1265 | Restam: {len(orders)}')
else:
    print('Order #1265 nao encontrada (ja processada?)')
