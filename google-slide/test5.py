"""普通模型 vs Deep Research：同一個問題，在 CLI 上直接看出差在哪。

    uv run test5.py                      # 用預設問題
    uv run test5.py "你的問題"            # 換問題
    uv run test5.py --full               # 印完整全文（預設只印開頭）
    uv run test5.py --self-check         # 不打 API，跑內建 assert

兩者 API 差別只有三個字：
    model=...                → 一次回答，不上網，秒級
    agent=..., background=True → 自己搜、自己讀、自己引用，分鐘級，要輪詢
"""

import os
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path

PLAIN_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.7-flash")
DEEP_AGENT = os.getenv("GEMINI_DEEP_AGENT", "deep-research-preview-04-2026")
QUESTION = "研究 2026 年 Google TPU 的發展與競爭態勢，附來源"
POLL_SECONDS = 5

DIM, BOLD, CYAN, GREEN, YELLOW, RESET = (
    ("\033[2m", "\033[1m", "\033[36m", "\033[32m", "\033[33m", "\033[0m")
    if sys.stdout.isatty() else ("",) * 6
)


# ── 對齊用：中文是全寬字，算 2 格才不會排歪 ──────────────────────────
def width(s):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def pad(s, n):
    return s + " " * max(0, n - width(s))


def summarize(interaction, secs):
    """把一次 interaction 壓成幾個可比較的數字。"""
    steps = interaction.steps or []
    kinds = Counter(s.type for s in steps)
    sources, chars = set(), 0
    for s in steps:
        for block in getattr(s, "content", None) or []:
            if block.type != "text":
                continue
            chars += len(block.text or "")
            for a in block.annotations or []:
                if getattr(a, "url", None):
                    sources.add(a.url)
    return {
        "耗時": (f"{secs:.1f}s", secs),
        "步數": (str(len(steps)), len(steps)),
        "搜尋次數": (str(kinds["google_search_call"]), kinds["google_search_call"]),
        "讀網頁": (str(kinds["url_context_call"]), kinds["url_context_call"]),
        "思考步": (str(kinds["thought"]), kinds["thought"]),
        "引用來源": (str(len(sources)), len(sources)),
        "產出字數": (f"{chars:,}", chars),
        "tokens": (f"{(interaction.usage.total_tokens if interaction.usage else 0):,}",
                   interaction.usage.total_tokens if interaction.usage else 0),
    }


def table(left, right, l_name, r_name):
    """並排比較表，最後一欄是倍數 —— 差距一眼看到。"""
    k_w = max(width(k) for k in left) + 2
    print(f"\n{BOLD}{pad('指標', k_w)}{pad(l_name, 22)}{pad(r_name, 22)}倍數{RESET}")
    print(DIM + "─" * (k_w + 50) + RESET)
    for k in left:
        a, b = left[k][1], right[k][1]
        ratio = f"{b / a:.0f}×" if a else (f"{GREEN}0 → {b}{RESET}" if b else "—")
        print(f"{pad(k, k_w)}{pad(left[k][0], 22)}{pad(right[k][0], 22)}{ratio}")


def preview(text, full, n=600):
    return text if full else (text[:n] + f"{DIM}…（共 {len(text):,} 字，全文見 .md）{RESET}"
                              if len(text) > n else text)


def run(question, full=False):
    from google import genai

    with genai.Client() as client:
        # ── 普通模型：一次就回，沒有工具、沒有來源 ──────────────────
        print(f"{BOLD}問題{RESET} {question}\n")
        print(f"{CYAN}{BOLD}[1] 普通模型{RESET} {DIM}model={PLAIN_MODEL}{RESET}")
        t0 = time.monotonic()
        plain = client.interactions.create(model=PLAIN_MODEL, input=question)
        plain_stats = summarize(plain, time.monotonic() - t0)
        print(f"    {GREEN}完成{RESET} {plain_stats['耗時'][0]}\n")

        # ── Deep Research：agent= + background=True，然後輪詢 ────────
        print(f"{CYAN}{BOLD}[2] Deep Research{RESET} {DIM}agent={DEEP_AGENT}, background=True{RESET}")
        t0 = time.monotonic()
        deep = client.interactions.create(
            agent=DEEP_AGENT, input=question, background=True)
        while deep.status in ("queued", "in_progress"):
            time.sleep(POLL_SECONDS)
            deep = client.interactions.get(deep.id)
            kinds = Counter(s.type for s in deep.steps or [])
            trail = " ".join(f"{k}×{v}" for k, v in kinds.most_common(4))
            # \r 原地更新：學生看得到它一步一步在搜、在讀
            print(f"\r    {YELLOW}{deep.status}{RESET} "
                  f"{time.monotonic() - t0:5.0f}s  {DIM}{trail}{RESET}\033[K", end="")
        elapsed = time.monotonic() - t0
        print(f"\r    {GREEN}{deep.status}{RESET} {elapsed:.1f}s\033[K")
        if deep.status != "completed":
            print(f"{YELLOW}未完成：{deep.errors}{RESET}")
            return
        deep_stats = summarize(deep, elapsed)

    table(plain_stats, deep_stats, "普通模型", "Deep Research")

    for name, it in (("out-plain.md", plain), ("out-deep.md", deep)):
        Path(name).write_text(it.output_text or "")
    print(f"\n{CYAN}{BOLD}普通模型回答{RESET}\n{preview(plain.output_text or '', full)}")
    print(f"\n{CYAN}{BOLD}Deep Research 報告{RESET}\n{preview(deep.output_text or '', full)}")
    print(f"\n{DIM}全文：out-plain.md / out-deep.md{RESET}")


# ── 內建自我檢查：用假物件驗統計與排版，不打 API ──────────────────────
def self_check():
    from types import SimpleNamespace as N

    cite = N(type="url_citation", url="https://a.dev")
    fake = N(usage=N(total_tokens=91204), steps=[
        N(type="google_search_call", content=None),
        N(type="google_search_call", content=None),
        N(type="url_context_call", content=None),
        N(type="thought", content=[N(type="text", text="嗯", annotations=None)]),
        N(type="model_output", content=[
            N(type="text", text="報告" * 10, annotations=[cite, cite]),
            N(type="image", text=None, annotations=None)]),
    ])
    s = summarize(fake, 214.5)
    assert s["搜尋次數"][1] == 2 and s["讀網頁"][1] == 1 and s["思考步"][1] == 1
    assert s["引用來源"][1] == 1, "同一個 url 重複引用只能算一個來源"
    assert s["產出字數"][1] == 21 and s["tokens"][0] == "91,204"

    empty = summarize(N(usage=None, steps=None), 3.2)
    assert empty["步數"][1] == 0 and empty["tokens"][1] == 0  # 沒 steps 也不能炸

    assert width("普通模型") == 8 and width("abc") == 3
    assert pad("耗時", 8) == "耗時" + " " * 4
    print(f"{GREEN}self-check ok{RESET}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--self-check" in args:
        self_check()
    else:
        q = next((a for a in args if not a.startswith("--")), QUESTION)
        run(q, full="--full" in args)
