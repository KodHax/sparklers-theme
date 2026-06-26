import os
from dotenv import load_dotenv

load_dotenv()


class ShopifyConfig:
    def __init__(self, shop_url: str, access_token: str = "", client_id: str = "", client_secret: str = ""):
        self.shop_url = shop_url.rstrip("/")
        self._access_token = access_token
        self._client_id = client_id
        self._client_secret = client_secret
        self.api_version = os.getenv("API_VERSION", "2024-10")
        self._resolved_token = None

    @property
    def access_token(self) -> str:
        if self._resolved_token:
            return self._resolved_token

        if self._access_token:
            self._resolved_token = self._access_token
            return self._resolved_token

        if self._client_id and self._client_secret:
            from utils.oauth import obtain_token
            self._resolved_token = obtain_token(self.shop_url, self._client_id, self._client_secret)
            return self._resolved_token

        raise RuntimeError(
            f"No credentials for {self.shop_url}. "
            "Set ACCESS_TOKEN or CLIENT_ID + CLIENT_SECRET in .env"
        )

    @property
    def graphql_url(self) -> str:
        return f"{self.shop_url}/admin/api/{self.api_version}/graphql.json"

    @property
    def rest_url(self) -> str:
        return f"{self.shop_url}/admin/api/{self.api_version}"

    @property
    def headers(self) -> dict:
        return {
            "X-Shopify-Access-Token": self.access_token,
            "Content-Type": "application/json",
        }


SOURCE = ShopifyConfig(
    shop_url=os.getenv("SOURCE_SHOP_URL", ""),
    access_token=os.getenv("SOURCE_ACCESS_TOKEN", ""),
    client_id=os.getenv("SOURCE_CLIENT_ID", ""),
    client_secret=os.getenv("SOURCE_CLIENT_SECRET", ""),
)

DEST = ShopifyConfig(
    shop_url=os.getenv("DEST_SHOP_URL", ""),
    access_token=os.getenv("DEST_ACCESS_TOKEN", ""),
    client_id=os.getenv("DEST_CLIENT_ID", ""),
    client_secret=os.getenv("DEST_CLIENT_SECRET", ""),
)

MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT_REQUESTS", "4"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "50"))
DATA_DIR = os.getenv("DATA_DIR", "./data")
LOG_DIR = os.getenv("LOG_DIR", "./logs")
