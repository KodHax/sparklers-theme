#!/usr/bin/env python3
"""
Fase 2: Merge local dos 3 ficheiros de extração.
Cruza produtos_base.json + produtos_meta_seo.json + mapa_colecoes.json
usando o `handle` como chave primária.
Gera: data_ready/migracao_pronta.json
"""
import json
import os
from collections import defaultdict

from rich.console import Console
from rich.table import Table

from config import DATA_DIR

console = Console()
READY_DIR = os.path.join(os.path.dirname(DATA_DIR), "data_ready")


def _load(filename: str):
    path = os.path.join(DATA_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def run():
    console.print("\n[bold green]═══ MERGE LOCAL ═══[/bold green]\n")

    products_base = _load("produtos_base.json")
    meta_seo = _load("produtos_meta_seo.json")
    collections = _load("mapa_colecoes.json")

    console.print(f"  produtos_base.json:     {len(products_base)} produtos")
    console.print(f"  produtos_meta_seo.json: {len(meta_seo)} produtos")
    console.print(f"  mapa_colecoes.json:     {len(collections)} coleções")

    meta_index = {}
    for p in meta_seo:
        handle = p.get("handle")
        if handle:
            meta_index[handle] = {
                "seo": p.get("seo", {}),
                "metafields": [e["node"] for e in p.get("metafields", {}).get("edges", [])],
            }

    collection_index = defaultdict(list)
    for coll in collections:
        coll_handle = coll.get("handle")
        for prod_handle in coll.get("_product_handles", []):
            collection_index[prod_handle].append(coll_handle)

    merged = []
    missing_meta = 0

    for product in products_base:
        handle = product.get("handle")

        images = [e["node"] for e in product.get("images", {}).get("edges", [])]
        variants = [e["node"] for e in product.get("variants", {}).get("edges", [])]

        entry = {
            "id": product.get("id"),
            "title": product.get("title"),
            "handle": handle,
            "descriptionHtml": product.get("descriptionHtml", ""),
            "vendor": product.get("vendor"),
            "productType": product.get("productType"),
            "status": product.get("status"),
            "tags": product.get("tags", []),
            "templateSuffix": product.get("templateSuffix"),
            "options": product.get("options", []),
            "images": [
                {"url": img.get("url"), "altText": img.get("altText", "")}
                for img in images
            ],
            "variants": [],
            "colecoes_alvo": collection_index.get(handle, []),
        }

        meta = meta_index.get(handle)
        if meta:
            entry["seo"] = meta["seo"]
            entry["metafields"] = meta["metafields"]
        else:
            entry["seo"] = {}
            entry["metafields"] = []
            missing_meta += 1

        for v in variants:
            inv_item = v.get("inventoryItem", {}) or {}
            measurement = inv_item.get("measurement", {}) or {}
            weight = measurement.get("weight", {}) or {}

            entry["variants"].append({
                "id": v.get("id"),
                "title": v.get("title"),
                "price": v.get("price"),
                "compareAtPrice": v.get("compareAtPrice"),
                "sku": v.get("sku"),
                "barcode": v.get("barcode"),
                "weight": weight.get("value"),
                "weightUnit": weight.get("unit"),
                "selectedOptions": v.get("selectedOptions", []),
                "inventoryItemId": inv_item.get("id"),
                "tracked": inv_item.get("tracked", False),
            })

        merged.append(entry)

    os.makedirs(READY_DIR, exist_ok=True)
    out_path = os.path.join(READY_DIR, "migracao_pronta.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    table = Table(title="Merge Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Total Products", str(len(merged)))
    table.add_row("With Metafields/SEO", str(len(merged) - missing_meta))
    table.add_row("Missing Meta Match", str(missing_meta))
    table.add_row("Total Variants", str(sum(len(p["variants"]) for p in merged)))
    table.add_row("Total Images", str(sum(len(p["images"]) for p in merged)))
    table.add_row("Products in Collections", str(sum(1 for p in merged if p["colecoes_alvo"])))
    table.add_row("Output", out_path)
    console.print(table)

    console.print("\n[bold green]═══ MERGE COMPLETO ═══[/bold green]")


if __name__ == "__main__":
    run()
