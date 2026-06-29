#!/usr/bin/env python3
"""
Migração de Encomendas entre lojas Shopify via GraphQL Admin API.
Extrai todas as encomendas com informação completa (itens, tracking, pagamento, etc.)
e importa na loja destino.

Uso:
  python migrate_orders.py extract                      # Extrai encomendas da loja origem
  python migrate_orders.py upload [--limit N] [--full]  # Envia para loja destino

Nota: A criação de encomendas na Shopify via API tem limitações.
Encomendas são criadas como "imported" e não processam pagamentos reais.
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

ORDERS_QUERY = """
query getOrders($first: Int!, $cursor: String) {
  orders(first: $first, after: $cursor, sortKey: CREATED_AT, query: "status:any") {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id
        name
        email
        phone
        createdAt
        processedAt
        closedAt
        cancelledAt
        cancelReason
        displayFinancialStatus
        displayFulfillmentStatus
        note
        tags
        currencyCode
        totalPriceSet { shopMoney { amount currencyCode } }
        subtotalPriceSet { shopMoney { amount currencyCode } }
        totalTaxSet { shopMoney { amount currencyCode } }
        totalShippingPriceSet { shopMoney { amount currencyCode } }
        totalDiscountsSet { shopMoney { amount currencyCode } }
        totalRefundedSet { shopMoney { amount currencyCode } }
        customer {
          id
          email
          firstName
          lastName
        }
        shippingAddress {
          firstName
          lastName
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
        }
        billingAddress {
          firstName
          lastName
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
        }
        lineItems(first: 100) {
          edges {
            node {
              title
              quantity
              originalUnitPriceSet { shopMoney { amount currencyCode } }
              discountedUnitPriceSet { shopMoney { amount currencyCode } }
              totalDiscountSet { shopMoney { amount currencyCode } }
              sku
              variantTitle
              vendor
              taxLines {
                title
                rate
                priceSet { shopMoney { amount currencyCode } }
              }
              product { id handle }
              variant { id }
            }
          }
        }
        shippingLines(first: 10) {
          edges {
            node {
              title
              code
              source
              originalPriceSet { shopMoney { amount currencyCode } }
              discountedPriceSet { shopMoney { amount currencyCode } }
              taxLines {
                title
                rate
                priceSet { shopMoney { amount currencyCode } }
              }
            }
          }
        }
        taxLines {
          title
          rate
          priceSet { shopMoney { amount currencyCode } }
        }
        fulfillments {
          id
          status
          createdAt
          trackingInfo {
            company
            number
            url
          }
          fulfillmentLineItems(first: 100) {
            edges {
              node {
                lineItem { title sku quantity }
                quantity
              }
            }
          }
        }
        transactions(first: 20) {
          gateway
          kind
          status
          amountSet { shopMoney { amount currencyCode } }
          processedAt
        }
        refunds {
          id
          createdAt
          note
          refundLineItems(first: 50) {
            edges {
              node {
                lineItem { title sku }
                quantity
                subtotalSet { shopMoney { amount currencyCode } }
              }
            }
          }
        }
        discountApplications(first: 20) {
          edges {
            node {
              allocationMethod
              targetSelection
              targetType
              value {
                ... on MoneyV2 { amount currencyCode }
                ... on PricingPercentageValue { percentage }
              }
            }
          }
        }
      }
    }
  }
}
"""

ORDER_CREATE = """
mutation orderCreate($order: OrderCreateOrderInput!, $options: OrderCreateOptionsInput) {
  orderCreate(order: $order, options: $options) {
    order { id name }
    userErrors { field message }
  }
}
"""

GET_FULFILLMENT_ORDERS = """
query($orderId: ID!) {
  order(id: $orderId) {
    fulfillmentOrders(first: 10) {
      edges {
        node {
          id
          status
          requestStatus
          assignedLocation { name }
          lineItems(first: 100) {
            edges { node { id remainingQuantity } }
          }
        }
      }
    }
  }
}
"""

FULFILLMENT_CREATE = """
mutation fulfillmentCreateV2($fulfillment: FulfillmentV2Input!) {
  fulfillmentCreateV2(fulfillment: $fulfillment) {
    fulfillment { id status }
    userErrors { field message }
  }
}
"""

FULFILLMENT_TRACKING_UPDATE = """
mutation fulfillmentTrackingInfoUpdateV2($fulfillmentId: ID!, $trackingInfoInput: FulfillmentTrackingInput!) {
  fulfillmentTrackingInfoUpdateV2(fulfillmentId: $fulfillmentId, trackingInfoInput: $trackingInfoInput) {
    fulfillment { id status }
    userErrors { field message }
  }
}
"""

GET_ORDER_FULFILLMENTS = """
query($orderId: ID!) {
  order(id: $orderId) {
    fulfillments {
      id
      trackingInfo { number company url }
    }
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


async def extract_orders(client):
    console.print("\n[bold cyan]Extracting Orders...[/bold cyan]")
    orders = []
    cursor = None
    page = 0

    while True:
        result = await client.execute(ORDERS_QUERY, {"first": 20, "cursor": cursor})
        data = (result.get("data") or {}).get("orders") or {}
        edges = data.get("edges", [])

        for edge in edges:
            node = edge["node"]
            node["lineItems"] = [
                e["node"] for e in (node.get("lineItems") or {}).get("edges", [])
            ]
            node["shippingLines"] = [
                e["node"] for e in (node.get("shippingLines") or {}).get("edges", [])
            ]
            node["discountApplications"] = [
                e["node"] for e in (node.get("discountApplications") or {}).get("edges", [])
            ]
            for ful in node.get("fulfillments", []):
                ful["fulfillmentLineItems"] = [
                    e["node"] for e in (ful.get("fulfillmentLineItems") or {}).get("edges", [])
                ]
            for ref in node.get("refunds", []):
                ref["refundLineItems"] = [
                    e["node"] for e in (ref.get("refundLineItems") or {}).get("edges", [])
                ]
            orders.append(node)

        page += 1
        console.print(f"  Page {page}: {len(orders)} orders", end="\r")

        page_info = data.get("pageInfo", {})
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")

    paid = sum(1 for o in orders if o.get("displayFinancialStatus") == "PAID")
    fulfilled = sum(1 for o in orders if o.get("displayFulfillmentStatus") == "FULFILLED")
    cancelled = sum(1 for o in orders if o.get("cancelledAt"))
    with_tracking = sum(1 for o in orders if any(
        f.get("trackingInfo") for f in o.get("fulfillments", [])
    ))

    console.print(f"\n  Total: {len(orders)}")
    console.print(f"  Paid: {paid} | Fulfilled: {fulfilled} | Cancelled: {cancelled} | With tracking: {with_tracking}")
    _save("orders.json", orders)


def _build_address(addr):
    if not addr:
        return None
    result = {}
    for f in ["firstName", "lastName", "address1", "address2", "city", "province",
              "provinceCode", "country", "zip", "phone", "company"]:
        if addr.get(f):
            result[f] = addr[f]
    if addr.get("countryCodeV2"):
        result["countryCode"] = addr["countryCodeV2"]
    return result if result else None


async def upload_orders(client, limit=None):
    label = f" (limit: {limit})" if limit else " (ALL)"
    console.print(f"\n[bold cyan]Uploading Orders{label}...[/bold cyan]")

    orders = _load("orders.json")
    if limit:
        orders = orders[:limit]

    customer_state = StateManager("dest_customers")
    logger = MigrationLogger("upload_orders")
    state = StateManager("dest_orders")

    for i, order in enumerate(orders):
        old_id = order.get("id", "")
        order_name = order.get("name", old_id)

        if state.is_done(old_id):
            continue

        line_items = []
        for item in order.get("lineItems", []):
            li = {
                "title": item.get("title", "Unknown"),
                "quantity": item.get("quantity", 1),
                "priceSet": item.get("originalUnitPriceSet"),
            }
            if item.get("sku"):
                li["sku"] = item["sku"]
            if item.get("taxLines"):
                li["taxLines"] = [
                    {
                        "title": t.get("title", "Tax"),
                        "rate": t.get("rate", 0),
                        "priceSet": t.get("priceSet"),
                    }
                    for t in item["taxLines"]
                ]
            line_items.append(li)

        if not line_items:
            logger.error(order_name, "SKIP", "No line items")
            continue

        order_input = {
            "lineItems": line_items,
            "currency": order.get("currencyCode", "EUR"),
            "financialStatus": (order.get("displayFinancialStatus") or "PAID").upper(),
        }

        if order.get("processedAt"):
            order_input["processedAt"] = order["processedAt"]
        if order.get("note"):
            order_input["note"] = order["note"]
        if order.get("tags"):
            order_input["tags"] = order["tags"]
        if order.get("email"):
            order_input["email"] = order["email"]
        if order.get("phone"):
            order_input["phone"] = order["phone"]

        if order.get("customer"):
            cust_email = order["customer"].get("email")
            new_cust_id = customer_state.get_new_id(cust_email) if cust_email else None
            if new_cust_id:
                order_input["customer"] = {"id": new_cust_id}

        shipping = _build_address(order.get("shippingAddress"))
        if shipping:
            order_input["shippingAddress"] = shipping

        billing = _build_address(order.get("billingAddress"))
        if billing:
            order_input["billingAddress"] = billing

        if order.get("shippingLines"):
            order_input["shippingLines"] = []
            for sl in order["shippingLines"]:
                sl_input = {"title": sl.get("title", "Shipping")}
                if sl.get("originalPriceSet"):
                    sl_input["priceSet"] = sl["originalPriceSet"]
                if sl.get("code"):
                    sl_input["code"] = sl["code"]
                if sl.get("taxLines"):
                    sl_input["taxLines"] = [
                        {"title": t.get("title", "Tax"), "rate": t.get("rate", 0), "priceSet": t.get("priceSet")}
                        for t in sl["taxLines"]
                    ]
                order_input["shippingLines"].append(sl_input)

        if order.get("transactions"):
            order_input["transactions"] = []
            for tx in order["transactions"]:
                tx_input = {
                    "kind": tx.get("kind", "SALE"),
                    "status": tx.get("status", "SUCCESS"),
                    "gateway": tx.get("gateway", "manual"),
                    "amountSet": tx.get("amountSet"),
                }
                if tx.get("processedAt"):
                    tx_input["processedAt"] = tx["processedAt"]
                order_input["transactions"].append(tx_input)

        try:
            result = await client.execute(ORDER_CREATE, {
                "order": order_input,
                "options": {"inventoryBehaviour": "BYPASS", "sendReceipt": False, "sendFulfillmentReceipt": False},
            })

            top_errors = result.get("errors", [])
            access_denied = any("Access denied" in str(e) for e in top_errors)

            mut = (result.get("data") or {}).get("orderCreate") or {}
            user_errors = mut.get("userErrors", [])
            new_order = mut.get("order")

            if user_errors:
                err_msg = "; ".join(e["message"] for e in user_errors)
                logger.error(order_name, "USER_ERROR", err_msg)
            elif not new_order and not access_denied:
                logger.error(order_name, "NO_DATA", str(result)[:300])
            else:
                order_id = new_order["id"] if new_order else None

                if not order_id and access_denied:
                    logger.error(order_name, "ACCESS_DENIED", "Order may have been created but response blocked by scope error")
                    continue

                state.mark_done(old_id, order_id)
                logger.success(order_name, f"-> {order_id}")

                fulfillments = order.get("fulfillments", [])
                if fulfillments and order_id:
                    try:
                        fo_result = await client.execute(GET_FULFILLMENT_ORDERS, {"orderId": order_id})
                        fo_data = (fo_result.get("data") or {}).get("order") or {}
                        fo_edges = (fo_data.get("fulfillmentOrders") or {}).get("edges", [])
                    except Exception:
                        fo_edges = []
                        console.print(f"  [yellow]{order_name}: Could not fetch fulfillmentOrders (missing scope?)[/yellow]")

                    for fo_edge in fo_edges:
                        fo_n = fo_edge["node"]
                        loc = (fo_n.get("assignedLocation") or {}).get("name", "?")
                        console.print(f"  [dim]{order_name}: FO status={fo_n.get('status')} request={fo_n.get('requestStatus')} location={loc}[/dim]")

                    for ful in fulfillments:
                        tracking = ful.get("trackingInfo", [])
                        if not fo_edges:
                            console.print(f"  [yellow]{order_name}: No fulfillment orders found[/yellow]")
                            continue

                        fo_line_items = []
                        fo_grouped = {}
                        for fo_edge in fo_edges:
                            fo_node = fo_edge["node"]
                            for li_edge in (fo_node.get("lineItems") or {}).get("edges", []):
                                li_node = li_edge["node"]
                                remaining = li_node.get("remainingQuantity", 0)
                                if remaining > 0:
                                    if fo_node["id"] not in fo_grouped:
                                        fo_grouped[fo_node["id"]] = []
                                    fo_grouped[fo_node["id"]].append(
                                        {"id": li_node["id"], "quantity": remaining}
                                    )
                        for fo_id, items in fo_grouped.items():
                            fo_line_items.append({
                                "fulfillmentOrderId": fo_id,
                                "fulfillmentOrderLineItems": items,
                            })

                        if not fo_line_items:
                            console.print(f"  [yellow]{order_name}: All items have remainingQuantity=0 (fulfillment may not be needed)[/yellow]")
                            continue

                        tracking_input = {}
                        if tracking:
                            t = tracking[0] if isinstance(tracking, list) else tracking
                            if t.get("number"):
                                tracking_input["number"] = t["number"]
                            if t.get("company"):
                                tracking_input["company"] = t["company"]
                            if t.get("url"):
                                tracking_input["url"] = t["url"]

                        ful_input = {
                            "lineItemsByFulfillmentOrder": fo_line_items,
                            "notifyCustomer": False,
                        }
                        if tracking_input:
                            ful_input["trackingInfo"] = tracking_input

                        try:
                            ful_result = await client.execute(FULFILLMENT_CREATE, {"fulfillment": ful_input})
                            ful_mut = (ful_result.get("data") or {}).get("fulfillmentCreateV2") or {}
                            ful_errors = ful_mut.get("userErrors", [])
                            if ful_errors:
                                console.print(f"  [yellow]Fulfillment error for {order_name}: {ful_errors}[/yellow]")
                            else:
                                console.print(f"  [green]Fulfillment + tracking created for {order_name}[/green]")
                        except Exception as fe:
                            console.print(f"  [yellow]Fulfillment failed for {order_name}: {fe}[/yellow]")
        except Exception as e:
            logger.error(order_name, "EXCEPTION", str(e))

        if (i + 1) % 20 == 0:
            console.print(f"  Progress: {i + 1}/{len(orders)}")

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
        console.print("\n[bold green]═══ EXTRACT ORDERS ═══[/bold green]")
        async with GraphQLClient(SOURCE, MAX_CONCURRENT) as client:
            await extract_orders(client)
        console.print("\n[bold green]═══ EXTRAÇÃO COMPLETA ═══[/bold green]")

    elif command == "upload":
        label = "TESTE" if limit else "COMPLETO"
        console.print(f"\n[bold green]═══ UPLOAD {label} ═══[/bold green]")
        async with GraphQLClient(DEST, MAX_CONCURRENT) as client:
            await upload_orders(client, limit)
        console.print("\n[bold green]═══ UPLOAD COMPLETO ═══[/bold green]")

    else:
        console.print("[yellow]Uso:[/yellow]")
        console.print("  python migrate_orders.py extract")
        console.print("  python migrate_orders.py upload [--limit N] [--full]")


if __name__ == "__main__":
    asyncio.run(run())
