#!/usr/bin/env python3
"""
Migração de Ficheiros/Imagens entre lojas Shopify via GraphQL Admin API.
Exporta todos os ficheiros com os nomes originais e importa na loja destino.
Valida duplicados por filename antes de enviar.

Uso:
  python migrate_files.py extract                      # Extrai lista de ficheiros da loja origem
  python migrate_files.py upload [--limit N] [--full]  # Envia para loja destino
"""
import asyncio
import json
import os
import sys

from rich.console import Console

from config import SOURCE, DEST, MAX_CONCURRENT, DATA_DIR
from utils.graphql_client import GraphQLClient
from utils.state import StateManager
from utils.logger import MigrationLogger

console = Console()

FILES_QUERY = """
query getFiles($first: Int!, $cursor: String) {
  files(first: $first, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        ... on MediaImage {
          id
          alt
          fileStatus
          image {
            url
            width
            height
          }
          originalFileSize
          mimeType
        }
        ... on GenericFile {
          id
          alt
          fileStatus
          url
          originalFileSize
          mimeType
        }
        ... on Video {
          id
          alt
          fileStatus
          originalFileSize
          sources {
            url
            mimeType
            format
            height
            width
          }
        }
      }
    }
  }
}
"""

FILE_CREATE = """
mutation fileCreate($files: [FileCreateInput!]!) {
  fileCreate(files: $files) {
    files {
      id
      alt
      fileStatus
    }
    userErrors { field message }
  }
}
"""


def _save(filename, data):
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    console.print(f"  Saved {path} (ok)")


