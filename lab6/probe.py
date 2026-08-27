"""用 MCP client 直接把 server 當子行程跑起來，驗 tools/resources/prompts 都活著。

Inspector 是給人點的；這支是給你貼在終端機裡當驗收指令的（不用瀏覽器、不用 host）。

跑法：
  uv run probe.py               # 走 stdio，自己 spawn server.py（會打一次 open-meteo）
  uv run probe.py --offline     # 跳過會連網的 get_weather
  uv run probe.py --aha         # 三張對照表：你敲的 vs 模型收到的（不連網）
"""

import ast
import asyncio
import json
import pathlib
import sys
import unicodedata

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = pathlib.Path(__file__).parent.resolve()
# host 也是用這種方式啟動我們：uv run --directory <專案> server.py
PARAMS = StdioServerParameters(command="uv", args=["run", "--directory", str(HERE), "server.py"])


async def main(offline: bool):
    async with stdio_client(PARAMS) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()

            tools = (await s.list_tools()).tools
            print("tools:", [t.name for t in tools])
            for t in tools:
                # description 空的＝忘了寫 docstring，模型會亂選工具
                assert t.description, f"{t.name} 沒有 description（docstring 忘了寫）"
                types = {k: v.get("type") for k, v in t.input_schema["properties"].items()}
                assert "string" not in types.values(), f"{t.name} 參數變成 string，型別註記漏了：{types}"
                print(f"  {t.name} {types} required={t.input_schema['required']}")

            ok = await s.call_tool("convert_currency", {"amount": 100})
            print("convert_currency(100) ->", ok.content[0].text.replace("\n", ""))
            assert not ok.is_error and "3200" in ok.content[0].text

            bad = await s.call_tool("convert_currency", {"amount": -5})
            print("convert_currency(-5) -> is_error =", bad.is_error, "|", bad.content[0].text)
            assert bad.is_error and "必須 >= 0" in bad.content[0].text  # 訊息要傳到模型手上

            templates = [r.uri_template for r in (await s.list_resource_templates()).resource_templates]
            print("resource templates:", templates)
            text = (await s.read_resource("course://glossary/mcp")).contents[0].text
            print("course://glossary/mcp ->", text[:40], "…")
            assert "USB-C" in text

            prompts = (await s.list_prompts()).prompts
            print("prompts:", [p.name for p in prompts])
            got = await s.get_prompt("daily_briefing", {"city": "高雄"})
            assert "get_weather" in got.messages[0].content.text

            if offline:
                print("skip get_weather（--offline）")
            else:
                w = await s.call_tool("get_weather", {"lat": 25.03, "lon": 121.56})
                print("get_weather(台北) ->", w.content[0].text.replace("\n", ""))
                assert not w.is_error and "temp_c" in w.content[0].text

    print("probe OK")


# ── 以下是 --aha 用的：把「你敲的鍵盤」和「模型收到的規格」擺在一起看 ──────────

# M1 手寫 function calling declaration 的等價物（同樣兩個工具）。字元數就是你要敲的量。
HAND_DECL = """[
  {
    "name": "convert_currency",
    "description": "把美元金額換算成新台幣（TWD）。什麼時候用我：使用者提到美元、USD、匯率換算時。",
    "parameters": {
      "type": "object",
      "properties": {
        "amount": {"type": "number", "description": "美元金額，必須 >= 0"},
        "rate": {"type": "number", "description": "1 美元兌台幣的匯率，必須 > 0，預設 32.0"}
      },
      "required": ["amount"]
    }
  },
  {
    "name": "get_weather",
    "description": "查詢指定經緯度的即時天氣：氣溫、風速、降雨量。",
    "parameters": {
      "type": "object",
      "properties": {
        "lat": {"type": "number", "description": "緯度 -90~90"},
        "lon": {"type": "number", "description": "經度 -180~180"}
      },
      "required": ["lat", "lon"]
    }
  }
]"""

BOLD, DIM, CYAN, GREEN, RESET = (
    ("\033[1m", "\033[2m", "\033[36m", "\033[32m", "\033[0m")
    if sys.stdout.isatty() else ("",) * 5
)


def _w(s):  # 中文是全寬字，算 2 格才不會排歪
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _pad(s, n):
    return s + " " * max(0, n - _w(s))


