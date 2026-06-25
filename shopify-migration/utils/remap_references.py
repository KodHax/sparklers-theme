"""
Remapeia Metafields com referências (product_reference, collection_reference, etc.)
após todos os objetos estarem criados na loja destino.
"""
import asyncio
import json
import os
import re

from rich.console import Console

from config import DEST, DATA_DIR, MAX_CONCURRENT
from utils.graphql_client import GraphQLClient
from utils.logger import MigrationLogger
from utils.state import StateManager

console = Console()

REFERENCE_TYPES = {
    "product_reference",
    "collection_reference",
    "variant_reference",
    "list.product_reference",
    "list.collection_reference",
    "list.variant_reference",
}

UPDATE_METAFIELD = """
mutation metafieldsSet($metafields: [MetafieldsSetInput!]!) {
  metafieldsSet(metafields: $metafields) {
    metafields { id key namespace }
    userErrors { field message }
  }
}
"""

GID_PATTERN = re.compile(r"gid://shopify/\w+/\d+")


def _remap_gid(value: str, product_state: StateManager, collection_state: StateManager, variant_state: StateManager) -> str | None:
    def replace_match(match):
        old_gid = match.group(0)
        for st in [product_state, collection_state, variant_state]:
            new_gid = st.get_new_id(old_gid)
            if new_gid and new_gid not in ("exists", ""):
                return new_gid
        return old_gid

    new_value = GID_PATTERN.sub(replace_match, value)
    return new_value if new_value != value else None


async def remap_reference_metafields():
    console.print("\n[bold cyan]Remapping Reference Metafields...[/bold cyan]")

    products_path = os.path.join(DATA_DIR, "products.json")
    if not os.path.exists(products_path):
        console.print("[red]No products.json found.[/red]")
        return

    with open(products_path, "r") as f:
        products = json.load(f)

    product_state = StateManager("products")
    collection_state = StateManager("collections")
    variant_state = StateManager("variant_map")
    logger = MigrationLogger("remap_references")

    metafields_to_update = []

    for product in products:
        old_pid = product["id"]
        new_pid = product_state.get_new_id(old_pid)
        if not new_pid or new_pid in ("exists", ""):
            continue

        for edge in product.get("metafields", {}).get("edges", []):
            mf = edge["node"]
            if mf["type"] not in REFERENCE_TYPES:
                continue

            new_value = _remap_gid(mf["value"], product_state, collection_state, variant_state)
            if new_value:
                metafields_to_update.append({
                    "ownerId": new_pid,
                    "namespace": mf["namespace"],
                    "key": mf["key"],
                    "value": new_value,
                    "type": mf["type"],
                })

        for vedge in product.get("variants", {}).get("edges", []):
            variant = vedge["node"]
            old_vid = variant["id"]
            new_vid = variant_state.get_new_id(old_vid)
            if not new_vid:
                continue

            for edge in variant.get("metafields", {}).get("edges", []):
                mf = edge["node"]
                if mf["type"] not in REFERENCE_TYPES:
                    continue

                new_value = _remap_gid(mf["value"], product_state, collection_state, variant_state)
                if new_value:
                    metafields_to_update.append({
                        "ownerId": new_vid,
                        "namespace": mf["namespace"],
                        "key": mf["key"],
                        "value": new_value,
                        "type": mf["type"],
                    })

    console.print(f"  Reference metafields to remap: {len(metafields_to_update)}")

    if not metafields_to_update:
        console.print("  [green]No reference metafields to remap.[/green]")
        return

    async with GraphQLClient(DEST, MAX_CONCURRENT) as client:
        batch_size = 25
        for i in range(0, len(metafields_to_update), batch_size):
            batch = metafields_to_update[i:i + batch_size]
            try:
                result = await client.execute(UPDATE_METAFIELD, {"metafields": batch})
                errors = result.get("data", {}).get("metafieldsSet", {}).get("userErrors", [])
                if errors:
                    for e in errors:
                        logger.error(f"batch_{i}", "USER_ERROR", e["message"])
                else:
                    logger.success(f"batch_{i}", f"{len(batch)} metafields updated")
            except Exception as e:
                logger.error(f"batch_{i}", "EXCEPTION", str(e))

    console.print(f"  {logger.summary()}")
    logger.close()


if __name__ == "__main__":
    asyncio.run(remap_reference_metafields())
