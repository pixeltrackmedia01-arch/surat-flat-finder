"""Gujarat RERA (gujrera.gujarat.gov.in): registered residential projects for a district, with unit counts and carpet areas.

usage: python gujrera.py surat  -> out/<city>/gujrera.json

Polite (one request per second), cached, resumable. Only project-level fields are kept: the public
list also carries promoters' personal details (phone, email, Aadhaar, PAN), which are dropped on read
and never written to disk.
"""
import json
import pathlib
import sys
import subprocess
import time

ROOT = pathlib.Path(__file__).parent
CITIES = json.loads((ROOT.parent / "data" / "cities.json").read_text(encoding="utf-8"))
CITY = next((a for a in sys.argv[1:] if a in CITIES), "surat")
DISTRICT = CITIES[CITY].get("rera_district", CITIES[CITY]["name"])
BASE = "https://gujrera.gujarat.gov.in"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"
CACHE = ROOT / "cache" / "gujrera" / CITY
OUT = ROOT / "out" / CITY
SQM_TO_SQFT = 10.7639
KEEP = ("projectRegId", "projectName", "promoterName", "regNo", "project_status", "projectType",
        "project_address", "startDate", "endDate", "approvedOn")
# typeOfInventory codes seen in older filings; newer filings use words
INVENTORY = {"20": "Flat", "21": "Shop", "22": "Office", "23": "Row house", "24": "Bungalow", "25": "Plot"}


def get(path, cache_name):
    f = CACHE / cache_name
    if f.exists() and f.stat().st_size > 50:
        return json.loads(f.read_text(encoding="utf-8"))
    for attempt in range(3):
        try:
            # curl: Python's urllib takes ~20 s per request against this server, curl well under 1 s
            r = subprocess.run(["curl", "-s", "-A", UA, "-H", "Accept: application/json", "--max-time", "90", BASE + path],
                               capture_output=True)
            if r.returncode:
                raise RuntimeError(f"curl exit {r.returncode}")
            data = json.loads(r.stdout)
            time.sleep(1.0)
            return data
        except Exception as e:
            print("  retry", attempt + 1, path, e, flush=True)
            time.sleep(5 * (attempt + 1))
    return None


def save(cache_name, obj):
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / cache_name).write_text(json.dumps(obj), encoding="utf-8")


def project_list():
    data = get(f"/dashboard/get-district-wise-projectlist/0/0/all/{DISTRICT}/Residential", "list.json")
    rows = data["data"] if isinstance(data, dict) else data
    rows = [{k: r.get(k) for k in KEEP} for r in rows]  # drop personal fields before caching
    save("list.json", rows)
    return rows


def details(reg_id):
    name = f"d{reg_id}.json"
    raw = get(f"/project_reg/public/getproject-details/{reg_id}", name)
    if raw is None:
        return None
    d = raw.get("data", raw) if isinstance(raw, dict) and "data" in raw else raw
    if not isinstance(d, dict) or "projectDetail" not in d and "dev" not in d:
        # cached already-trimmed record
        if isinstance(raw, dict) and "units" in raw:
            return raw
        return None
    pd = d.get("projectDetail") or {}
    units = []
    for dev in d.get("dev") or []:
        for it in dev.get("internalDev") or []:
            n, carpet = it.get("noOfInventory"), it.get("carpetArea")
            if not n:
                continue
            kind = str(it.get("typeOfInventory") or "")
            units.append({"type": INVENTORY.get(kind, kind) or None, "count": n,
                          "carpet_sqm_total": carpet,
                          "avg_carpet_sqft": round(carpet * SQM_TO_SQFT / n) if carpet else None})
    out = {"units": units, "pincode": pd.get("pinCode"), "tp": pd.get("tPName") or pd.get("validTpName"),
           "land_sqm": pd.get("totAreaOfLandLayout") or pd.get("totAreaOfLand"),
           "address": " ".join(x.strip() for x in (pd.get("projectAddress"), pd.get("projectAddress2")) if x and x.strip())}
    save(name, out)  # cache only the trimmed, non-personal record
    return out


def main():
    rows = project_list()
    print(f"{DISTRICT}: {len(rows)} residential RERA projects", flush=True)
    out = []
    for i, r in enumerate(rows, 1):
        det = details(r["projectRegId"]) or {}
        out.append({**r, **det})
        if i % 50 == 0 or i == len(rows):
            print(f"details {i}/{len(rows)}", flush=True)
            OUT.mkdir(parents=True, exist_ok=True)
            (OUT / "gujrera.json").write_text(json.dumps(out, indent=0), encoding="utf-8")


if __name__ == "__main__":
    main()
