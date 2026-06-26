#!/usr/bin/env python3
"""
Fase 3: Upload de teste controlado (50 produtos).
Ordem estrita:
  1. Criar metafield definitions
  2. Criar coleções vazias
  3. Upload de 50 produtos (DRAFT) com SEO, metafields e imagens
  4. Associar produtos às coleções

Uso:
  python upload_test.py              # Corre tudo (50 produtos)
  python upload_test.py --limit 10   # Testar com 10 produtos
  python upload_test.py --full       # Upload de TODOS os produtos
  python upload_test.py defs         # Só criar metafield definitions
  python upload_test.py metaobjects  # Só criar metaobject definitions + entries
  python upload_test.py colecoes     # Só criar coleções
  python upload_test.py produtos     # Só upload de produtos
  python upload_test.py associar     # Só associar coleções
"""
import asyncio
import json
import os
import sys

from rich.console import Console

from config import DEST, DATA_DIR, MAX_CONCURRENT
from utils.graphql_client import GraphQLClient
from utils.logger import MigrationLogger
from utils.state import StateManager

console = Console()
READY_DIR = os.path.join(os.path.dirname(DATA_DIR), "data_ready")

# ─── MUTATIONS ───

CREATE_METAFIELD_DEF = """
mutation($definition: MetafieldDefinitionInput!) {
  metafieldDefinitionCreate(definition: $definition) {
    createdDefinition { id namespace key }
    userErrors { field message }
  }
}
"""

CREATE_COLLECTION = """
mutation($input: CollectionInput!) {
  collectionCreate(input: $input) {
    collection { id title handle }
    userErrors { field message }
  }
}
"""

