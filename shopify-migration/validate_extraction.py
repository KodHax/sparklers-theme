#!/usr/bin/env python3
"""
Validação da extração: compara os dados locais com os counts reais da loja.
Valida produtos, variantes, coleções, imagens e metafields.

Uso:
  python validate_extraction.py
"""
import asyncio
import json
import os

from rich.console import Console
from rich.table import Table

from config import SOURCE, MAX_CONCURRENT, DATA_DIR
from utils.graphql_client import GraphQLClient

console = Console()

PRODUCTS_COUNT_QUERY = """
query { productsCount { count } }
"""

VARIANTS_COUNT_QUERY = """
query { productVariantsCount { count } }
"""

COLLECTIONS_COUNT_QUERY = """
query { collectionsCount { count } }
"""

FILES_COUNT_QUERY = """
query { filesCount(scope: ALL) { count } }
"""

METAFIELD_DEFS_COUNT_QUERY = """
query($ownerType: MetafieldOwnerType!) {
  metafieldDefinitions(ownerType: $ownerType, first: 1) {
    edges { node { id } }
  }
}
"""

PRODUCTS_IMAGES_SAMPLE = """
query($cursor: String) {
  products(first: 250, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        handle
        imagesCount: images(first: 1) { edges { node { id } } }
        variantsCount: variants(first: 1) { edges { node { id } } }
      }
    }
  }
}
"""


def _load(filename: str):
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


async def _get_count(client: GraphQLClient, query: str, key: str, variables: dict | None = None) -> int | str:
    try:
        result = await client.execute(query, variables)
        data = result.get("data", {})
        return data.get(key, {}).get("count", "N/A")
    except Exception as e:
        return f"Error: {e}"


