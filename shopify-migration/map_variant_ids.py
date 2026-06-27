import json
import asyncio
from config import SOURCE, DEST, MAX_CONCURRENT
from utils.graphql_client import GraphQLClient

PRODUCT_VARIANTS_QUERY = """
query($id: ID!) {
  product(id: $id) {
    variants(first: 100) {
      edges { node { id } }
    }
  }
}
"""

old_pids = "15083014062457,15254643900793,15083017404793,15428832461177,15083013407097,15357132210553,15083016716665,15083017372025,15083016618361,15357131850105,15083015569785,15083016585593,15303261061497,15083017699705,15083015373177,15083013898617,15083017732473,15083014291833,15083017503097,15083016520057,15083017634169,15083017601401,15083014947193,55609143067001,15404702597497,15370266542457,15083014586745,15083014652281,15083014553977,15083013734777,15083017437561,15083014488441,55609143361913,15083016847737".split(",")

old_vids = "55974783025529,55935482429817,55984871604601,56140138185081,55978713022841,55896084873593,56223877792121,56223877824889,55978829971833,55609143361913,55609127371129,15083013374329,57186808136057,57186808168825,63778682306937,55978804216185,56030781145465,56694835413369".split(",")

async def run():
    with open("data_ready/migracao_pronta.json", encoding="utf-8") as f:
        products = json.load(f)
    with open("data/state_dest_products.json", encoding="utf-8") as f:
        pstate = json.load(f)

    id_to_handle = {}
    id_to_product = {}
    for p in products:
        old_id = p.get("id", "").split("/")[-1]
        id_to_handle[old_id] = p.get("handle", "")
        id_to_product[old_id] = p

    # Map old variant ID -> (old product id, variant index)
    vid_to_info = {}
    for p in products:
        old_pid = p.get("id", "").split("/")[-1]
        for idx, v in enumerate(p.get("variants", [])):
            vid = str(v.get("id", "")).split("/")[-1]
            vid_to_info[vid] = (old_pid, idx)

    # For each old variant, find which product it belongs to, get new product, fetch variants
    needed_products = set()
    for vid in old_vids:
        info = vid_to_info.get(vid)
        if info:
            needed_products.add(info[0])
        else:
            print(f"WARNING: variant {vid} not found in any product")

    # Get new product GIDs
    product_new_gids = {}
    for old_pid in needed_products:
        h = id_to_handle.get(old_pid)
        if h and h in pstate:
            product_new_gids[old_pid] = pstate[h]

    # Fetch variants from destination for each needed product
    new_variant_map = {}  # old_pid -> [new_variant_ids]
    async with GraphQLClient(DEST, MAX_CONCURRENT) as client:
        for old_pid, new_gid in product_new_gids.items():
            result = await client.execute(PRODUCT_VARIANTS_QUERY, {"id": new_gid})
            variants = ((result.get("data") or {}).get("product") or {}).get("variants", {}).get("edges", [])
            new_variant_map[old_pid] = [e["node"]["id"].split("/")[-1] for e in variants]

    # Now map each old variant
    print("=== NEW VARIANT IDS ===")
    new_vids = []
    for vid in old_vids:
        info = vid_to_info.get(vid)
        if not info:
            new_vids.append("???")
            print(f"{vid} -> ??? (variant not found in source data)")
            continue

        old_pid, idx = info
        new_variants = new_variant_map.get(old_pid, [])
        if idx < len(new_variants):
            new_vid = new_variants[idx]
            new_vids.append(new_vid)
            print(f"{vid} -> {new_vid}")
        else:
            new_vids.append("???")
            print(f"{vid} -> ??? (index {idx} out of range, product {old_pid} has {len(new_variants)} variants)")

    # Also redo products for completeness
    print()
    print("=== NEW PRODUCT IDS ===")
    new_pids = []
    for pid in old_pids:
        h = id_to_handle.get(pid, "???")
        new_gid = pstate.get(h, "???")
        new_id = new_gid.split("/")[-1] if "/" in str(new_gid) else "???"
        new_pids.append(new_id)

    print()
    print("=== COPY-PASTE READY ===")
    print("fast_pids_all:", ",".join(new_pids))
    print()
    print("fast_vids:", ",".join(new_vids))

asyncio.run(run())
