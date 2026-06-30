#!/usr/bin/env python3
"""
1. Ativa todos os produtos (tira de DRAFT -> ACTIVE)
2. Publica em TODOS os canais disponíveis (Online Store, Google, etc.)

Uso:
  python publish_products.py          # Lista canais e contagem
  python publish_products.py --publish # Ativa e publica tudo
"""
import asyncio
import sys

from rich.console import Console

from config import DEST, MAX_CONCURRENT
from utils.graphql_client import GraphQLClient

console = Console()

GET_PUBLICATIONS = """
query {
  publications(first: 20) {
    edges {
      node {
        id
        name
      }
    }
  }
}
"""

LIST_PRODUCTS = """
query($first: Int!, $cursor: String) {
  products(first: $first, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    edges { node { id title handle status } }
  }
}
"""

ACTIVATE_PRODUCT = """
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
    publishable { availablePublicationsCount { count } }
    userErrors { field message }
  }
}
"""


async def run():
    publish = "--publish" in sys.argv

    async with GraphQLClient(DEST, MAX_CONCURRENT) as client:
        console.print("\n[bold cyan]Fetching sales channels...[/bold cyan]")
        pub_result = await client.execute(GET_PUBLICATIONS, {})
        pub_edges = ((pub_result.get("data") or {}).get("publications") or {}).get("edges", [])

        all_pub_ids = []
        for edge in pub_edges:
            node = edge["node"]
            console.print(f"  Channel: {node['name']} ({node['id']})")
            all_pub_ids.append(node["id"])

        if not all_pub_ids:
            console.print("[red]No sales channels found.[/red]")
            return

        console.print(f"\n  [green]{len(all_pub_ids)} canais encontrados[/green]")

        console.print("\n[bold cyan]Fetching products...[/bold cyan]")
        products = []
        cursor = None
        while True:
            result = await client.execute(LIST_PRODUCTS, {"first": 50, "cursor": cursor})
            data = (result.get("data") or {}).get("products") or {}
            edges = data.get("edges", [])
            products.extend([e["node"] for e in edges])
            page_info = data.get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")

        drafts = [p for p in products if p.get("status") == "DRAFT"]
        console.print(f"  Total: {len(products)} | Draft: {len(drafts)}")

        if not publish:
            console.print(f"\n[yellow]Para ativar e publicar em todos os canais:[/yellow]")
            console.print("  python publish_products.py --publish")
            return

        # Step 1: Activate all draft products
        if drafts:
            console.print(f"\n[bold green]Ativando {len(drafts)} produtos em draft...[/bold green]")
            activated = 0
            for p in drafts:
                try:
                    result = await client.execute(ACTIVATE_PRODUCT, {
                        "input": {"id": p["id"], "status": "ACTIVE"}
                    })
                    mut = (result.get("data") or {}).get("productUpdate") or {}
                    user_errors = mut.get("userErrors", [])
                    if not user_errors:
                        activated += 1
                except Exception:
                    pass
            console.print(f"  [green]Ativados: {activated}[/green]")

        # Step 2: Publish all to every channel
        pub_input = [{"publicationId": pid} for pid in all_pub_ids]
        console.print(f"\n[bold green]Publicando {len(products)} produtos em {len(all_pub_ids)} canais...[/bold green]")
        published = 0
        errors = 0

        for p in products:
            try:
                result = await client.execute(PUBLISH_PRODUCT, {
                    "id": p["id"],
                    "input": pub_input,
                })
                mut = (result.get("data") or {}).get("publishablePublish") or {}
                user_errors = mut.get("userErrors", [])
                if user_errors:
                    errors += 1
                    console.print(f"  [red]{p['handle']}: {user_errors[0]['message']}[/red]")
                else:
                    published += 1
            except Exception as e:
                errors += 1
                console.print(f"  [red]{p['handle']}: {e}[/red]")

            if (published + errors) % 100 == 0 and (published + errors) > 0:
                console.print(f"  Progress: {published + errors}/{len(products)}")

        console.print(f"\n  [green]Publicados: {published}[/green] | [red]Erros: {errors}[/red]")


if __name__ == "__main__":
    asyncio.run(run())