def _row(cells, widths):
    print("".join(_pad(c, w) for c, w in zip(cells, widths)))


def _server_source():
    """從 server.py 的 AST 撈兩個工具的 docstring 與行數 —— 不 import，沒有副作用。"""
    tree = ast.parse((HERE / "server.py").read_text())
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in ("convert_currency", "get_weather"):
            out[node.name] = (ast.get_docstring(node), node.end_lineno - node.lineno + 1, node.lineno)
    return out


async def aha():
    src = _server_source()
    async with stdio_client(PARAMS) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()
            tools = (await s.list_tools()).tools
            templates = (await s.list_resource_templates()).resource_templates
            prompts = (await s.list_prompts()).prompts

            # 拆開來看才誠實：schema 是 SDK 生的，description 是你 docstring 的原文
            gen_schema = sum(len(json.dumps(t.input_schema, ensure_ascii=False)) for t in tools)
            gen_desc = sum(len(t.description) for t in tools)
            gen = gen_schema + gen_desc
            hand = len(HAND_DECL)
            py_lines = sum(v[1] for v in src.values())

            print(f"\n{BOLD}{CYAN}① 你敲的鍵盤 vs 模型收到的規格{RESET}  {DIM}（兩個工具合計）{RESET}")
            w = [34, 24, 26]
            print(BOLD + "".join(_pad(c, x) for c, x in zip(["指標", "手寫 declaration（M1）", "@mcp.tool()"], w)) + RESET)
            print(DIM + "─" * sum(w) + RESET)
            _row(["你敲的 declaration 字元", f"{hand:,}", f"{GREEN}0{RESET}"], w)
            _row(["你敲的 python 行（含 docstring）", "還要另外寫函式本體", f"{py_lines}"], w)
            _row(["模型收到的規格字元", f"{hand:,}", f"{gen:,}"], w)
            _row(["  ↳ SDK 從型別註記生的 schema", "0（都是你敲的）", f"{gen_schema:,}"], w)
            _row(["  ↳ 你 docstring 的原文", f"（含在上面 {hand} 裡）", f"{gen_desc:,}"], w)
            _row(["再加第 3 個工具要敲的 schema", "再一份", f"{GREEN}0{RESET}"], w)
            _row(["再接第 2、3、4 個 host", "每個 host 一份", f"{GREEN}改設定檔，程式 0 行{RESET}"], w)

            print(f"\n{BOLD}{CYAN}② 模型看到的原文，逐字就是你的 docstring{RESET}")
            for t in tools:
                doc, _, lineno = src[t.name]
                same = doc.strip() == t.description.strip()  # SDK 只多補一個結尾換行
                print(f"  {t.name}  server.py L{lineno} 的 docstring == 模型收到的 description ？ "
                      f"{(GREEN if same else '') + str(same) + RESET}")
            head = tools[0].description.splitlines()[0]
            print(f'  {DIM}模型讀到的第一行：{RESET}「{head}」')
            payload = len(json.dumps([t.model_dump() for t in tools], ensure_ascii=False))
            print(f"  {DIM}tools/list 完整 payload {payload:,} 字元 —— 每開一個新對話就整份送進 context{RESET}")

            print(f"\n{BOLD}{CYAN}③ 你寫了 4 個能力，模型自己碰得到幾個{RESET}")
            w2 = [36, 22, 16]
            print(BOLD + "".join(_pad(c, x) for c, x in zip(["能力", "誰決定要用它", "在 tools/list？"], w2)) + RESET)
            print(DIM + "─" * sum(w2) + RESET)
            for t in tools:
                _row([f"{t.name} (tool)", "模型", f"{GREEN}是{RESET}"], w2)
            for r in templates:
                _row([f"{r.uri_template} (resource)", "host／使用者", "否"], w2)
            for p in prompts:
                _row([f"{p.name} (prompt)", "使用者按 /", "否"], w2)
            n = len(tools) + len(templates) + len(prompts)
            print(f"  {DIM}→ 寫了 {n} 個能力，模型自己叫得動 {len(tools)} 個；"
                  f"名詞表 agent 永遠不會自己去查。{RESET}")
    print("\naha OK")


if __name__ == "__main__":
    if "--aha" in sys.argv:
        asyncio.run(aha())
    else:
        asyncio.run(main("--offline" in sys.argv))
