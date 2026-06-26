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
  python extract_steps.py inventory # Só Query 4 (inventory levels)
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

# ─── METAOBJECT DEFINITIONS & ENTRIES ───

METAOBJECT_DEFINITIONS_QUERY = """
query($cursor: String) {
  metaobjectDefinitions(first: 50, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id
        name
        type
        fieldDefinitions {
          key
          name
          type { name }
          required
          validations { name value }
        }
      }
    }
  }
}
"""

METAOBJECTS_BY_TYPE_QUERY = """
query($type: String!, $cursor: String) {
  metaobjects(type: $type, first: 50, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id
        handle
        type
        fields {
          key
          value
          type
          reference {
            ... on MediaImage {
              __typename
              id
              image { url altText }
            }
            ... on Metaobject {
              __typename
              id
              handle
              type
            }
            ... on Product {
              __typename
              id
              handle
            }
            ... on Collection {
              __typename
              id
              handle
            }
            ... on GenericFile {
              __typename
              id
              url
            }
          }
        }
      }
    }
  }
}
"""

# ─── QUERY 4: Inventory Levels ───

INVENTORY_ITEMS_QUERY = """
query($inventoryItemIds: [ID!]!) {
  nodes(ids: $inventoryItemIds) {
    ... on InventoryItem {
      id
      tracked
      inventoryLevels(first: 10) {
        edges {
          node {
            location { id name }
            quantities(names: ["available", "on_hand"]) {
              name
              quantity
            }
          }
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
    """Paginate using pageInfo.endCursor until hasNextPage is False.
    On persistent failures, reduces batch size to isolate corrupted items
    and skips them to continue extraction."""
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn

    all_items = []
    cursor = None
    consecutive_errors = 0
    max_consecutive_errors = 5
    skipped_cursors = []
    current_first = first

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
            variables = {"first": current_first, "cursor": cursor}
            try:
                data = await client.execute(query, variables)
            except Exception as e:
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    skip_result = await _try_skip_batch(client, query, path, cursor, current_first, first)
                    if skip_result:
                        new_cursor, rescued_items = skip_result
                        all_items.extend(rescued_items)
                        progress.update(task, completed=len(all_items))
                        skipped_cursors.append({"at_item": len(all_items), "cursor": cursor, "error": str(e)})
                        console.print(f"\n  [yellow]⚠ Skipped corrupted batch at item ~{len(all_items)}, rescued {len(rescued_items)} items, continuing...[/yellow]")
                        cursor = new_cursor
                        consecutive_errors = 0
                        current_first = first
                        continue
                    console.print(f"\n  [red]Cannot skip batch, stopped at {len(all_items)} items: {e}[/red]")
                    break
                wait = min(2 ** consecutive_errors, 30)
                console.print(f"\n  [yellow]Error ({consecutive_errors}/{max_consecutive_errors}), retrying in {wait}s...[/yellow]")
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
                        skip_result = await _try_skip_batch(client, query, path, cursor, current_first, first)
                        if skip_result:
                            new_cursor, rescued_items = skip_result
                            all_items.extend(rescued_items)
                            progress.update(task, completed=len(all_items))
                            skipped_cursors.append({"at_item": len(all_items), "cursor": cursor, "errors": str(data["errors"])[:200]})
                            console.print(f"\n  [yellow]⚠ Skipped corrupted batch at item ~{len(all_items)}, rescued {len(rescued_items)} items, continuing...[/yellow]")
                            cursor = new_cursor
                            consecutive_errors = 0
                            current_first = first
                            continue
                        console.print(f"\n  [red]Cannot skip batch, stopped at {len(all_items)} items[/red]")
                        break
                    wait = min(2 ** consecutive_errors, 30)
                    console.print(f"\n  [yellow]Empty page with errors ({consecutive_errors}/{max_consecutive_errors}), retrying in {wait}s...[/yellow]")
                    await asyncio.sleep(wait)
                    continue
                break

            consecutive_errors = 0
            current_first = first
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

    if skipped_cursors:
        skip_path = os.path.join(DATA_DIR, "skipped_batches.json")
        with open(skip_path, "w") as f:
            json.dump(skipped_cursors, f, indent=2)
        console.print(f"\n  [yellow]⚠ {len(skipped_cursors)} batch(es) skipped. Details in {skip_path}[/yellow]")

    return all_items


async def _try_skip_batch(
    client: GraphQLClient,
    query: str,
    path: list[str],
    stuck_cursor: str | None,
    current_first: int,
    original_first: int,
) -> tuple[str, list] | None:
    """Try to skip past a corrupted batch by reducing batch size to 1,
    fetching items one by one to find the good ones, then jumping ahead."""
    console.print(f"\n  [cyan]Attempting to skip corrupted batch (reducing to first:1)...[/cyan]")

    rescued = []
    skip_cursor = stuck_cursor

    for attempt in range(original_first + 5):
        try:
            data = await client.execute(query, {"first": 1, "cursor": skip_cursor})
        except Exception:
            skip_cursor = None
            break

        node = data.get("data", {})
        for key in path:
            node = node.get(key, {})

        edges = node.get("edges", [])
        page_info = node.get("pageInfo", {})

        if edges and not data.get("errors"):
            rescued.extend([e["node"] for e in edges])

        if not page_info.get("hasNextPage"):
            if rescued:
                return None, rescued
            return None

        new_cursor = page_info.get("endCursor")
        if not new_cursor:
            break

        skip_cursor = new_cursor

        if len(rescued) >= 3 or (edges and not data.get("errors")):
            test_data = await client.execute(query, {"first": original_first, "cursor": skip_cursor})
            test_node = test_data.get("data", {})
            for key in path:
                test_node = test_node.get(key, {})
            if test_node.get("edges") and not test_data.get("errors"):
                console.print(f"  [green]Found clean batch after skipping {attempt + 1} items[/green]")
                return skip_cursor, rescued

    if skip_cursor and skip_cursor != stuck_cursor:
        return skip_cursor, rescued

    return None


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


async def extract_metaobjects(client: GraphQLClient):
    console.print("\n[bold cyan]Metaobject Definitions & Entries...[/bold cyan]")

    definitions = await _paginate_endcursor(
        client, METAOBJECT_DEFINITIONS_QUERY, ["metaobjectDefinitions"],
        first=50, total_estimate=50,
    )
    console.print(f"  Definitions found: {len(definitions)}")
    _save("metaobject_definitions.json", definitions)

    all_entries = []
    for defn in definitions:
        obj_type = defn.get("type", "")
        console.print(f"  [dim]Fetching entries for type '{obj_type}'...[/dim]")
        entries = []
        cursor = None

        while True:
            try:
                result = await client.execute(METAOBJECTS_BY_TYPE_QUERY, {
                    "type": obj_type, "first": 50, "cursor": cursor,
                })
            except Exception as e:
                console.print(f"    [red]Error fetching {obj_type}: {e}[/red]")
                break

            node = result.get("data", {}).get("metaobjects", {})
            edges = node.get("edges", [])
            if not edges:
                break
            entries.extend([e["node"] for e in edges])
            page_info = node.get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")

        console.print(f"    {obj_type}: {len(entries)} entries")
        all_entries.extend(entries)

    _save("metaobjects.json", all_entries)
    console.print(f"  Total metaobject entries: {len(all_entries)}")
    return definitions, all_entries


async def extract_inventory(client: GraphQLClient):
    console.print("\n[bold cyan]Query 4: Inventory Levels...[/bold cyan]")
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

    products_path = os.path.join(DATA_DIR, "produtos_base.json")
    if not os.path.exists(products_path):
        console.print("  [red]produtos_base.json não encontrado. Corre 'base' primeiro.[/red]")
        return

    with open(products_path, "r", encoding="utf-8") as f:
        products = json.load(f)

    inventory_item_ids = []
    for p in products:
        for edge in p.get("variants", {}).get("edges", []):
            inv_id = edge["node"].get("inventoryItem", {}).get("id")
            if inv_id:
                inventory_item_ids.append(inv_id)

    console.print(f"  Total inventory items to fetch: {len(inventory_item_ids):,}")

    inventory_data = {}
    batch_size = 50

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]Fetching inventory..."),
        BarColumn(bar_width=40),
        TextColumn("({task.completed}/{task.total})"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Inventory...", total=len(inventory_item_ids))

        for i in range(0, len(inventory_item_ids), batch_size):
            batch = inventory_item_ids[i:i + batch_size]
            try:
                result = await client.execute(INVENTORY_ITEMS_QUERY, {"inventoryItemIds": batch})
                nodes = result.get("data", {}).get("nodes", [])
                for node in nodes:
                    if not node:
                        continue
                    item_id = node.get("id")
                    levels = []
                    for edge in node.get("inventoryLevels", {}).get("edges", []):
                        lvl = edge["node"]
                        levels.append({
                            "locationId": lvl["location"]["id"],
                            "locationName": lvl["location"]["name"],
                            "quantities": {q["name"]: q["quantity"] for q in lvl.get("quantities", [])},
                        })
                    inventory_data[item_id] = levels
            except Exception as e:
                console.print(f"\n  [yellow]Error at batch {i}: {e}[/yellow]")

            progress.update(task, completed=min(i + batch_size, len(inventory_item_ids)))

    _save("inventory_levels.json", inventory_data)
    console.print(f"  Total items with inventory: {len(inventory_data):,}")

    total_on_hand = sum(
        q.get("on_hand", 0)
        for levels in inventory_data.values()
        for lvl in levels
        for q in [lvl["quantities"]]
    )
    console.print(f"  Total on-hand stock: {total_on_hand:,}")

    return inventory_data


def _print_extraction_report():
    """Print detailed stats after extraction completes."""
    from rich.table import Table
    from collections import Counter

    products_base = None
    meta_seo = None
    collections = None
    metafield_defs = None

    for fname, var_name in [
        ("produtos_base.json", "products_base"),
        ("produtos_meta_seo.json", "meta_seo"),
        ("mapa_colecoes.json", "collections"),
        ("metafield_definitions.json", "metafield_defs"),
    ]:
        path = os.path.join(DATA_DIR, fname)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                locals()[var_name] = json.load(f)

    products_base = locals().get("products_base")
    meta_seo = locals().get("meta_seo")
    collections = locals().get("collections")
    metafield_defs = locals().get("metafield_defs")

    if not products_base:
        return

    total_products = len(products_base)
    variant_counts = []
    image_counts = []
    products_without_variants = 0
    products_without_images = 0

    for p in products_base:
        variants = p.get("variants", {}).get("edges", [])
        images = p.get("images", {}).get("edges", [])
        n_variants = len(variants)
        n_images = len(images)
        variant_counts.append(n_variants)
        image_counts.append(n_images)
        if n_variants == 0:
            products_without_variants += 1
        if n_images == 0:
            products_without_images += 1

    total_variants = sum(variant_counts)
    total_images = sum(image_counts)
    variant_distribution = Counter(variant_counts)
    image_distribution = Counter(image_counts)

    colls_total = len(collections) if collections else 0
    colls_manual = 0
    colls_smart = 0
    colls_products_total = 0
    colls_empty = 0
    if collections:
        for c in collections:
            handles = c.get("_product_handles", [])
            if c.get("_type") == "smart":
                colls_smart += 1
            else:
                colls_manual += 1
            colls_products_total += len(handles)
            if len(handles) == 0:
                colls_empty += 1

    meta_count = len(meta_seo) if meta_seo else 0
    meta_with_seo = 0
    meta_with_metafields = 0
    total_metafields = 0
    if meta_seo:
        for p in meta_seo:
            seo = p.get("seo", {})
            if seo.get("title") or seo.get("description"):
                meta_with_seo += 1
            mfs = p.get("metafields", {}).get("edges", [])
            if mfs:
                meta_with_metafields += 1
                total_metafields += len(mfs)

    defs_count = len(metafield_defs) if metafield_defs else 0
    defs_product = sum(1 for d in (metafield_defs or []) if d.get("_ownerType") == "PRODUCT")
    defs_variant = sum(1 for d in (metafield_defs or []) if d.get("_ownerType") == "PRODUCTVARIANT")

    console.print("\n")
    summary = Table(title="Resumo da Extração", title_style="bold green")
    summary.add_column("Metric", style="cyan", min_width=38)
    summary.add_column("Value", style="bold white", justify="right")

    summary.add_row("[bold]── PRODUTOS ──", "")
    summary.add_row("Total de Produtos", f"{total_products:,}")
    summary.add_row("Total de Variantes", f"{total_variants:,}")
    summary.add_row("Média de Variantes/Produto", f"{total_variants / max(total_products, 1):.1f}")
    summary.add_row("Max Variantes num Produto", f"{max(variant_counts) if variant_counts else 0}")
    summary.add_row("Produtos sem Variantes", f"{products_without_variants}")

    summary.add_row("[bold]── IMAGENS ──", "")
    summary.add_row("Total de Imagens", f"{total_images:,}")
    summary.add_row("Média de Imagens/Produto", f"{total_images / max(total_products, 1):.1f}")
    summary.add_row("Max Imagens num Produto", f"{max(image_counts) if image_counts else 0}")
    summary.add_row("Produtos com Imagens", f"{total_products - products_without_images:,}")
    summary.add_row("Produtos sem Imagens", f"{products_without_images}")

    summary.add_row("[bold]── COLEÇÕES ──", "")
    summary.add_row("Total de Coleções", f"{colls_total}")
    summary.add_row("  Manuais (Custom)", f"{colls_manual}")
    summary.add_row("  Automatizadas (Smart)", f"{colls_smart}")
    summary.add_row("  Coleções Vazias", f"{colls_empty}")
    summary.add_row("Associações Produto-Coleção", f"{colls_products_total:,}")

    summary.add_row("[bold]── SEO & METAFIELDS ──", "")
    summary.add_row("Produtos com Meta/SEO extraídos", f"{meta_count:,}")
    summary.add_row("  Com SEO (title ou description)", f"{meta_with_seo:,}")
    summary.add_row("  Com Metafields", f"{meta_with_metafields:,}")
    summary.add_row("Total de Metafields (valores)", f"{total_metafields:,}")
    summary.add_row("Metafield Definitions", f"{defs_count}")
    summary.add_row("  De Produto", f"{defs_product}")
    summary.add_row("  De Variante", f"{defs_variant}")

    mo_defs_path = os.path.join(DATA_DIR, "metaobject_definitions.json")
    mo_entries_path = os.path.join(DATA_DIR, "metaobjects.json")
    mo_defs = []
    mo_entries = []
    if os.path.exists(mo_defs_path):
        with open(mo_defs_path, "r", encoding="utf-8") as f:
            mo_defs = json.load(f)
    if os.path.exists(mo_entries_path):
        with open(mo_entries_path, "r", encoding="utf-8") as f:
            mo_entries = json.load(f)

    if mo_defs or mo_entries:
        from collections import Counter as MoCounter
        mo_type_counts = MoCounter(e.get("type", "?") for e in mo_entries)

        summary.add_row("[bold]── METAOBJECTS ──", "")
        summary.add_row("Metaobject Definitions", f"{len(mo_defs)}")
        summary.add_row("Total Metaobject Entries", f"{len(mo_entries):,}")
        for mo_type, count in mo_type_counts.most_common():
            summary.add_row(f"  {mo_type}", f"{count:,}")

    console.print(summary)

    dist_table = Table(title="Distribuição de Variantes por Produto", title_style="bold blue")
    dist_table.add_column("Variantes", style="cyan", justify="center")
    dist_table.add_column("Produtos", style="white", justify="right")
    dist_table.add_column("% do Total", style="dim", justify="right")
    dist_table.add_column("", style="green")

    for count in sorted(variant_distribution.keys()):
        n_products = variant_distribution[count]
        pct = (n_products / total_products) * 100
        bar = "█" * max(1, int(pct / 2))
        dist_table.add_row(str(count), f"{n_products:,}", f"{pct:.1f}%", bar)

    console.print(dist_table)

    img_dist_table = Table(title="Distribuição de Imagens por Produto", title_style="bold blue")
    img_dist_table.add_column("Imagens", style="cyan", justify="center")
    img_dist_table.add_column("Produtos", style="white", justify="right")
    img_dist_table.add_column("% do Total", style="dim", justify="right")
    img_dist_table.add_column("", style="magenta")

    for count in sorted(image_distribution.keys()):
        n_products = image_distribution[count]
        pct = (n_products / total_products) * 100
        bar = "█" * max(1, int(pct / 2))
        img_dist_table.add_row(str(count), f"{n_products:,}", f"{pct:.1f}%", bar)

    console.print(img_dist_table)

    if max(variant_counts, default=0) > 50:
        console.print("\n  [yellow]⚠ Produtos com muitas variantes (>50):[/yellow]")
        for p in products_base:
            n = len(p.get("variants", {}).get("edges", []))
            if n > 50:
                console.print(f"    {p.get('handle', '?')} — {n} variantes")

    skipped_path = os.path.join(DATA_DIR, "skipped_batches.json")
    if os.path.exists(skipped_path):
        with open(skipped_path, "r") as f:
            skipped = json.load(f)
        if skipped:
            console.print(f"\n  [yellow]⚠ {len(skipped)} batch(es) foram saltados durante a extração[/yellow]")

    console.print(f"\n  [dim]Para validar contra a loja: python validate_extraction.py[/dim]")


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
        if command in ("all", "metaobjects"):
            await extract_metaobjects(client)
        if command in ("all", "inventory"):
            await extract_inventory(client)

    _print_extraction_report()
    console.print("\n[bold green]═══ EXTRAÇÃO COMPLETA ═══[/bold green]")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    asyncio.run(run(cmd))
