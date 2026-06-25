"""
FASE 4: Validação e Auditoria (QA)
Compara contagens entre origem e destino, valida integridade.
Inclui ativação em bulk (publishablePublish) para Go-Live.
"""
import asyncio
import json
import os

from rich.console import Console
from rich.table import Table

from config import SOURCE, DEST, DATA_DIR, MAX_CONCURRENT
from utils.graphql_client import GraphQLClient
from utils.logger import MigrationLogger

console = Console()

COUNT_QUERY = """
query {
  productsCount { count }
}
"""

VARIANTS_COUNT_QUERY = """
query {
  productVariantsCount { count }
}
"""

COLLECTIONS_COUNT_QUERY = """
query {
  collectionsCount { count }
}
"""

ACTIVATE_PRODUCTS = """
mutation productUpdate($input: ProductInput!) {
  productUpdate(input: $input) {
    product { id status }
    userErrors { field message }
  }
}
"""

PUBLISH_PRODUCT = """
mutation publishablePublish($id: ID!, $input: [PublicationInput!]!) {
  publishablePublish(id: $id, input: $input) {
    publishable { ... on Product { id } }
    userErrors { field message }
  }
}
"""

GET_PUBLICATIONS = """
query {
  publications(first: 20) {
    edges { node { id name } }
  }
}
"""

LIST_DRAFT_PRODUCTS = """
query($cursor: String) {
  products(first: 250, query: "status:draft", after: $cursor) {
    edges {
      cursor
      node { id handle }
    }
    pageInfo { hasNextPage }
  }
}
"""


async def count_objects(client: GraphQLClient, label: str) -> dict:
    counts = {}
    for name, query in [("products", COUNT_QUERY), ("variants", VARIANTS_COUNT_QUERY), ("collections", COLLECTIONS_COUNT_QUERY)]:
        result = await client.execute(query)
        data = result.get("data", {})
        key = f"{name}Count"
        counts[name] = data.get(key, {}).get("count", "N/A")
    return counts


async def run_audit():
    console.print("\n[bold green]═══ FASE 4: VALIDAÇÃO E AUDITORIA ═══[/bold green]\n")

    async with GraphQLClient(SOURCE, MAX_CONCURRENT) as src_client:
        src_counts = await count_objects(src_client, "Source")

    async with GraphQLClient(DEST, MAX_CONCURRENT) as dest_client:
        dest_counts = await count_objects(dest_client, "Destination")

    table = Table(title="Audit: Source vs Destination")
    table.add_column("Object", style="cyan")
    table.add_column("Source", style="green")
    table.add_column("Destination", style="yellow")
    table.add_column("Match", style="bold")

    all_match = True
    for key in ["products", "variants", "collections"]:
        src = src_counts.get(key, "?")
        dst = dest_counts.get(key, "?")
        match = "✓" if src == dst else "✗ MISMATCH"
        if src != dst:
            all_match = False
        table.add_row(key.capitalize(), str(src), str(dst), match)

    console.print(table)

    if all_match:
        console.print("\n[bold green]All counts match! Migration validated.[/bold green]")
    else:
        console.print("\n[bold red]MISMATCHES DETECTED. Review logs before Go-Live.[/bold red]")

    extracted = os.path.join(DATA_DIR, "products.json")
    if os.path.exists(extracted):
        with open(extracted, "r") as f:
            products = json.load(f)
        total_metafields = sum(
            len(p.get("metafields", {}).get("edges", []))
            for p in products
        )
        console.print(f"\n  Extracted product metafields: {total_metafields}")


async def go_live():
    """Activate all DRAFT products and publish to Online Store."""
    console.print("\n[bold yellow]═══ GO-LIVE: Activating Products ═══[/bold yellow]\n")

    async with GraphQLClient(DEST, MAX_CONCURRENT) as client:
        pub_result = await client.execute(GET_PUBLICATIONS)
        publications = [e["node"] for e in pub_result["data"]["publications"]["edges"]]
        online_store_pub = None
        for pub in publications:
            if "online store" in pub["name"].lower():
                online_store_pub = pub["id"]
                break

        if not online_store_pub and publications:
            online_store_pub = publications[0]["id"]

        if not online_store_pub:
            console.print("[red]No publication found. Cannot publish.[/red]")
            return

        console.print(f"  Publishing to: {online_store_pub}")

        draft_products = await client.paginate(LIST_DRAFT_PRODUCTS, ["products"])
        logger = MigrationLogger("phase4_golive")
        console.print(f"  Draft products to activate: {len(draft_products)}")

        for product in draft_products:
            pid = product["id"]
            try:
                await client.execute(ACTIVATE_PRODUCTS, {
                    "input": {"id": pid, "status": "ACTIVE"}
                })
                await client.execute(PUBLISH_PRODUCT, {
                    "id": pid,
                    "input": [{"publicationId": online_store_pub}],
                })
                logger.success(pid)
            except Exception as e:
                logger.error(pid, "GOLIVE_ERROR", str(e))

        console.print(f"  {logger.summary()}")
        logger.close()

    console.print("\n[bold green]═══ GO-LIVE COMPLETO ═══[/bold green]")


async def run():
    await run_audit()


if __name__ == "__main__":
    asyncio.run(run())
