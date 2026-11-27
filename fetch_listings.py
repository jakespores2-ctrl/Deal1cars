#!/usr/bin/env python3
"""Daily listings update for deal1cars.com.

Reads vehicle auctions from GSA Auctions (federal surplus) and, when keys are set, eBay Motors,
then writes listings.json next to index.html. Uses only the Python standard library.

Secrets (set in the repo under Settings > Secrets and variables > Actions):
  GSA_API_KEY         free key from https://api.data.gov/signup/        (needed for GSA)
  EBAY_CLIENT_ID      eBay developer keyset, production                 (optional)
  EBAY_CLIENT_SECRET  eBay developer keyset, production                 (optional)
  EBAY_CAMPAIGN_ID    eBay Partner Network campaign id for commissions  (optional)
  AUTODEV_API_KEY     Auto.dev key for dealer "for sale" listings         (optional)
"""
import base64
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

OUT = os.environ.get("LISTINGS_FILE", "listings.json")
GSA_URL = "https://api.gsa.gov/assets/gsaauctions/v2/auctions"
MAX_PER_SOURCE = 5000
EBAY_PAGES = int(os.environ.get("EBAY_PAGES", "4"))  # 50 listings per page, per search type

MAKES = ("FORD CHEVROLET CHEVY DODGE JEEP TOYOTA HONDA NISSAN GMC RAM CHRYSLER BUICK CADILLAC LINCOLN HYUNDAI KIA SUBARU "
         "MAZDA VOLKSWAGEN VW BMW MERCEDES VOLVO AUDI LEXUS ACURA INFINITI MITSUBISHI PONTIAC SATURN MERCURY OLDSMOBILE TESLA "
         "INTERNATIONAL FREIGHTLINER KENWORTH PETERBILT MACK ISUZU HINO HARLEY HARLEY-DAVIDSON POLARIS KAWASAKI YAMAHA SUZUKI "
         "LAND ROVER RANGE PORSCHE MINI FIAT GENESIS").split()
BODIES = ("SEDAN SUV PICKUP TRUCK VAN MINIVAN COUPE WAGON CROSSOVER HATCHBACK CONVERTIBLE BUS AUTOMOBILE VEHICLE "
          "MOTORCYCLE AMBULANCE CUTAWAY").split()
BAD = ("PARTS PART TIRE TIRES ENGINE ENGINES BATTERY BATTERIES WHEEL WHEELS SEAT SEATS SCRAP GENERATOR GENERATORS").split()
CATS = [  # checked in this order; first match wins
    ("trailer", "TRAILER TRAILERS SEMITRAILER SEMI-TRAILER"),
    ("boat", "BOAT BOATS VESSEL YACHT SAILBOAT PONTOON KAYAK KAYAKS CANOE CANOES WATERCRAFT SKIFF BARGE TUGBOAT FERRY HOVERCRAFT CATAMARAN DINGHY LAUNCH CUTTER RAFT JETSKI JET-SKI MARINE"),
    ("aircraft", "AIRCRAFT AIRPLANE HELICOPTER AIRPLANES CESSNA PIPER BEECHCRAFT"),
    ("rv", "RV MOTORHOME MOTOR-HOME CAMPER"),
    ("motorcycle", "MOTORCYCLE MOTORCYCLES ATV ATVS UTV UTVS SCOOTER MOPED SNOWMOBILE SNOWMOBILES GATOR SIDE-BY-SIDE CART SNOW-MOBILE SNOWCAT"),
]
EQUIP = "TRACTOR BULLDOZER DOZER EXCAVATOR LOADER BACKHOE FORKLIFT GRADER CRANE SKID ROLLER SWEEPER PAVER MOWER MOWERS ZTR"

def word_re(words):
    return re.compile(r"\b(?:" + "|".join(re.escape(w) for w in words) + r")\b")


MAKE_RE, BODY_RE, BAD_RE = word_re(MAKES), word_re(BODIES), word_re(BAD)
CAT_RES = [(c, word_re(w.split())) for c, w in CATS]
EQUIP_RE = word_re(EQUIP.split())
YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-3]\d)\b")


