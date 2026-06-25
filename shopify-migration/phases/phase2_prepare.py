"""
FASE 2: Preparação da Estrutura na Loja de Destino
Cria Metafield Definitions + Collections (Smart com regras, Manual vazias).
"""
import asyncio
import json
import os

from rich.console import Console

from config import DEST, DATA_DIR, MAX_CONCURRENT
from utils.graphql_client import GraphQLClient
from utils.logger import MigrationLogger
from utils.state import StateManager

console = Console()

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


def _load(filename: str):
    path = os.path.join(DATA_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


async def create_metafield_definitions(client: GraphQLClient):
    console.print("[bold cyan]Creating Metafield Definitions...[/bold cyan]")
    defs = _load("metafield_definitions.json")
    logger = MigrationLogger("phase2_metafield_defs")
    state = StateManager("metafield_defs")

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
                if "already exists" in err_msg.lower():
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


async def create_collections(client: GraphQLClient):
    console.print("[bold cyan]Creating Collections...[/bold cyan]")
    collections = _load("collections.json")
    logger = MigrationLogger("phase2_collections")
    state = StateManager("collections")

    smart = [c for c in collections if c["_type"] == "smart"]
    manual = [c for c in collections if c["_type"] == "manual"]

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

        if coll["_type"] == "smart" and coll.get("ruleSet"):
            coll_input["ruleSet"] = {
                "appliedDisjunctively": coll["ruleSet"]["appliedDisjunctively"],
                "rules": [
                    {"column": r["column"], "relation": r["relation"], "condition": r["condition"]}
                    for r in coll["ruleSet"]["rules"]
                ],
            }

        metafields = coll.get("metafields", {}).get("edges", [])
        if metafields:
            coll_input["metafields"] = [
                {
                    "namespace": mf["node"]["namespace"],
                    "key": mf["node"]["key"],
                    "value": mf["node"]["value"],
                    "type": mf["node"]["type"],
                }
                for mf in metafields
            ]

        try:
            result = await client.execute(CREATE_COLLECTION, {"input": coll_input})
            errors = result.get("data", {}).get("collectionCreate", {}).get("userErrors", [])
            if errors:
                logger.error(old_id, "USER_ERROR", "; ".join(e["message"] for e in errors))
            else:
                new_id = result["data"]["collectionCreate"]["collection"]["id"]
                state.mark_done(old_id, new_id)
                logger.success(old_id, f"-> {new_id}")
        except Exception as e:
            logger.error(old_id, "EXCEPTION", str(e))

    console.print(f"  Smart: {len(smart)} | Manual: {len(manual)}")
    console.print(f"  {logger.summary()}")
    logger.close()


async def run():
    console.print("\n[bold green]═══ FASE 2: PREPARAÇÃO DA ESTRUTURA ═══[/bold green]\n")
    async with GraphQLClient(DEST, MAX_CONCURRENT) as client:
        await create_metafield_definitions(client)
        await create_collections(client)
    console.print("\n[bold green]═══ FASE 2 COMPLETA ═══[/bold green]")


if __name__ == "__main__":
    asyncio.run(run())
