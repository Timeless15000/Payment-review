"""
Outstanding dashboard + Payment Review — builds index.html (served by GitHub Pages).

Pulls ALL outstanding (AUTHORISED / awaiting-payment) sales invoices for the
three Timeless entities from the Xero API, plus contact emails and org
short-codes, and renders template.html into index.html.

Environment variables (provided by GitHub Actions secrets):
    XERO_CLIENT_ID, XERO_CLIENT_SECRET, XERO_REFRESH_TOKEN
The refresh token rotates each run; the new one is written to token.json,
which the workflow commits back to the repo.
"""
import os, json, base64, datetime, re, time
from zoneinfo import ZoneInfo
import requests

CLIENT_ID = os.environ["XERO_CLIENT_ID"]
CLIENT_SECRET = os.environ["XERO_CLIENT_SECRET"]

ENTITY_ORDER = ["SOR", "TCC", "TPM", "TF"]
ENTITY_LABEL = {"SOR": "SOR", "TCC": "TCCS", "TPM": "TPM", "TF": "TF"}
ENAMES = {"ALL": "All entities", "TPM": "Timeless Property Maintenance",
          "SOR": "SOR Services", "TCC": "Timeless Commercial Clean Sydney",
          "TF": "Teamforce"}
# fallback short-codes if the API doesn't return one
ORG_FALLBACK = {"SOR": "!1jrRM", "TCC": "!xWj4p", "TPM": "!Z8FyC", "TF": ""}


def entity_code(tenant_name):
    n = tenant_name.lower()
    if "property maintenance" in n: return "TPM"
    if "sor services" in n:         return "SOR"
    if "commercial clean" in n:     return "TCC"
    if "teamforce" in n:            return "TF"
    return None


def _save(rt):
    json.dump({"refresh_token": rt}, open("token.json", "w"))


def refresh(rt):
    """Swap a refresh token for an access token, retrying transient errors.

    The new refresh token is written to token.json IMMEDIATELY, and the
    workflow commits it even when a later step fails - otherwise one bad
    run would silently burn the token and break every run after it.
    """
    basic = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    last = None
    for attempt in range(3):
        try:
            r = requests.post("https://identity.xero.com/connect/token",
                headers={"Authorization": f"Basic {basic}",
                         "Content-Type": "application/x-www-form-urlencoded"},
                data={"grant_type": "refresh_token", "refresh_token": rt},
                timeout=30)
            if r.status_code == 429 or r.status_code >= 500:
                last = RuntimeError(f"Xero returned {r.status_code}")
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code >= 400:
                # Xero's body says WHY: invalid_grant (token dead or already
                # used) vs invalid_client (client id/secret don't match).
                print(f"Xero {r.status_code} body: {r.text[:300]}", flush=True)
                raise RuntimeError(f"Xero {r.status_code} {r.text[:200]}")
            r.raise_for_status()
            tok = r.json()
            _save(tok["refresh_token"])
            return tok["access_token"]
        except requests.RequestException as e:
            last = e
            time.sleep(5 * (attempt + 1))
    raise last


def get_access_token():
    """token.json first, then the XERO_REFRESH_TOKEN secret as a backup.

    Falling back means a single dead token no longer needs a manual
    GET_TOKEN.bat run - the schedule heals itself on the next attempt.
    """
    tried = []
    if os.path.exists("token.json"):
        try:
            return refresh(json.load(open("token.json"))["refresh_token"])
        except Exception as e:
            tried.append(f"token.json -> {e}")
            print("token.json refresh failed:", e, flush=True)
    backup = os.environ.get("XERO_REFRESH_TOKEN", "").strip()
    if backup:
        try:
            access = refresh(backup)
            print("Recovered using the XERO_REFRESH_TOKEN secret.", flush=True)
            return access
        except Exception as e:
            tried.append(f"XERO_REFRESH_TOKEN -> {e}")
    raise SystemExit("Xero auth failed. Re-run GET_TOKEN.bat and update "
                     "token.json + the XERO_REFRESH_TOKEN secret. "
                     + " | ".join(tried))


def api_get(access, tenant_id, path, params=None):
    r = requests.get("https://api.xero.com/api.xro/2.0/" + path,
        headers={"Authorization": f"Bearer {access}",
                 "Xero-tenant-id": tenant_id, "Accept": "application/json"},
        params=params or {})
    r.raise_for_status()
    return r.json()


