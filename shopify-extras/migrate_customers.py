#!/usr/bin/env python3
"""
Migração de Clientes entre lojas Shopify via GraphQL Admin API.

Uso:
  python migrate_customers.py extract                      # Extrai clientes da loja origem
  python migrate_customers.py upload [--limit N] [--full]  # Envia para loja destino
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shopify-migration"))

from rich.console import Console

from config import SOURCE, DEST, MAX_CONCURRENT, DATA_DIR
from utils.graphql_client import GraphQLClient
from utils.state import StateManager
from utils.logger import MigrationLogger

console = Console()

CUSTOMERS_QUERY = """
query getCustomers($first: Int!, $cursor: String) {
  customers(first: $first, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id
        firstName
        lastName
        email
        phone
        taxExempt
        tags
        note
        locale
        createdAt
        emailMarketingConsent {
          marketingState
          consentUpdatedAt
          marketingOptInLevel
        }
        smsMarketingConsent {
          marketingState
          consentUpdatedAt
          marketingOptInLevel
        }
        addresses {
          address1
          address2
          city
          province
          provinceCode
          country
          countryCodeV2
          zip
          phone
          company
          firstName
          lastName
        }
        defaultAddress {
          address1
          address2
          city
          province
          provinceCode
          country
          countryCodeV2
          zip
          phone
          company
          firstName
          lastName
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
"""

CREATE_CUSTOMER = """
mutation customerCreate($input: CustomerInput!) {
  customerCreate(input: $input) {
    customer { id email }
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


async def extract_customers(client):
    console.print("\n[bold cyan]Extracting Customers...[/bold cyan]")
    customers = []
    cursor = None
    page = 0

    while True:
        result = await client.execute(CUSTOMERS_QUERY, {"first": 50, "cursor": cursor})
        data = (result.get("data") or {}).get("customers") or {}
        edges = data.get("edges", [])

        for edge in edges:
            node = edge["node"]
            node["metafields"] = [
                e["node"] for e in (node.get("metafields") or {}).get("edges", [])
                if e["node"].get("namespace") != "shopify"
            ]
            customers.append(node)

        page += 1
        console.print(f"  Page {page}: {len(customers)} customers", end="\r")

        page_info = data.get("pageInfo", {})
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")

    console.print(f"\n  Total: {len(customers)}")
    _save("customers.json", customers)


async def upload_customers(client, limit=None):
    label = f" (limit: {limit})" if limit else " (ALL)"
    console.print(f"\n[bold cyan]Uploading Customers{label}...[/bold cyan]")

    customers = _load("customers.json")
    if limit:
        customers = customers[:limit]

    logger = MigrationLogger("upload_customers")
    state = StateManager("dest_customers")

    for i, cust in enumerate(customers):
        email = cust.get("email", "")
        old_id = cust.get("id", "")
        key = email or old_id

        if state.is_done(key):
            continue

        cust_input = {}
        for field in ["firstName", "lastName", "email", "phone", "note", "locale"]:
            if cust.get(field):
                cust_input[field] = cust[field]

        if cust.get("tags"):
            cust_input["tags"] = cust["tags"]

        cust_input["taxExempt"] = cust.get("taxExempt", False)

        if cust.get("emailMarketingConsent"):
            c = cust["emailMarketingConsent"]
            entry = {"marketingState": c.get("marketingState"), "marketingOptInLevel": c.get("marketingOptInLevel")}
            if c.get("consentUpdatedAt"):
                entry["consentUpdatedAt"] = c["consentUpdatedAt"]
            cust_input["emailMarketingConsent"] = entry

        if cust.get("smsMarketingConsent"):
            c = cust["smsMarketingConsent"]
            entry = {"marketingState": c.get("marketingState"), "marketingOptInLevel": c.get("marketingOptInLevel")}
            if c.get("consentUpdatedAt"):
                entry["consentUpdatedAt"] = c["consentUpdatedAt"]
            cust_input["smsMarketingConsent"] = entry

        addresses = cust.get("addresses", [])
        if addresses:
            cust_input["addresses"] = []
            for addr in addresses:
                addr_input = {}
                for f in ["address1", "address2", "city", "province", "provinceCode",
                          "country", "countryCodeV2", "zip", "phone", "company", "firstName", "lastName"]:
                    if addr.get(f):
                        addr_input[f] = addr[f]
                if addr_input:
                    cust_input["addresses"].append(addr_input)

        if cust.get("metafields"):
            cust_input["metafields"] = [
                {"namespace": mf["namespace"], "key": mf["key"], "value": mf["value"], "type": mf["type"]}
                for mf in cust["metafields"]
            ]

        try:
            result = await client.execute(CREATE_CUSTOMER, {"input": cust_input})
            mut = (result.get("data") or {}).get("customerCreate") or {}
            user_errors = mut.get("userErrors", [])

            if user_errors:
                logger.error(key, "USER_ERROR", "; ".join(e["message"] for e in user_errors))
            else:
                new_cust = mut.get("customer")
                if new_cust:
                    state.mark_done(key, new_cust["id"])
                    logger.success(key, f"-> {new_cust['id']}")
                else:
                    logger.error(key, "NO_DATA", str(result)[:300])
        except Exception as e:
            logger.error(key, "EXCEPTION", str(e))

        if (i + 1) % 50 == 0:
            console.print(f"  Progress: {i + 1}/{len(customers)}")

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
        console.print("\n[bold green]═══ EXTRACT CUSTOMERS ═══[/bold green]")
        async with GraphQLClient(SOURCE, MAX_CONCURRENT) as client:
            await extract_customers(client)
        console.print("\n[bold green]═══ EXTRAÇÃO COMPLETA ═══[/bold green]")

    elif command == "upload":
        label = "TESTE" if limit else "COMPLETO"
        console.print(f"\n[bold green]═══ UPLOAD {label} ═══[/bold green]")
        async with GraphQLClient(DEST, MAX_CONCURRENT) as client:
            await upload_customers(client, limit)
        console.print("\n[bold green]═══ UPLOAD COMPLETO ═══[/bold green]")

    else:
        console.print("[yellow]Uso:[/yellow]")
        console.print("  python migrate_customers.py extract")
        console.print("  python migrate_customers.py upload [--limit N] [--full]")


if __name__ == "__main__":
    asyncio.run(run())