STATE_ABBR = {n.rsplit(" ", 1)[0].lower(): n.rsplit(" ", 1)[1] for n in "Alabama AL|Alaska AK|Arizona AZ|Arkansas AR|California CA|Colorado CO|Connecticut CT|Delaware DE|District of Columbia DC|Washington DC DC|Florida FL|Georgia GA|Hawaii HI|Idaho ID|Illinois IL|Indiana IN|Iowa IA|Kansas KS|Kentucky KY|Louisiana LA|Maine ME|Maryland MD|Massachusetts MA|Michigan MI|Minnesota MN|Mississippi MS|Missouri MO|Montana MT|Nebraska NE|Nevada NV|New Hampshire NH|New Jersey NJ|New Mexico NM|New York NY|North Carolina NC|North Dakota ND|Ohio OH|Oklahoma OK|Oregon OR|Pennsylvania PA|Rhode Island RI|South Carolina SC|South Dakota SD|Tennessee TN|Texas TX|Utah UT|Vermont VT|Virginia VA|Washington WA|West Virginia WV|Wisconsin WI|Wyoming WY|Puerto Rico PR|Guam GU".split("|")}


def norm_state(v):
    """eBay gives 'California' or 'CA' (sometimes in other forms). Return a 2-letter US code, or ''."""
    t = re.sub(r"[^A-Za-z ]", "", str(v or "")).strip()
    if re.fullmatch(r"[A-Za-z]{2}", t):
        return t.upper()
    return STATE_ABBR.get(re.sub(r"\s+", " ", t).lower(), "")


def zip3(v):
    """eBay often masks the ZIP (e.g. '945**'). Keep the first 3 digits, which still means a region."""
    m = re.match(r"^\s*(\d{3})", str(v or ""))
    return m.group(1) if m else ""


def zip5(v):
    m = re.match(r"^\s*(\d{5})(?:-\d{4})?\s*$", str(v or ""))
    return m.group(1) if m else ""


def log(msg):
    print(msg, flush=True)


