import asyncio
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from rich.console import Console

console = Console()


class GraphQLClient:
    def __init__(self, config, max_concurrent: int = 4):
        self.config = config
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self._client = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            headers=self.config.headers,
            timeout=httpx.Timeout(60.0, connect=10.0),
        )
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException)),
    )
    async def execute(self, query: str, variables: dict | None = None) -> dict:
        async with self.semaphore:
            response = await self._client.post(
                self.config.graphql_url,
                json={"query": query, "variables": variables or {}},
            )
            response.raise_for_status()
            data = response.json()

            if "errors" in data:
                errors_str = str(data["errors"])
                for err in data["errors"]:
                    ext = err.get("extensions", {})
                    if "THROTTLED" in str(ext) or "MAX_COST_EXCEEDED" in str(ext):
                        cost_info = ext.get("cost", {})
                        wait_time = max(cost_info.get("requestedQueryCost", 2) / 100, 2)
                        console.print(f"[yellow]Throttled/cost exceeded, waiting {wait_time:.0f}s...[/yellow]")
                        await asyncio.sleep(min(wait_time, 10))
                        raise httpx.HTTPStatusError(
                            "Throttled", request=response.request, response=response
                        )
                if not data.get("data"):
                    console.print(f"[red]GraphQL errors: {errors_str[:500]}[/red]")

            return data

    async def paginate(self, query: str, path: list[str], variables: dict | None = None) -> list:
        all_items = []
        vars_ = dict(variables or {})
        vars_.setdefault("cursor", None)

        while True:
            data = await self.execute(query, vars_)
            node = data.get("data", {})
            for key in path:
                node = node.get(key, {})

            edges = node.get("edges", [])
            if not edges:
                break

            all_items.extend([edge["node"] for edge in edges])
            page_info = node.get("pageInfo", {})

            if not page_info.get("hasNextPage"):
                break

            vars_["cursor"] = edges[-1]["cursor"]
            console.print(f"  [dim]Fetched {len(all_items)} items...[/dim]")

        return all_items