def _load(filename):
    path = os.path.join(DATA_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _extract_filename(url):
    if not url:
        return None
    return url.split("?")[0].split("/")[-1]


async def _fetch_all_files(client, label=""):
    files = []
    cursor = None
    page = 0

    while True:
        result = await client.execute(FILES_QUERY, {"first": 50, "cursor": cursor})
        data = (result.get("data") or {}).get("files") or {}
        edges = data.get("edges", [])

        for edge in edges:
            node = edge["node"]
            if not node.get("id"):
                continue

            file_entry = {
                "id": node["id"],
                "alt": node.get("alt", ""),
                "fileStatus": node.get("fileStatus"),
                "mimeType": node.get("mimeType"),
                "originalFileSize": node.get("originalFileSize"),
            }

            if node.get("image"):
                file_entry["type"] = "IMAGE"
                file_entry["url"] = node["image"].get("url")
                file_entry["width"] = node["image"].get("width")
                file_entry["height"] = node["image"].get("height")
            elif node.get("sources"):
                file_entry["type"] = "VIDEO"
                if node["sources"]:
                    file_entry["url"] = node["sources"][0].get("url")
            elif node.get("url"):
                file_entry["type"] = "GENERIC"
                file_entry["url"] = node["url"]
            else:
                continue

            file_entry["filename"] = _extract_filename(file_entry.get("url"))
            files.append(file_entry)

        page += 1
        console.print(f"  {label}Page {page}: {len(files)} files", end="\r")

        page_info = data.get("pageInfo", {})
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")

    console.print()
    return files


async def extract_files(client):
    console.print("\n[bold cyan]Extracting Files from Source...[/bold cyan]")
    files = await _fetch_all_files(client, label="[SOURCE] ")

    images = sum(1 for f in files if f.get("type") == "IMAGE")
    videos = sum(1 for f in files if f.get("type") == "VIDEO")
    generic = sum(1 for f in files if f.get("type") == "GENERIC")

    console.print(f"  Total: {len(files)} (Images: {images}, Videos: {videos}, Generic: {generic})")
    _save("files.json", files)


async def upload_files(client, limit=None):
    label = f" (limit: {limit})" if limit else " (ALL)"
    console.print(f"\n[bold cyan]Uploading Files{label}...[/bold cyan]")

    source_files = _load("files.json")
    if limit:
        source_files = source_files[:limit]

    console.print("  [cyan]Fetching existing files from destination to check duplicates...[/cyan]")
    dest_files = await _fetch_all_files(client, label="[DEST] ")
    existing_filenames = set()
    for f in dest_files:
        fn = f.get("filename")
        if fn:
            existing_filenames.add(fn.lower())
    console.print(f"  [dim]Found {len(existing_filenames)} existing files in destination[/dim]")

    logger = MigrationLogger("upload_files")
    state = StateManager("dest_files")
    skipped_duplicates = 0

    batch_size = 10
    for i in range(0, len(source_files), batch_size):
        batch = source_files[i:i + batch_size]
        create_inputs = []

        for file in batch:
            old_id = file.get("id", "")
            if state.is_done(old_id):
                continue

            filename = file.get("filename", "")
            if filename and filename.lower() in existing_filenames:
                skipped_duplicates += 1
                state.mark_done(old_id, "duplicate")
                continue

            url = file.get("url")
            if not url:
                continue

            file_input = {
                "originalSource": url,
                "alt": file.get("alt", ""),
                "contentType": file.get("type", "IMAGE"),
            }

            if filename:
                file_input["filename"] = filename

            create_inputs.append((old_id, file_input, filename))

        if not create_inputs:
            continue

        try:
            result = await client.execute(FILE_CREATE, {
                "files": [inp for _, inp, _ in create_inputs],
            })

            mut = (result.get("data") or {}).get("fileCreate") or {}
            user_errors = mut.get("userErrors", [])

            if user_errors:
                err_msg = "; ".join(e["message"] for e in user_errors)
                for old_id, _, _ in create_inputs:
                    logger.error(old_id, "USER_ERROR", err_msg)
            else:
                new_files = mut.get("files", [])
                for idx, (old_id, _, fn) in enumerate(create_inputs):
                    if idx < len(new_files) and new_files[idx]:
                        state.mark_done(old_id, new_files[idx]["id"])
                        logger.success(old_id, f"{fn} -> {new_files[idx]['id']}")
                        if fn:
                            existing_filenames.add(fn.lower())
                    else:
                        logger.error(old_id, "NO_DATA", "No file returned")
        except Exception as e:
            for old_id, _, _ in create_inputs:
                logger.error(old_id, "EXCEPTION", str(e))

        processed = min(i + batch_size, len(source_files))
        if processed % 50 == 0 or processed == len(source_files):
            console.print(f"  Progress: {processed}/{len(source_files)} (skipped {skipped_duplicates} duplicates)")

    if skipped_duplicates:
        console.print(f"  [yellow]Skipped {skipped_duplicates} duplicate files (already exist in destination)[/yellow]")
    console.print(f"  {logger.summary()}")
    logger.close()


async def run():
    args = sys.argv[1:]
    command = args[0] if args else ""
    limit = 50

    if "--full" in args:
        limit = None
    elif "--limit" in args:
        idx = args.index("--limit")
        if idx + 1 < len(args):
            limit = int(args[idx + 1])

    if command == "extract":
        console.print("\n[bold green]═══ EXTRACT FILES ═══[/bold green]")
        async with GraphQLClient(SOURCE, MAX_CONCURRENT) as client:
            await extract_files(client)
        console.print("\n[bold green]═══ EXTRAÇÃO COMPLETA ═══[/bold green]")

    elif command == "upload":
        label = "TESTE" if limit else "COMPLETO"
        console.print(f"\n[bold green]═══ UPLOAD {label} ═══[/bold green]")
        async with GraphQLClient(DEST, MAX_CONCURRENT) as client:
            await upload_files(client, limit)
        console.print("\n[bold green]═══ UPLOAD COMPLETO ═══[/bold green]")

    else:
        console.print("[yellow]Uso:[/yellow]")
        console.print("  python migrate_files.py extract")
        console.print("  python migrate_files.py upload [--limit N] [--full]")


if __name__ == "__main__":
    asyncio.run(run())
