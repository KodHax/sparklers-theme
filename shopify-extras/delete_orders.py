#!/usr/bin/env python3
"""
Apaga todas as encomendas da loja destino.

Uso:
  python delete_orders.py          # Lista quantas encomendas existem
  python delete_orders.py --delete # Apaga todas as encomendas
"""
import asyncio
import sys

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

DELETE_ORDER = """
mutation orderDelete($orderId: ID!) {
  orderDelete(input: {id: $orderId}) {
    deletedOrderId
    userErrors { field message }
  }
}
"""


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
            console.print("\n[yellow]Para apagar, corre:[/yellow]")
            console.print("  python delete_orders.py --delete")
            return

        console.print(f"\n[bold red]Deleting {len(orders)} orders...[/bold red]")
        deleted = 0
        errors = 0

        for order in orders:
            oid = order["id"]
            name = order.get("name", oid)

            try:
                cancel_result = await client.execute(CANCEL_ORDER, {
                    "orderId": oid,
                    "reason": "OTHER",
                    "refund": False,
                    "restock": False,
                })
            except Exception:
                pass

            try:
                result = await client.execute(DELETE_ORDER, {"orderId": oid})
                mut = (result.get("data") or {}).get("orderDelete") or {}
                user_errors = mut.get("userErrors", [])

                if user_errors:
                    console.print(f"  [red]{name}: {user_errors[0]['message']}[/red]")
                    errors += 1
                elif mut.get("deletedOrderId"):
                    deleted += 1
                else:
                    console.print(f"  [red]{name}: Unknown error[/red]")
                    errors += 1
            except Exception as e:
                console.print(f"  [red]{name}: {e}[/red]")
                errors += 1

            if (deleted + errors) % 20 == 0:
                console.print(f"  Progress: {deleted + errors}/{len(orders)}")

        console.print(f"\n  [green]Deleted: {deleted}[/green] | [red]Errors: {errors}[/red]")


if __name__ == "__main__":
    asyncio.run(run())
