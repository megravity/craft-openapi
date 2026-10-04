import asyncio

import httpx
import pytest

from craft_wrapper.craft.daily.client import DailyClient
from craft_wrapper.craft.transport import CraftTransport


@pytest.mark.parametrize("markdown", [False, True])
def test_opaque_id_encoding_without_date_selector(markdown):
    calls = []

    async def run():
        def handler(request):
            calls.append(request)
            assert request.url.path == "/api/v1/blocks"
            assert dict(request.url.params) == {"id": "opaque &/?#%", "maxDepth": "1"}
            assert "#" not in str(request.url)
            if markdown:
                return httpx.Response(
                    200, text="Example", headers={"content-type": "text/markdown"}
                )
            return httpx.Response(200, json={"id": "opaque &/?#%", "type": "page"})

        async with httpx.AsyncClient(
            base_url="https://example.test/api/v1/", transport=httpx.MockTransport(handler)
        ) as http:
            client = DailyClient(CraftTransport(http))
            await (
                client.read_markdown("opaque &/?#%")
                if markdown
                else client.get_block("opaque &/?#%")
            )

    asyncio.run(run())
    assert len(calls) == 1
