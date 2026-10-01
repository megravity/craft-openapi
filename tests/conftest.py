import json
from pathlib import Path

import pytest

from craft_wrapper.config import Settings


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        craft_space_base_url="https://connect.craft.do/links/testing-link-secret/api/v1",
        wrapper_api_token="test-wrapper-token",
    )


@pytest.fixture
def fixtures():
    return json.loads((Path(__file__).parent / "fixtures" / "space.json").read_text())
