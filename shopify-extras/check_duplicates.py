#!/usr/bin/env python3
"""
Verifica produtos duplicados na loja destino e opcionalmente apaga os duplicados.

Uso:
  python check_duplicates.py              # Lista duplicados
  python check_duplicates.py --delete     # Apaga duplicados (mantém o mais antigo)
"""
import asyncio
import sys
from collections import defaultdict

from rich.console import Console

from config import DEST, MAX_CONCURRENT
from utils.graphql_client import GraphQLClient

console = Console()

LIST_PRODUCTS = """
query($first: Int!, $cursor: String) {
  products(first: $first, after: $cursor, sortKey: CREATED_AT) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id
        handle
        title
        createdAt
        status
      }
    }
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
        console.print("\n[bold cyan]Fetching all products from destination...[/bold cyan]")
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

        console.print(f"  Total products: {len(products)}")

        by_handle = defaultdict(list)
        for p in products:
            by_handle[p["handle"]].append(p)

        duplicates = {h: prods for h, prods in by_handle.items() if len(prods) > 1}
        unique = len(by_handle)
        dup_count = sum(len(prods) - 1 for prods in duplicates.values())

        console.print(f"  Unique handles: {unique}")
        console.print(f"  Duplicate handles: {len(duplicates)} ({dup_count} extra products)")

        if not duplicates:
            console.print("\n[green]No duplicates found![/green]")
            return

        for handle, prods in list(duplicates.items())[:20]:
            console.print(f"\n  [yellow]{handle}[/yellow] ({len(prods)}x):")
            for p in prods:
                console.print(f"    {p['id']} - {p['createdAt']} - {p['status']}")

        if len(duplicates) > 20:
            console.print(f"\n  ... and {len(duplicates) - 20} more duplicate handles")

        if not delete:
            console.print(f"\n[yellow]Para apagar os {dup_count} duplicados (mantém o mais antigo):[/yellow]")
            console.print("  python check_duplicates.py --delete")
            return

        console.print(f"\n[bold red]Deleting {dup_count} duplicate products...[/bold red]")
        deleted = 0
        errors = 0

        for handle, prods in duplicates.items():
            sorted_prods = sorted(prods, key=lambda p: p["createdAt"])
            to_delete = sorted_prods[1:]

            for p in to_delete:
                try:
                    result = await client.execute(DELETE_PRODUCT, {
                        "input": {"id": p["id"]}
                    })
                    mut = (result.get("data") or {}).get("productDelete") or {}
                    user_errors = mut.get("userErrors", [])

                    if user_errors:
                        console.print(f"  [red]{handle}: {user_errors[0]['message']}[/red]")
                        errors += 1
                    elif mut.get("deletedProductId"):
                        deleted += 1
                    else:
                        errors += 1
                except Exception as e:
                    console.print(f"  [red]{handle}: {e}[/red]")
                    errors += 1

                if (deleted + errors) % 50 == 0 and (deleted + errors) > 0:
                    console.print(f"  Progress: {deleted + errors}/{dup_count}")

        console.print(f"\n  [green]Deleted: {deleted}[/green] | [red]Errors: {errors}[/red]")
        console.print(f"  Remaining products: ~{len(products) - deleted}")


if __name__ == "__main__":
    asyncio.run(run())