def http_json(url, headers=None, data=None, method=None, timeout=90):
    req = urllib.request.Request(url, headers=headers or {}, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        if err.code == 404:
            raise
        try:
            body = err.read().decode("utf-8", "replace")[:300]
        except Exception:
            body = ""
        raise RuntimeError("HTTP %s %s | %s" % (err.code, err.reason, body))


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


def classify(name, desc=""):
    """Return a category for vehicles, boats, trailers etc., or None to skip the lot."""
    up = (name or "").upper().replace("SNOW MOBILE", "SNOWMOBILE").replace("JET SKI", "JETSKI").replace("SIDE BY SIDE", "SIDE-BY-SIDE").replace("FOUR WHEELER", "ATV")
    if re.search(r"\bOUTBOARDS?\b", up) and not re.search(r"\bPARTS?\b", up):
        return "boat"  # outboard motors
    if not up or BAD_RE.search(up):
        return None
    for cat, rx in CAT_RES:
        if rx.search(up):
            return cat
    if MAKE_RE.search(up) or BODY_RE.search(up):
        return "vehicle"
    if EQUIP_RE.search(up):
        return "equipment"
    d = (desc or "").upper()
    if re.search(r"\bVIN\b|\bODOMETER\b|\bMILEAGE\b", d) or MAKE_RE.search(d):
        return "vehicle"
    return None


def lower_keys(d):
    return {str(k).lower(): v for k, v in d.items()} if isinstance(d, dict) else {}


def transform_gsa(results, today):
    out, seen, rejected = [], set(), []
    for r in results or []:
        r = lower_keys(r)
        name = (r.get("itemname") or "").strip()
        lots = r.get("lotinfo") or []
        desc = (lower_keys(lots[0]).get("lotdescript") or "").strip() if lots and isinstance(lots[0], dict) else ""
        cat = classify(name, desc)
        if not cat:
            rejected.append(name)
            continue
        end = (r.get("aucenddt") or "").strip()[:10]
        if end and end < today.isoformat():
            continue
        key = "%s-%s" % (r.get("saleno"), r.get("lotno"))
        if key in seen:
            continue
        seen.add(key)
        city = (r.get("propertycity") or r.get("locationcity") or "").strip()
        state = (r.get("propertystate") or r.get("locationst") or "").strip().upper()
        bid = to_number(r.get("highbidamount"))
        url = (r.get("itemdescurl") or "").strip()
        if not url.lower().startswith("http"):
            url = "https://gsaauctions.gov/"
        image = (r.get("imageurl") or "").strip()
        if image and not image.lower().startswith("http"):
            image = ""
        year = YEAR_RE.search(name)
        out.append({
            "id": "gsa-" + key,
            "source": "gsa",
            "category": cat,
            "title": nice_title(name),
            "year": int(year.group(1)) if year else None,
            "price": bid if bid and bid > 0 else None,
            "bids": int(to_number(r.get("bidderscount")) or 0),
            "endDate": end or None,
            "endAt": None,
            "zip": zip5(r.get("propertyzip") or r.get("locationzip")),
            "city": nice_title(city) if city else "",
            "state": norm_state(state) or state[:2],
            "image": image,
            "url": url,
            "desc": desc[:160],
            "seller": (r.get("agencyname") or "").strip(),
            "status": (r.get("auctionstatus") or "").strip() or "S",
        })
    log("Skipped %d lots that did not look like vehicles. First 40: %s" % (len(rejected), "; ".join(n[:40] for n in rejected[:40])))
    return out[:MAX_PER_SOURCE]


def ebay_token(client_id, secret):
    auth = base64.b64encode(("%s:%s" % (client_id, secret)).encode()).decode()
    data = urllib.parse.urlencode({"grant_type": "client_credentials",
                                   "scope": "https://api.ebay.com/oauth/api_scope"}).encode()
    resp = http_json("https://api.ebay.com/identity/v1/oauth2/token",
                     {"Authorization": "Basic " + auth, "Content-Type": "application/x-www-form-urlencoded"},
                     data, "POST")
    return resp["access_token"]


def transform_ebay(resp, fixed=False):
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
            "category": "vehicle",
            "title": title,
            "year": int(year.group(1)) if year else None,
            "price": bid,
            "bids": int(to_number(it.get("bidCount")) or 0),
            "endDate": None if fixed else (it.get("itemEndDate") or "")[:10] or None,
            "endAt": None if fixed else (it.get("itemEndDate") or None),
            "zip": zip5(loc.get("postalCode")),
            "zip3": zip3(loc.get("postalCode")),
            "city": (loc.get("city") or "").strip(),
            "state": norm_state(loc.get("stateOrProvince")),
            "image": ((it.get("image") or {}).get("imageUrl") or ""),
            "url": url,
            "desc": (it.get("shortDescription") or "")[:160],
            "seller": "",
            "status": "F" if fixed else "A",
        })
        if fixed:
            out[-1]["fixed"] = True
            out[-1]["bids"] = 0
    return out


AUTODEV_URL = "https://api.auto.dev/listings"
AUTODEV_LIMIT = int(os.environ.get("AUTODEV_LIMIT", "20"))          # free plan caps each call at 20 listings
AUTODEV_MAX_CALLS = int(os.environ.get("AUTODEV_MAX_CALLS", "25"))  # calls per refresh
AUTODEV_MIN_HOURS = float(os.environ.get("AUTODEV_MIN_HOURS", "22"))  # refresh at most about once a day (free plan: 1,000 calls/month)


def flat(d, prefix=""):
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            key = prefix + str(k)
            if isinstance(v, dict):
                out.update(flat(v, key + "."))
            else:
                out[key] = v
    return out


