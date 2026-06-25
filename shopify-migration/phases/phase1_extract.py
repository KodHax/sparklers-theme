"""
FASE 1: Extração Total da Loja de Origem
Extrai: Metafield Definitions, Collections, Products (core + SEO + variants + media + options), Locations, Inventory.
"""
import asyncio
import json
import os

from rich.console import Console
from rich.progress import track

from config import SOURCE, DATA_DIR, MAX_CONCURRENT
from utils.graphql_client import GraphQLClient
from utils.logger import MigrationLogger

console = Console()

# ─── QUERIES ───

METAFIELD_DEFINITIONS_QUERY = """
query($ownerType: MetafieldOwnerType!, $cursor: String) {
  metafieldDefinitions(ownerType: $ownerType, first: 100, after: $cursor) {
    edges {
      cursor
      node {
        namespace
        key
        name
        type { name }
        description
        ownerType
        pinnedPosition
        validations { name value }
      }
    }
    pageInfo { hasNextPage }
  }
}
"""

COLLECTIONS_QUERY = """
query($cursor: String) {
  collections(first: 50, after: $cursor) {
    edges {
      cursor
      node {
        id
        title
        handle
        descriptionHtml
        sortOrder
        ruleSet { appliedDisjunctively rules { column relation condition } }
        seo { title description }
        image { url altText }
        metafields(first: 50) {
          edges { node { namespace key value type } }
        }
      }
    }
    pageInfo { hasNextPage }
  }
}
"""

COLLECTION_PRODUCTS_QUERY = """
query($collectionId: ID!, $cursor: String) {
  collection(id: $collectionId) {
    products(first: 250, after: $cursor) {
      edges {
        cursor
        node { id }
      }
      pageInfo { hasNextPage }
    }
  }
}
"""

PRODUCTS_QUERY = """
query($cursor: String) {
  products(first: 10, after: $cursor) {
    edges {
      cursor
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
        seo { title description }
        options { name values }
        metafields(first: 20) {
          edges { node { namespace key value type } }
        }
        variants(first: 30) {
          edges {
            node {
              id
              title
              sku
              price
              compareAtPrice
              barcode
              selectedOptions { name value }
              inventoryItem { id tracked measurement { weight { value unit } } }
              metafields(first: 10) {
                edges { node { namespace key value type } }
              }
            }
          }
        }
      }
    }
    pageInfo { hasNextPage }
  }
}
"""

PRODUCT_MEDIA_QUERY = """
query($productId: ID!, $cursor: String) {
  product(id: $productId) {
    media(first: 50, after: $cursor) {
      edges {
        cursor
        node {
          ... on MediaImage {
            id
            image { url altText }
          }
        }
      }
      pageInfo { hasNextPage }
    }
    variants(first: 100) {
      edges {
        node {
          id
          image { url altText }
        }
      }
    }
  }
}
"""

LOCATIONS_QUERY = """
query {
  locations(first: 50) {
    edges {
      node {
        id
        name
        address { address1 city country zip }
        isActive
      }
    }
  }
}
"""

INVENTORY_LEVELS_QUERY = """
query($inventoryItemId: ID!, $cursor: String) {
  inventoryItem(id: $inventoryItemId) {
    inventoryLevels(first: 50, after: $cursor) {
      edges {
        cursor
        node {
          location { id name }
          quantities(names: ["available", "on_hand"]) {
            name
            quantity
          }
        }
      }
      pageInfo { hasNextPage }
    }
  }
}
"""


def _save(filename: str, data):
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    console.print(f"  [green]Saved {path} ({len(data) if isinstance(data, list) else 'ok'})[/green]")


async def extract_metafield_definitions(client: GraphQLClient) -> list:
    console.print("[bold cyan]Extracting Metafield Definitions...[/bold cyan]")
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


async def extract_collections(client: GraphQLClient) -> list:
    console.print("[bold cyan]Extracting Collections...[/bold cyan]")
    collections = await client.paginate(COLLECTIONS_QUERY, ["collections"])

    for coll in collections:
        is_manual = coll.get("ruleSet") is None
        coll["_type"] = "manual" if is_manual else "smart"
        if is_manual:
            product_ids = await client.paginate(
                COLLECTION_PRODUCTS_QUERY,
                ["collection", "products"],
                {"collectionId": coll["id"]},
            )
            coll["_productIds"] = [p["id"] for p in product_ids]
            console.print(f"  Manual collection '{coll['title']}': {len(coll['_productIds'])} products")

    _save("collections.json", collections)
    return collections


