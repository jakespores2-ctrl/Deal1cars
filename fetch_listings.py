#!/usr/bin/env python3
"""Daily listings update for deal1cars.com.

Reads vehicle auctions from GSA Auctions (federal surplus) and, when keys are set, eBay Motors,
then writes listings.json next to index.html. Uses only the Python standard library.

Secrets (set in the repo under Settings > Secrets and variables > Actions):
  GSA_API_KEY         free key from https://api.data.gov/signup/        (needed for GSA)
  EBAY_CLIENT_ID      eBay developer keyset, production                 (optional)
  EBAY_CLIENT_SECRET  eBay developer keyset, production                 (optional)
  EBAY_CAMPAIGN_ID    eBay Partner Network campaign id for commissions  (optional)
"""
import base64
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

OUT = os.environ.get("LISTINGS_FILE", "listings.json")
GSA_URL = "https://api.gsa.gov/assets/gsaauctions/v2/auctions"
MAX_PER_SOURCE = 800

MAKES = ("FORD CHEVROLET CHEVY DODGE JEEP TOYOTA HONDA NISSAN GMC RAM CHRYSLER BUICK CADILLAC LINCOLN HYUNDAI KIA SUBARU "
         "MAZDA VOLKSWAGEN VW BMW MERCEDES VOLVO AUDI LEXUS ACURA INFINITI MITSUBISHI PONTIAC SATURN MERCURY OLDSMOBILE TESLA "
         "INTERNATIONAL FREIGHTLINER KENWORTH PETERBILT MACK ISUZU HINO HARLEY HARLEY-DAVIDSON POLARIS KAWASAKI YAMAHA SUZUKI "
         "LAND ROVER RANGE PORSCHE MINI FIAT GENESIS").split()
BODIES = ("SEDAN SUV PICKUP TRUCK VAN MINIVAN COUPE WAGON CROSSOVER HATCHBACK CONVERTIBLE BUS AUTOMOBILE VEHICLE "
          "MOTORCYCLE AMBULANCE CUTAWAY").split()
BAD = ("PARTS PART TIRE TIRES ENGINE ENGINES BATTERY WHEEL WHEELS SEAT SEATS TRAILER TRAILERS FORKLIFT BOAT VESSEL AIRCRAFT "
       "TRACTOR MOWER GENERATOR CART BULLDOZER LOADER EXCAVATOR CRANE SCRAP").split()


def word_re(words):
    return re.compile(r"\b(?:" + "|".join(re.escape(w) for w in words) + r")\b")


MAKE_RE, BODY_RE, BAD_RE = word_re(MAKES), word_re(BODIES), word_re(BAD)
YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-3]\d)\b")


def log(msg):
    print(msg, flush=True)


