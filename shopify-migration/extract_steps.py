#!/usr/bin/env python3
"""
Fase 1: Extração em 3 fluxos independentes e leves.
- Query 1: Estrutura comercial, variantes e imagens -> produtos_base.json
- Query 2: Mapeamento de coleções -> mapa_colecoes.json
- Query 3: SEO e metafields -> produtos_meta_seo.json

Uso:
  python extract_steps.py all       # Corre as 3 queries
  python extract_steps.py base      # Só Query 1
  python extract_steps.py colecoes  # Só Query 2
  python extract_steps.py meta      # Só Query 3
"""
import asyncio
import json
import os
import sys

from rich.console import Console

from config import SOURCE, DATA_DIR, MAX_CONCURRENT
from utils.graphql_client import GraphQLClient

console = Console()

# ─── QUERY 1: Produtos Base ───

PRODUCTS_BASE_QUERY = """
query getProductsBase($first: Int!, $cursor: String) {
  products(first: $first, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id
        title
        handle
        descriptionHtml
        vendor
        productType
        status
        tags
        templateSuffix
        images(first: 10) {
          edges { node { url altText } }
        }
        variants(first: 30) {
          edges {
            node {
              id
              title
              price
              compareAtPrice
              sku
              barcode
              selectedOptions { name value }
              inventoryItem {
                id
                tracked
                measurement { weight { value unit } }
              }
            }
          }
        }
        options { name values }
      }
    }
  }
}
"""

# ─── QUERY 2: Coleções ───

COLLECTIONS_MAP_QUERY = """
query getCollectionsMap($first: Int!, $cursor: String) {
  collections(first: $first, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id
        title
        handle
        descriptionHtml
        sortOrder
        seo { title description }
        image { url altText }
        ruleSet {
          appliedDisjunctively
          rules { column relation condition }
        }
        products(first: 250) {
          edges { node { handle } }
        }
      }
    }
  }
}
"""

COLLECTION_PRODUCTS_NEXT = """
query($collectionId: ID!, $first: Int!, $cursor: String) {
  collection(id: $collectionId) {
    products(first: $first, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      edges { node { handle } }
    }
  }
}
"""

# ─── QUERY 3: SEO + Metafields ───

PRODUCTS_META_SEO_QUERY = """
query getProductsMetaAndSEO($first: Int!, $cursor: String) {
  products(first: $first, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        handle
        seo { title description }
        metafields(first: 60) {
          edges { node { namespace key value type } }
        }
      }
    }
  }
}
"""

# ─── METAFIELD DEFINITIONS ───

METAFIELD_DEFINITIONS_QUERY = """
query($ownerType: MetafieldOwnerType!, $cursor: String) {
  metafieldDefinitions(ownerType: $ownerType, first: 100, after: $cursor) {
    edges {
      cursor
      node {
        namespace key name
        type { name }
        description
        ownerType
        validations { name value }
      }
    }
    pageInfo { hasNextPage }
  }
}
"""


def _save(filename: str, data):
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    count = len(data) if isinstance(data, list) else "ok"
    console.print(f"  [green]Saved {path} ({count})[/green]")


