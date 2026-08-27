"""把五支 --self-check 收成 pytest 一個檔，CI 只要 uv run pytest -q。"""

import pytest

from civicguard import audit, brief, cwa, mcp_server, shelters


@pytest.mark.parametrize("mod", [audit, brief, cwa, shelters, mcp_server])
def test_self_check(mod):
    mod._self_check()
