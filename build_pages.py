#!/usr/bin/env python3
"""Builds search-friendly landing pages from listings.json (run after fetch_listings.py).

Writes browse/<slug>.html for each type page and each state with enough listings,
refreshes sitemap.xml, and refreshes the "Browse by state" links block in index.html.
Standard library only. Listings are baked into the HTML so Google can read them.
"""
import datetime
import html
import json
import os
import re

SITE = "https://deal1cars.com"
OUT_DIR = os.environ.get("BROWSE_DIR", "browse")
LISTINGS = os.environ.get("LISTINGS_FILE", "listings.json")
SITEMAP = os.environ.get("SITEMAP_FILE", "sitemap.xml")
INDEX = os.environ.get("INDEX_FILE", "index.html")
MAX_CARDS = 60
MIN_STATE = 3

STATES = {"AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
          "CT": "Connecticut", "DE": "Delaware", "DC": "Washington DC", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
          "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky",
          "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
          "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
          "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota",
          "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
          "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
          "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
          "PR": "Puerto Rico", "GU": "Guam"}

TRUCK_RE = re.compile(r"\b(TRUCK|PICKUP|F-?[1-9]50|SILVERADO|SIERRA|RAM|TUNDRA|TACOMA|DUMP|FLATBED)\b", re.I)
SUV_RE = re.compile(r"\b(SUV|VAN|MINIVAN|EXPLORER|TAHOE|SUBURBAN|EXPEDITION|YUKON|ESCAPE|CARAVAN|TRANSIT|ODYSSEY|SIENNA)\b", re.I)

# slug, h1, short name, category filter or None, extra regex, intro paragraphs, home link param
TYPES = [
    ("government-surplus-trucks", "Government Surplus Trucks at Auction", "trucks", "vehicle", TRUCK_RE,
     ["Federal agencies sell pickups, dump trucks, flatbeds and utility trucks once they leave service. This page lists trucks currently offered on GSA Auctions and eBay Motors, refreshed daily.",
      "Work trucks often have high mileage and visible wear, so check the listing photos and inspection details, and ask about a viewing before you bid."],
     "type=vehicle&q=truck"),
    ("government-surplus-suvs-and-vans", "Government Surplus SUVs and Vans at Auction", "SUVs and vans", "vehicle", SUV_RE,
     ["SUVs, passenger vans and cargo vans are among the most common vehicles sold at government surplus auctions. These are current listings from GSA Auctions and eBay Motors.",
      "Condition varies a lot between lots. Read each listing for mileage, keys and title notes before you bid."],
     "type=vehicle&q=suv"),
    ("government-surplus-cars-and-trucks", "Government Surplus Cars and Trucks at Auction", "cars and trucks", "vehicle", None,
     ["Every car, truck, van and SUV we found on GSA Auctions and eBay Motors, in one list. Bids are placed on the original site, so each button below opens the real listing.",
      "Prices shown are the last bid seen at the latest update and can change at any time."],
     "type=vehicle"),
    ("boats-at-auction", "Boats at Auction: Government Surplus and eBay Motors", "boats", "boat", None,
     ["Federal agencies sell surplus boats and vessels, from small skiffs and patrol boats to larger craft. These listings come from GSA Auctions and eBay Motors.",
      "Boats can need work and are often sold as-is. Check hull, engine and trailer details in the listing, and ask about inspection before you bid."],
     "type=boat"),
    ("trailers-at-auction", "Trailers at Auction: Government Surplus and eBay Motors", "trailers", "trailer", None,
     ["Utility, flatbed, enclosed and equipment trailers appear regularly in surplus sales. These are the trailers currently listed on GSA Auctions and eBay Motors.",
      "Look for title or registration notes in each listing, since paperwork rules differ by state."],
     "type=trailer"),
    ("motorcycles-and-atvs-at-auction", "Motorcycles, ATVs and UTVs at Auction", "motorcycles and ATVs", "motorcycle", None,
     ["Motorcycles, ATVs, UTVs, scooters and golf carts sold through government surplus and eBay Motors auctions, listed in one place.",
      "Many are sold as-is. Check mileage, keys and title notes in the original listing."],
     "type=motorcycle"),
    ("rvs-and-motorhomes-at-auction", "RVs and Motorhomes at Auction", "RVs and motorhomes", "rv", None,
     ["Motorhomes and campers offered at government surplus and eBay Motors auctions.",
      "Inspect living quarters and mechanicals where you can, and read the listing for what is included."],
     "type=rv"),
    ("heavy-equipment-at-auction", "Heavy Equipment at Auction: Government Surplus", "heavy equipment", "equipment", None,
     ["Tractors, loaders, forklifts, graders and other heavy equipment sold by government agencies on GSA Auctions.",
      "Equipment is usually sold as-is, so check hours, condition notes and pickup requirements in the listing."],
     "type=equipment"),
]

