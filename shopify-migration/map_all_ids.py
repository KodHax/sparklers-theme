import asyncio
from config import SOURCE, DEST, MAX_CONCURRENT
from utils.graphql_client import GraphQLClient

PRODUCT_QUERY = """
query($id: ID!) {
  product(id: $id) {
    id
    title
    handle
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

PRODUCT_BY_HANDLE = """
query($query: String!) {
  products(first: 1, query: $query) {
    edges {
      node {
        id
        title
        handle
        variants(first: 100) {
          edges { node { id title sku } }
        }
      }
    }
  }
}
"""

old_pids = "15083014062457,15254643900793,15083017404793,15428832461177,15083013407097,15357132210553,15083016716665,15083017372025,15083016618361,15357131850105,15083015569785,15083016585593,15303261061497,15083017699705,15083015373177,15083013898617,15083017732473,15083014291833,15083017503097,15083016520057,15083017634169,15083017601401,15083014947193,55609143067001,15404702597497,15370266542457,15083014586745,15083014652281,15083014553977,15083013734777,15083017437561,15083014488441,55609143361913,15083016847737".split(",")

old_vids = "55974783025529,55935482429817,55984871604601,56140138185081,55978713022841,55896084873593,56223877792121,56223877824889,55978829971833,55609143361913,55609127371129,15083013374329,57186808136057,57186808168825,63778682306937,55978804216185,56030781145465,56694835413369".split(",")


async def run():
    # Step 1: Go to SOURCE store, get handle for each old product/variant
    print("=== STEP 1: Fetching from SOURCE store ===\n")
    product_handles = {}  # old_pid -> handle
    variant_info = {}  # old_vid -> (handle, variant_index, sku)

    async with GraphQLClient(SOURCE, MAX_CONCURRENT) as src:
        print("--- Products ---")
        for pid in old_pids:
            gid = f"gid://shopify/Product/{pid}"
            result = await src.execute(PRODUCT_QUERY, {"id": gid})
            product = (result.get("data") or {}).get("product")
            if product:
                handle = product["handle"]
                product_handles[pid] = handle
                print(f"  {pid}: {product['title']} ({handle})")
            else:
                product_handles[pid] = None
                print(f"  {pid}: NOT FOUND")

        print("\n--- Variants ---")
        for vid in old_vids:
            gid = f"gid://shopify/ProductVariant/{vid}"
            result = await src.execute(VARIANT_QUERY, {"id": gid})
            variant = (result.get("data") or {}).get("productVariant")
            if variant:
                prod = variant.get("product", {})
                handle = prod.get("handle", "")
                sku = variant.get("sku", "")
                variant_info[vid] = {"handle": handle, "sku": sku, "title": variant.get("title", "")}
                print(f"  {vid}: {variant['title']} (sku: {sku}, product: {handle})")
            else:
                variant_info[vid] = None
                print(f"  {vid}: NOT FOUND")

    # Step 2: Go to DEST store, find new IDs by handle
    print("\n\n=== STEP 2: Fetching from DEST store ===\n")
    new_pids = []
    new_vids = []

    async with GraphQLClient(DEST, MAX_CONCURRENT) as dest:
        # Map products
        print("--- Products ---")
        for pid in old_pids:
            handle = product_handles.get(pid)
            if not handle:
                new_pids.append("???")
                print(f"  {pid} -> ??? (not found in source)")
                continue

            result = await dest.execute(PRODUCT_BY_HANDLE, {"query": f"handle:{handle}"})
            edges = ((result.get("data") or {}).get("products") or {}).get("edges", [])
            if edges:
                new_id = edges[0]["node"]["id"].split("/")[-1]
                new_pids.append(new_id)
                print(f"  {pid} -> {new_id} ({handle})")
            else:
                new_pids.append("???")
                print(f"  {pid} -> ??? (not found in dest: {handle})")

        # Map variants
        print("\n--- Variants ---")
        variant_cache = {}  # handle -> [variants from dest]
        for vid in old_vids:
            info = variant_info.get(vid)
            if not info:
                new_vids.append("???")
                print(f"  {vid} -> ??? (not found in source)")
                continue

            handle = info["handle"]
            sku = info["sku"]

            if handle not in variant_cache:
                result = await dest.execute(PRODUCT_BY_HANDLE, {"query": f"handle:{handle}"})
                edges = ((result.get("data") or {}).get("products") or {}).get("edges", [])
                if edges:
                    dest_variants = [e["node"] for e in edges[0]["node"]["variants"]["edges"]]
                    variant_cache[handle] = dest_variants
                else:
                    variant_cache[handle] = []

            dest_variants = variant_cache.get(handle, [])
            # Match by SKU first, then by title
            matched = None
            for dv in dest_variants:
                if sku and dv.get("sku") == sku:
                    matched = dv["id"].split("/")[-1]
                    break
            if not matched:
                for dv in dest_variants:
                    if dv.get("title") == info["title"]:
                        matched = dv["id"].split("/")[-1]
                        break
            if not matched and len(dest_variants) == 1:
                matched = dest_variants[0]["id"].split("/")[-1]

            if matched:
                new_vids.append(matched)
                print(f"  {vid} -> {matched} ({handle} / {sku})")
            else:
                new_vids.append("???")
                print(f"  {vid} -> ??? (no match in dest: {handle} / {sku})")

    # Final output
    print("\n\n=== COPY-PASTE READY ===\n")
    print(f'assign fast_pids_all = "{",".join(new_pids)}" | split: ","')
    print(f'assign fast_vids = "{",".join(new_vids)}" | split: ","')


asyncio.run(run())
