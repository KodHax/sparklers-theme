#!/usr/bin/env python3
"""
Fase 2: Merge local dos ficheiros de extração.
Cruza produtos_base + produtos_meta_seo + mapa_colecoes + metaobjects
usando o `handle` como chave primária.
Resolve referências de metaobjects nos metafields dos produtos.
Gera: data_ready/migracao_pronta.json
"""
import json
import os
import re
from collections import defaultdict

from rich.console import Console
from rich.table import Table

from config import DATA_DIR

console = Console()
READY_DIR = os.path.join(os.path.dirname(DATA_DIR), "data_ready")

GID_PATTERN = re.compile(r"gid://shopify/Metaobject/(\d+)")

REFERENCE_TYPES = {
    "metaobject_reference",
    "list.metaobject_reference",
    "file_reference",
    "list.file_reference",
}


def _load(filename: str):
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_metaobject_index(entries: list) -> dict:
    """Index metaobject entries by ID for fast lookup."""
    index = {}
    for entry in entries:
        mo_id = entry.get("id", "")
        index[mo_id] = {
            "id": mo_id,
            "handle": entry.get("handle"),
            "type": entry.get("type"),
            "fields": {},
        }
        for field in entry.get("fields", []):
            field_data = {
                "key": field.get("key"),
                "value": field.get("value"),
                "type": field.get("type"),
            }
            ref = field.get("reference")
            if ref:
                field_data["reference"] = ref
            index[mo_id]["fields"][field["key"]] = field_data
    return index


def _resolve_metafield_references(metafields: list, mo_index: dict) -> list:
    """Enrich metafields that contain metaobject references with the actual data."""
    resolved = []
    for mf in metafields:
        mf_copy = dict(mf)
        mf_type = mf.get("type", "")
        value = mf.get("value", "")

        if mf_type in REFERENCE_TYPES and value:
            if mf_type.startswith("list."):
                try:
                    ids = json.loads(value)
                    refs = [mo_index.get(gid) for gid in ids if mo_index.get(gid)]
                    if refs:
                        mf_copy["_resolved_references"] = refs
                except (json.JSONDecodeError, TypeError):
                    pass
            else:
                ref = mo_index.get(value)
                if ref:
                    mf_copy["_resolved_reference"] = ref

        resolved.append(mf_copy)
    return resolved


def run():
    console.print("\n[bold green]═══ MERGE LOCAL ═══[/bold green]\n")

    products_base = _load("produtos_base.json")
    meta_seo = _load("produtos_meta_seo.json")
    collections = _load("mapa_colecoes.json")
    metaobjects = _load("metaobjects.json")
    mo_definitions = _load("metaobject_definitions.json")

    if not products_base:
        console.print("[red]produtos_base.json não encontrado. Corre extract_steps.py primeiro.[/red]")
        return

    console.print(f"  produtos_base.json:           {len(products_base)} produtos")
    console.print(f"  produtos_meta_seo.json:       {len(meta_seo) if meta_seo else 0} produtos")
    console.print(f"  mapa_colecoes.json:           {len(collections) if collections else 0} coleções")
    console.print(f"  metaobject_definitions.json:  {len(mo_definitions) if mo_definitions else 0} definitions")
    console.print(f"  metaobjects.json:             {len(metaobjects) if metaobjects else 0} entries")

    inventory = _load("inventory_levels.json")
    console.print(f"  inventory_levels.json:         {len(inventory) if inventory else 0} items")

    mo_index = _build_metaobject_index(metaobjects) if metaobjects else {}

    meta_index = {}
    if meta_seo:
        for p in meta_seo:
            handle = p.get("handle")
            if handle:
                meta_index[handle] = {
                    "seo": p.get("seo", {}),
                    "metafields": [e["node"] for e in p.get("metafields", {}).get("edges", [])],
                }

    collection_index = defaultdict(list)
    if collections:
        for coll in collections:
            coll_handle = coll.get("handle")
            for prod_handle in coll.get("_product_handles", []):
                collection_index[prod_handle].append(coll_handle)

    merged = []
    missing_meta = 0
    resolved_refs = 0

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
            metafields = meta["metafields"]
            if mo_index:
                metafields = _resolve_metafield_references(metafields, mo_index)
                for mf in metafields:
                    if "_resolved_reference" in mf or "_resolved_references" in mf:
                        resolved_refs += 1
            entry["metafields"] = metafields
        else:
            entry["seo"] = {}
            entry["metafields"] = []
            missing_meta += 1

        for v in variants:
            inv_item = v.get("inventoryItem", {}) or {}
            measurement = inv_item.get("measurement", {}) or {}
            weight = measurement.get("weight", {}) or {}

            variant_entry = {
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
            }

            if inventory and inv_item.get("id"):
                levels = inventory.get(inv_item["id"], [])
                if levels:
                    variant_entry["inventoryLevels"] = levels

            entry["variants"].append(variant_entry)

        merged.append(entry)

    os.makedirs(READY_DIR, exist_ok=True)
    out_path = os.path.join(READY_DIR, "migracao_pronta.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    mo_out_path = os.path.join(READY_DIR, "metaobjects_ready.json")
    if metaobjects and mo_definitions:
        mo_ready = {
            "definitions": mo_definitions,
            "entries": metaobjects,
        }
        with open(mo_out_path, "w", encoding="utf-8") as f:
            json.dump(mo_ready, f, ensure_ascii=False, indent=2)

    table = Table(title="Merge Summary", title_style="bold green")
    table.add_column("Metric", style="cyan", min_width=35)
    table.add_column("Value", style="green", justify="right")
    table.add_row("Total Products", f"{len(merged):,}")
    table.add_row("With Metafields/SEO", f"{len(merged) - missing_meta:,}")
    table.add_row("Missing Meta Match", str(missing_meta))
    table.add_row("Total Variants", f"{sum(len(p['variants']) for p in merged):,}")
    table.add_row("Total Images", f"{sum(len(p['images']) for p in merged):,}")
    table.add_row("Products in Collections", f"{sum(1 for p in merged if p['colecoes_alvo']):,}")
    table.add_row("Metaobject Refs Resolved", f"{resolved_refs:,}")
    table.add_row("Metaobjects (definitions)", f"{len(mo_definitions) if mo_definitions else 0}")
    table.add_row("Metaobjects (entries)", f"{len(metaobjects) if metaobjects else 0}")
    table.add_row("Output (products)", out_path)
    if metaobjects:
        table.add_row("Output (metaobjects)", mo_out_path)
    console.print(table)

    console.print("\n[bold green]═══ MERGE COMPLETO ═══[/bold green]")


if __name__ == "__main__":
    run()