CSS = """
:root{--bg:#f1f4f6;--surface:#fff;--fg:#14202b;--muted:#566878;--line:#d8e0e6;--accent:#0b6b63;--accent-fg:#fff;--soft:#e1f0ee;--hi:#a8520a;--gsa:#1d4f91;--gsa-bg:#e3edf9;--ebay:#8a2b6b;--ebay-bg:#f8e6f1;--shadow:0 1px 2px rgba(20,32,43,.06),0 6px 18px rgba(20,32,43,.07);--font-display:"Bricolage Grotesque","Helvetica Neue",Arial,sans-serif;--font-body:"Inter",system-ui,-apple-system,"Segoe UI",sans-serif}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0e151b;--surface:#161f27;--fg:#e8eef3;--muted:#94a5b4;--line:#26333f;--accent:#3fc1b2;--accent-fg:#05201d;--soft:#13302e;--hi:#f0a24a;--gsa:#8db8f0;--gsa-bg:#162a45;--ebay:#eba4d2;--ebay-bg:#3a1830;--shadow:0 1px 2px rgba(0,0,0,.4),0 6px 18px rgba(0,0,0,.3);color-scheme:dark}}
:root[data-theme="dark"]{--bg:#0e151b;--surface:#161f27;--fg:#e8eef3;--muted:#94a5b4;--line:#26333f;--accent:#3fc1b2;--accent-fg:#05201d;--soft:#13302e;--hi:#f0a24a;--gsa:#8db8f0;--gsa-bg:#162a45;--ebay:#eba4d2;--ebay-bg:#3a1830;--shadow:0 1px 2px rgba(0,0,0,.4),0 6px 18px rgba(0,0,0,.3);color-scheme:dark}
html{color-scheme:light dark}*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 var(--font-body)}
a{color:var(--accent)}:focus-visible{outline:3px solid var(--hi);outline-offset:2px}
.wrap{max-width:1160px;margin:0 auto;padding:14px 16px 48px}
.sitebar{display:flex;align-items:center;gap:6px 18px;flex-wrap:wrap;background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:10px 14px;margin-bottom:20px;box-shadow:var(--shadow)}
.sitebar .brand{display:flex;align-items:center;gap:12px;font-family:var(--font-display);font-weight:700;font-size:24px;color:var(--fg);text-decoration:none;margin-right:auto}
.sitebar .brand img{width:50px;height:50px;display:block;border-radius:12px}
.sitebar nav{display:flex;flex-wrap:wrap;align-items:center;gap:4px}
.sitebar nav a{text-decoration:none;font-size:14px;font-weight:500;color:var(--muted);padding:7px 11px;border-radius:8px}
.sitebar nav a:hover{color:var(--fg);background:var(--bg)}
.sitebar nav a.primary{background:var(--accent);color:var(--accent-fg);font-weight:600}
.sitebar nav .sep{width:1px;height:20px;background:var(--line);margin:0 4px}
.crumbs{font-size:13px;color:var(--muted);margin:0 0 8px}.crumbs a{color:var(--muted)}
h1{font-family:var(--font-display);font-size:clamp(26px,4.5vw,40px);line-height:1.1;margin:0 0 10px;text-wrap:balance}
.lead{color:var(--muted);max-width:75ch;margin:0 0 8px}
.cta{display:inline-block;margin:10px 0 4px;padding:11px 18px;border-radius:10px;background:var(--accent);color:var(--accent-fg);font-weight:600;text-decoration:none}
.ad{margin:20px 0;min-height:90px;display:flex;align-items:center;justify-content:center;border:1px dashed var(--line);border-radius:10px;color:var(--muted);font-size:12px}
.meta-line{color:var(--muted);font-size:13px;margin:16px 0 12px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:16px;list-style:none;margin:0;padding:0}
.card{display:flex;flex-direction:column;background:var(--surface);border:1px solid var(--line);border-radius:14px;overflow:hidden;box-shadow:var(--shadow);min-width:0}
.thumb{position:relative;aspect-ratio:16/10;background:linear-gradient(135deg,var(--soft),var(--bg));display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:13px;overflow:hidden}
.thumb img{width:100%;height:100%;object-fit:cover;display:block}
.badge{position:absolute;top:10px;left:10px;font-size:11px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;padding:3px 9px;border-radius:99px}
.badge.gsa{color:var(--gsa);background:var(--gsa-bg)}.badge.ebay{color:var(--ebay);background:var(--ebay-bg)}
.body{padding:13px 15px 15px;display:flex;flex-direction:column;gap:5px;flex:1}
.card h2{font-family:var(--font-display);font-size:17px;line-height:1.25;margin:0;overflow-wrap:anywhere}
.price{font-size:21px;font-weight:600;color:var(--accent)}.price small{font-size:12px;font-weight:500;color:var(--muted)}
.meta{color:var(--muted);font-size:13px}
.view{margin-top:auto;display:block;text-align:center;padding:10px;border-radius:10px;background:var(--accent);color:var(--accent-fg);font-weight:600;font-size:14px;text-decoration:none}
.empty{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:28px 20px;text-align:center}
.links{margin-top:34px}.links h2{font-family:var(--font-display);font-size:20px;margin:0 0 10px}
.links ul{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:8px}
.links a{display:inline-block;padding:7px 13px;border:1px solid var(--line);border-radius:99px;background:var(--surface);text-decoration:none;font-size:14px;color:var(--fg)}
.links a:hover{border-color:var(--accent)}
footer{margin-top:28px;font-size:12.5px;color:var(--muted);max-width:90ch}
@media(max-width:640px){.sitebar nav{display:none}.sitebar{justify-content:center;padding:14px}.sitebar .brand{margin:0;font-size:30px;gap:14px}.sitebar .brand img{width:64px;height:64px;border-radius:16px}.mobnav{display:flex!important}}
.mobnav{display:none;flex-wrap:wrap;justify-content:center;gap:8px 16px;margin:26px 0 8px;font-size:14px}.mobnav a{color:var(--accent);font-weight:600;text-decoration:none}
"""

