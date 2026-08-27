"""Enterprise（Vertex）路線連通性 smoke test：Lab 5 步驟 4 與 7 的驗收工具。

跑法：
    uv run vertex_smoke.py               # 真的呼叫一次 Gemini（要 ADC ＋ aiplatform API 已開）
    uv run vertex_smoke.py --self-check  # 只驗環境變數判斷邏輯，不連網、不花錢
    uv run vertex_smoke.py --explain     # 印出目前環境會走哪條路線，不呼叫 API
    uv run vertex_smoke.py --aha         # 同一行 Client()、三種憑證的端點對照，離線、不花錢

型號名以課程投影片為準（gemini-3.7-flash）。若 404，用 client.models.list() 確認現行型號。
"""

import os
import sys

MODEL = "gemini-3.7-flash"


def resolve_route(env):
    """看環境變數決定會走哪條路線，回 (route, project, location, problems)。

    這是整支腳本唯一不 trivial 的邏輯：SDK 的路線選擇規則寫在 _api_client.py，
    學生 90% 的「明明設了卻連不上」都是這裡沒對齊。
    """
    enterprise_raw = env.get("GOOGLE_GENAI_USE_ENTERPRISE") or env.get("GOOGLE_GENAI_USE_VERTEXAI")
    # SDK 的判斷就是這一行（_api_client.py:655-662）：只認 'true' / '1'，不分大小寫。
    enterprise = str(enterprise_raw).lower() in ("true", "1")
    project = env.get("GOOGLE_CLOUD_PROJECT")
    location = env.get("GOOGLE_CLOUD_LOCATION")
    api_key = env.get("GEMINI_API_KEY") or env.get("GOOGLE_API_KEY")
    problems = []

    if not enterprise:
        if enterprise_raw is not None:
            problems.append(
                f"GOOGLE_GENAI_USE_ENTERPRISE={enterprise_raw!r} 不算 true："
                f"SDK 只認 'true' 與 '1'（不分大小寫），其他值一律當沒設，靜默走 Developer 路線"
            )
        if api_key:
            return "developer", None, None, problems
        problems.append("既沒開 Enterprise 也沒有 API key → Client() 會丟 "
                        "ValueError: No API key was provided.")
        return "none", None, None, problems

    if not project:
        problems.append("GOOGLE_CLOUD_PROJECT 沒設 → SDK 會去 ADC 撈 project，撈不到就丟 "
                        "'Could not resolve project using application default credentials.'")
    if not location:
        problems.append("GOOGLE_CLOUD_LOCATION 沒設 → 課程統一 us-central1")
    if api_key:
        problems.append("同時有 API key 與 project/location：明確傳入的 project/location 會贏，"
                        "SDK 只記一條 INFO log（預設看不到），所以出錯時很難察覺。"
                        "跑 Enterprise 就把 GEMINI_API_KEY unset。")
    return "enterprise", project, location, problems


def explain(env):
    route, project, location, problems = resolve_route(env)
    print(f"路線：{route}  project={project}  location={location}")
    for p in problems:
        print(f"  ! {p}")
    return route == "enterprise" and not any("沒設" in p for p in problems)


def call(project, location):
    # import 放在函式裡：--self-check / --explain 就不用裝 google-genai 也能跑
    from google import genai

    # 一定要 with（或綁變數）。genai.Client().interactions.create(...) 的 Client
    # 是暫時物件，請求送出前就被 GC 關掉 → RuntimeError: Cannot send a request,
    # as the client has been closed.
    with genai.Client(enterprise=True, project=project, location=location) as client:
        it = client.interactions.create(
            model=MODEL,
            input="用一句話確認 Vertex 通了，並說出你是哪個模型。",
        )
    print(it.output_text)
    print(f"[tokens] {it.usage.total_tokens}", file=sys.stderr)


# ── --aha：同一行 genai.Client()，換環境變數就換伺服器 ──────────────────
ENV_KEYS = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_ENTERPRISE",
            "GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION")

CODE = "genai.Client()"  # 三個情境的程式碼欄位都填這個字串 —— 這就是重點

SCENARIOS = [
    ("Lab 1（M1-M4）", {"GEMINI_API_KEY": "fake-not-a-real-key"},
     "你貼進 shell 的字串"),
    ("Lab 5 本機（現在）", {"GOOGLE_GENAI_USE_ENTERPRISE": "True",
                            "GOOGLE_CLOUD_PROJECT": "agent-course-2026",
                            "GOOGLE_CLOUD_LOCATION": "us-central1"},
     "~/.config/gcloud/…default_credentials.json"),
    ("Lab 10 Cloud Run", {"GOOGLE_GENAI_USE_ENTERPRISE": "True",
                          "GOOGLE_CLOUD_PROJECT": "agent-course-2026",
                          "GOOGLE_CLOUD_LOCATION": "us-central1"},
     "metadata server 現發的短效 token"),
]


def width(s):
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def pad(s, n):
    return s + " " * max(0, n - width(s))


def probe(env):
    """在假環境下建一個 Client，回它「決定要打哪台伺服器」的結果。不連網、不呼叫 API。"""
    from google import genai

    saved = {k: os.environ.pop(k, None) for k in ENV_KEYS}
    try:
        os.environ.update(env)
        client = genai.Client()
        api = client._api_client  # 內部欄位：這裡就是要掀開蓋子看
        return api._http_options.base_url
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v