def pick(f, *names):
    """First non-empty value whose key equals, or ends with '.', one of the names (case-insensitive)."""
    low = {k.lower(): v for k, v in f.items()}
    for n in names:
        n = n.lower()
        for k, v in low.items():
            if (k == n or k.endswith("." + n)) and v not in (None, "", [], {}):
                return v
    return None


def first_url(v):
    if isinstance(v, str):
        return v
    if isinstance(v, list) and v:
        return first_url(v[0])
    if isinstance(v, dict):
        return first_url(v.get("url") or v.get("src") or v.get("href"))
    return ""


def transform_autodev(items):
    out, seen = [], set()
    for it in items or []:
        f = flat(it)
        vin = str(pick(f, "vin") or "").strip()
        year, make, model, trim = pick(f, "year"), pick(f, "make"), pick(f, "model"), pick(f, "trim")
        title = " ".join(str(x) for x in (year, make, model, trim) if x)
        price = to_number(pick(f, "price"))
        url = first_url(pick(f, "vdp", "vdpUrl", "listingUrl", "url"))
        if not title or not price or not url.lower().startswith("http"):
            continue
        key = vin or url
        if key in seen:
            continue
        seen.add(key)
        loc = pick(f, "location")
        lat, lon = to_number(pick(f, "lat", "latitude")), to_number(pick(f, "lon", "lng", "longitude"))
        if lat is None and isinstance(loc, (list, tuple)) and len(loc) == 2:  # GeoJSON order is [lon, lat]
            lon, lat = to_number(loc[0]), to_number(loc[1])
        elif lat is None and isinstance(loc, str) and "," in loc:
            a, b = loc.split(",", 1)
            lat, lon = to_number(a), to_number(b)
        image = first_url(pick(f, "primaryImage", "primaryPhoto", "photoUrl", "image", "photos", "images"))
        yr = to_number(year)
        rec = {
            "id": "dealer-" + key,
            "source": "dealer",
            "category": "vehicle",
            "title": title,
            "year": int(yr) if yr else None,
            "price": price,
            "bids": 0,
            "endDate": None,
            "endAt": None,
            "zip": zip5(pick(f, "zip", "zipcode", "postalCode")),
            "city": str(pick(f, "city") or "").strip(),
            "state": norm_state(pick(f, "state")),
            "image": image if image.lower().startswith("http") else "",
            "url": url,
            "desc": "",
            "seller": str(pick(f, "dealer.name", "dealerName", "dealer") if not isinstance(pick(f, "dealer"), dict) else "").strip()[:60],
            "status": "F",
        }
        miles = to_number(pick(f, "miles", "mileage"))
        if miles:
            rec["miles"] = int(miles)
        if lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180:
            rec["lat"], rec["lon"] = round(lat, 3), round(lon, 3)
        out.append(rec)
    return out


def fetch_autodev(api_key):
    headers = {"Authorization": "Bearer " + api_key, "Content-Type": "application/json", "Accept": "application/json"}
    items, calls = [], 0
    for page in range(1, AUTODEV_MAX_CALLS + 1):
        params = urllib.parse.urlencode({"page": page, "limit": AUTODEV_LIMIT, "sort": "updatedAt.desc"})
        resp = http_json(AUTODEV_URL + "?" + params, headers)
        calls += 1
        data = resp.get("data") if isinstance(resp, dict) else resp
        data = data or []
        if page == 1:
            log("Auto.dev sample fields: %s" % sorted(flat(data[0]).keys())[:60] if data else "Auto.dev returned no listings on page 1.")
        items.extend(data)
        if len(data) < AUTODEV_LIMIT:
            break
    out = transform_autodev(items)
    log("Auto.dev: %d raw listings, %d usable, %d calls." % (len(items), len(out), calls))
    return out, calls


def fetch_gsa(api_key):
    resp = http_json(GSA_URL, {"X-API-KEY": api_key, "Accept": "application/json"})
    results = resp if isinstance(resp, list) else (lower_keys(resp).get("results") or [])
    results = results or []
    log("GSA API returned %d auction lots in total." % len(results))
    if not results:
        log("Raw response (first 300 chars): %s" % json.dumps(resp)[:300])
    for r in results[:5]:
        r = lower_keys(r)
        log("  sample: %r | end %r | status %r" % ((r.get("itemname") or "")[:60], r.get("aucenddt"), r.get("auctionstatus")))
    return transform_gsa(results, datetime.datetime.now(datetime.timezone.utc).date())