HEAD_LINKS = ('<link rel="icon" href="/favicon.ico" sizes="48x48"><link rel="icon" href="/favicon.svg" type="image/svg+xml">'
              '<link rel="apple-touch-icon" href="/apple-touch-icon.png"><link rel="preconnect" href="https://fonts.googleapis.com">'
              '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700&family=Inter:wght@400;500;600&display=swap">')

BAR = ('<div class="sitebar"><a class="brand" href="/"><img src="/favicon.svg" alt="" width="50" height="50">Deal1Cars</a>'
       '<nav aria-label="Main"><a class="primary" href="/">Auctions</a><span class="sep" aria-hidden="true"></span>'
       '<a href="/auto-loan-calculator.html">Loan Calculator</a><a href="/tax-return.html">Tax Estimate</a>'
       '<a href="/scientific-calculator.html">Scientific</a></nav></div>')

SRC = {"gsa": "GSA Auctions", "ebay": "eBay Motors"}


def e(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def parse_end(l):
    s = l.get("endAt") or l.get("endDate")
    if not s:
        return datetime.datetime.max
    try:
        return datetime.datetime.fromisoformat(str(s).replace("Z", "")[:19])
    except ValueError:
        return datetime.datetime.max


def is_future(l, now):
    d = parse_end(l)
    if l.get("endAt"):
        return d > now
    return d == datetime.datetime.max or d.date() >= now.date()


def card(l):
    url = l.get("url") or ""
    if not re.match(r"^https?://", url, re.I):
        return ""
    img = l.get("image") or ""
    thumb = ('<img src="%s" alt="%s" loading="lazy" referrerpolicy="no-referrer" width="400" height="250">' % (e(img), e(l.get("title")))
             if re.match(r"^https?://", img, re.I) else "No photo")
    price = l.get("price")
    p = ("$%s <small>current bid</small>" % format(int(round(price)), ",")) if price else "<small>No bids yet</small>"
    loc = ", ".join(x for x in (l.get("city"), l.get("state")) if x)
    end = l.get("endDate") or ""
    rel = "noopener noreferrer sponsored" if l.get("source") == "ebay" else "noopener noreferrer"
    return ('<li class="card"><div class="thumb">%s<span class="badge %s">%s</span></div><div class="body"><h2>%s</h2>'
            '<div class="price">%s</div>%s%s<a class="view" href="%s" target="_blank" rel="%s">View on %s &#8599;</a></div></li>'
            % (thumb, "ebay" if l.get("source") == "ebay" else "gsa", e(SRC.get(l.get("source"), "Source")), e(l.get("title")), p,
               ('<div class="meta">%s</div>' % e(loc)) if loc else "",
               ('<div class="meta">Ends %s</div>' % e(end)) if end else "", e(url), rel, e(SRC.get(l.get("source"), "source site"))))


def page(path, title, desc, h1, intro, rows, total, home_q, updated, extra_links, canonical_path, noindex):
    cards = "".join(card(l) for l in rows[:MAX_CARDS])
    if cards:
        body = '<ul class="grid">%s</ul>' % cards
    else:
        body = '<div class="empty"><h2>No listings right now</h2><p>New listings are added every day. Try the <a href="/">full search</a>.</p></div>'
    more = ('<a class="cta" href="/?%s">Search and filter all %s listings</a>' % (e(home_q), format(total, ","))) if total else ""
    links = "".join('<li><a href="%s">%s</a></li>' % (e(u), e(t)) for u, t in extra_links)
    upd = ("Updated %s" % updated) if updated else ""
    doc = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
           '%s<title>%s</title><meta name="description" content="%s"><link rel="canonical" href="%s%s">%s'
           '<meta property="og:type" content="website"><meta property="og:title" content="%s"><meta property="og:description" content="%s"><meta property="og:url" content="%s%s">'
           '%s<style>%s</style></head><body><div class="wrap">%s'
           '<p class="crumbs"><a href="/">Auctions</a> &rsaquo; %s</p><h1>%s</h1>%s%s'
           '<!-- AD SPACE: top banner. Paste your ad code inside this div. --><div class="ad ad-top" aria-label="Advertisement">Ad space</div>'
           '<p class="meta-line">%s listing%s &middot; %s</p>%s'
           '<!-- AD SPACE: bottom banner. Paste your ad code inside this div. --><div class="ad ad-bottom" aria-label="Advertisement">Ad space</div>'
           '<section class="links"><h2>More ways to browse</h2><ul>%s</ul></section>'
           '<footer>Deal1Cars is an independent site and is not affiliated with GSA, GSA Auctions or eBay. Listing details, prices and end times come from those sites and can change, so confirm on the original listing before you bid. <a href="/privacy-policy.html">Privacy Policy</a></footer>'
           '<div class="mobnav"><a href="/">Auctions</a><a href="/auto-loan-calculator.html">Loan Calculator</a><a href="/tax-return.html">Tax Estimate</a><a href="/scientific-calculator.html">Scientific</a></div></div></body></html>') % (
        HEAD_LINKS, e(title), e(desc), SITE, canonical_path, '<meta name="robots" content="noindex">' if noindex else "",
        e(title), e(desc), SITE, canonical_path, "", CSS, BAR, e(h1.split(":")[0]), e(h1),
        "".join('<p class="lead">%s</p>' % e(p) for p in intro), more, format(total, ","), "" if total == 1 else "s", e(upd), body, links)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)


