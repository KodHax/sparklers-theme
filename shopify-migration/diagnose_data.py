#!/usr/bin/env python3
"""
Diagnóstico: detecta duplicados, valida integridade e cruza dados extraídos.

Uso:
  python diagnose_data.py
"""
import json
import os
from collections import Counter

from rich.console import Console
from rich.table import Table

from config import DATA_DIR

console = Console()


def _load(filename: str):
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def diagnose_products():
    console.print("\n[bold green]═══ DIAGNÓSTICO DE DADOS EXTRAÍDOS ═══[/bold green]\n")

    products = _load("produtos_base.json")
    if not products:
        console.print("[red]produtos_base.json não encontrado.[/red]")
        return

    # ─── Duplicados de Produtos ───
    console.print("[bold cyan]1. Duplicados de Produtos[/bold cyan]")

    all_handles = [p.get("handle", "") for p in products]
    all_ids = [p.get("id", "") for p in products]

    handle_counts = Counter(all_handles)
    id_counts = Counter(all_ids)

    dup_handles = {h: c for h, c in handle_counts.items() if c > 1}
    dup_ids = {i: c for i, c in id_counts.items() if c > 1}

    if dup_handles:
        dup_table = Table(title="Handles Duplicados", title_style="bold red")
        dup_table.add_column("Handle", style="red")
        dup_table.add_column("Ocorrências", justify="right")
        for h, c in sorted(dup_handles.items(), key=lambda x: -x[1])[:20]:
            dup_table.add_row(h, str(c))
        console.print(dup_table)
        console.print(f"  Total handles duplicados: {len(dup_handles)}")
        console.print(f"  Produtos extra por duplicação: {sum(c - 1 for c in dup_handles.values())}")
    else:
        console.print("  [green]Sem handles duplicados.[/green]")

    if dup_ids:
        console.print(f"  [red]IDs duplicados: {len(dup_ids)}[/red]")
        for i, c in list(dup_ids.items())[:5]:
            console.print(f"    {i} — {c}x")
    else:
        console.print("  [green]Sem IDs duplicados.[/green]")

    unique_products = len(set(all_handles))
    console.print(f"\n  Produtos totais no ficheiro: {len(products)}")
    console.print(f"  Handles únicos: {unique_products}")

    # ─── Variantes ───
    console.print("\n[bold cyan]2. Análise de Variantes[/bold cyan]")

    total_variants = 0
    all_variant_ids = []
    all_skus = []
    products_by_variant_count = Counter()

    for p in products:
        variants = p.get("variants", {}).get("edges", [])
        n = len(variants)
        total_variants += n
        products_by_variant_count[n] += 1
        for v in variants:
            vid = v["node"].get("id", "")
            sku = v["node"].get("sku", "")
            all_variant_ids.append(vid)
            if sku:
                all_skus.append(sku)

    unique_variant_ids = len(set(all_variant_ids))
    dup_variant_ids = total_variants - unique_variant_ids

    sku_counts = Counter(all_skus)
    dup_skus = {s: c for s, c in sku_counts.items() if c > 1}

    var_table = Table(title="Resumo de Variantes", title_style="bold blue")
    var_table.add_column("Metric", style="cyan", min_width=35)
    var_table.add_column("Value", style="white", justify="right")
    var_table.add_row("Total variantes no ficheiro", f"{total_variants:,}")
    var_table.add_row("Variant IDs únicos", f"{unique_variant_ids:,}")
    var_table.add_row("Variant IDs duplicados", f"{dup_variant_ids:,}")
    var_table.add_row("SKUs com valor", f"{len(all_skus):,}")
    var_table.add_row("SKUs únicos", f"{len(set(all_skus)):,}")
    var_table.add_row("SKUs duplicados (mesmo SKU, n>1)", f"{len(dup_skus):,}")
    console.print(var_table)

    if dup_variant_ids > 0:
        vid_counts = Counter(all_variant_ids)
        console.print(f"\n  [red]⚠ {dup_variant_ids} variant IDs duplicados![/red]")
        console.print(f"  Isto explica o MISMATCH — mesmas variantes contadas múltiplas vezes.")
        for vid, c in sorted(vid_counts.items(), key=lambda x: -x[1])[:5]:
            if c > 1:
                console.print(f"    {vid} — {c}x")

    if dup_skus:
        console.print(f"\n  [yellow]SKUs duplicados (top 10):[/yellow]")
        for s, c in sorted(dup_skus.items(), key=lambda x: -x[1])[:10]:
            console.print(f"    '{s}' — {c}x")

    # ─── Variantes: contagem real (únicas) ───
    console.print(f"\n  [bold]Contagem real de variantes (IDs únicos): {unique_variant_ids:,}[/bold]")

    # ─── Meta/SEO cruzamento ───
    console.print("\n[bold cyan]3. Cruzamento com Meta/SEO[/bold cyan]")
    meta_seo = _load("produtos_meta_seo.json")
    if meta_seo:
        meta_handles = set(p.get("handle", "") for p in meta_seo)
        base_handles = set(all_handles)
        in_base_not_meta = base_handles - meta_handles
        in_meta_not_base = meta_handles - base_handles

        cross_table = Table(title_style="dim")
        cross_table.add_column("Metric", style="cyan", min_width=35)
        cross_table.add_column("Value", style="white", justify="right")
        cross_table.add_row("Handles em produtos_base", f"{len(base_handles):,}")
        cross_table.add_row("Handles em meta_seo", f"{len(meta_handles):,}")
        cross_table.add_row("Em base mas não em meta", f"{len(in_base_not_meta):,}")
        cross_table.add_row("Em meta mas não em base", f"{len(in_meta_not_base):,}")
        console.print(cross_table)

        if in_base_not_meta:
            console.print(f"  [yellow]Produtos sem meta/SEO (primeiros 5):[/yellow]")
            for h in list(in_base_not_meta)[:5]:
                console.print(f"    {h}")
    else:
        console.print("  [yellow]produtos_meta_seo.json não encontrado.[/yellow]")

    # ─── Coleções cruzamento ───
    console.print("\n[bold cyan]4. Cruzamento com Coleções[/bold cyan]")
    collections = _load("mapa_colecoes.json")
    if collections:
        base_handles = set(all_handles)
        coll_handles = set()
        for c in collections:
            for h in c.get("_product_handles", []):
                coll_handles.add(h)

        orphan_products = base_handles - coll_handles
        ghost_refs = coll_handles - base_handles

        coll_table = Table(title_style="dim")
        coll_table.add_column("Metric", style="cyan", min_width=35)
        coll_table.add_column("Value", style="white", justify="right")
        coll_table.add_row("Produtos em pelo menos 1 coleção", f"{len(base_handles & coll_handles):,}")
        coll_table.add_row("Produtos sem coleção (órfãos)", f"{len(orphan_products):,}")
        coll_table.add_row("Refs em coleções sem produto", f"{len(ghost_refs):,}")
        console.print(coll_table)

        if ghost_refs:
            console.print(f"  [yellow]Handles referenciados em coleções mas não extraídos (primeiros 5):[/yellow]")
            for h in list(ghost_refs)[:5]:
                console.print(f"    {h}")
    else:
        console.print("  [yellow]mapa_colecoes.json não encontrado.[/yellow]")

    console.print(f"\n[bold green]═══ DIAGNÓSTICO COMPLETO ═══[/bold green]\n")


if __name__ == "__main__":
    diagnose_products()
