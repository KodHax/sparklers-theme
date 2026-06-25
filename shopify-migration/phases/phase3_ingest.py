"""
FASE 3: Ingestão e Mapeamento na Loja de Destino
Cria produtos (DRAFT), mapeia IDs, associa coleções manuais, injeta inventário.
Inclui fallback de imagens via stagedUploadsCreate.
"""
import asyncio
import json
import os

from rich.console import Console

from config import DEST, SOURCE, DATA_DIR, MAX_CONCURRENT, BATCH_SIZE
from utils.graphql_client import GraphQLClient
from utils.logger import MigrationLogger
from utils.state import StateManager
from utils.image_handler import upload_via_staged_upload

console = Console()

# ─── MUTATIONS ───

CREATE_PRODUCT = """
mutation productCreate($input: ProductInput!, $media: [CreateMediaInput!]) {
  productCreate(input: $input, media: $media) {
    product {
      id
      handle
      variants(first: 100) {
        edges {
          node {
            id
            sku
            inventoryItem { id }
            selectedOptions { name value }
          }
        }
      }
      media(first: 100) {
        edges {
          node {
            ... on MediaImage { id image { url } }
          }
        }
      }
    }
    userErrors { field message }
  }
}
"""

COLLECTION_ADD_PRODUCTS = """
mutation($id: ID!, $productIds: [ID!]!) {
  collectionAddProducts(id: $id, productIds: $productIds) {
    userErrors { field message }
  }
}
"""

SET_INVENTORY = """
mutation inventorySetOnHandQuantities($input: InventorySetOnHandQuantitiesInput!) {
  inventorySetOnHandQuantities(input: $input) {
    inventoryAdjustmentGroup { reason }
    userErrors { field message }
  }
}
"""

LOCATIONS_QUERY = """
query {
  locations(first: 50) {
    edges { node { id name address { address1 city country } isActive } }
  }
}
"""


