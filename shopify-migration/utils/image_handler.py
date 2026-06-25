import asyncio
import os
import httpx
from rich.console import Console

console = Console()


async def upload_via_staged_upload(client, dest_config, image_url: str, filename: str) -> str | None:
    """Fallback: download image locally then upload via stagedUploadsCreate."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as http:
            resp = await http.get(image_url)
            resp.raise_for_status()
            image_data = resp.content
    except Exception as e:
        console.print(f"[red]Failed to download image {image_url}: {e}[/red]")
        return None

    mutation = """
    mutation stagedUploadsCreate($input: [StagedUploadInput!]!) {
      stagedUploadsCreate(input: $input) {
        stagedTargets {
          url
          resourceUrl
          parameters { name value }
        }
        userErrors { field message }
      }
    }
    """
    variables = {
        "input": [{
            "resource": "IMAGE",
            "filename": filename,
            "mimeType": _guess_mime(filename),
            "httpMethod": "POST",
        }]
    }

    result = await client.execute(mutation, variables)
    targets = result.get("data", {}).get("stagedUploadsCreate", {}).get("stagedTargets", [])
    if not targets:
        return None

    target = targets[0]
    form_data = {p["name"]: p["value"] for p in target["parameters"]}

    async with httpx.AsyncClient(timeout=60.0) as http:
        resp = await http.post(
            target["url"],
            data=form_data,
            files={"file": (filename, image_data, _guess_mime(filename))},
        )
        if resp.status_code not in (200, 201):
            console.print(f"[red]Staged upload failed: {resp.status_code}[/red]")
            return None

    return target["resourceUrl"]


def _guess_mime(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    return {
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
    }.get(ext, "image/jpeg")