def fetch_ebay(client_id, secret, campaign):
    token = ebay_token(client_id, secret)
    headers = {"Authorization": "Bearer " + token, "X-EBAY-C-MARKETPLACE-ID": "EBAY_MOTORS_US", "Accept": "application/json"}
    if campaign:
        headers["X-EBAY-C-ENDUSERCTX"] = "affiliateCampaignId=" + campaign
    items, seen = [], set()
    # pass 1: auctions, pass 2: fixed-price "Buy It Now" cars
    for buying, sort, fixed in (("AUCTION", "endingSoonest", False), ("FIXED_PRICE", "newlyListed", True)):
        got = 0
        for offset in range(0, 50 * EBAY_PAGES, 50):
            params = urllib.parse.urlencode({"category_ids": "6001", "filter": "buyingOptions:{%s}" % buying,
                                             "sort": sort, "limit": "50", "offset": str(offset)})
            try:
                resp = http_json("https://api.ebay.com/buy/browse/v1/item_summary/search?" + params, headers)
            except Exception as e:
                if not fixed:
                    raise  # the auction pass is the main one
                log("eBay Buy It Now search failed (auctions are unaffected): %s" % e)
                break
            if offset == 0 and not fixed:
                log("eBay sample locations: %r" % [(it.get("itemLocation") or {}) for it in ((resp or {}).get("itemSummaries") or [])[:4]])
            for rec in transform_ebay(resp, fixed):
                if rec["id"] not in seen:  # an auction that also offers Buy It Now stays an auction
                    seen.add(rec["id"])
                    items.append(rec)
                    got += 1
            if len((resp or {}).get("itemSummaries") or []) < 50:
                break
        log("eBay %s: %d listings." % ("Buy It Now" if fixed else "auctions", got))
    return items[:MAX_PER_SOURCE]


GEO_FILE = os.environ.get("GEO_CACHE_FILE", "geo_cache.json")
MAX_NEW_GEO = 400