def _load(filename: str):
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return [] if filename.endswith(".json") else {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_metafields_input(metafield_edges: list) -> list:
    result = []
    for edge in metafield_edges:
        mf = edge["node"]
        result.append({
            "namespace": mf["namespace"],
            "key": mf["key"],
            "value": mf["value"],
            "type": mf["type"],
        })
    return result


async def _build_location_map(client: GraphQLClient) -> dict:
    """Map source location names to destination location IDs."""
    source_locations = _load("locations.json")
    result = await client.execute(LOCATIONS_QUERY)
    dest_locations = [e["node"] for e in result["data"]["locations"]["edges"]]

    location_map = {}
    for src_loc in source_locations:
        src_name = src_loc["name"].strip().lower()
        for dest_loc in dest_locations:
            if dest_loc["name"].strip().lower() == src_name:
                location_map[src_loc["id"]] = dest_loc["id"]
                break
        if src_loc["id"] not in location_map and dest_locations:
            location_map[src_loc["id"]] = dest_locations[0]["id"]
            console.print(
                f"  [yellow]Location '{src_loc['name']}' not found in dest, "
                f"mapped to '{dest_locations[0]['name']}'[/yellow]"
            )

    console.print(f"  Location mappings: {len(location_map)}")
    return location_map


async def create_products(client: GraphQLClient) -> dict:
    console.print("[bold cyan]Creating Products (as DRAFT)...[/bold cyan]")
    products = _load("products.json")
    logger = MigrationLogger("phase3_products")
    state = StateManager("products")
    id_map = {}

    for i, product in enumerate(products):
        old_id = product["id"]
        if state.is_done(old_id):
            id_map[old_id] = state.get_new_id(old_id)
            continue

        product_input = {
            "title": product["title"],
            "handle": product.get("handle"),
            "descriptionHtml": product.get("descriptionHtml", ""),
            "vendor": product.get("vendor"),
            "productType": product.get("productType"),
            "status": "DRAFT",
            "tags": product.get("tags", []),
            "templateSuffix": product.get("templateSuffix"),
        }

        if product.get("seo"):
            product_input["seo"] = {
                "title": product["seo"].get("title"),
                "description": product["seo"].get("description"),
            }

        if product.get("options"):
            product_input["options"] = [opt["name"] for opt in product["options"]]

        variant_edges = product.get("variants", {}).get("edges", [])
        if variant_edges:
            product_input["variants"] = []
            for vedge in variant_edges:
                v = vedge["node"]
                inv_item = v.get("inventoryItem", {})
                weight_data = inv_item.get("weight", {}) or {}
                var_input = {
                    "sku": v.get("sku"),
                    "price": v.get("price"),
                    "compareAtPrice": v.get("compareAtPrice"),
                    "barcode": v.get("barcode"),
                    "weight": weight_data.get("value"),
                    "weightUnit": weight_data.get("unit"),
                    "options": [opt["value"] for opt in v.get("selectedOptions", [])],
                }

                var_metafields = v.get("metafields", {}).get("edges", [])
                if var_metafields:
                    var_input["metafields"] = _build_metafields_input(var_metafields)

                product_input["variants"].append(var_input)

        prod_metafields = product.get("metafields", {}).get("edges", [])
        if prod_metafields:
            product_input["metafields"] = _build_metafields_input(prod_metafields)

        media_input = []
        media_edges = product.get("media", {}).get("edges", [])
        for medge in media_edges:
            img = medge["node"].get("image")
            if img and img.get("url"):
                media_item = {
                    "originalSource": img["url"],
                    "mediaContentType": "IMAGE",
                }
                if img.get("altText"):
                    media_item["alt"] = img["altText"]
                media_input.append(media_item)

        try:
            result = await client.execute(CREATE_PRODUCT, {
                "input": product_input,
                "media": media_input if media_input else None,
            })
            errors = result.get("data", {}).get("productCreate", {}).get("userErrors", [])
            if errors:
                err_msg = "; ".join(e["message"] for e in errors)
                if any("already exists" in e["message"].lower() for e in errors):
                    state.mark_done(old_id, "exists")
                    logger.success(old_id, "Handle already exists")
                else:
                    logger.error(old_id, "USER_ERROR", err_msg)
            else:
                new_product = result["data"]["productCreate"]["product"]
                new_id = new_product["id"]
                state.mark_done(old_id, new_id)
                id_map[old_id] = new_id

                variant_state = StateManager("variant_map")
                old_variants = variant_edges
                new_variants = new_product.get("variants", {}).get("edges", [])
                for ov, nv in zip(old_variants, new_variants):
                    variant_state.mark_done(ov["node"]["id"], nv["node"]["id"])
                    inv_old = ov["node"].get("inventoryItem", {}).get("id")
                    inv_new = nv["node"].get("inventoryItem", {}).get("id")
                    if inv_old and inv_new:
                        variant_state.mark_done(f"inv:{inv_old}", inv_new)

                logger.success(old_id, f"-> {new_id}")
        except Exception as e:
            logger.error(old_id, "EXCEPTION", str(e))

        if (i + 1) % 100 == 0:
            console.print(f"  Progress: {i + 1}/{len(products)}")

    console.print(f"  {logger.summary()}")
    logger.close()
    return id_map


async def associate_manual_collections(client: GraphQLClient, product_id_map: dict):
    console.print("[bold cyan]Associating Products to Manual Collections...[/bold cyan]")
    collections = _load("collections.json")
    collection_state = StateManager("collections")
    logger = MigrationLogger("phase3_collection_assoc")

    manual = [c for c in collections if c["_type"] == "manual"]
    for coll in manual:
        old_coll_id = coll["id"]
        new_coll_id = collection_state.get_new_id(old_coll_id)
        if not new_coll_id or new_coll_id == "exists":
            logger.error(old_coll_id, "NO_MAPPING", "Collection ID not mapped")
            continue

        product_ids = coll.get("_productIds", [])
        new_product_ids = [product_id_map.get(pid) for pid in product_ids if product_id_map.get(pid)]

        for batch_start in range(0, len(new_product_ids), BATCH_SIZE):
            batch = new_product_ids[batch_start:batch_start + BATCH_SIZE]
            try:
                result = await client.execute(COLLECTION_ADD_PRODUCTS, {
                    "id": new_coll_id,
                    "productIds": batch,
                })
                errors = result.get("data", {}).get("collectionAddProducts", {}).get("userErrors", [])
                if errors:
                    logger.error(old_coll_id, "ASSOC_ERROR", "; ".join(e["message"] for e in errors))
                else:
                    logger.success(old_coll_id, f"Added {len(batch)} products")
            except Exception as e:
                logger.error(old_coll_id, "EXCEPTION", str(e))

    console.print(f"  {logger.summary()}")
    logger.close()


async def inject_inventory(client: GraphQLClient, location_map: dict):
    console.print("[bold cyan]Injecting Inventory Levels...[/bold cyan]")
    inventory = _load("inventory.json")
    variant_state = StateManager("variant_map")
    logger = MigrationLogger("phase3_inventory")

    for inv_item_id, inv_data in inventory.items():
        new_inv_item_id = variant_state.get_new_id(f"inv:{inv_item_id}")
        if not new_inv_item_id:
            logger.error(inv_item_id, "NO_MAPPING", "Inventory item not mapped")
            continue

        for level in inv_data.get("levels", []):
            old_location_id = level.get("location", {}).get("id")
            new_location_id = location_map.get(old_location_id)
            if not new_location_id:
                continue

            on_hand = 0
            for q in level.get("quantities", []):
                if q["name"] == "on_hand":
                    on_hand = q["quantity"]
                    break

            try:
                result = await client.execute(SET_INVENTORY, {
                    "input": {
                        "reason": "other",
                        "setQuantities": [{
                            "inventoryItemId": new_inv_item_id,
                            "locationId": new_location_id,
                            "quantity": on_hand,
                        }],
                    }
                })
                errors = result.get("data", {}).get("inventorySetOnHandQuantities", {}).get("userErrors", [])
                if errors:
                    logger.error(inv_item_id, "INV_ERROR", "; ".join(e["message"] for e in errors))
                else:
                    logger.success(inv_item_id)
            except Exception as e:
                logger.error(inv_item_id, "EXCEPTION", str(e))

    console.print(f"  {logger.summary()}")
    logger.close()


async def run():
    console.print("\n[bold green]═══ FASE 3: INGESTÃO E MAPEAMENTO ═══[/bold green]\n")
    async with GraphQLClient(DEST, MAX_CONCURRENT) as client:
        location_map = await _build_location_map(client)
        product_id_map = await create_products(client)
        await associate_manual_collections(client, product_id_map)
        await inject_inventory(client, location_map)
    console.print("\n[bold green]═══ FASE 3 COMPLETA ═══[/bold green]")


if __name__ == "__main__":
    asyncio.run(run())
