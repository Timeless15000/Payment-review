"""
ONE-TIME Xero authorisation. Run this ONCE on your own computer to grant the
app access to your Xero organisations and obtain a refresh token.

Usage (in a terminal / command prompt, in this folder):
    pip install requests
    set XERO_CLIENT_ID=your_client_id            (Windows)   OR
    export XERO_CLIENT_ID=your_client_id         (Mac/Linux)
    set XERO_CLIENT_SECRET=your_client_secret
    python authorize.py

A browser window opens -> log in to Xero -> on the "allow access" screen
TICK ALL THREE organisations (TPM, SOR, TCC) -> Allow.
The script prints your REFRESH TOKEN. Copy it; you'll paste it into GitHub
as the secret XERO_REFRESH_TOKEN.
"""
import os, base64, secrets, urllib.parse, webbrowser, http.server, threading, requests

CLIENT_ID = os.environ["XERO_CLIENT_ID"]
CLIENT_SECRET = os.environ["XERO_CLIENT_SECRET"]
REDIRECT = "http://localhost:8080/callback"
SCOPE = "openid profile email accounting.invoices.read accounting.contacts.read accounting.settings.read offline_access"

code_holder = {}
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.urlparse(self.path)
        if q.path == "/callback":
            params = urllib.parse.parse_qs(q.query)
            code_holder["code"] = params.get("code", [None])[0]
            self.send_response(200); self.end_headers()
            self.wfile.write(b"<h2>Done. You can close this tab and return to the terminal.</h2>")
        else:
            self.send_response(404); self.end_headers()
    def log_message(self, *a): pass

def main():
    state = secrets.token_urlsafe(16)
    auth_url = "https://login.xero.com/identity/connect/authorize?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": CLIENT_ID, "redirect_uri": REDIRECT,
        "scope": SCOPE, "state": state,
    }, quote_via=urllib.parse.quote)
    print(">>> authorize.py VERSION 7 (adds contacts/settings read)  |  scope =", SCOPE)
    print(">>> AUTH URL:", auth_url)
    srv = http.server.HTTPServer(("localhost", 8080), H)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    print("Opening browser to authorise. TICK ALL 3 ORGANISATIONS on the consent screen.")
    webbrowser.open(auth_url)
    while "code" not in code_holder:
        pass
    code = code_holder["code"]
    basic = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    r = requests.post("https://identity.xero.com/connect/token",
        headers={"Authorization": f"Basic {basic}",
                 "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT})
    r.raise_for_status()
    tok = r.json()
    print("\n==================  YOUR REFRESH TOKEN  ==================\n")
    print(tok["refresh_token"])
    print("\n==========================================================")
    print("Copy the line above into GitHub as the secret  XERO_REFRESH_TOKEN")

if __name__ == "__main__":
    main()