def aha():
    tty = sys.stdout.isatty()
    B, D, G, R = ("\033[1m", "\033[2m", "\033[32m", "\033[0m") if tty else ("",) * 4
    rows = [(name, probe(env), cred) for name, env, cred in SCENARIOS]

    w0 = max(width(r[0]) for r in rows) + 2
    w1 = max(width(CODE), 14) + 2
    w2 = max(width(r[1]) for r in rows) + 2
    print(f"\n{B}{pad('情境', w0)}{pad('程式碼', w1)}{pad('SDK 實際打的端點', w2)}憑證從哪來{R}")
    print(D + "─" * (w0 + w1 + w2 + 30) + R)
    for name, base, cred in rows:
        print(f"{pad(name, w0)}{pad(CODE, w1)}{pad(base, w2)}{cred}")

    print(f"\n{D}① 與 ② 是本機真的建出 Client 量到的；③ 的環境變數與 ② 相同，"
          f"差別只在憑證來源（本機沒有 metadata server，端點沿用 ② 的量測值）。{R}")
    print(f"程式碼欄位三格完全相同 → {G}{B}diff 0 行{R}；端點從 "
          f"{rows[0][1]} 換成 {rows[1][1]} → {G}{B}換了一台伺服器{R}")
    print(f"{D}換憑證是改環境，不是改程式碼。{R}\n")


def self_check():
    E = "GOOGLE_GENAI_USE_ENTERPRISE"

    # --aha 的排版：中文全寬字算 2 格，不然表格會歪
    assert width("情境") == 4 and width("abc") == 3
    assert pad("情境", 8) == "情境    " and pad("太長了啦", 2) == "太長了啦"

    # 三件套都齊 → enterprise，沒問題
    r, p, l, probs = resolve_route({E: "True", "GOOGLE_CLOUD_PROJECT": "agent-course-2026",
                                   "GOOGLE_CLOUD_LOCATION": "us-central1"})
    assert (r, p, l, probs) == ("enterprise", "agent-course-2026", "us-central1", []), (r, p, l, probs)

    # 舊名 GOOGLE_GENAI_USE_VERTEXAI 仍然吃（2025 舊寫法，SDK 還相容）
    r, _, _, _ = resolve_route({"GOOGLE_GENAI_USE_VERTEXAI": "TRUE",
                                "GOOGLE_CLOUD_PROJECT": "x", "GOOGLE_CLOUD_LOCATION": "y"})
    assert r == "enterprise", r

    # 開了 Enterprise 但沒 project → 要點出 ADC 撈不到 project 的錯誤
    r, p, _, probs = resolve_route({E: "true", "GOOGLE_CLOUD_LOCATION": "us-central1"})
    assert r == "enterprise" and p is None
    assert any("Could not resolve project" in x for x in probs), probs

    # 沒 location → 要提醒
    _, _, l, probs = resolve_route({E: "true", "GOOGLE_CLOUD_PROJECT": "x"})
    assert l is None and any("GOOGLE_CLOUD_LOCATION" in x for x in probs), probs

    # "1" 算 true（SDK 認）
    r, _, _, _ = resolve_route({E: "1", "GOOGLE_CLOUD_PROJECT": "x", "GOOGLE_CLOUD_LOCATION": "y"})
    assert r == "enterprise", r

    # 打錯值：SDK 只認 true/1，寫 yes 會被當成沒設 → 不能謊報 enterprise
    r, _, _, probs = resolve_route({E: "yes", "GOOGLE_CLOUD_PROJECT": "x", "GOOGLE_CLOUD_LOCATION": "y"})
    assert r == "none" and any("不算 true" in x for x in probs), (r, probs)
    r, _, _, probs = resolve_route({E: "True!", "GEMINI_API_KEY": "k"})
    assert r == "developer" and any("不算 true" in x for x in probs), probs

    # 什麼都沒有 → 要預告 SDK 的真實錯誤訊息
    r, _, _, probs = resolve_route({})
    assert r == "none" and any("No API key was provided" in x for x in probs), probs

    # 只有 API key → developer 路線（M1-M4 用的那條）
    r, _, _, probs = resolve_route({"GEMINI_API_KEY": "k"})
    assert (r, probs) == ("developer", []), (r, probs)

    # Enterprise + API key 同時在 → 要警告，但仍走 enterprise
    r, _, _, probs = resolve_route({E: "True", "GOOGLE_CLOUD_PROJECT": "x",
                                   "GOOGLE_CLOUD_LOCATION": "y", "GEMINI_API_KEY": "k"})
    assert r == "enterprise" and any("同時有 API key" in x for x in probs), probs

    print("vertex_smoke.py --self-check 全部通過")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        self_check()
    elif "--aha" in sys.argv:
        aha()
    elif "--explain" in sys.argv:
        sys.exit(0 if explain(os.environ) else 1)
    else:
        route, project, location, problems = resolve_route(os.environ)
        if route != "enterprise":
            print(f"環境不是 Enterprise 路線（目前：{route}）。要跑這個 smoke test 請先：", file=sys.stderr)
            print("  export GOOGLE_GENAI_USE_ENTERPRISE=True", file=sys.stderr)
            print("  export GOOGLE_CLOUD_PROJECT=<你的專案ID>", file=sys.stderr)
            print("  export GOOGLE_CLOUD_LOCATION=us-central1", file=sys.stderr)
            for p in problems:
                print(f"  ! {p}", file=sys.stderr)
            sys.exit(1)
        for p in problems:
            print(f"! {p}", file=sys.stderr)
        if not project or not location:
            sys.exit(1)
        call(project, location)