async def _count_real_store_data(client: GraphQLClient) -> dict:
    """Count real variants and images by paginating through all products."""
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

    total_products = 0
    total_variants = 0
    total_images = 0
    products_with_images = 0
    cursor = None

    REAL_COUNT_QUERY = """
    query($cursor: String) {
      products(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        edges {
          node {
            variants(first: 100) { edges { node { id } } }
            images(first: 100) { edges { node { id } } }
          }
        }
      }
    }
    """

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]Counting store data..."),
        BarColumn(bar_width=30),
        TextColumn("({task.completed} products)"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Counting...", total=None)

        while True:
            try:
                result = await client.execute(REAL_COUNT_QUERY, {"cursor": cursor})
            except Exception:
                break

            data = result.get("data", {}).get("products", {})
            edges = data.get("edges", [])
            if not edges:
                break

            for edge in edges:
                total_products += 1
                n_variants = len(edge["node"].get("variants", {}).get("edges", []))
                n_images = len(edge["node"].get("images", {}).get("edges", []))
                total_variants += n_variants
                total_images += n_images
                if n_images > 0:
                    products_with_images += 1

            progress.update(task, completed=total_products)

            page_info = data.get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")
            if not cursor:
                break

    return {
        "products": total_products,
        "variants": total_variants,
        "images": total_images,
        "products_with_images": products_with_images,
    }


async def run():
    console.print("\n[bold green]═══ VALIDAÇÃO: Local vs Loja de Origem ═══[/bold green]\n")

    console.print("[bold cyan]Fetching real store counts (product by product)...[/bold cyan]")
    async with GraphQLClient(SOURCE, MAX_CONCURRENT) as client:
        store_collections = await _get_count(client, COLLECTIONS_COUNT_QUERY, "collectionsCount")

        api_products = await _get_count(client, PRODUCTS_COUNT_QUERY, "productsCount")
        api_variants = await _get_count(client, VARIANTS_COUNT_QUERY, "productVariantsCount")
        console.print(f"  [dim]API productsCount: {api_products} | API productVariantsCount: {api_variants}[/dim]")

        real_counts = await _count_real_store_data(client)
        store_products = real_counts["products"]
        store_variants = real_counts["variants"]
        store_images = real_counts["images"]
        store_with_images = real_counts["products_with_images"]

        if isinstance(api_variants, int) and api_variants != store_variants:
            console.print(f"  [yellow]⚠ productVariantsCount ({api_variants:,}) differs from real count ({store_variants:,})[/yellow]")
            console.print(f"  [yellow]  Using real count (sum of variants per product) for validation.[/yellow]")

    products_base = _load("produtos_base.json")
    meta_seo = _load("produtos_meta_seo.json")
    collections = _load("mapa_colecoes.json")
    metafield_defs = _load("metafield_definitions.json")

    local_products = 0
    local_variants = 0
    local_images = 0
    local_with_images = 0
    local_without_variants = 0

    if products_base:
        local_products = len(products_base)
        for p in products_base:
            variants = p.get("variants", {}).get("edges", [])
            images = p.get("images", {}).get("edges", [])
            local_variants += len(variants)
            local_images += len(images)
            if len(images) > 0:
                local_with_images += 1
            if len(variants) == 0:
                local_without_variants += 1

    local_collections = len(collections) if collections else 0
    local_meta_products = len(meta_seo) if meta_seo else 0
    local_metafield_defs = len(metafield_defs) if metafield_defs else 0

    local_colls_manual = 0
    local_colls_smart = 0
    local_colls_products_total = 0
    if collections:
        for c in collections:
            if c.get("_type") == "smart":
                local_colls_smart += 1
            else:
                local_colls_manual += 1
            local_colls_products_total += len(c.get("_product_handles", []))

    table = Table(title="Validação: Extração Local vs Loja", title_style="bold green")
    table.add_column("Objeto", style="cyan", min_width=30)
    table.add_column("Loja (real)", style="bold white", justify="right")
    table.add_column("Local (extraído)", style="bold white", justify="right")
    table.add_column("Diff", justify="right")
    table.add_column("Status", justify="center")

    def _add_row(label, store_val, local_val):
        if isinstance(store_val, str):
            table.add_row(label, store_val, str(local_val), "?", "[yellow]?[/yellow]")
            return
        diff = local_val - store_val
        diff_str = f"{diff:+,}" if diff != 0 else "0"
        if diff == 0:
            status = "[bold green]OK[/bold green]"
        elif abs(diff) <= 5:
            status = "[yellow]~OK[/yellow]"
        else:
            status = "[bold red]MISMATCH[/bold red]"
        table.add_row(label, f"{store_val:,}", f"{local_val:,}", diff_str, status)

    _add_row("Produtos", store_products, local_products)
    _add_row("Variantes", store_variants, local_variants)
    _add_row("Imagens (total)", store_images, local_images)
    _add_row("Produtos c/ imagens", store_with_images, local_with_images)
    _add_row("Coleções", store_collections, local_collections)
    _add_row("Produtos c/ Meta/SEO", store_products if isinstance(store_products, int) else 0, local_meta_products)

    console.print(table)

    details = Table(title="Detalhe Local", title_style="bold blue")
    details.add_column("Metric", style="cyan", min_width=35)
    details.add_column("Value", style="white", justify="right")
    details.add_row("Metafield Definitions extraídas", str(local_metafield_defs))
    details.add_row("Coleções Manuais", str(local_colls_manual))
    details.add_row("Coleções Smart (Automatizadas)", str(local_colls_smart))
    details.add_row("Total produtos mapeados em coleções", f"{local_colls_products_total:,}")
    details.add_row("Média variantes/produto", f"{local_variants / max(local_products, 1):.1f}")
    details.add_row("Max variantes num produto", str(max(
        (len(p.get("variants", {}).get("edges", [])) for p in (products_base or [])),
        default=0
    )))
    details.add_row("Produtos sem variantes", str(local_without_variants))
    details.add_row("Produtos sem imagens", str(local_products - local_with_images))
    console.print(details)

    if isinstance(store_products, int) and local_products < store_products:
        missing = store_products - local_products
        pct = (missing / store_products) * 100
        console.print(f"\n  [bold red]ATENÇÃO: Faltam {missing:,} produtos ({pct:.1f}%) na extração![/bold red]")
        console.print(f"  [yellow]Verifica data/skipped_batches.json para detalhes dos batches saltados.[/yellow]")
    elif isinstance(store_products, int) and local_products == store_products:
        console.print(f"\n  [bold green]Extração completa! Todos os {store_products:,} produtos foram extraídos.[/bold green]")

    console.print()


if __name__ == "__main__":
    asyncio.run(run())
