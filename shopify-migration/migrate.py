#!/usr/bin/env python3
"""
Shopify Migration Tool — Orquestrador Principal
Migra ~55k produtos entre duas lojas Shopify com integridade total.

Uso:
  python migrate.py extract        # Fase 1: Extração
  python migrate.py prepare        # Fase 2: Preparação da estrutura
  python migrate.py ingest         # Fase 3: Ingestão e mapeamento
  python migrate.py remap          # Remapear metafields com referências
  python migrate.py validate       # Fase 4: Auditoria
  python migrate.py golive         # Ativar produtos + publicar
  python migrate.py full           # Fases 1-4 sequenciais (sem golive)
"""
import asyncio
import sys

from rich.console import Console

console = Console()


async def main():
    if len(sys.argv) < 2:
        console.print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "extract":
        from phases.phase1_extract import run
        await run()

    elif command == "prepare":
        from phases.phase2_prepare import run
        await run()

    elif command == "ingest":
        from phases.phase3_ingest import run
        await run()

    elif command == "remap":
        from utils.remap_references import remap_reference_metafields
        await remap_reference_metafields()

    elif command == "validate":
        from phases.phase4_validate import run
        await run()

    elif command == "golive":
        confirm = input("\n⚠️  Go-Live irá ATIVAR todos os produtos DRAFT. Confirmar? (yes/no): ")
        if confirm.strip().lower() == "yes":
            from phases.phase4_validate import go_live
            await go_live()
        else:
            console.print("[yellow]Go-Live cancelado.[/yellow]")

    elif command == "full":
        from phases.phase1_extract import run as run1
        from phases.phase2_prepare import run as run2
        from phases.phase3_ingest import run as run3
        from utils.remap_references import remap_reference_metafields
        from phases.phase4_validate import run as run4

        await run1()
        await run2()
        await run3()
        await remap_reference_metafields()
        await run4()

    else:
        console.print(f"[red]Unknown command: {command}[/red]")
        console.print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
