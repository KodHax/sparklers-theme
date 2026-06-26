"""
Shopify OAuth 2.0 flow for apps created via Partners/Dev Dashboard.
Launches a local HTTP server to capture the authorization callback,
then exchanges the code for an offline access token.
"""
import hashlib
import hmac
import json
import os
import secrets
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlencode, urlparse, parse_qs

import httpx
from rich.console import Console

console = Console()

SCOPES = (
    "read_products,write_products,"
    "read_inventory,write_inventory,"
    "read_locations,"
    "read_content,write_content,"
    "read_metaobjects,write_metaobjects,"
    "read_publications,write_publications,"
    "read_product_listings,"
    "read_collection_listings,"
    "write_merchant_managed_fulfillment_orders,"
    "read_assigned_fulfillment_orders"
)

TOKEN_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def _cache_path(shop_domain: str) -> str:
    os.makedirs(TOKEN_CACHE_DIR, exist_ok=True)
    safe = shop_domain.replace("https://", "").replace("/", "_").replace(".", "_")
    return os.path.join(TOKEN_CACHE_DIR, f".token_{safe}.json")


def _load_cached_token(shop_domain: str) -> str | None:
    path = _cache_path(shop_domain)
    if os.path.exists(path):
        with open(path, "r") as f:
            data = json.load(f)
            token = data.get("access_token")
            if token:
                console.print(f"  [green]Using cached token for {shop_domain}[/green]")
                return token
    return None


def _save_token(shop_domain: str, access_token: str):
    path = _cache_path(shop_domain)
    with open(path, "w") as f:
        json.dump({"access_token": access_token}, f)


def invalidate_cached_token(shop_url: str):
    """Delete cached token to force re-authentication."""
    shop_domain = shop_url.rstrip("/")
    path = _cache_path(shop_domain)
    if os.path.exists(path):
        os.remove(path)
        console.print(f"  [yellow]Token cache removed for {shop_domain}[/yellow]")
    else:
        console.print(f"  [dim]No cached token found for {shop_domain}[/dim]")


def _verify_hmac(query_params: dict, client_secret: str) -> bool:
    params = {k: v for k, v in query_params.items() if k != "hmac"}
    sorted_params = "&".join(f"{k}={params[k]}" for k in sorted(params))
    digest = hmac.new(
        client_secret.encode(), sorted_params.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(digest, query_params.get("hmac", ""))


def obtain_token(shop_url: str, client_id: str, client_secret: str) -> str:
    """Run full OAuth flow: authorize -> callback -> exchange -> return access_token."""
    shop_domain = shop_url.rstrip("/")

    cached = _load_cached_token(shop_domain)
    if cached:
        return cached

    callback_port = int(os.getenv("OAUTH_CALLBACK_PORT", "8899"))
    redirect_uri = f"http://localhost:{callback_port}/callback"
    nonce = secrets.token_hex(16)

    shop_name = shop_domain.replace("https://", "").replace(".myshopify.com", "")
    auth_url = (
        f"https://{shop_name}.myshopify.com/admin/oauth/authorize?"
        + urlencode({
            "client_id": client_id,
            "scope": SCOPES,
            "redirect_uri": redirect_uri,
            "state": nonce,
        })
    )

    console.print(f"\n[bold yellow]═══ AUTENTICAÇÃO OAUTH ═══[/bold yellow]")
    console.print(f"  Loja: {shop_domain}")
    console.print(f"\n  [bold]Abre este URL no browser para autorizar:[/bold]")
    console.print(f"  [link]{auth_url}[/link]\n")

    webbrowser.open(auth_url)

    authorization_code = None
    received_state = None

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal authorization_code, received_state
            parsed = urlparse(self.path)
            params = {k: v[0] for k, v in parse_qs(parsed.query).items()}

            if parsed.path == "/callback" and "code" in params:
                authorization_code = params["code"]
                received_state = params.get("state")

                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h2>Autorizado com sucesso!</h2>"
                    b"<p>Pode fechar esta janela.</p></body></html>"
                )
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Invalid callback")

        def log_message(self, format, *args):
            pass

    console.print(f"  [dim]Aguardando callback em localhost:{callback_port}...[/dim]")
    server = HTTPServer(("localhost", callback_port), CallbackHandler)
    server.handle_request()
    server.server_close()

    if not authorization_code:
        raise RuntimeError("OAuth callback failed: no authorization code received")

    if received_state != nonce:
        raise RuntimeError("OAuth state mismatch — possible CSRF attack")

    console.print("  [green]Código de autorização recebido. A trocar por token...[/green]")

    token_url = f"https://{shop_name}.myshopify.com/admin/oauth/access_token"
    resp = httpx.post(token_url, json={
        "client_id": client_id,
        "client_secret": client_secret,
        "code": authorization_code,
    }, timeout=30.0)
    resp.raise_for_status()

    access_token = resp.json().get("access_token")
    if not access_token:
        raise RuntimeError(f"Token exchange failed: {resp.text}")

    _save_token(shop_domain, access_token)
    console.print("  [bold green]Token obtido e guardado com sucesso![/bold green]\n")

    return access_token
