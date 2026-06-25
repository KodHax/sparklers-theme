import os
from dotenv import load_dotenv

load_dotenv()


class ShopifyConfig:
    def __init__(self, shop_url: str, access_token: str):
        self.shop_url = shop_url.rstrip("/")
        self.access_token = access_token
        self.api_version = os.getenv("API_VERSION", "2024-10")

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
)

DEST = ShopifyConfig(
    shop_url=os.getenv("DEST_SHOP_URL", ""),
    access_token=os.getenv("DEST_ACCESS_TOKEN", ""),
)

MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT_REQUESTS", "4"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "50"))
DATA_DIR = os.getenv("DATA_DIR", "./data")
LOG_DIR = os.getenv("LOG_DIR", "./logs")
