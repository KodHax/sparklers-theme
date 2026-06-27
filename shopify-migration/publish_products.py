#!/usr/bin/env python3
"""
Publica todos os produtos no canal "Online Store".
Produtos ativos mas não publicados no canal não aparecem no tema.

Uso:
  python publish_products.py          # Lista quantos precisam de ser publicados
  python publish_products.py --publish # Publica todos
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
    edges { node { id title handle } }
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

        online_store_pub = None
        for edge in pub_edges:
            node = edge["node"]
            console.print(f"  Channel: {node['name']} ({node['id']})")
            if "online store" in node["name"].lower() or "loja online" in node["name"].lower():
                online_store_pub = node["id"]

        if not online_store_pub:
            console.print("[red]Could not find 'Online Store' publication. Available channels listed above.[/red]")
            return

        console.print(f"\n  [green]Online Store publication: {online_store_pub}[/green]")

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

        console.print(f"  Found {len(products)} products")

        if not publish:
            console.print(f"\n[yellow]Para publicar todos no Online Store:[/yellow]")
            console.print("  python publish_products.py --publish")
            return

        console.print(f"\n[bold green]Publishing {len(products)} products to Online Store...[/bold green]")
        published = 0
        errors = 0

        for p in products:
            try:
                result = await client.execute(PUBLISH_PRODUCT, {
                    "id": p["id"],
                    "input": [{"publicationId": online_store_pub}],
                })
                mut = (result.get("data") or {}).get("publishablePublish") or {}
                user_errors = mut.get("userErrors", [])
                if user_errors:
                    console.print(f"  [red]{p['handle']}: {user_errors[0]['message']}[/red]")
                    errors += 1
                else:
                    published += 1
            except Exception as e:
                console.print(f"  [red]{p['handle']}: {e}[/red]")
                errors += 1

            if (published + errors) % 100 == 0 and (published + errors) > 0:
                console.print(f"  Progress: {published + errors}/{len(products)}")

        console.print(f"\n  [green]Published: {published}[/green] | [red]Errors: {errors}[/red]")


if __name__ == "__main__":
    asyncio.run(run())
