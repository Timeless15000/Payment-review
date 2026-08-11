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
import os, json, base64, datetime, re
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


def load_refresh_token():
    if os.path.exists("token.json"):
        return json.load(open("token.json"))["refresh_token"]
    return os.environ["XERO_REFRESH_TOKEN"]


def refresh(rt):
    basic = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    r = requests.post("https://identity.xero.com/connect/token",
        headers={"Authorization": f"Basic {basic}",
                 "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "refresh_token", "refresh_token": rt})
    r.raise_for_status()
    tok = r.json()
    json.dump({"refresh_token": tok["refresh_token"]}, open("token.json", "w"))
    return tok["access_token"]


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
    return re.sub(r"^[.\-|=*\s•]+", "", str(s or "")).strip().lower()


def build():
    access = refresh(load_refresh_token())
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
    live = {(a["ent"], tnorm(a["site"])): a for a in agg}
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
        a = live.get((s["ent"], tnorm(s["site"])))
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
