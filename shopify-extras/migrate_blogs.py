#!/usr/bin/env python3
"""
Migração de Blogs e Artigos entre lojas Shopify via GraphQL Admin API.
Extrai todos os blogs com os seus artigos (título, HTML, SEO, autor,
tags, imagem, visibilidade, handle, datas) e importa na loja destino.

Uso:
  python migrate_blogs.py extract                # Extrai blogs e artigos da loja origem
  python migrate_blogs.py upload --limit 1       # Testa com 1 artigo
  python migrate_blogs.py upload --full          # Envia tudo
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

LIST_BLOGS = """
query($first: Int!, $cursor: String) {
  blogs(first: $first, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id
        title
        handle
        templateSuffix
      }
    }
  }
}
"""

BLOG_ARTICLES = """
query($blogId: ID!, $first: Int!, $cursor: String) {
  blog(id: $blogId) {
    articles(first: $first, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      edges {
        node {
          id
          title
          handle
          body
          summary
          tags
          publishedAt
          createdAt
          updatedAt
          isPublished
          templateSuffix
          author { name }
          image {
            url
            altText
            width
            height
          }
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
}
"""

BLOG_CREATE = """
mutation blogCreate($blog: BlogCreateInput!) {
  blogCreate(blog: $blog) {
    blog { id title handle }
    userErrors { field message }
  }
}
"""

BLOG_BY_HANDLE = """
query($query: String!) {
  blogs(first: 1, query: $query) {
    edges { node { id handle } }
  }
}
"""

ARTICLE_CREATE = """
mutation articleCreate($article: ArticleCreateInput!) {
  articleCreate(article: $article) {
    article { id title handle }
    userErrors { field message }
  }
}
"""

ARTICLE_BY_HANDLE = """
query($blogId: ID!, $first: Int!, $cursor: String) {
  blog(id: $blogId) {
    articles(first: $first, after: $cursor) {
      edges { node { id handle } }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""

ARTICLE_UPDATE = """
mutation articleUpdate($id: ID!, $article: ArticleUpdateInput!) {
  articleUpdate(id: $id, article: $article) {
    article { id title handle }
    userErrors { field message }
  }
}
"""


async def extract_blogs():
    os.makedirs(DATA_DIR, exist_ok=True)
    blogs_data = []

    async with GraphQLClient(SOURCE, MAX_CONCURRENT) as client:
        console.print("\n[bold cyan]Extraindo blogs da loja origem...[/bold cyan]")

        blogs = []
        cursor = None
        while True:
            result = await client.execute(LIST_BLOGS, {"first": 50, "cursor": cursor})
            data = (result.get("data") or {}).get("blogs") or {}
            edges = data.get("edges", [])
            blogs.extend([e["node"] for e in edges])
            pi = data.get("pageInfo", {})
            if not pi.get("hasNextPage"):
                break
            cursor = pi.get("endCursor")

        console.print(f"  Encontrados {len(blogs)} blogs")

        for blog in blogs:
            console.print(f"\n  [cyan]{blog['title']}[/cyan] ({blog['handle']})")
            articles = []
            cursor = None
            while True:
                result = await client.execute(BLOG_ARTICLES, {
                    "blogId": blog["id"], "first": 50, "cursor": cursor,
                })
                art_data = ((result.get("data") or {}).get("blog") or {}).get("articles") or {}
                edges = art_data.get("edges", [])
                for e in edges:
                    node = e["node"]
                    articles.append({
                        "id": node["id"],
                        "title": node["title"],
                        "handle": node["handle"],
                        "body": node["body"],
                        "summary": node.get("summary") or "",
                        "tags": node.get("tags", []),
                        "publishedAt": node.get("publishedAt"),
                        "createdAt": node["createdAt"],
                        "updatedAt": node["updatedAt"],
                        "isPublished": node["isPublished"],
                        "templateSuffix": node.get("templateSuffix") or "",
                        "author": (node.get("author") or {}).get("name", ""),
                        "image": node.get("image"),
                        "metafields": [
                            {
                                "namespace": m["node"]["namespace"],
                                "key": m["node"]["key"],
                                "value": m["node"]["value"],
                                "type": m["node"]["type"],
                            }
                            for m in (node.get("metafields") or {}).get("edges", [])
                        ],
                    })

                pi = art_data.get("pageInfo", {})
                if not pi.get("hasNextPage"):
                    break
                cursor = pi.get("endCursor")

            console.print(f"    {len(articles)} artigos")
            for a in articles:
                status = "[green]pub[/green]" if a["isPublished"] else "[yellow]rasc[/yellow]"
                console.print(f"    • {a['title']} [{a['handle']}] {status}")

            blogs_data.append({
                "id": blog["id"],
                "title": blog["title"],
                "handle": blog["handle"],
                "templateSuffix": blog.get("templateSuffix") or "",
                "articles": articles,
            })

    total_articles = sum(len(b["articles"]) for b in blogs_data)
    out_file = os.path.join(DATA_DIR, "blogs.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(blogs_data, f, ensure_ascii=False, indent=2)

    console.print(f"\n  Total: {len(blogs_data)} blogs, {total_articles} artigos")
    console.print(f"  Guardado em {out_file}")


async def _find_existing_articles(client, blog_id):
    existing = {}
    cursor = None
    while True:
        result = await client.execute(ARTICLE_BY_HANDLE, {
            "blogId": blog_id, "first": 50, "cursor": cursor,
        })
        art_data = ((result.get("data") or {}).get("blog") or {}).get("articles") or {}
        for e in art_data.get("edges", []):
            existing[e["node"]["handle"]] = e["node"]["id"]
        pi = art_data.get("pageInfo", {})
        if not pi.get("hasNextPage"):
            break
        cursor = pi.get("endCursor")
    return existing


async def upload_blogs():
    blogs_file = os.path.join(DATA_DIR, "blogs.json")
    if not os.path.exists(blogs_file):
        console.print("[red]Ficheiro blogs.json não encontrado. Corre 'extract' primeiro.[/red]")
        return

    with open(blogs_file, "r", encoding="utf-8") as f:
        blogs_data = json.load(f)

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
        total = sum(len(b["articles"]) for b in blogs_data)
        console.print(f"\n[yellow]Encontrados {len(blogs_data)} blogs com {total} artigos.[/yellow]")
        console.print("  python migrate_blogs.py upload --full")
        console.print("  python migrate_blogs.py upload --limit 1")
        return

    state = StateManager("state_blogs.json")
    created_blogs = 0
    created_articles = 0
    updated_articles = 0
    errors = 0
    article_count = 0

    async with GraphQLClient(DEST, MAX_CONCURRENT) as client:
        console.print(f"\n[bold green]Importando blogs...[/bold green]")

        for blog in blogs_data:
            blog_handle = blog["handle"]

            check = await client.execute(BLOG_BY_HANDLE, {"query": f"handle:{blog_handle}"})
            existing_edges = ((check.get("data") or {}).get("blogs") or {}).get("edges", [])

            if existing_edges:
                dest_blog_id = existing_edges[0]["node"]["id"]
                console.print(f"\n  [blue]Blog '{blog['title']}' já existe[/blue]")
            else:
                blog_input = {
                    "title": blog["title"],
                    "handle": blog_handle,
                }
                if blog.get("templateSuffix"):
                    blog_input["templateSuffix"] = blog["templateSuffix"]

                result = await client.execute(BLOG_CREATE, {"blog": blog_input})
                mut = (result.get("data") or {}).get("blogCreate") or {}
                user_errors = mut.get("userErrors", [])
                if user_errors:
                    console.print(f"  [red]Blog '{blog['title']}': {user_errors[0]['message']}[/red]")
                    errors += 1
                    continue
                dest_blog_id = mut["blog"]["id"]
                created_blogs += 1
                console.print(f"\n  [green]Blog '{blog['title']}' criado[/green]")

            existing_articles = await _find_existing_articles(client, dest_blog_id)

            for article in blog["articles"]:
                if 0 < limit <= article_count:
                    break

                art_handle = article["handle"]
                state_key = f"{blog_handle}/{art_handle}"

                if state.is_done(state_key):
                    console.print(f"    [dim]{art_handle}: já importado[/dim]")
                    article_count += 1
                    continue

                art_input = {
                    "blogId": dest_blog_id,
                    "title": article["title"],
                    "handle": art_handle,
                    "body": article["body"] or "",
                    "summary": article["summary"] or "",
                    "tags": article.get("tags", []),
                    "isPublished": article["isPublished"],
                }


                if article.get("templateSuffix"):
                    art_input["templateSuffix"] = article["templateSuffix"]

                if article.get("author"):
                    art_input["author"] = {"name": article["author"]}

                if article.get("image") and article["image"].get("url"):
                    art_input["image"] = {
                        "url": article["image"]["url"],
                        "altText": article["image"].get("altText") or "",
                    }

                try:
                    if art_handle in existing_articles:
                        existing_id = existing_articles[art_handle]
                        update_input = {k: v for k, v in art_input.items() if k != "blogId"}
                        result = await client.execute(ARTICLE_UPDATE, {
                            "id": existing_id,
                            "article": update_input,
                        })
                        mut = (result.get("data") or {}).get("articleUpdate") or {}
                        user_errors = mut.get("userErrors", [])
                        if user_errors:
                            console.print(f"    [red]{art_handle}: {user_errors[0]['message']}[/red]")
                            errors += 1
                            article_count += 1
                            continue
                        updated_articles += 1
                        console.print(f"    [blue]{art_handle}: atualizado[/blue]")
                    else:
                        result = await client.execute(ARTICLE_CREATE, {"article": art_input})
                        mut = (result.get("data") or {}).get("articleCreate") or {}
                        user_errors = mut.get("userErrors", [])
                        if user_errors:
                            console.print(f"    [red]{art_handle}: {user_errors[0]['message']}[/red]")
                            errors += 1
                            article_count += 1
                            continue
                        created_articles += 1
                        console.print(f"    [green]{art_handle}: criado[/green]")

                    new_art_id = (mut.get("article") or {}).get("id")
                    if new_art_id and article.get("metafields"):
                        for mf in article["metafields"]:
                            try:
                                await client.execute("""
                                    mutation metafieldsSet($metafields: [MetafieldsSetInput!]!) {
                                      metafieldsSet(metafields: $metafields) {
                                        userErrors { field message }
                                      }
                                    }
                                """, {
                                    "metafields": [{
                                        "ownerId": new_art_id,
                                        "namespace": mf["namespace"],
                                        "key": mf["key"],
                                        "value": mf["value"],
                                        "type": mf["type"],
                                    }]
                                })
                            except Exception:
                                pass

                    state.mark_done(state_key)

                except Exception as e:
                    console.print(f"    [red]{art_handle}: {e}[/red]")
                    errors += 1

                article_count += 1

            if 0 < limit <= article_count:
                break

        console.print(f"\n  Blogs: [green]{created_blogs} criados[/green]")
        console.print(f"  Artigos: [green]{created_articles} criados[/green] | [blue]{updated_articles} atualizados[/blue] | [red]{errors} erros[/red]")


async def run():
    if len(sys.argv) < 2:
        console.print("[yellow]Uso: python migrate_blogs.py [extract|upload][/yellow]")
        return

    command = sys.argv[1]
    if command == "extract":
        await extract_blogs()
    elif command == "upload":
        await upload_blogs()
    else:
        console.print(f"[red]Comando desconhecido: {command}[/red]")


if __name__ == "__main__":
    asyncio.run(run())