def get_tenants(access):
    r = requests.get("https://api.xero.com/connections",
                     headers={"Authorization": f"Bearer {access}",
                              "Content-Type": "application/json"})
    r.raise_for_status()
    return r.json()


def get_shortcode(access, tenant_id):
    try:
        orgs = api_get(access, tenant_id, "Organisation").get("Organisations", [])
        sc = (orgs[0].get("ShortCode") or "").strip() if orgs else ""
        if sc and not sc.startswith("!"):
            sc = "!" + sc
        return sc or None
    except Exception:
        return None


def get_unpaid_invoices(access, tenant_id):
    out, page = [], 1
    while True:
        j = api_get(access, tenant_id, "Invoices",
                    {"where": 'Type=="ACCREC" AND Status=="AUTHORISED"',
                     "page": page, "pageSize": 100})
        inv = j.get("Invoices", [])
        if not inv: break
        out.extend(inv)
        if len(inv) < 100: break
        page += 1
    return out


def get_contact_emails(access, tenant_id, ids):
    """ContactID -> email (may be empty)."""
    emails = {}
    ids = [i for i in ids if i]
    for k in range(0, len(ids), 40):
        chunk = ids[k:k + 40]
        try:
            j = api_get(access, tenant_id, "Contacts", {"IDs": ",".join(chunk)})
            for c in j.get("Contacts", []):
                emails[c.get("ContactID")] = (c.get("EmailAddress") or "").strip()
        except Exception:
            pass
    return emails


def parse_date(s):
    try: return datetime.date.fromisoformat(s[:10])
    except Exception: return None


def tnorm(s):
    s = re.sub(r"^[.\-|=*\s•]+", "", str(s or ""))
    return re.sub(r"[\s\-–]+$", "", s).strip().lower()


ABBR = {"street": "st", "road": "rd", "avenue": "ave", "drive": "dr",
        "highway": "hwy", "parade": "pde", "place": "pl", "court": "ct",
        "crescent": "cres", "lane": "ln", "boulevard": "bvd", "square": "sq"}


def mnorm(s):
    """Looser form for terminated-name matching: tnorm + drop punctuation +
    abbreviate street words + collapse spaces."""
    s = re.sub(r"[^a-z0-9 ]", " ", tnorm(s))
    words = [ABBR.get(w, w) for w in s.split()]
    return " ".join(words)


def spnum(s):
    m = re.search(r"\b(?:sp|dp)\s*(\d{3,})", str(s or "").lower())
    return m.group(1) if m else None


def match_terminated(site, live, live_items):
    """Find the live unpaid group for a terminated customer.
    1) exact normalised name  2) unique SP/DP number  3) unique name-prefix
    (both compared in a loose form: punctuation removed, Street->St etc)."""
    n = tnorm(site)
    if not n:
        return None
    a = live.get(n)
    if a:
        return a
    num = spnum(site)
    if num:
        hits = [x for k, x in live_items if spnum(k) == num]
        if len(hits) == 1:
            return hits[0]
    nn = mnorm(site)
    if len(nn) >= 4:
        hits = []
        for k, x in live_items:
            kk = mnorm(k)
            if len(kk) >= 4 and (kk.startswith(nn) or nn.startswith(kk)):
                hits.append(x)
        if len(hits) == 1:
            return hits[0]
    return None


