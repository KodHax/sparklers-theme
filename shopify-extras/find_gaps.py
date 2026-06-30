import json

orders = json.load(open('data/orders.json', encoding='utf-8'))
names = [int(o['name'].replace('#', '')) for o in orders]

gaps = []
for i in range(len(names) - 1):
    if names[i + 1] != names[i] + 1:
        gaps.append((names[i], names[i + 1]))

if gaps:
    for a, b in gaps:
        print(f'Buraco entre #{a} e #{b}')
else:
    print('Sem buracos — sequencia continua')

print(f'\nPrimeira: #{names[0]} | Ultima: #{names[-1]} | Total: {len(names)}')
