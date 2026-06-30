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

# All unique product IDs from the code
ALL_PIDS = [
    "15598677295481",  # ENVIO_PRODUCT_ID
    "15169830420857", "15161428640121", "15172284907897", "15170716565881",
    "15083014062457", "15254643900793", "15083013407097", "15357132210553",
    "15083016716665", "15083017372025", "15083016618361", "15357131850105",
    "15083015569785", "15083016585593", "15303261061497", "15083017699705",
    "15083015373177", "15083013898617", "15083017732473", "15083014291833",
    "15083017503097", "15083016520057", "15083017634169", "15083017601401",
    "15083014947193", "15370266542457", "15083014586745", "15083014652281",
    "15083014553977", "15083013734777", "15083017437561", "15083014488441",
    "15404702597497", "15083016847737", "55609143067001", "55609143361913",
    "15151676686713", "56140138185081", "15238599639417", "15170780791161",
    "15083013374329", "57186808136057", "57186808168825", "63778682306937",
    "15170769420665", "15182128447865", "56694835413369", "15428832461177",
    "15083017175417", "15083017404793",
]

# All unique variant IDs from the code
ALL_VIDS = [
    "63745756561785",  # ENVIO_VARIANT_ID
    "55974783025529", "55935482429817", "55984871604601", "55978713022841",
    "55609127371129", "55609143361913", "55896084873593", "56223877792121",
    "56223877824889", "55978829971833", "55978804216185", "56030781145465",
]

# Variant picker - fast_pids_all
FAST_PIDS = [
    "15083014062457", "15254643900793", "15083017404793", "15428832461177",
    "15083013407097", "15357132210553", "15083016716665", "15083017372025",
    "15083016618361", "15357131850105", "15083015569785", "15083016585593",
    "15303261061497", "15083017699705", "15083015373177", "15083013898617",
    "15083017732473", "15083014291833", "15083017503097", "15083016520057",
    "15083017634169", "15083017601401", "15083014947193", "55609143067001",
    "15404702597497", "15370266542457", "15083014586745", "15083014652281",
    "15083014553977", "15083013734777", "15083017437561", "15083014488441",
    "55609143361913", "15083016847737",
]

# Variant picker - fast_vids
FAST_VIDS = [
    "55974783025529", "55935482429817", "55984871604601", "56140138185081",
    "55978713022841", "55896084873593", "56223877792121", "56223877824889",
    "55978829971833", "55609143361913", "55609127371129", "15083013374329",
    "57186808136057", "57186808168825", "63778682306937", "55978804216185",
    "56030781145465", "56694835413369",
]

# Remove duplicates preserving order
seen_p = set()
UNIQUE_PIDS = []
for p in ALL_PIDS + FAST_PIDS:
    if p not in seen_p:
        seen_p.add(p)
        UNIQUE_PIDS.append(p)

seen_v = set()
UNIQUE_VIDS = []
for v in ALL_VIDS + FAST_VIDS:
    if v not in seen_v:
        seen_v.add(v)
        UNIQUE_VIDS.append(v)


async def map_product(src, dest, pid, cache):
    if pid in cache:
        return cache[pid]
    gid = f"gid://shopify/Product/{pid}"
    result = await src.execute(PRODUCT_QUERY, {"id": gid})
    product = (result.get("data") or {}).get("product")
    if not product:
        cache[pid] = None
        return None
    handle = product["handle"]
    result2 = await dest.execute(PRODUCT_BY_HANDLE, {"query": f"handle:{handle}"})
    edges = ((result2.get("data") or {}).get("products") or {}).get("edges", [])
    if edges:
        new_id = edges[0]["node"]["id"].split("/")[-1]
        cache[pid] = {"old": pid, "new": new_id, "handle": handle, "title": product["title"], "variants": edges[0]["node"]["variants"]["edges"]}
        return cache[pid]
    cache[pid] = None
    return None


async def map_variant(src, dest, vid, product_cache):
    gid = f"gid://shopify/ProductVariant/{vid}"
    result = await src.execute(VARIANT_QUERY, {"id": gid})
    variant = (result.get("data") or {}).get("productVariant")
    if not variant:
        return None
    prod = variant.get("product", {})
    handle = prod.get("handle", "")
    sku = variant.get("sku", "")
    title = variant.get("title", "")

    # Find dest product
    dest_variants = []
    for cached in product_cache.values():
        if cached and cached["handle"] == handle:
            dest_variants = [e["node"] for e in cached.get("variants", [])]
            break

    if not dest_variants:
        result2 = await dest.execute(PRODUCT_BY_HANDLE, {"query": f"handle:{handle}"})
        edges = ((result2.get("data") or {}).get("products") or {}).get("edges", [])
        if edges:
            dest_variants = [e["node"] for e in edges[0]["node"]["variants"]["edges"]]

    # Match by SKU, then title, then single variant
    for dv in dest_variants:
        if sku and dv.get("sku") == sku:
            return dv["id"].split("/")[-1]
    for dv in dest_variants:
        if dv.get("title") == title:
            return dv["id"].split("/")[-1]
    if len(dest_variants) == 1:
        return dest_variants[0]["id"].split("/")[-1]
    return None


