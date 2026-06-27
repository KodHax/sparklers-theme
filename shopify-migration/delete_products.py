#!/usr/bin/env python3
"""
Apaga todos os produtos da loja destino.

Uso:
  python delete_products.py          # Lista quantos produtos existem
  python delete_products.py --delete # Apaga todos os produtos
"""
import asyncio
import sys

from rich.console import Console

from config import DEST, MAX_CONCURRENT
from utils.graphql_client import GraphQLClient

console = Console()

LIST_PRODUCTS = """
query($first: Int!, $cursor: String) {
  products(first: $first, after: $cursor, sortKey: CREATED_AT) {
    pageInfo { hasNextPage endCursor }
    edges { node { id title handle } }
  }
}
"""

DELETE_PRODUCT = """
mutation productDelete($input: ProductDeleteInput!) {
  productDelete(input: $input) {
    deletedProductId
    userErrors { field message }
  }
}
"""


async def run():
    delete = "--delete" in sys.argv

    async with GraphQLClient(DEST, MAX_CONCURRENT) as client:
        console.print("\n[bold cyan]Fetching products from destination...[/bold cyan]")
        products = []
        cursor = None

        while True:
            result = await client.execute(LIST_PRODUCTS, {"first": 50, "cursor": cursor})
            data = (result.get("data") or {}).get("products") or {}
            edges = data.get("edges", [])
            products.extend([e["node"] for e in edges])

            page_info = data.get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")

            if len(products) % 200 == 0:
                console.print(f"  Fetched {len(products)}...", end="\r")

        console.print(f"  Found {len(products)} products")

        if not delete:
            for p in products[:10]:
                console.print(f"    {p.get('handle', '')} - {p.get('title', '')}")
            if len(products) > 10:
                console.print(f"    ... e mais {len(products) - 10}")
            console.print("\n[yellow]Para apagar, corre:[/yellow]")
            console.print("  python delete_products.py --delete")
            return

        console.print(f"\n[bold red]Deleting {len(products)} products...[/bold red]")
        deleted = 0
        errors = 0

        for p in products:
            pid = p["id"]
            label = p.get("handle", pid)

            try:
                result = await client.execute(DELETE_PRODUCT, {"input": {"id": pid}})
                mut = (result.get("data") or {}).get("productDelete") or {}
                user_errors = mut.get("userErrors", [])

                if user_errors:
                    console.print(f"  [red]{label}: {user_errors[0]['message']}[/red]")
                    errors += 1
                elif mut.get("deletedProductId"):
                    deleted += 1
                else:
                    console.print(f"  [red]{label}: Unknown error[/red]")
                    errors += 1
            except Exception as e:
                console.print(f"  [red]{label}: {e}[/red]")
                errors += 1

            if (deleted + errors) % 50 == 0 and (deleted + errors) > 0:
                console.print(f"  Progress: {deleted + errors}/{len(products)}")

        console.print(f"\n  [green]Deleted: {deleted}[/green] | [red]Errors: {errors}[/red]")


if __name__ == "__main__":
    asyncio.run(run())
