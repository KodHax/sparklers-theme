#!/usr/bin/env python3
"""
Migração de Páginas entre lojas Shopify via GraphQL Admin API.
Extrai todas as páginas (título, HTML, SEO, visibilidade, template)
e importa na loja destino.

Uso:
  python migrate_pages.py extract                # Extrai páginas da loja origem
  python migrate_pages.py upload [--full]         # Envia para loja destino
"""
import asyncio
import json
import os
import sys

from rich.console import Console

from config import SOURCE, DEST, MAX_CONCURRENT, DATA_DIR
from utils.graphql_client import GraphQLClient
from utils.state import StateManager

console = Console()

PAGES_QUERY = """
query getPages($first: Int!, $cursor: String) {
  pages(first: $first, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id
        title
        handle
        body
        bodySummary
        isPublished
        publishedAt
        templateSuffix
        createdAt
        updatedAt
        metafields(first: 20) {
          edges {
            node {
              namespace
              key
              value
              type
            }
          }
        }
      }
    }
  }
}
"""

PAGE_BY_HANDLE = """
query($query: String!) {
  pages(first: 1, query: $query) {
    edges { node { id handle } }
  }
}
"""

PAGE_CREATE = """
mutation pageCreate($page: PageCreateInput!) {
  pageCreate(page: $page) {
    page {
      id
      title
      handle
    }
    userErrors {
      field
      message
    }
  }
}
"""

PAGE_UPDATE = """
mutation pageUpdate($id: ID!, $page: PageUpdateInput!) {
  pageUpdate(id: $id, page: $page) {
    page {
      id
      title
      handle
    }
    userErrors {
      field
      message
    }
  }
}
"""


