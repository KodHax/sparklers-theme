#!/usr/bin/env python3
"""
Download all images from Shopify source store to local folders:
  images/products/   - product images
  images/collections/ - collection images
  images/files/      - files (generic media)
  images/articles/   - blog article images

Uso:
  python download_images.py
"""
import asyncio
import os
import re
import aiohttp
import aiofiles
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from config import SOURCE, DATA_DIR
from utils.graphql_client import GraphQLClient

console = Console()
BASE_DIR = os.path.join(DATA_DIR, "..", "images")

PRODUCT_IMAGES_QUERY = """
query($first: Int!, $cursor: String) {
  products(first: $first, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        handle
        media(first: 50) {
          edges {
            node {
              ... on MediaImage {
                image { url altText }
              }
            }
          }
        }
      }
    }
  }
}
"""

COLLECTION_IMAGES_QUERY = """
query($first: Int!, $cursor: String) {
  collections(first: $first, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        handle
        image { url altText }
      }
    }
  }
}
"""

FILES_QUERY = """
query($first: Int!, $cursor: String) {
  files(first: $first, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        ... on MediaImage {
          image { url }
          originalFileSize
        }
        ... on GenericFile {
          url
          originalFileSize
        }
      }
    }
  }
}
"""

BLOGS_QUERY = """
query($first: Int!, $cursor: String) {
  blogs(first: $first, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        handle
        articles(first: 50) {
          edges {
            node {
              handle
              image { url altText }
            }
          }
        }
      }
    }
  }
}
"""


def sanitize(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", name)


async def download_file(session: aiohttp.ClientSession, url: str, dest: str, semaphore: asyncio.Semaphore):
    if os.path.exists(dest):
        return True
    try:
        async with semaphore:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status == 200:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    async with aiofiles.open(dest, "wb") as f:
                        await f.write(await resp.read())
                    return True
    except Exception:
        pass
    return False


async def collect_product_images(client):
    images = []
    cursor = None
    while True:
        result = await client.execute(PRODUCT_IMAGES_QUERY, {"first": 50, "cursor": cursor})
        data = (result.get("data") or {}).get("products") or {}
        for edge in data.get("edges", []):
            node = edge["node"]
            handle = sanitize(node["handle"])
            for i, m in enumerate(node.get("media", {}).get("edges", [])):
                img = m["node"].get("image")
                if img and img.get("url"):
                    url = img["url"].split("?")[0]
                    ext = url.rsplit(".", 1)[-1] if "." in url else "jpg"
                    dest = os.path.join(BASE_DIR, "products", handle, f"{i+1}.{ext}")
                    images.append((url, dest))
        if not data.get("pageInfo", {}).get("hasNextPage"):
            break
        cursor = data["pageInfo"]["endCursor"]
    return images


async def collect_collection_images(client):
    images = []
    cursor = None
    while True:
        result = await client.execute(COLLECTION_IMAGES_QUERY, {"first": 50, "cursor": cursor})
        data = (result.get("data") or {}).get("collections") or {}
        for edge in data.get("edges", []):
            node = edge["node"]
            img = node.get("image")
            if img and img.get("url"):
                url = img["url"].split("?")[0]
                ext = url.rsplit(".", 1)[-1] if "." in url else "jpg"
                handle = sanitize(node["handle"])
                dest = os.path.join(BASE_DIR, "collections", f"{handle}.{ext}")
                images.append((url, dest))
        if not data.get("pageInfo", {}).get("hasNextPage"):
            break
        cursor = data["pageInfo"]["endCursor"]
    return images


async def collect_files(client):
    files = []
    cursor = None
    while True:
        result = await client.execute(FILES_QUERY, {"first": 50, "cursor": cursor})
        data = (result.get("data") or {}).get("files") or {}
        for edge in data.get("edges", []):
            node = edge["node"]
            url = None
            if node.get("image"):
                url = node["image"].get("url")
            elif node.get("url"):
                url = node["url"]
            if url:
                url_clean = url.split("?")[0]
                filename = sanitize(url_clean.rsplit("/", 1)[-1])
                dest = os.path.join(BASE_DIR, "files", filename)
                files.append((url, dest))
        if not data.get("pageInfo", {}).get("hasNextPage"):
            break
        cursor = data["pageInfo"]["endCursor"]
    return files


async def collect_article_images(client):
    images = []
    cursor = None
    while True:
        result = await client.execute(BLOGS_QUERY, {"first": 20, "cursor": cursor})
        data = (result.get("data") or {}).get("blogs") or {}
        for edge in data.get("edges", []):
            blog = edge["node"]
            blog_handle = sanitize(blog["handle"])
            for art_edge in blog.get("articles", {}).get("edges", []):
                art = art_edge["node"]
                img = art.get("image")
                if img and img.get("url"):
                    url = img["url"].split("?")[0]
                    ext = url.rsplit(".", 1)[-1] if "." in url else "jpg"
                    art_handle = sanitize(art["handle"])
                    dest = os.path.join(BASE_DIR, "articles", blog_handle, f"{art_handle}.{ext}")
                    images.append((url, dest))
        if not data.get("pageInfo", {}).get("hasNextPage"):
            break
        cursor = data["pageInfo"]["endCursor"]
    return images


async def run():
    os.makedirs(BASE_DIR, exist_ok=True)
    semaphore = asyncio.Semaphore(10)

    async with GraphQLClient(SOURCE, 4) as client:
        console.print("\n[bold cyan]Collecting image URLs...[/bold cyan]")

        product_imgs = await collect_product_images(client)
        console.print(f"  Products:    {len(product_imgs)} images")

        coll_imgs = await collect_collection_images(client)
        console.print(f"  Collections: {len(coll_imgs)} images")

        files = await collect_files(client)
        console.print(f"  Files:       {len(files)} files")

        article_imgs = await collect_article_images(client)
        console.print(f"  Articles:    {len(article_imgs)} images")

    all_items = product_imgs + coll_imgs + files + article_imgs
    console.print(f"\n[bold green]Total: {len(all_items)} files to download[/bold green]")
    console.print(f"Destination: {os.path.abspath(BASE_DIR)}\n")

    downloaded = 0
    errors = 0

    async with aiohttp.ClientSession() as session:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Downloading...", total=len(all_items))
            tasks = [download_file(session, url, dest, semaphore) for url, dest in all_items]
            for coro in asyncio.as_completed(tasks):
                ok = await coro
                if ok:
                    downloaded += 1
                else:
                    errors += 1
                progress.advance(task)

    console.print(f"\n[green]Downloaded: {downloaded}[/green] | [red]Errors: {errors}[/red]")
    console.print(f"Saved to: {os.path.abspath(BASE_DIR)}")


if __name__ == "__main__":
    asyncio.run(run())