async def _paginate_endcursor(
    client: GraphQLClient,
    query: str,
    path: list[str],
    first: int = 50,
    total_estimate: int = 55000,
) -> list:
    """Paginate using pageInfo.endCursor until hasNextPage is False."""
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn

    all_items = []
    cursor = None
    consecutive_errors = 0
    max_consecutive_errors = 10

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=40),
        TextColumn("[progress.percentage]{task.percentage:>3.1f}%"),
        TextColumn("({task.completed}/{task.total})"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Extracting...", total=total_estimate)

        while True:
            variables = {"first": first, "cursor": cursor}
            try:
                data = await client.execute(query, variables)
            except Exception as e:
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    console.print(f"\n  [red]Stopped after {max_consecutive_errors} consecutive errors: {e}[/red]")
                    break
                wait = min(2 ** consecutive_errors, 30)
                console.print(f"\n  [yellow]Error (attempt {consecutive_errors}/{max_consecutive_errors}), retrying in {wait}s: {e}[/yellow]")
                await asyncio.sleep(wait)
                continue

            node = data.get("data", {})
            for key in path:
                node = node.get(key, {})

            edges = node.get("edges", [])
            if not edges:
                if data.get("errors"):
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        console.print(f"\n  [red]Stopped: too many consecutive errors with empty data[/red]")
                        break
                    wait = min(2 ** consecutive_errors, 30)
                    console.print(f"\n  [yellow]Empty page with errors ({consecutive_errors}/{max_consecutive_errors}), retrying in {wait}s...[/yellow]")
                    await asyncio.sleep(wait)
                    continue
                break

            consecutive_errors = 0
            all_items.extend([edge["node"] for edge in edges])
            progress.update(task, completed=len(all_items))

            if len(all_items) > total_estimate:
                progress.update(task, total=len(all_items) + 5000)

            page_info = node.get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break

            cursor = page_info.get("endCursor")
            if not cursor:
                console.print(f"\n  [red]endCursor is None but hasNextPage=True at {len(all_items)} items[/red]")
                break

        progress.update(task, completed=len(all_items), total=len(all_items))

    return all_items


async def extract_products_base(client: GraphQLClient):
    console.print("\n[bold cyan]Query 1: Produtos Base (estrutura + variantes + imagens)...[/bold cyan]")
    products = await _paginate_endcursor(client, PRODUCTS_BASE_QUERY, ["products"], first=50, total_estimate=55000)
    console.print(f"  Total: {len(products)} produtos")
    _save("produtos_base.json", products)
    return products


async def extract_collections_map(client: GraphQLClient):
    console.print("\n[bold cyan]Query 2: Mapeamento de Coleções...[/bold cyan]")
    collections = await _paginate_endcursor(client, COLLECTIONS_MAP_QUERY, ["collections"], first=50, total_estimate=66)

    for coll in collections:
        is_smart = coll.get("ruleSet") is not None
        coll["_type"] = "smart" if is_smart else "manual"

        product_edges = coll.get("products", {}).get("edges", [])
        product_handles = [e["node"]["handle"] for e in product_edges]

        if not is_smart and len(product_edges) == 250:
            console.print(f"  [dim]Collection '{coll['title']}' has 250+ products, fetching all...[/dim]")
            cursor = None
            while True:
                result = await client.execute(COLLECTION_PRODUCTS_NEXT, {
                    "collectionId": coll["id"],
                    "first": 250,
                    "cursor": cursor,
                })
                coll_data = result.get("data", {}).get("collection", {}).get("products", {})
                extra_edges = coll_data.get("edges", [])
                if not extra_edges:
                    break
                product_handles.extend([e["node"]["handle"] for e in extra_edges])
                page_info = coll_data.get("pageInfo", {})
                if not page_info.get("hasNextPage"):
                    break
                cursor = page_info.get("endCursor")

        coll["_product_handles"] = product_handles
        if "products" in coll:
            del coll["products"]

        console.print(f"  {coll['_type'].upper():6s} | {coll['title']} ({len(product_handles)} produtos)")

    _save("mapa_colecoes.json", collections)
    return collections


async def extract_products_meta_seo(client: GraphQLClient):
    console.print("\n[bold cyan]Query 3: SEO + Metafields...[/bold cyan]")
    products = await _paginate_endcursor(client, PRODUCTS_META_SEO_QUERY, ["products"], first=100, total_estimate=55000)
    console.print(f"  Total: {len(products)} produtos com meta/SEO")
    _save("produtos_meta_seo.json", products)
    return products


async def extract_metafield_definitions(client: GraphQLClient):
    console.print("\n[bold cyan]Metafield Definitions...[/bold cyan]")
    all_defs = []
    for owner_type in ["PRODUCT", "PRODUCTVARIANT"]:
        defs = await client.paginate(
            METAFIELD_DEFINITIONS_QUERY,
            ["metafieldDefinitions"],
            {"ownerType": owner_type},
        )
        for d in defs:
            d["_ownerType"] = owner_type
        all_defs.extend(defs)
        console.print(f"  {owner_type}: {len(defs)} definitions")
    _save("metafield_definitions.json", all_defs)
    return all_defs


async def run(command: str = "all"):
    console.print("\n[bold green]═══ EXTRAÇÃO ═══[/bold green]")
    async with GraphQLClient(SOURCE, MAX_CONCURRENT) as client:
        if command in ("all", "defs"):
            await extract_metafield_definitions(client)
        if command in ("all", "base"):
            await extract_products_base(client)
        if command in ("all", "colecoes"):
            await extract_collections_map(client)
        if command in ("all", "meta"):
            await extract_products_meta_seo(client)
    console.print("\n[bold green]═══ EXTRAÇÃO COMPLETA ═══[/bold green]")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    asyncio.run(run(cmd))