def build():
    access = get_access_token()
    tenants = get_tenants(access)
    today = datetime.datetime.now(ZoneInfo("Australia/Sydney")).date()
    rows = []
    orgsc = {}
    for t in tenants:
        code = entity_code(t["tenantName"])
        if not code: continue
        tid = t["tenantId"]
        orgsc[code] = get_shortcode(access, tid) or ORG_FALLBACK.get(code, "")
        invs = get_unpaid_invoices(access, tid)
        cids = list({(iv.get("Contact") or {}).get("ContactID") for iv in invs})
        emails = get_contact_emails(access, tid, cids)
        for iv in invs:
            due = parse_date(iv.get("DueDateString") or iv.get("DueDate", "") or "")
            idt = parse_date(iv.get("DateString") or iv.get("Date", "") or "")
            days = (today - due).days if due and (today - due).days > 0 else None
            ct = iv.get("Contact") or {}
            rows.append({
                "ent": code,
                "contact": (ct.get("Name") or "").strip(),
                "cid": ct.get("ContactID") or "",
                "em": emails.get(ct.get("ContactID"), ""),
                "inv": iv.get("InvoiceNumber", ""),
                "id": iv.get("InvoiceID", ""),
                "ref": iv.get("Reference", ""),
                "amount": float(iv.get("AmountDue", 0) or 0),
                "days": days,
                "y": idt.year if idt else None,
                "m": idt.month if idt else None,
                "my": idt.strftime("%b %Y") if idt else None,
                "dt": idt.strftime("%-d %b %Y") if idt else "",
            })

    # ---- DATA (dashboard aggregation, same as the original) ----
    groups = {}
    for r in rows:
        key = (r["ent"], r["contact"].lstrip("=").strip())
        groups.setdefault(key, []).append(r)
    agg = []
    for (ent, cleaned), items in groups.items():
        has_eq = any(i["contact"].lstrip().startswith("=") for i in items)
        disp = ("=" + cleaned) if has_eq else cleaned
        dated = [i for i in items if i["y"]]
        oldest = min(dated, key=lambda i: (i["y"], i["m"]))["my"] if dated else None
        invs = sorted(items, key=lambda i: ((i["y"] or 0), (i["m"] or 0), i["amount"]), reverse=True)
        agg.append({"ent": ent, "site": disp, "count": len(items),
                    "total": round(sum(i["amount"] for i in items), 2), "oldest": oldest,
                    "invoices": [{"inv": i["inv"], "ref": i["ref"], "amount": i["amount"],
                                  "days": i["days"], "my": i["my"], "id": i["id"]} for i in invs]})
    # live lookup for the Terminated view BEFORE the SOR 2+ filter
    live_by_ent = {}
    for a in agg:
        live_by_ent.setdefault(a["ent"], {})[tnorm(a["site"])] = a
    # SOR shows sites with 2+ unpaid only (same as the original dashboard)
    agg = [a for a in agg if not (a["ent"] == "SOR" and a["count"] < 2)]
    agg.sort(key=lambda x: (-x["count"], -x["total"]))

    # ---- TERMI (terminated customers; seed list + live amounts) ----
    termi = []
    try:
        seed = json.load(open("terminated_seed.json", encoding="utf-8"))
    except Exception:
        seed = []
    for s in seed:
        ent_live = live_by_ent.get(s["ent"], {})
        a = match_terminated(s["site"], ent_live, list(ent_live.items()))
        termi.append({
            "ent": s["ent"], "site": s["site"],
            "termdate": s.get("termdate", ""), "paid": a is None,
            "team": s.get("team", ""),
            "count": a["count"] if a else 0,
            "total": a["total"] if a else 0,
            "oldest": (a.get("oldest") or "") if a else "",
            "invoices": a["invoices"] if a else [],
        })

    # ---- PAY (flat rows for the Payment Review view) ----
    pay = []
    for r in rows:
        if r["y"] is None: continue
        pay.append({"e": r["ent"], "c": r["contact"], "cid": r["cid"], "em": r["em"],
                    "d": r["y"] * 12 + (r["m"] - 1), "a": r["amount"], "n": r["inv"],
                    "r": r["ref"], "dt": r["dt"], "od": r["days"], "id": r["id"]})

    now = datetime.datetime.now(ZoneInfo("Australia/Sydney"))
    updated = now.strftime("%-d %b %Y · %-I:%M %p ") + now.tzname()
    asat = now.strftime("%-d %b %Y")

    html = open("template.html", encoding="utf-8").read()
    html = (html.replace("__DATA__", json.dumps(agg))
                .replace("__ENAMES__", json.dumps(ENAMES))
                .replace("__TERMI__", json.dumps(termi))
                .replace("__PAY__", json.dumps(pay))
                .replace("__ORGSC__", json.dumps(orgsc))
                .replace("__UPDATED__", updated)
                .replace("__ASAT__", asat)
                .replace("__TZ__", now.tzname()))
    open("index.html", "w", encoding="utf-8").write(html)
    print("Built index.html:", len(rows), "invoices,", len(agg), "sites,",
          len(pay), "pay rows,", len(termi), "terminated,", "orgs:", orgsc)


if __name__ == "__main__":
    build()