async def extract_pages():
    os.makedirs(DATA_DIR, exist_ok=True)
    pages = []

    async with GraphQLClient(SOURCE, MAX_CONCURRENT) as client:
        console.print("\n[bold cyan]Extraindo páginas da loja origem...[/bold cyan]")
        cursor = None
        while True:
            result = await client.execute(PAGES_QUERY, {"first": 50, "cursor": cursor})
            data = (result.get("data") or {}).get("pages") or {}
            edges = data.get("edges", [])
            for edge in edges:
                node = edge["node"]
                page = {
                    "id": node["id"],
                    "title": node["title"],
                    "handle": node["handle"],
                    "body": node["body"],
                    "bodySummary": node.get("bodySummary", ""),
                    "isPublished": node["isPublished"],
                    "publishedAt": node.get("publishedAt"),
                    "templateSuffix": node.get("templateSuffix") or "",
                    "createdAt": node["createdAt"],
                    "updatedAt": node["updatedAt"],
                    "metafields": [
                        {
                            "namespace": m["node"]["namespace"],
                            "key": m["node"]["key"],
                            "value": m["node"]["value"],
                            "type": m["node"]["type"],
                        }
                        for m in (node.get("metafields") or {}).get("edges", [])
                    ],
                }
                pages.append(page)

            page_info = data.get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")

        console.print(f"  Extraídas {len(pages)} páginas")

    out_file = os.path.join(DATA_DIR, "pages.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(pages, f, ensure_ascii=False, indent=2)

    console.print(f"  Guardado em {out_file}")
    for p in pages:
        status = "[green]publicada[/green]" if p["isPublished"] else "[yellow]rascunho[/yellow]"
        template = f" (template: {p['templateSuffix']})" if p["templateSuffix"] else ""
        console.print(f"  • {p['title']} [{p['handle']}] {status}{template}")


async def upload_pages():
    pages_file = os.path.join(DATA_DIR, "pages.json")
    if not os.path.exists(pages_file):
        console.print("[red]Ficheiro pages.json não encontrado. Corre 'extract' primeiro.[/red]")
        return

    with open(pages_file, "r", encoding="utf-8") as f:
        pages = json.load(f)

    limit = 0
    for i, arg in enumerate(sys.argv):
        if arg == "--limit" and i + 1 < len(sys.argv):
            try:
                limit = int(sys.argv[i + 1])
            except ValueError:
                limit = 1
        elif arg == "--full":
            limit = -1

    if limit == 0:
        console.print(f"\n[yellow]Encontradas {len(pages)} páginas para importar.[/yellow]")
        console.print("  python migrate_pages.py upload --full")
        console.print("  python migrate_pages.py upload --limit 1")
        return

    if limit > 0:
        pages = pages[:limit]

    state = StateManager("state_pages.json")
    created = 0
    updated = 0
    errors = 0

    async with GraphQLClient(DEST, MAX_CONCURRENT) as client:
        console.print(f"\n[bold green]Importando {len(pages)} páginas...[/bold green]")

        for page in pages:
            handle = page["handle"]

            if state.is_done(handle):
                console.print(f"  [dim]{handle}: já importada[/dim]")
                continue

            # Check if page already exists in destination
            check = await client.execute(PAGE_BY_HANDLE, {"query": f"handle:{handle}"})
            existing_edges = ((check.get("data") or {}).get("pages") or {}).get("edges", [])

            page_input = {
                "title": page["title"],
                "handle": handle,
                "body": page["body"] or "",
                "isPublished": page["isPublished"],
                "templateSuffix": page["templateSuffix"] or None,
            }

            # Remove None templateSuffix
            if page_input["templateSuffix"] is None:
                del page_input["templateSuffix"]

            try:
                if existing_edges:
                    existing_id = existing_edges[0]["node"]["id"]
                    result = await client.execute(PAGE_UPDATE, {
                        "id": existing_id,
                        "page": page_input,
                    })
                    mut = (result.get("data") or {}).get("pageUpdate") or {}
                    user_errors = mut.get("userErrors", [])
                    if user_errors:
                        console.print(f"  [red]{handle}: {user_errors[0]['message']}[/red]")
                        errors += 1
                        continue
                    updated += 1
                    console.print(f"  [blue]{handle}: atualizada[/blue]")
                else:
                    result = await client.execute(PAGE_CREATE, {"page": page_input})
                    mut = (result.get("data") or {}).get("pageCreate") or {}
                    user_errors = mut.get("userErrors", [])
                    if user_errors:
                        console.print(f"  [red]{handle}: {user_errors[0]['message']}[/red]")
                        errors += 1
                        continue
                    created += 1
                    console.print(f"  [green]{handle}: criada[/green]")

                # Import metafields if any
                if page.get("metafields"):
                    new_page_id = mut.get("page", {}).get("id")
                    if new_page_id:
                        for mf in page["metafields"]:
                            try:
                                await client.execute("""
                                    mutation metafieldsSet($metafields: [MetafieldsSetInput!]!) {
                                      metafieldsSet(metafields: $metafields) {
                                        userErrors { field message }
                                      }
                                    }
                                """, {
                                    "metafields": [{
                                        "ownerId": new_page_id,
                                        "namespace": mf["namespace"],
                                        "key": mf["key"],
                                        "value": mf["value"],
                                        "type": mf["type"],
                                    }]
                                })
                            except Exception:
                                pass

                state.mark_done(handle)

            except Exception as e:
                console.print(f"  [red]{handle}: {e}[/red]")
                errors += 1

        console.print(f"\n  [green]Criadas: {created}[/green] | [blue]Atualizadas: {updated}[/blue] | [red]Erros: {errors}[/red]")


async def run():
    if len(sys.argv) < 2:
        console.print("[yellow]Uso: python migrate_pages.py [extract|upload][/yellow]")
        return

    command = sys.argv[1]
    if command == "extract":
        await extract_pages()
    elif command == "upload":
        await upload_pages()
    else:
        console.print(f"[red]Comando desconhecido: {command}[/red]")


if __name__ == "__main__":
    asyncio.run(run())