async def run():
    product_cache = {}
    pid_map = {}
    vid_map = {}

    async with GraphQLClient(SOURCE, MAX_CONCURRENT) as src, GraphQLClient(DEST, MAX_CONCURRENT) as dest:
        print("=== MAPPING PRODUCTS ===\n")
        for pid in UNIQUE_PIDS:
            info = await map_product(src, dest, pid, product_cache)
            if info:
                pid_map[pid] = info["new"]
                print(f"  {pid} -> {info['new']}  ({info['handle']})")
            else:
                pid_map[pid] = "???"
                print(f"  {pid} -> ???  (NOT FOUND)")

        print("\n=== MAPPING VARIANTS ===\n")
        for vid in UNIQUE_VIDS:
            new_vid = await map_variant(src, dest, vid, product_cache)
            if new_vid:
                vid_map[vid] = new_vid
                print(f"  {vid} -> {new_vid}")
            else:
                vid_map[vid] = "???"
                print(f"  {vid} -> ???  (NOT FOUND)")

    # Build the ELIGIBLE array
    ELIGIBLE = [
        ("15169830420857", "55974783025529"),
        ("15161428640121", "55935482429817"),
        ("15172284907897", "55984871604601"),
        ("15170716565881", "55978713022841"),
        ("15083014062457", None), ("15254643900793", None),
        ("15083013407097", None), ("15357132210553", None),
        ("15083016716665", None), ("15083017372025", None),
        ("15083016618361", None), ("15357131850105", None),
        ("15083015569785", None), ("15083016585593", None),
        ("15303261061497", None), ("15083017699705", None),
        ("15083015373177", None), ("15083013898617", None),
        ("15083017732473", None), ("15083014291833", None),
        ("15083017503097", None), ("15083016520057", None),
        ("15083017634169", None), ("15083017601401", None),
        ("15083014947193", None), ("15370266542457", None),
        ("15083014586745", None), ("15083014652281", None),
        ("15083014553977", None), ("15083013734777", None),
        ("15083017437561", None), ("15083014488441", None),
        ("15404702597497", None), ("15083016847737", None),
        ("55609143067001", "55609127371129"),
        ("55609143361913", "55609143361913"),
        ("15151676686713", "55896084873593"),
        ("56140138185081", None),
        ("15238599639417", "56223877792121"),
        ("15238599639417", "56223877824889"),
        ("15170780791161", "55978829971833"),
        ("15083013374329", None),
        ("57186808136057", None),
        ("57186808168825", None),
        ("63778682306937", None),
        ("15170769420665", "55978804216185"),
        ("15182128447865", "56030781145465"),
        ("56694835413369", None),
        ("15428832461177", None),
        ("15083017175417", None),
        ("15083017404793", None),
    ]

    print("\n\n=== COPY-PASTE READY ===\n")
    envio_pid = pid_map.get("15598677295481", "???")
    envio_vid = vid_map.get("63745756561785", "???")
    print(f"  var ENVIO_PRODUCT_ID = {envio_pid};")
    print(f"  var ENVIO_VARIANT_ID = '{envio_vid}';")
    print("  var warningActive = false;")
    print()
    print("  var ELIGIBLE = [")
    for old_pid, old_vid in ELIGIBLE:
        new_pid = pid_map.get(old_pid, "???")
        if old_vid:
            new_vid = vid_map.get(old_vid, "???")
            print(f"    {{ pid: {new_pid}, vid: {new_vid} }},")
        else:
            print(f"    {{ pid: {new_pid}, vid: null }},")
    print("  ];")

    print("\n\n=== VARIANT PICKER (fast_pids_all / fast_vids) ===\n")
    new_fast_pids = [pid_map.get(p, "???") for p in FAST_PIDS]
    new_fast_vids = [vid_map.get(v, "???") for v in FAST_VIDS]
    print("  Liquid (assign):")
    print(f'  assign fast_pids_all = "{",".join(new_fast_pids)}" | split: ","')
    print(f'  assign fast_vids = "{",".join(new_fast_vids)}" | split: ","')
    print()
    print("  HTML (data attributes):")
    print(f'  data-fast-pids="{",".join(new_fast_pids)}"')
    print(f'  data-fast-vids="{",".join(new_fast_vids)}"')


asyncio.run(run())
