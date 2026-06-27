#!/usr/bin/env python3
"""
Apaga todos os clientes da loja destino.

Uso:
  python delete_customers.py          # Lista quantos clientes existem
  python delete_customers.py --delete # Apaga todos os clientes
"""
import asyncio
import sys

from rich.console import Console

from config import DEST, MAX_CONCURRENT
from utils.graphql_client import GraphQLClient

console = Console()

LIST_CUSTOMERS = """
query($first: Int!, $cursor: String) {
  customers(first: $first, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    edges { node { id email firstName lastName } }
  }
}
"""

DELETE_CUSTOMER = """
mutation customerDelete($id: ID!) {
  customerDelete(input: {id: $id}) {
    deletedCustomerId
    userErrors { field message }
  }
}
"""


async def run():
    delete = "--delete" in sys.argv

    async with GraphQLClient(DEST, MAX_CONCURRENT) as client:
        console.print("\n[bold cyan]Fetching customers from destination...[/bold cyan]")
        customers = []
        cursor = None

        while True:
            result = await client.execute(LIST_CUSTOMERS, {"first": 50, "cursor": cursor})
            data = (result.get("data") or {}).get("customers") or {}
            edges = data.get("edges", [])
            customers.extend([e["node"] for e in edges])

            page_info = data.get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")

        console.print(f"  Found {len(customers)} customers")

        if not delete:
            for c in customers[:10]:
                console.print(f"    {c.get('email', 'N/A')} - {c.get('firstName', '')} {c.get('lastName', '')}")
            if len(customers) > 10:
                console.print(f"    ... e mais {len(customers) - 10}")
            console.print("\n[yellow]Para apagar, corre:[/yellow]")
            console.print("  python delete_customers.py --delete")
            return

        console.print(f"\n[bold red]Deleting {len(customers)} customers...[/bold red]")
        deleted = 0
        errors = 0

        for cust in customers:
            cid = cust["id"]
            label = cust.get("email") or cid

            try:
                result = await client.execute(DELETE_CUSTOMER, {"id": cid})
                mut = (result.get("data") or {}).get("customerDelete") or {}
                user_errors = mut.get("userErrors", [])

                if user_errors:
                    console.print(f"  [red]{label}: {user_errors[0]['message']}[/red]")
                    errors += 1
                elif mut.get("deletedCustomerId"):
                    deleted += 1
                else:
                    console.print(f"  [red]{label}: Unknown error[/red]")
                    errors += 1
            except Exception as e:
                console.print(f"  [red]{label}: {e}[/red]")
                errors += 1

            if (deleted + errors) % 20 == 0:
                console.print(f"  Progress: {deleted + errors}/{len(customers)}")

        console.print(f"\n  [green]Deleted: {deleted}[/green] | [red]Errors: {errors}[/red]")


if __name__ == "__main__":
    asyncio.run(run())
