"""Cloud Run service-to-service 認證的三個小函式。只用標準庫，沒有 ADK 依賴。

跑法：
  uv run --no-project concierge/auth.py --self-check   # 離線驗，不連網、不花錢

為什麼要獨立成一支檔案：agent.py 一 import google.adk 就需要整套環境，
這裡想驗的其實只是「audience 算得對不對」——那是 401 最常見的原因，
單獨拉出來就能離線驗到，不必為了跑一個 assert 去裝 200MB 依賴。
"""

import sys
from types import SimpleNamespace


def audience(url):
    """ID token 的 audience：目標服務的根網址，不含路徑。

    Cloud Run 驗 token 時比對的是 audience 全等，多一個 /mcp 就 401，
    而且錯誤訊息只說 "Unauthorized"，不會告訴你是 audience 的問題。
    """
    if "://" not in url:
        raise ValueError("audience 需要完整網址（含 https://），收到 %r" % url)
    scheme, rest = url.split("://", 1)
    return scheme + "://" + rest.split("/", 1)[0]


def endpoint(base):
    """把服務根網址補成 MCP 端點：一定要有一個（且只有一個）/mcp。"""
    base = base.rstrip("/")
    return base if base.endswith("/mcp") else base + "/mcp"


def auth_headers(url, fetch=None):
    """回傳呼叫 url 要帶的 header。

    走 `gcloud run services proxy` 的 localhost 不需要 header —— proxy 已經幫你簽好了，
    再自己塞一個 Authorization 進去反而會蓋掉 proxy 的，變成 401。
    """
    aud = audience(url)
    if aud.split("://", 1)[1].split(":")[0] in ("localhost", "127.0.0.1"):
        return {}
    if fetch is None:
        fetch = _fetch_id_token
    return {"Authorization": "Bearer " + fetch(aud)}


def _fetch_id_token(aud):
    """真的去換 token。在 Cloud Run 裡走 metadata server，本機走 ADC。

    延後 import：--self-check 不該為了驗字串處理去裝 google-auth。
    """
    import google.auth.transport.requests
    import google.oauth2.id_token

    return google.oauth2.id_token.fetch_id_token(
        google.auth.transport.requests.Request(), aud
    )


def _self_check():
    assert audience("https://mcp-tools-abc123-uc.a.run.app/mcp") == \
        "https://mcp-tools-abc123-uc.a.run.app"
    assert audience("https://x-uc.a.run.app") == "https://x-uc.a.run.app"
    assert audience("https://x-uc.a.run.app/") == "https://x-uc.a.run.app"
    try:
        audience("mcp-tools-abc.run.app")   # 忘了寫 https:// 是真的會發生
    except ValueError:
        pass
    else:
        raise AssertionError("少了 scheme 應該要噴 ValueError")

    assert endpoint("https://x-uc.a.run.app") == "https://x-uc.a.run.app/mcp"
    assert endpoint("https://x-uc.a.run.app/") == "https://x-uc.a.run.app/mcp"
    assert endpoint("https://x-uc.a.run.app/mcp") == "https://x-uc.a.run.app/mcp"
    assert endpoint("https://x-uc.a.run.app/mcp/") == "https://x-uc.a.run.app/mcp"

    # 假的 token 來源：記下被要求的 audience，證明我們沒把 /mcp 一起送出去
    spy = SimpleNamespace(seen=[])

    def fake(aud):
        spy.seen.append(aud)
        return "fake-token"

    h = auth_headers("https://mcp-tools-abc123-uc.a.run.app/mcp", fetch=fake)
    assert h == {"Authorization": "Bearer fake-token"}, h
    assert spy.seen == ["https://mcp-tools-abc123-uc.a.run.app"], spy.seen

    def boom(aud):
        raise AssertionError("proxy 不該去換 token")

    assert auth_headers("http://localhost:3000/mcp", fetch=boom) == {}
    assert auth_headers("http://127.0.0.1:3000/mcp", fetch=boom) == {}

    print("self-check ok")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
    else:
        print(__doc__)