def main():
    try:
        with open(LISTINGS, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        print("No listings.json, nothing to build.")
        return 0
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    listings = [l for l in data.get("listings", []) if l.get("title") and is_future(l, now)]
    listings.sort(key=parse_end)
    updated = ""
    if data.get("updated"):
        try:
            updated = datetime.datetime.fromisoformat(data["updated"].replace("Z", "")).strftime("%b %d, %Y").replace(" 0", " ")
        except ValueError:
            pass
    if not listings:
        print("No listings, leaving existing pages and sitemap unchanged.")
        return 0

    # state pages
    by_state = {}
    for l in listings:
        st = (l.get("state") or "").upper()
        if st in STATES:
            by_state.setdefault(st, []).append(l)
    states = sorted([s for s, v in by_state.items() if len(v) >= MIN_STATE], key=lambda s: -len(by_state[s]))[:60]
    state_links = [("/browse/government-surplus-vehicles-%s.html" % slugify(STATES[s]), "%s (%d)" % (STATES[s], len(by_state[s]))) for s in states]
    state_links.sort(key=lambda x: x[1])
    type_links = [("/browse/%s.html" % t[0], t[1].replace(" at Auction", "").replace(": Government Surplus and eBay Motors", "").replace(": Government Surplus", "")) for t in TYPES]

    written = []
    built_types = 0
    for slug, h1, short, cat, rx, intro, home_q in TYPES:
        rows = [l for l in listings if (not cat or (l.get("category") or "vehicle") == cat)]
        if rx:
            rows = [l for l in rows if rx.search(l.get("title") or "")]
        n = len(rows)
        title = "%s | Deal1Cars" % h1
        desc = "%s %s listed now from GSA Auctions and eBay Motors. Updated hourly." % (format(n, ","), short.capitalize()) if n else \
            "Browse %s from GSA Auctions and eBay Motors on Deal1Cars." % short
        path = "/browse/%s.html" % slug
        page(os.path.join(OUT_DIR, slug + ".html"), title, desc, h1, intro, rows, n, home_q, updated,
             [l for l in type_links if l[0] != path] + [("/", "All auctions")] + state_links[:12], path, n == 0)
        if n:
            written.append(path)
            built_types += 1

    for s in states:
        name, rows = STATES[s], by_state[s]
        slug = "government-surplus-vehicles-%s" % slugify(name)
        h1 = "Government Surplus Vehicles and Boats in %s" % name
        intro = ["%d vehicle, boat and trailer auction%s currently listed in %s on GSA Auctions and eBay Motors." % (len(rows), "" if len(rows) == 1 else "s", name),
                 "Each button opens the original listing, where you can see photos, pickup location and bid details. Check inspection and pickup rules before you bid."]
        path = "/browse/%s.html" % slug
        page(os.path.join(OUT_DIR, slug + ".html"), "%s | Deal1Cars" % h1,
             "%d government surplus and eBay Motors auctions in %s: cars, trucks, boats and more. Updated hourly." % (len(rows), name),
             h1, intro, rows, len(rows), "state=%s" % s, updated, type_links + [("/", "All auctions")], path, False)
        written.append(path)

    # sitemap
    today = now.strftime("%Y-%m-%d")
    fixed = ["/", "/auto-loan-calculator.html", "/more-auction-sites.html", "/guides/how-to-buy-government-surplus-vehicle.html", "/guides/auction-fees-and-hidden-costs.html", "/tax-return.html", "/scientific-calculator.html", "/privacy-policy.html"]
    urls = [(u, "1.0" if u == "/" else None) for u in fixed] + [(u, None) for u in written]
    xml = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u, pr in urls:
        xml.append("  <url>\n    <loc>%s%s</loc>\n    <lastmod>%s</lastmod>%s\n  </url>" % (SITE, u, today, ("\n    <priority>%s</priority>" % pr) if pr else ""))
    xml.append("</urlset>\n")
    with open(SITEMAP, "w", encoding="utf-8") as f:
        f.write("\n".join(xml))

    # refresh the home page link block
    try:
        with open(INDEX, encoding="utf-8") as f:
            idx = f.read()
        block = "<!--BROWSE-LINKS-->%s<!--/BROWSE-LINKS-->" % "".join(
            '<li><a href="%s">%s</a></li>' % (e(u), e(t)) for u, t in type_links + state_links)
        new = re.sub(r"<!--BROWSE-LINKS-->.*?<!--/BROWSE-LINKS-->", lambda m: block, idx, flags=re.S)
        if new != idx:
            with open(INDEX, "w", encoding="utf-8") as f:
                f.write(new)
    except OSError:
        pass
    print("Built %d pages (%d type pages with listings, %d state pages)." % (len(written), built_types, len(states)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