def http_json(url, headers=None, data=None, method=None, timeout=90):
    req = urllib.request.Request(url, headers=headers or {}, data=data, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def nice_title(text):
    words = []
    for w in re.split(r"(\s+)", text.strip()):
        if not w.strip():
            words.append(" ")
        elif len(w) <= 3 or any(c.isdigit() for c in w):
            words.append(w.upper())
        else:
            words.append(w.capitalize())
    return re.sub(r"\s+", " ", "".join(words)).strip()


def to_number(v):
    try:
        n = float(v)
        return n if n == n else None
    except (TypeError, ValueError):
        return None


def is_vehicle(name, desc=""):
    up = (name or "").upper()
    if not up or BAD_RE.search(up):
        return False
    if MAKE_RE.search(up) or BODY_RE.search(up):
        return True
    d = (desc or "").upper()
    return bool(re.search(r"\bVIN\b|\bODOMETER\b|\bMILEAGE\b", d) or MAKE_RE.search(d))


def transform_gsa(results, today):
    out, seen = [], set()
    for r in results or []:
        name = (r.get("ItemName") or "").strip()
        lots = r.get("LotInfo") or []
        desc = (lots[0].get("LotDescript") or "").strip() if lots and isinstance(lots[0], dict) else ""
        if not is_vehicle(name, desc):
            continue
        end = (r.get("AucEndDt") or "").strip()[:10]
        if end and end < today.isoformat():
            continue
        key = "%s-%s" % (r.get("SaleNo"), r.get("LotNo"))
        if key in seen:
            continue
        seen.add(key)
        city = (r.get("PropertyCity") or r.get("LocationCity") or "").strip()
        state = (r.get("PropertyState") or r.get("LocationST") or "").strip().upper()
        bid = to_number(r.get("HighBidAmount"))
        url = (r.get("ItemDescURL") or "").strip()
        if not url.lower().startswith("http"):
            url = "https://gsaauctions.gov/"
        image = (r.get("ImageURL") or "").strip()
        if image and not image.lower().startswith("http"):
            image = ""
        year = YEAR_RE.search(name)
        out.append({
            "id": "gsa-" + key,
            "source": "gsa",
            "title": nice_title(name),
            "year": int(year.group(1)) if year else None,
            "price": bid if bid and bid > 0 else None,
            "bids": int(to_number(r.get("BiddersCount")) or 0),
            "endDate": end or None,
            "endAt": None,
            "city": nice_title(city) if city else "",
            "state": state,
            "image": image,
            "url": url,
            "desc": desc[:160],
            "seller": (r.get("AgencyName") or "").strip(),
            "status": (r.get("AuctionStatus") or "").strip() or "S",
        })
    return out[:MAX_PER_SOURCE]


def ebay_token(client_id, secret):
    auth = base64.b64encode(("%s:%s" % (client_id, secret)).encode()).decode()
    data = urllib.parse.urlencode({"grant_type": "client_credentials",
                                   "scope": "https://api.ebay.com/oauth/api_scope"}).encode()
    resp = http_json("https://api.ebay.com/identity/v1/oauth2/token",
                     {"Authorization": "Basic " + auth, "Content-Type": "application/x-www-form-urlencoded"},
                     data, "POST")
    return resp["access_token"]


def transform_ebay(resp):
    out = []
    for it in (resp or {}).get("itemSummaries") or []:
        title = (it.get("title") or "").strip()
        if not title:
            continue
        bid = to_number((it.get("currentBidPrice") or {}).get("value")) or to_number((it.get("price") or {}).get("value"))
        loc = it.get("itemLocation") or {}
        year = YEAR_RE.search(title)
        url = it.get("itemAffiliateWebUrl") or it.get("itemWebUrl") or ""
        if not url.lower().startswith("http"):
            continue
        out.append({
            "id": "ebay-" + str(it.get("itemId") or url),
            "source": "ebay",
            "title": title,
            "year": int(year.group(1)) if year else None,
            "price": bid,
            "bids": int(to_number(it.get("bidCount")) or 0),
            "endDate": (it.get("itemEndDate") or "")[:10] or None,
            "endAt": it.get("itemEndDate") or None,
            "city": (loc.get("city") or "").strip(),
            "state": (loc.get("stateOrProvince") or "").strip().upper()[:2],
            "image": ((it.get("image") or {}).get("imageUrl") or ""),
            "url": url,
            "desc": (it.get("shortDescription") or "")[:160],
            "seller": "",
            "status": "A",
        })
    return out


def fetch_gsa(api_key):
    resp = http_json(GSA_URL, {"X-API-KEY": api_key, "Accept": "application/json"})
    results = resp.get("results") if isinstance(resp, dict) else resp
    results = results or []
    log("GSA API returned %d auction lots in total." % len(results))
    if not results:
        log("Raw response (first 300 chars): %s" % json.dumps(resp)[:300])
    for r in results[:15]:
        log("  sample: %r | end %r | status %r" % ((r.get("ItemName") or "")[:60], r.get("AucEndDt"), r.get("AuctionStatus")))
    return transform_gsa(results, datetime.datetime.now(datetime.timezone.utc).date())


def fetch_ebay(client_id, secret, campaign):
    token = ebay_token(client_id, secret)
    headers = {"Authorization": "Bearer " + token, "X-EBAY-C-MARKETPLACE-ID": "EBAY_MOTORS_US", "Accept": "application/json"}
    if campaign:
        headers["X-EBAY-C-ENDUSERCTX"] = "affiliateCampaignId=" + campaign
    items = []
    for offset in range(0, 200, 50):
        params = urllib.parse.urlencode({"category_ids": "6001", "filter": "buyingOptions:{AUCTION}",
                                         "sort": "endingSoonest", "limit": "50", "offset": str(offset)})
        resp = http_json("https://api.ebay.com/buy/browse/v1/item_summary/search?" + params, headers)
        page = transform_ebay(resp)
        items.extend(page)
        if len((resp or {}).get("itemSummaries") or []) < 50:
            break
    return items[:MAX_PER_SOURCE]


def load_previous():
    try:
        with open(OUT, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def main():
    prev = load_previous()
    prev_items = prev.get("listings") if isinstance(prev.get("listings"), list) else []
    sources, listings = {}, []

    gsa_key = os.environ.get("GSA_API_KEY", "").strip()
    if gsa_key:
        try:
            items = fetch_gsa(gsa_key)
            listings.extend(items)
            sources["gsa"] = {"ok": True, "count": len(items)}
            log("GSA: %d vehicles" % len(items))
        except Exception as e:  # keep the last good data for this source
            log("GSA failed: %s" % e)
            old = [x for x in prev_items if x.get("source") == "gsa"]
            listings.extend(old)
            sources["gsa"] = {"ok": False, "count": len(old), "error": str(e)[:200]}
    else:
        log("GSA_API_KEY is not set, skipping GSA.")

    cid, sec = os.environ.get("EBAY_CLIENT_ID", "").strip(), os.environ.get("EBAY_CLIENT_SECRET", "").strip()
    campaign = os.environ.get("EBAY_CAMPAIGN_ID", "").strip()
    if cid and sec:
        try:
            items = fetch_ebay(cid, sec, campaign)
            listings.extend(items)
            sources["ebay"] = {"ok": True, "count": len(items)}
            log("eBay: %d vehicles" % len(items))
        except Exception as e:
            log("eBay failed: %s" % e)
            old = [x for x in prev_items if x.get("source") == "ebay"]
            listings.extend(old)
            sources["ebay"] = {"ok": False, "count": len(old), "error": str(e)[:200]}
    else:
        log("EBAY_CLIENT_ID / EBAY_CLIENT_SECRET not set, skipping eBay.")

    if not sources:
        log("No sources configured. Leaving %s unchanged." % OUT)
        return 0
    if not any(s.get("ok") for s in sources.values()) and not listings:
        log("Every source failed and there is no earlier data. Leaving %s unchanged." % OUT)
        return 1

    doc = {
        "updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "affiliate": bool(campaign and "ebay" in sources and sources["ebay"].get("ok")),
        "sources": sources,
        "listings": listings,
    }
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, OUT)
    log("Wrote %d listings to %s" % (len(listings), OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