CREATE_PRODUCT = """
mutation productCreate($input: ProductInput!, $media: [CreateMediaInput!]) {
  productCreate(input: $input, media: $media) {
    product {
      id
      handle
      variants(first: 100) {
        edges { node { id sku } }
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

CREATE_METAOBJECT_DEF = """
mutation metaobjectDefinitionCreate($definition: MetaobjectDefinitionCreateInput!) {
  metaobjectDefinitionCreate(definition: $definition) {
    metaobjectDefinition { id type name }
    userErrors { field message }
  }
}
"""

CREATE_METAOBJECT = """
mutation metaobjectCreate($metaobject: MetaobjectCreateInput!) {
  metaobjectCreate(metaobject: $metaobject) {
    metaobject { id handle type }
    userErrors { field message }
  }
}
"""


def _load(filename: str, directory: str = DATA_DIR):
    path = os.path.join(directory, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


async def create_metafield_definitions(client: GraphQLClient):
    console.print("\n[bold cyan]Step 1: Creating Metafield Definitions...[/bold cyan]")
    defs = _load("metafield_definitions.json")
    logger = MigrationLogger("upload_metafield_defs")
    state = StateManager("dest_metafield_defs")

    for d in defs:
        key = f"{d['_ownerType']}:{d['namespace']}.{d['key']}"
        if state.is_done(key):
            continue

        definition_input = {
            "namespace": d["namespace"],
            "key": d["key"],
            "name": d.get("name", d["key"]),
            "type": d["type"]["name"],
            "ownerType": d["_ownerType"],
        }
        if d.get("description"):
            definition_input["description"] = d["description"]
        if d.get("validations"):
            definition_input["validations"] = [
                {"name": v["name"], "value": v["value"]}
                for v in d["validations"]
            ]

        try:
            result = await client.execute(CREATE_METAFIELD_DEF, {"definition": definition_input})
            errors = result.get("data", {}).get("metafieldDefinitionCreate", {}).get("userErrors", [])
            if errors:
                err_msg = "; ".join(e["message"] for e in errors)
                if "already exists" in err_msg.lower() or "taken" in err_msg.lower():
                    state.mark_done(key, "exists")
                    logger.success(key, "Already exists")
                else:
                    logger.error(key, "USER_ERROR", err_msg)
            else:
                new_id = result["data"]["metafieldDefinitionCreate"]["createdDefinition"]["id"]
                state.mark_done(key, new_id)
                logger.success(key)
        except Exception as e:
            logger.error(key, "EXCEPTION", str(e))

    console.print(f"  {logger.summary()}")
    logger.close()


async def create_metaobjects(client: GraphQLClient):
    console.print("\n[bold cyan]Step 1b: Creating Metaobject Definitions & Entries...[/bold cyan]")

    mo_definitions = _load("metaobject_definitions.json")
    mo_entries = _load("metaobjects.json")

    if not mo_definitions:
        console.print("  [yellow]No metaobject_definitions.json found, skipping.[/yellow]")
        return

    logger = MigrationLogger("upload_metaobjects")
    state = StateManager("dest_metaobjects")

    for defn in mo_definitions:
        obj_type = defn.get("type", "")
        key = f"def:{obj_type}"
        if state.is_done(key):
            continue

        field_defs = []
        for fd in defn.get("fieldDefinitions", []):
            field_def = {
                "key": fd["key"],
                "name": fd.get("name", fd["key"]),
                "type": fd["type"]["name"],
            }
            if fd.get("required"):
                field_def["required"] = True
            if fd.get("validations"):
                field_def["validations"] = [
                    {"name": v["name"], "value": v["value"]}
                    for v in fd["validations"]
                ]
            field_defs.append(field_def)

        try:
            result = await client.execute(CREATE_METAOBJECT_DEF, {
                "definition": {
                    "type": obj_type,
                    "name": defn.get("name", obj_type),
                    "fieldDefinitions": field_defs,
                }
            })
            errors = result.get("data", {}).get("metaobjectDefinitionCreate", {}).get("userErrors", [])
            if errors:
                err_msg = "; ".join(e["message"] for e in errors)
                if "already exists" in err_msg.lower() or "taken" in err_msg.lower():
                    state.mark_done(key, "exists")
                    logger.success(key, "Already exists")
                else:
                    logger.error(key, "USER_ERROR", err_msg)
            else:
                new_id = result["data"]["metaobjectDefinitionCreate"]["metaobjectDefinition"]["id"]
                state.mark_done(key, new_id)
                logger.success(key, f"-> {new_id}")
        except Exception as e:
            logger.error(key, "EXCEPTION", str(e))

    console.print(f"  Definitions: {logger.summary()}")

    if not mo_entries:
        console.print("  [yellow]No metaobjects.json found, skipping entries.[/yellow]")
        logger.close()
        return

    for entry in mo_entries:
        old_id = entry.get("id", "")
        if state.is_done(old_id):
            continue

        fields = []
        for field in entry.get("fields", []):
            value = field.get("value")
            if value is not None and value != "":
                fields.append({
                    "key": field["key"],
                    "value": value,
                })

        try:
            result = await client.execute(CREATE_METAOBJECT, {
                "metaobject": {
                    "type": entry.get("type", ""),
                    "handle": entry.get("handle"),
                    "fields": fields,
                }
            })
            errors = result.get("data", {}).get("metaobjectCreate", {}).get("userErrors", [])
            if errors:
                err_msg = "; ".join(e["message"] for e in errors)
                if "already exists" in err_msg.lower() or "taken" in err_msg.lower():
                    state.mark_done(old_id, "exists")
                    logger.success(old_id, "Already exists")
                else:
                    logger.error(old_id, "USER_ERROR", err_msg)
            else:
                new_mo = result["data"]["metaobjectCreate"]["metaobject"]
                state.mark_done(old_id, new_mo["id"])
                logger.success(old_id, f"-> {new_mo['id']}")
        except Exception as e:
            logger.error(old_id, "EXCEPTION", str(e))

    console.print(f"  Entries: {logger.summary()}")
    logger.close()


async def create_collections(client: GraphQLClient):
    console.print("\n[bold cyan]Step 2: Creating Collections...[/bold cyan]")
    collections = _load("mapa_colecoes.json")
    logger = MigrationLogger("upload_collections")
    state = StateManager("dest_collections")

    smart = [c for c in collections if c.get("_type") == "smart"]
    manual = [c for c in collections if c.get("_type") != "smart"]

    for coll in smart + manual:
        old_id = coll["id"]
        if state.is_done(old_id):
            continue

        coll_input = {
            "title": coll["title"],
            "handle": coll.get("handle"),
            "descriptionHtml": coll.get("descriptionHtml", ""),
            "sortOrder": coll.get("sortOrder"),
        }

        if coll.get("seo"):
            coll_input["seo"] = {
                "title": coll["seo"].get("title"),
                "description": coll["seo"].get("description"),
            }

        if coll.get("image", {}).get("url"):
            coll_input["image"] = {
                "src": coll["image"]["url"],
                "altText": coll["image"].get("altText", ""),
            }

        if coll.get("_type") == "smart" and coll.get("ruleSet"):
            coll_input["ruleSet"] = {
                "appliedDisjunctively": coll["ruleSet"]["appliedDisjunctively"],
                "rules": [
                    {"column": r["column"], "relation": r["relation"], "condition": r["condition"]}
                    for r in coll["ruleSet"]["rules"]
                ],
            }

        try:
            result = await client.execute(CREATE_COLLECTION, {"input": coll_input})
            errors = result.get("data", {}).get("collectionCreate", {}).get("userErrors", [])
            if errors:
                logger.error(old_id, "USER_ERROR", "; ".join(e["message"] for e in errors))
            else:
                new_coll = result["data"]["collectionCreate"]["collection"]
                state.mark_done(old_id, new_coll["id"])
                state.mark_done(f"handle:{new_coll['handle']}", new_coll["id"])
                logger.success(old_id, f"-> {new_coll['id']}")
        except Exception as e:
            logger.error(old_id, "EXCEPTION", str(e))

    console.print(f"  Smart: {len(smart)} | Manual: {len(manual)}")
    console.print(f"  {logger.summary()}")
    logger.close()


async def upload_products(client: GraphQLClient, limit: int | None = 50):
    label = f" (limit: {limit})" if limit else " (ALL)"
    console.print(f"\n[bold cyan]Step 3: Uploading Products as DRAFT{label}...[/bold cyan]")

    products = _load("migracao_pronta.json", READY_DIR)
    if limit:
        products = products[:limit]

    logger = MigrationLogger("upload_products")
    state = StateManager("dest_products")

    for i, product in enumerate(products):
        handle = product.get("handle", "")
        if state.is_done(handle):
            continue

        product_input = {
            "title": product["title"],
            "handle": handle,
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

        if product.get("variants"):
            product_input["variants"] = []
            for v in product["variants"]:
                var_input = {
                    "sku": v.get("sku"),
                    "price": v.get("price"),
                    "compareAtPrice": v.get("compareAtPrice"),
                    "barcode": v.get("barcode"),
                    "weight": v.get("weight"),
                    "weightUnit": v.get("weightUnit"),
                    "options": [opt["value"] for opt in v.get("selectedOptions", [])],
                }
                product_input["variants"].append(var_input)

        if product.get("metafields"):
            product_input["metafields"] = [
                {
                    "namespace": mf["namespace"],
                    "key": mf["key"],
                    "value": mf["value"],
                    "type": mf["type"],
                }
                for mf in product["metafields"]
            ]

        media_input = []
        for img in product.get("images", []):
            if img.get("url"):
                media_item = {"originalSource": img["url"], "mediaContentType": "IMAGE"}
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
                logger.error(handle, "USER_ERROR", err_msg)
            else:
                new_product = result["data"]["productCreate"]["product"]
                state.mark_done(handle, new_product["id"])
                logger.success(handle, f"-> {new_product['id']}")
        except Exception as e:
            logger.error(handle, "EXCEPTION", str(e))

        if (i + 1) % 50 == 0:
            console.print(f"  Progress: {i + 1}/{len(products)}")

    console.print(f"  {logger.summary()}")
    logger.close()


async def associate_collections(client: GraphQLClient, limit: int | None = 50):
    console.print("\n[bold cyan]Step 4: Associating Products to Collections...[/bold cyan]")

    products = _load("migracao_pronta.json", READY_DIR)
    if limit:
        products = products[:limit]

    product_state = StateManager("dest_products")
    collection_state = StateManager("dest_collections")
    logger = MigrationLogger("upload_collection_assoc")

    collection_products: dict[str, list[str]] = {}
    for product in products:
        handle = product.get("handle", "")
        new_pid = product_state.get_new_id(handle)
        if not new_pid:
            continue

        for coll_handle in product.get("colecoes_alvo", []):
            new_coll_id = collection_state.get_new_id(f"handle:{coll_handle}")
            if new_coll_id:
                collection_products.setdefault(new_coll_id, []).append(new_pid)

    for coll_id, product_ids in collection_products.items():
        batch_size = 50
        for i in range(0, len(product_ids), batch_size):
            batch = product_ids[i:i + batch_size]
            try:
                result = await client.execute(COLLECTION_ADD_PRODUCTS, {
                    "id": coll_id,
                    "productIds": batch,
                })
                errors = result.get("data", {}).get("collectionAddProducts", {}).get("userErrors", [])
                if errors:
                    logger.error(coll_id, "ASSOC_ERROR", "; ".join(e["message"] for e in errors))
                else:
                    logger.success(coll_id, f"Added {len(batch)} products")
            except Exception as e:
                logger.error(coll_id, "EXCEPTION", str(e))

    console.print(f"  {logger.summary()}")
    logger.close()


async def run():
    args = sys.argv[1:]
    command = args[0] if args else "all"
    limit = 50

    if "--full" in args:
        limit = None
    elif "--limit" in args:
        idx = args.index("--limit")
        if idx + 1 < len(args):
            limit = int(args[idx + 1])

    console.print(f"\n[bold green]═══ UPLOAD {'TESTE' if limit else 'COMPLETO'} ═══[/bold green]")

    async with GraphQLClient(DEST, MAX_CONCURRENT) as client:
        if command in ("all", "defs"):
            await create_metafield_definitions(client)
        if command in ("all", "metaobjects"):
            await create_metaobjects(client)
        if command in ("all", "colecoes"):
            await create_collections(client)
        if command in ("all", "produtos"):
            await upload_products(client, limit)
        if command in ("all", "associar"):
            await associate_collections(client, limit)

    console.print(f"\n[bold green]═══ UPLOAD COMPLETO ═══[/bold green]")


if __name__ == "__main__":
    asyncio.run(run())
