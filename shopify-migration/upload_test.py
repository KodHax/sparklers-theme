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
  python upload_test.py inventario  # Só injetar inventário
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
mutation productSet($input: ProductSetInput!) {
  productSet(input: $input) {
    product {
      id
      handle
      variants(first: 100) {
        edges { node { id sku inventoryItem { id } } }
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

GET_LOCATIONS = """
query { locations(first: 5) { edges { node { id name } } } }
"""

INVENTORY_SET_ON_HAND = """
mutation inventorySetOnHandQuantities($input: InventorySetOnHandQuantitiesInput!) {
  inventorySetOnHandQuantities(input: $input) {
    inventoryAdjustmentGroup { reason }
    userErrors { field message }
  }
}
"""


class AccessDeniedError(Exception):
    pass


def _check_api_errors(result: dict, context: str = ""):
    """Check for top-level GraphQL errors (403, Access Denied, etc.) and raise loudly."""
    errors = result.get("errors", [])
    if not errors:
        return
    for err in errors:
        msg = err.get("message", "")
        if "access denied" in msg.lower() or "forbidden" in msg.lower():
            raise AccessDeniedError(
                f"[ACESSO NEGADO] {msg}\n"
                f"  Contexto: {context}\n"
                f"  Solução: Apaga o token em cache e re-autentica com os scopes corretos.\n"
                f"  Corre: python -c \"from utils.oauth import invalidate_cached_token; invalidate_cached_token('URL_DA_LOJA')\""
            )
    error_msgs = "; ".join(e.get("message", str(e)) for e in errors)
    if not result.get("data"):
        raise RuntimeError(f"GraphQL API error ({context}): {error_msgs}")
    console.print(f"  [yellow]⚠ API warnings ({context}): {error_msgs[:300]}[/yellow]")


def _load(filename: str, directory: str = DATA_DIR):
    path = os.path.join(directory, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


async def create_metafield_definitions(client: GraphQLClient):
    console.print("\n[bold cyan]Step 1: Creating Metafield Definitions...[/bold cyan]")
    defs = _load("metafield_definitions.json")
    logger = MigrationLogger("upload_metafield_defs")
    state = StateManager("dest_metafield_defs")

    skipped_system = 0
    for d in defs:
        key = f"{d['_ownerType']}:{d['namespace']}.{d['key']}"

        if d["namespace"] == "shopify":
            skipped_system += 1
            state.mark_done(key, "system-managed")
            continue

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
            valid_validations = [
                {"name": v["name"], "value": v["value"]}
                for v in d["validations"]
                if v.get("name") != "metaobject_definition_id"
            ]
            if valid_validations:
                definition_input["validations"] = valid_validations

        try:
            result = await client.execute(CREATE_METAFIELD_DEF, {"definition": definition_input})
            _check_api_errors(result, f"metafieldDefinitionCreate [{key}]")
            data = result.get("data") or {}
            mutation_result = data.get("metafieldDefinitionCreate") or {}
            errors = mutation_result.get("userErrors", [])
            if errors:
                err_msg = "; ".join(e["message"] for e in errors)
                if "already exists" in err_msg.lower() or "taken" in err_msg.lower():
                    state.mark_done(key, "exists")
                    logger.success(key, "Already exists")
                else:
                    logger.error(key, "USER_ERROR", err_msg)
            else:
                created = mutation_result.get("createdDefinition")
                if created:
                    state.mark_done(key, created["id"])
                    logger.success(key)
                else:
                    logger.error(key, "NO_DATA", f"API returned no data: {str(result)[:300]}")
        except AccessDeniedError:
            raise
        except Exception as e:
            logger.error(key, "EXCEPTION", str(e))

    if skipped_system:
        console.print(f"  [dim]Skipped {skipped_system} system-managed (shopify.*) definitions[/dim]")
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

    skipped_system = 0
    for defn in mo_definitions:
        obj_type = defn.get("type", "")
        key = f"def:{obj_type}"

        if obj_type.startswith("shopify--"):
            skipped_system += 1
            state.mark_done(key, "system-managed")
            continue

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
            _check_api_errors(result, f"metaobjectDefinitionCreate [{obj_type}]")
            data = result.get("data") or {}
            mutation_result = data.get("metaobjectDefinitionCreate") or {}
            errors = mutation_result.get("userErrors", [])
            if errors:
                err_msg = "; ".join(e["message"] for e in errors)
                if "already exists" in err_msg.lower() or "taken" in err_msg.lower():
                    state.mark_done(key, "exists")
                    logger.success(key, "Already exists")
                else:
                    logger.error(key, "USER_ERROR", err_msg)
            else:
                new_def = mutation_result.get("metaobjectDefinition")
                if new_def:
                    state.mark_done(key, new_def["id"])
                    logger.success(key, f"-> {new_def['id']}")
                else:
                    logger.error(key, "NO_DATA", f"API returned no data: {str(result)[:300]}")
        except AccessDeniedError:
            raise
        except Exception as e:
            logger.error(key, "EXCEPTION", str(e))

    if skipped_system:
        console.print(f"  [dim]Skipped {skipped_system} system-managed (shopify--*) definitions[/dim]")
    console.print(f"  Definitions: {logger.summary()}")

    if not mo_entries:
        console.print("  [yellow]No metaobjects.json found, skipping entries.[/yellow]")
        logger.close()
        return

    skipped_entries = 0
    for entry in mo_entries:
        old_id = entry.get("id", "")
        entry_type = entry.get("type", "")

        if entry_type.startswith("shopify--"):
            skipped_entries += 1
            state.mark_done(old_id, "system-managed")
            continue

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
                    "type": entry_type,
                    "handle": entry.get("handle"),
                    "fields": fields,
                }
            })
            _check_api_errors(result, f"metaobjectCreate [{old_id}]")
            data = result.get("data") or {}
            mutation_result = data.get("metaobjectCreate") or {}
            errors = mutation_result.get("userErrors", [])
            if errors:
                err_msg = "; ".join(e["message"] for e in errors)
                if "already exists" in err_msg.lower() or "taken" in err_msg.lower():
                    state.mark_done(old_id, "exists")
                    logger.success(old_id, "Already exists")
                else:
                    logger.error(old_id, "USER_ERROR", err_msg)
            else:
                new_mo = mutation_result.get("metaobject")
                if new_mo:
                    state.mark_done(old_id, new_mo["id"])
                    logger.success(old_id, f"-> {new_mo['id']}")
                else:
                    logger.error(old_id, "NO_DATA", f"API returned no data: {str(result)[:300]}")
        except AccessDeniedError:
            raise
        except Exception as e:
            logger.error(old_id, "EXCEPTION", str(e))

    if skipped_entries:
        console.print(f"  [dim]Skipped {skipped_entries} system-managed (shopify--*) entries[/dim]")
    console.print(f"  Entries: {logger.summary()}")
    logger.close()


async def create_collections(client: GraphQLClient, limit: int | None = None):
    label = f" (limit: {limit})" if limit else ""
    console.print(f"\n[bold cyan]Step 2: Creating Collections{label}...[/bold cyan]")
    collections = _load("mapa_colecoes.json")
    logger = MigrationLogger("upload_collections")
    state = StateManager("dest_collections")

    smart = [c for c in collections if c.get("_type") == "smart"]
    manual = [c for c in collections if c.get("_type") != "smart"]

    all_colls = smart + manual
    if limit:
        all_colls = all_colls[:limit]

    for coll in all_colls:
        old_id = coll["id"]
        if state.is_done(old_id):
            continue

        coll_input = {
            "title": coll["title"],
            "handle": coll.get("handle"),
            "descriptionHtml": coll.get("descriptionHtml", ""),
            "sortOrder": coll.get("sortOrder"),
            "templateSuffix": coll.get("templateSuffix"),
        }

        if coll.get("seo"):
            coll_input["seo"] = {
                "title": coll["seo"].get("title"),
                "description": coll["seo"].get("description"),
            }

        if (coll.get("image") or {}).get("url"):
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
            _check_api_errors(result, f"collectionCreate [{coll.get('title', old_id)}]")
            data = result.get("data") or {}
            mutation_result = data.get("collectionCreate") or {}
            errors = mutation_result.get("userErrors", [])
            if errors:
                logger.error(old_id, "USER_ERROR", "; ".join(e["message"] for e in errors))
            else:
                new_coll = mutation_result.get("collection")
                if new_coll:
                    state.mark_done(old_id, new_coll["id"])
                    state.mark_done(f"handle:{new_coll['handle']}", new_coll["id"])
                    logger.success(old_id, f"-> {new_coll['id']}")
                else:
                    logger.error(old_id, "NO_DATA", f"API returned no data: {str(result)[:300]}")
        except AccessDeniedError:
            raise
        except Exception as e:
            logger.error(old_id, "EXCEPTION", str(e))

    smart_count = sum(1 for c in all_colls if c.get("_type") == "smart")
    manual_count = len(all_colls) - smart_count
    console.print(f"  Smart: {smart_count} | Manual: {manual_count} | Total: {len(all_colls)}")
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

        if product.get("category"):
            product_input["category"] = product["category"]["id"]

        if product.get("seo"):
            product_input["seo"] = {
                "title": product["seo"].get("title"),
                "description": product["seo"].get("description"),
            }

        if product.get("options"):
            product_input["productOptions"] = [
                {"name": opt["name"], "values": [{"name": val} for val in opt.get("values", [])]}
                for opt in product["options"]
            ]

        if product.get("variants"):
            product_input["variants"] = []
            for v in product["variants"]:
                var_input = {
                    "sku": v.get("sku"),
                    "price": v.get("price"),
                    "compareAtPrice": v.get("compareAtPrice"),
                    "barcode": v.get("barcode"),
                    "optionValues": [
                        {"name": opt["value"], "optionName": opt["name"]}
                        for opt in v.get("selectedOptions", [])
                    ],
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
                if mf.get("namespace") != "shopify"
            ]

        media_input = []
        for img in product.get("images", []):
            if img.get("url"):
                media_item = {"originalSource": img["url"], "mediaContentType": "IMAGE"}
                if img.get("altText"):
                    media_item["alt"] = img["altText"]
                media_input.append(media_item)

        if media_input:
            product_input["files"] = [
                {"originalSource": m["originalSource"], "contentType": "IMAGE", "alt": m.get("alt", "")}
                for m in media_input
            ]

        try:
            result = await client.execute(CREATE_PRODUCT, {"input": product_input})
            _check_api_errors(result, f"productSet [{handle}]")
            data = result.get("data") or {}
            mutation_result = data.get("productSet") or {}
            errors = mutation_result.get("userErrors", [])
            if errors:
                err_msg = "; ".join(e["message"] for e in errors)
                logger.error(handle, "USER_ERROR", err_msg)
            else:
                new_product = mutation_result.get("product")
                if new_product:
                    state.mark_done(handle, new_product["id"])
                    new_variants = [e["node"] for e in new_product.get("variants", {}).get("edges", [])]
                    variant_state = StateManager("dest_variant_inventory")
                    for idx, nv in enumerate(new_variants):
                        inv_item_id = (nv.get("inventoryItem") or {}).get("id")
                        if inv_item_id and idx < len(product.get("variants", [])):
                            old_variant = product["variants"][idx]
                            old_inv_id = old_variant.get("inventoryItemId", "")
                            if old_inv_id:
                                variant_state.mark_done(old_inv_id, inv_item_id)
                    logger.success(handle, f"-> {new_product['id']}")
                else:
                    logger.error(handle, "NO_DATA", f"API returned no data: {str(result)[:300]}")
        except AccessDeniedError:
            raise
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
                _check_api_errors(result, f"collectionAddProducts [{coll_id}]")
                errors = ((result.get("data") or {}).get("collectionAddProducts") or {}).get("userErrors", [])
                if errors:
                    logger.error(coll_id, "ASSOC_ERROR", "; ".join(e["message"] for e in errors))
                else:
                    logger.success(coll_id, f"Added {len(batch)} products")
            except AccessDeniedError:
                raise
            except Exception as e:
                logger.error(coll_id, "EXCEPTION", str(e))

    console.print(f"  {logger.summary()}")
    logger.close()


async def inject_inventory(client: GraphQLClient, limit: int | None = 50):
    label = f" (limit: {limit})" if limit else " (ALL)"
    console.print(f"\n[bold cyan]Step 5: Injecting Inventory{label}...[/bold cyan]")

    result = await client.execute(GET_LOCATIONS, {})
    locations = [e["node"] for e in ((result.get("data") or {}).get("locations") or {}).get("edges", [])]
    if not locations:
        console.print("  [red]No locations found in destination store![/red]")
        return

    location_id = locations[0]["id"]
    console.print(f"  Location: {locations[0]['name']} ({location_id})")

    products = _load("migracao_pronta.json", READY_DIR)
    if limit:
        products = products[:limit]

    variant_state = StateManager("dest_variant_inventory")
    logger = MigrationLogger("upload_inventory")

    quantities_to_set = []
    for product in products:
        for v in product.get("variants", []):
            old_inv_id = v.get("inventoryItemId", "")
            new_inv_id = variant_state.get_new_id(old_inv_id)
            if not new_inv_id:
                continue

            on_hand = 0
            for lvl in v.get("inventoryLevels", []):
                on_hand += lvl.get("quantities", {}).get("on_hand", 0)

            if on_hand > 0:
                quantities_to_set.append({
                    "inventoryItemId": new_inv_id,
                    "locationId": location_id,
                    "quantity": on_hand,
                    "_sku": v.get("sku", ""),
                })

    console.print(f"  Variants with stock to set: {len(quantities_to_set)}")

    batch_size = 50
    for i in range(0, len(quantities_to_set), batch_size):
        batch = quantities_to_set[i:i + batch_size]
        set_quantities = [
            {
                "inventoryItemId": q["inventoryItemId"],
                "locationId": q["locationId"],
                "quantity": q["quantity"],
            }
            for q in batch
        ]

        try:
            result = await client.execute(INVENTORY_SET_ON_HAND, {
                "input": {
                    "reason": "correction",
                    "setQuantities": set_quantities,
                }
            })
            _check_api_errors(result, f"inventorySetOnHandQuantities [batch {i}]")
            errors = ((result.get("data") or {}).get("inventorySetOnHandQuantities") or {}).get("userErrors", [])
            if errors:
                err_msg = "; ".join(e["message"] for e in errors)
                logger.error(f"batch_{i}", "USER_ERROR", err_msg)
            else:
                for q in batch:
                    logger.success(q["_sku"] or q["inventoryItemId"], f"qty={q['quantity']}")
        except AccessDeniedError:
            raise
        except Exception as e:
            logger.error(f"batch_{i}", "EXCEPTION", str(e))

        if (i + batch_size) % 200 == 0:
            console.print(f"  Progress: {min(i + batch_size, len(quantities_to_set))}/{len(quantities_to_set)}")

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

    try:
        async with GraphQLClient(DEST, MAX_CONCURRENT) as client:
            console.print(f"[bold cyan]Validando conexão com loja destino...[/bold cyan]")
            console.print(f"  URL: {DEST.shop_url}")
            if not DEST.shop_url:
                console.print("[bold red]ERRO: DEST_SHOP_URL não definido no .env[/bold red]")
                return
            try:
                test = await client.execute("query { shop { name } }", {})
                if test.get("errors"):
                    console.print(f"  [bold red]API Error: {test['errors']}[/bold red]")
                    return
                console.print(f"  [green]Conectado: {test['data']['shop']['name']}[/green]")
            except Exception as e:
                console.print(f"  [bold red]FALHA na conexão: {e}[/bold red]")
                return
            if command in ("all", "defs"):
                await create_metafield_definitions(client)
            if command in ("all", "metaobjects"):
                await create_metaobjects(client)
            if command in ("all", "colecoes"):
                await create_collections(client, limit)
            if command in ("all", "produtos"):
                await upload_products(client, limit)
            if command in ("all", "associar"):
                await associate_collections(client, limit)
            if command in ("all", "inventario"):
                await inject_inventory(client, limit)
    except AccessDeniedError as e:
        console.print(f"\n[bold red]{'═' * 60}[/bold red]")
        console.print(f"[bold red]ERRO FATAL: PERMISSÕES INSUFICIENTES[/bold red]")
        console.print(f"[bold red]{'═' * 60}[/bold red]")
        console.print(f"\n[red]{e}[/red]")
        console.print(f"\n[yellow]Passos para resolver:[/yellow]")
        console.print(f"  1. Apaga o token em cache:")
        console.print(f"     [cyan]python reauth.py[/cyan]")
        console.print(f"  2. Re-corre o upload (vai pedir nova autenticação)")
        console.print(f"     [cyan]python upload_test.py {command}[/cyan]")
        console.print()
        sys.exit(1)

    console.print(f"\n[bold green]═══ UPLOAD COMPLETO ═══[/bold green]")


if __name__ == "__main__":
    asyncio.run(run())
