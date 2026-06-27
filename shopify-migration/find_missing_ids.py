import asyncio
from config import SOURCE, DEST, MAX_CONCURRENT
from utils.graphql_client import GraphQLClient

PRODUCT_QUERY = """
query($id: ID!) {
  product(id: $id) {
    id
    title
    handle
    status
  }
}
"""

VARIANT_QUERY = """
query($id: ID!) {
  productVariant(id: $id) {
    id
    title
    sku
    product { id title handle }
  }
}
"""

missing_pids = ["55609143067001", "55609143361913"]
missing_vids = ["55609127371129", "15083013374329"]


async def run():
    async with GraphQLClient(SOURCE, MAX_CONCURRENT) as client:
        print("=== MISSING PRODUCTS ===")
        for pid in missing_pids:
            gid = f"gid://shopify/Product/{pid}"
            result = await client.execute(PRODUCT_QUERY, {"id": gid})
            product = (result.get("data") or {}).get("product")
            if product:
                print(f"  {pid}: {product['title']} (handle: {product['handle']}, status: {product['status']})")
            else:
                print(f"  {pid}: NOT FOUND (deleted?)")

        print()
        print("=== MISSING VARIANTS ===")
        for vid in missing_vids:
            gid = f"gid://shopify/ProductVariant/{vid}"
            result = await client.execute(VARIANT_QUERY, {"id": gid})
            variant = (result.get("data") or {}).get("productVariant")
            if variant:
                prod = variant.get("product", {})
                print(f"  {vid}: {variant['title']} (sku: {variant.get('sku')}, product: {prod.get('title')} - {prod.get('handle')})")
            else:
                print(f"  {vid}: NOT FOUND (deleted?)")


asyncio.run(run())
