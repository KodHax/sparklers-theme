#!/usr/bin/env python3
"""
Reordena os produtos dentro de cada coleção na loja destino
para corresponder à ordem da loja origem.

Uso:
  python reorder_collections.py              # Mostra coleções e contagens
  python reorder_collections.py --apply      # Aplica a ordem
"""
import asyncio
import sys

from rich.console import Console

from config import SOURCE, DEST, MAX_CONCURRENT
from utils.graphql_client import GraphQLClient
from utils.state import StateManager

console = Console()

LIST_COLLECTIONS = """
query($first: Int!, $cursor: String) {
  collections(first: $first, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id
        handle
        title
        productsCount { count }
      }
    }
  }
}
"""

COLLECTION_PRODUCTS = """
query($id: ID!, $first: Int!, $cursor: String) {
  collection(id: $id) {
    products(first: $first, after: $cursor, sortKey: COLLECTION_DEFAULT) {
      pageInfo { hasNextPage endCursor }
      edges {
        node { id handle }
      }
    }
  }
}
"""

COLLECTION_REORDER = """
mutation collectionReorderProducts($id: ID!, $moves: [MoveInput!]!) {
  collectionReorderProducts(id: $id, moves: $moves) {
    job { id }
    userErrors { field message }
  }
}
"""


async def _fetch_collection_products(client, collection_id):
    products = []
    cursor = None
    while True:
        result = await client.execute(COLLECTION_PRODUCTS, {
            "id": collection_id, "first": 50, "cursor": cursor,
        })
        data = ((result.get("data") or {}).get("collection") or {}).get("products") or {}
        edges = data.get("edges", [])
        products.extend([e["node"] for e in edges])
        page_info = data.get("pageInfo", {})
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")
    return products


async def _fetch_all_collections(client):
    collections = []
    cursor = None
    while True:
        result = await client.execute(LIST_COLLECTIONS, {"first": 50, "cursor": cursor})
        data = (result.get("data") or {}).get("collections") or {}
        edges = data.get("edges", [])
        collections.extend([e["node"] for e in edges])
        page_info = data.get("pageInfo", {})
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")
    return collections


async def run():
    apply = "--apply" in sys.argv

    console.print("\n[bold cyan]Fetching collections from SOURCE...[/bold cyan]")
    async with GraphQLClient(SOURCE, MAX_CONCURRENT) as source_client:
        source_collections = await _fetch_all_collections(source_client)
        console.print(f"  Found {len(source_collections)} collections in source")

        source_order = {}
        for coll in source_collections:
            products = await _fetch_collection_products(source_client, coll["id"])
            handle_order = [p["handle"] for p in products]
            source_order[coll["handle"]] = handle_order
            console.print(f"  {coll['handle']}: {len(handle_order)} products")

    console.print(f"\n[bold cyan]Fetching collections from DESTINATION...[/bold cyan]")
    async with GraphQLClient(DEST, MAX_CONCURRENT) as dest_client:
        dest_collections = await _fetch_all_collections(dest_client)
        console.print(f"  Found {len(dest_collections)} collections in destination")

        dest_by_handle = {c["handle"]: c for c in dest_collections}

        matched = 0
        for handle, order in source_order.items():
            if handle in dest_by_handle:
                matched += 1

        console.print(f"  Matched: {matched}/{len(source_order)} collections")

        if not apply:
            console.print(f"\n[yellow]Para aplicar a ordem:[/yellow]")
            console.print("  python reorder_collections.py --apply")
            return

        console.print(f"\n[bold green]Reordering products in collections...[/bold green]")
        reordered = 0
        errors = 0

        for handle, source_handles in source_order.items():
            dest_coll = dest_by_handle.get(handle)
            if not dest_coll or not source_handles:
                continue

            dest_products = await _fetch_collection_products(dest_client, dest_coll["id"])
            dest_by_prod_handle = {p["handle"]: p["id"] for p in dest_products}

            moves = []
            for position, prod_handle in enumerate(source_handles):
                prod_id = dest_by_prod_handle.get(prod_handle)
                if prod_id:
                    moves.append({
                        "id": prod_id,
                        "newPosition": str(position),
                    })

            if not moves:
                continue

            batch_size = 50
            for i in range(0, len(moves), batch_size):
                batch = moves[i:i + batch_size]
                try:
                    result = await dest_client.execute(COLLECTION_REORDER, {
                        "id": dest_coll["id"],
                        "moves": batch,
                    })
                    mut = (result.get("data") or {}).get("collectionReorderProducts") or {}
                    user_errors = mut.get("userErrors", [])
                    if user_errors:
                        console.print(f"  [red]{handle}: {user_errors[0]['message']}[/red]")
                        errors += 1
                    else:
                        reordered += 1
                except Exception as e:
                    console.print(f"  [red]{handle}: {e}[/red]")
                    errors += 1

            console.print(f"  [green]{handle}: {len(moves)} products reordered[/green]")

        console.print(f"\n  [green]Reordered: {reordered}[/green] | [red]Errors: {errors}[/red]")


if __name__ == "__main__":
    asyncio.run(run())
