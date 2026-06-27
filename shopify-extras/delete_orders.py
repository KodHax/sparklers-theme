#!/usr/bin/env python3
"""
Apaga todas as encomendas da loja destino.
Usa GraphQL para listar e cancelar, REST API para apagar (GraphQL não tem orderDelete).

Uso:
  python delete_orders.py          # Lista quantas encomendas existem
  python delete_orders.py --delete # Apaga todas as encomendas
"""
import asyncio
import sys

import httpx
from rich.console import Console

from config import DEST, MAX_CONCURRENT
from utils.graphql_client import GraphQLClient

console = Console()

LIST_ORDERS = """
query($first: Int!, $cursor: String) {
  orders(first: $first, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    edges { node { id name } }
  }
}
"""

CANCEL_ORDER = """
mutation orderCancel($orderId: ID!, $reason: OrderCancelReason!, $refund: Boolean!, $restock: Boolean!) {
  orderCancel(orderId: $orderId, reason: $reason, refund: $refund, restock: $restock) {
    orderCancelUserErrors { field message }
  }
}
"""


def _gid_to_rest_id(gid: str) -> str:
    return gid.split("/")[-1]


async def run():
    delete = "--delete" in sys.argv

    async with GraphQLClient(DEST, MAX_CONCURRENT) as client:
        console.print("\n[bold cyan]Fetching orders from destination...[/bold cyan]")
        orders = []
        cursor = None

        while True:
            result = await client.execute(LIST_ORDERS, {"first": 50, "cursor": cursor})
            data = (result.get("data") or {}).get("orders") or {}
            edges = data.get("edges", [])
            orders.extend([e["node"] for e in edges])

            page_info = data.get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")

        console.print(f"  Found {len(orders)} orders")

        if not delete:
            for o in orders[:10]:
                console.print(f"    {o.get('name', o['id'])}")
            if len(orders) > 10:
                console.print(f"    ... e mais {len(orders) - 10}")
            console.print("\n[yellow]Para apagar, corre:[/yellow]")
            console.print("  python delete_orders.py --delete")
            return

        console.print(f"\n[bold red]Deleting {len(orders)} orders...[/bold red]")
        deleted = 0
        errors = 0

        rest_headers = {
            "X-Shopify-Access-Token": DEST.access_token,
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(headers=rest_headers, timeout=30.0) as rest:
            for order in orders:
                oid = order["id"]
                name = order.get("name", oid)
                rest_id = _gid_to_rest_id(oid)

                try:
                    await client.execute(CANCEL_ORDER, {
                        "orderId": oid,
                        "reason": "OTHER",
                        "refund": False,
                        "restock": False,
                    })
                except Exception:
                    pass

                try:
                    resp = await rest.delete(f"{DEST.rest_url}/orders/{rest_id}.json")
                    if resp.status_code == 200:
                        deleted += 1
                    else:
                        console.print(f"  [red]{name}: HTTP {resp.status_code} - {resp.text[:200]}[/red]")
                        errors += 1
                except Exception as e:
                    console.print(f"  [red]{name}: {e}[/red]")
                    errors += 1

                if (deleted + errors) % 20 == 0 and (deleted + errors) > 0:
                    console.print(f"  Progress: {deleted + errors}/{len(orders)}")

        console.print(f"\n  [green]Deleted: {deleted}[/green] | [red]Errors: {errors}[/red]")


if __name__ == "__main__":
    asyncio.run(run())
