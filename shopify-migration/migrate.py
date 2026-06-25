#!/usr/bin/env python3
"""
Shopify Migration Tool — Orquestrador Principal

Uso:
  python extract_steps.py all          # Fase 1: Extrair (3 queries leves)
  python extract_steps.py base         # Só produtos base
  python extract_steps.py colecoes     # Só coleções
  python extract_steps.py meta         # Só SEO + metafields

  python merge_data.py                 # Fase 2: Merge local -> migracao_pronta.json

  python upload_test.py                # Fase 3: Upload teste (50 produtos)
  python upload_test.py --limit 10     # Upload teste (10 produtos)
  python upload_test.py --full         # Upload TODOS os produtos
  python upload_test.py defs           # Só criar metafield definitions
  python upload_test.py colecoes       # Só criar coleções
  python upload_test.py produtos       # Só upload produtos
  python upload_test.py associar       # Só associar coleções
"""
import asyncio
import sys

from rich.console import Console

console = Console()


async def main():
    if len(sys.argv) < 2:
        console.print(__doc__)
        sys.exit(0)

    command = sys.argv[1].lower()

    if command == "extract":
        from extract_steps import run
        cmd = sys.argv[2] if len(sys.argv) > 2 else "all"
        await run(cmd)

    elif command == "merge":
        from merge_data import run
        run()

    elif command == "upload":
        from upload_test import run
        await run()

    else:
        console.print(f"[red]Unknown: {command}[/red]")
        console.print(__doc__)


if __name__ == "__main__":
    asyncio.run(main())