async def extract_products(client: GraphQLClient) -> list:
    console.print("[bold cyan]Extracting Products (core + variants)...[/bold cyan]")
    products = await client.paginate(PRODUCTS_QUERY, ["products"])
    console.print(f"  Products fetched: {len(products)}")

    console.print("[bold cyan]Extracting Product Media (separate pass)...[/bold cyan]")
    for i, product in enumerate(products):
        pid = product["id"]
        try:
            media_items = await client.paginate(
                PRODUCT_MEDIA_QUERY,
                ["product", "media"],
                {"productId": pid},
            )
            product["media"] = {"edges": [{"node": m} for m in media_items]}

            media_result = await client.execute(PRODUCT_MEDIA_QUERY, {"productId": pid})
            variant_edges = media_result.get("data", {}).get("product", {}).get("variants", {}).get("edges", [])
            for ve in variant_edges:
                vid = ve["node"]["id"]
                vimg = ve["node"].get("image")
                for var_edge in product.get("variants", {}).get("edges", []):
                    if var_edge["node"]["id"] == vid:
                        var_edge["node"]["image"] = vimg
                        break
        except Exception as e:
            console.print(f"  [yellow]Media fetch failed for {pid}: {e}[/yellow]")

        if (i + 1) % 100 == 0:
            console.print(f"  Media progress: {i + 1}/{len(products)}")

    console.print(f"  Total products extracted: {len(products)}")
    _save("products.json", products)
    return products


async def extract_locations(client: GraphQLClient) -> list:
    console.print("[bold cyan]Extracting Locations...[/bold cyan]")
    result = await client.execute(LOCATIONS_QUERY)
    locations = [e["node"] for e in result["data"]["locations"]["edges"]]
    _save("locations.json", locations)
    console.print(f"  Locations found: {len(locations)}")
    return locations


async def extract_inventory(client: GraphQLClient, products: list) -> dict:
    console.print("[bold cyan]Extracting Inventory Levels...[/bold cyan]")
    logger = MigrationLogger("phase1_inventory")
    inventory_map = {}

    for product in products:
        for edge in product.get("variants", {}).get("edges", []):
            variant = edge["node"]
            inv_item = variant.get("inventoryItem", {})
            inv_item_id = inv_item.get("id")
            if not inv_item_id or not inv_item.get("tracked"):
                continue
            try:
                levels = await client.paginate(
                    INVENTORY_LEVELS_QUERY,
                    ["inventoryItem", "inventoryLevels"],
                    {"inventoryItemId": inv_item_id},
                )
                inventory_map[inv_item_id] = {
                    "variant_id": variant["id"],
                    "sku": variant.get("sku", ""),
                    "levels": levels,
                }
                logger.success(inv_item_id)
            except Exception as e:
                logger.error(inv_item_id, "INVENTORY_FETCH", str(e))

    _save("inventory.json", inventory_map)
    console.print(f"  Inventory items mapped: {len(inventory_map)}")
    logger.close()
    return inventory_map


async def run():
    console.print("\n[bold green]═══ FASE 1: EXTRAÇÃO TOTAL ═══[/bold green]\n")
    async with GraphQLClient(SOURCE, MAX_CONCURRENT) as client:
        metafield_defs = await extract_metafield_definitions(client)
        collections = await extract_collections(client)
        products = await extract_products(client)
        locations = await extract_locations(client)
        inventory = await extract_inventory(client, products)

    console.print("\n[bold green]═══ FASE 1 COMPLETA ═══[/bold green]")
    console.print(f"  Metafield Defs: {len(metafield_defs)}")
    console.print(f"  Collections: {len(collections)}")
    console.print(f"  Products: {len(products)}")
    console.print(f"  Locations: {len(locations)}")
    console.print(f"  Inventory Items: {len(inventory)}")


if __name__ == "__main__":
    asyncio.run(run())