def geocode(listings):
    """Add lat/lon to each listing from its ZIP code (free zippopotam.us lookups, cached in geo_cache.json)."""
    try:
        with open(GEO_FILE, encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, ValueError):
        cache = {}
    need = sorted({l.get("zip") for l in listings if l.get("zip") and l["zip"] not in cache})[:MAX_NEW_GEO]
    done = 0
    for z in need:
        try:
            d = http_json("https://api.zippopotam.us/us/" + z, timeout=20)
            pl = (d.get("places") or [{}])[0]
            cache[z] = [round(float(pl["latitude"]), 3), round(float(pl["longitude"]), 3), (pl.get("state abbreviation") or "")]
        except urllib.error.HTTPError as e:
            if e.code == 404:
                cache[z] = None  # not a real ZIP, do not ask again
        except Exception:
            pass  # network hiccup, try again on the next run
        done += 1
        time.sleep(0.1)
    for l in listings:
        c = cache.get(l.get("zip") or "")
        if c:
            l["lat"], l["lon"] = c[0], c[1]
            if not l.get("state") and len(c) > 2 and c[2]:
                l["state"] = c[2]
    # listings with no usable ZIP (eBay often hides it): fall back to city + state
    def ckey(l):
        city, st = (l.get("city") or "").strip().lower(), (l.get("state") or "").strip().upper()
        return ("c:%s|%s" % (city, st)) if city and re.match(r"^[A-Z]{2}$", st) else ""
    need_c = sorted({ckey(l) for l in listings if "lat" not in l and ckey(l) and ckey(l) not in cache})[:MAX_NEW_GEO]
    for k in need_c:
        city, st = k[2:].split("|")
        try:
            d = http_json("https://api.zippopotam.us/us/%s/%s" % (st.lower(), urllib.parse.quote(city)), timeout=20)
            pl = (d.get("places") or [{}])[0]
            cache[k] = [round(float(pl["latitude"]), 3), round(float(pl["longitude"]), 3)]
        except urllib.error.HTTPError as e:
            if e.code == 404:
                cache[k] = None
        except Exception:
            pass
        done += 1
        time.sleep(0.1)
    for l in listings:
        if "lat" not in l and ckey(l):
            c = cache.get(ckey(l))
            if c:
                l["lat"], l["lon"] = c
    # last resort: only a 3-digit ZIP prefix is known. Look up a real ZIP that starts with it (about 30-60 mile accuracy).
    def z3key(l):
        return ("z3:" + l["zip3"]) if l.get("zip3") and "lat" not in l else ""
    need_z = sorted({z3key(l) for l in listings if z3key(l) and z3key(l) not in cache})[:MAX_NEW_GEO]
    for k in need_z:
        found = None
        for tail in ("01", "10", "00", "20", "30", "50"):
            try:
                d = http_json("https://api.zippopotam.us/us/" + k[3:] + tail, timeout=20)
                pl = (d.get("places") or [{}])[0]
                found = [round(float(pl["latitude"]), 3), round(float(pl["longitude"]), 3), (pl.get("state abbreviation") or "")]
                break
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    break
            except Exception:
                break
            time.sleep(0.1)
        if found:
            cache[k] = found
        done += 1
    for l in listings:
        if z3key(l):
            c = cache.get(z3key(l))
            if c:
                l["lat"], l["lon"] = c[0], c[1]
                if not l.get("state") and len(c) > 2 and c[2]:
                    l["state"] = c[2]
    n_ebay = [x for x in listings if x.get("source") == "ebay"]
    log("Locations: %d of %d eBay listings have coordinates." % (sum(1 for x in n_ebay if "lat" in x), len(n_ebay)))
    try:
        with open(GEO_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, separators=(",", ":"), sort_keys=True)
    except OSError:
        pass
    log("Locations: looked up %d new ZIPs, %d listings have coordinates." % (done, sum(1 for l in listings if "lat" in l)))


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

    dk = os.environ.get("AUTODEV_API_KEY", "").strip()
    if dk:
        old = [x for x in prev_items if x.get("source") == "dealer"]
        meta = (prev.get("sources") or {}).get("dealer") or {}
        try:
            last = datetime.datetime.fromisoformat(str(meta.get("fetchedAt", "")).replace("Z", "+00:00"))
        except ValueError:
            last = None
        age_h = (datetime.datetime.now(datetime.timezone.utc) - last).total_seconds() / 3600 if last else 1e9
        if old and meta.get("ok") and age_h < AUTODEV_MIN_HOURS:
            listings.extend(old)
            sources["dealer"] = dict(meta)
            log("Auto.dev: reusing %d saved listings (refreshed %.1f hours ago, saving API calls)." % (len(old), age_h))
        else:
            try:
                items, calls = fetch_autodev(dk)
                if not items and old:
                    raise RuntimeError("no usable listings returned")
                listings.extend(items)
                sources["dealer"] = {"ok": True, "count": len(items), "calls": calls,
                                     "fetchedAt": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
            except Exception as e:
                log("Auto.dev failed: %s" % e)
                listings.extend(old)
                sources["dealer"] = {"ok": False, "count": len(old), "error": str(e)[:200], "fetchedAt": meta.get("fetchedAt")}
    else:
        log("AUTODEV_API_KEY not set, skipping dealer listings.")

    if not sources:
        log("No sources configured. Leaving %s unchanged." % OUT)
        return 0
    if not any(s.get("ok") for s in sources.values()) and not listings:
        log("Every source failed and there is no earlier data. Leaving %s unchanged." % OUT)
        return 1

    try:
        geocode(listings)
    except Exception as e:
        log("Location lookup skipped: %s" % e)
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
