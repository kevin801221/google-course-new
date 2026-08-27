"""Lab 1：會查資料的 CLI 問答工具。

    uv run ask.py "2026 年最新的 Gemini 模型是？"
    uv run ask.py --json "..."          # 結構化輸出
    uv run ask.py --self-check          # 不打 API，用假事件驗事件處理
    uv run ask.py --aha                 # 不打 API，看事件流長相＋有無 tools 的對照表
"""

import json
import sys

MODEL = "gemini-3.7-flash"
SYSTEM = "以繁體中文回答，語氣精確，只根據搜尋到的資料回答，並附上來源。"
SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "sources": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "description": "0~1"},
    },
    "required": ["answer", "sources", "confidence"],
}

DIM, CYAN, RESET = ("\033[2m", "\033[36m", "\033[0m") if sys.stdout.isatty() else ("",) * 3


def render(events):
    """吃 SSE 事件流：逐字印答案，順手收集引用來源。

    event_type 只有這七種（注意沒有 step.complete，那是新手最常寫錯的名字）：
      interaction.created / step.start / step.delta / step.stop /
      interaction.status_update / interaction.completed / error
    這支程式只需要處理其中四種，其餘直接掉出 elif 鏈。
    """
    sources = []

    def collect(annotations):
        for a in annotations or []:
            if a.type == "url_citation":
                sources.append((a.title or a.url, a.url))

    for ev in events:
        if ev.event_type == "step.start" and ev.step.type == "google_search_call":
            print(f"{DIM}🔍 搜尋中…{RESET}", file=sys.stderr)
        elif ev.event_type == "step.delta":
            if ev.delta.type == "text":
                print(ev.delta.text, end="", flush=True)      # 逐字輸出
            elif ev.delta.type == "text_annotation_delta":
                collect(ev.delta.annotations)
        elif ev.event_type == "interaction.completed":
            # 收尾再撈一次：串流中途的 annotation delta 不保證完整
            for step in ev.interaction.steps or []:
                for block in getattr(step, "content", None) or []:
                    collect(getattr(block, "annotations", None))
        elif ev.event_type == "error":
            print(f"\n{ev.error}", file=sys.stderr)

    # ponytail: 去重只看 (title, url) 完全相同，同一頁不同 title／帶錨點的 URL 會重複；
    #           真的重複到礙眼再改成正規化 url 當 key
    return list(dict.fromkeys(sources))   # 去重且保留順序


def ask(question):
    # ponytail: 沒有 retry／timeout，撞 429 或斷線就直接 traceback（教學骨架，錯誤訊息本身就是教材）；
    #           進 CI 或跑批次再加指數退避
    from google import genai

    with genai.Client() as client:
        stream = client.interactions.create(
            model=MODEL,
            system_instruction=SYSTEM,
            input=question,
            tools=[{"type": "google_search"}],
            stream=True,
        )
        sources = render(stream)

    print(f"\n\n{CYAN}來源{RESET}")
    for title, url in sources or [("（模型沒有引用任何來源）", "")]:
        print(f"- {title} {DIM}{url}{RESET}")


def ask_json(question):
    """加分題：不串流，直接要一份符合 schema 的 JSON。"""
    from google import genai

    with genai.Client() as client:
        it = client.interactions.create(
            model=MODEL,
            system_instruction=SYSTEM,
            input=question,
            tools=[{"type": "google_search"}],
            response_mime_type="application/json",       # 有 response_format 就必填
            response_format={"type": "text", "mime_type": "application/json",
                             "schema": SCHEMA},
        )
    data = json.loads(it.output_text)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return data


# render() 有處理的四種 event_type；其餘直接掉出 elif 鏈（--aha 用它標記「接住 / 沒接」）
HANDLED = {"step.start", "step.delta", "interaction.completed", "error"}


def _fixture(grounded):
    """假事件流：欄位名與型別抄自 SDK，內容寫死。用來離線做前後對照，不打 API。"""
    from types import SimpleNamespace as N

    ann = [N(type="url_citation", title="Gemini models | Google AI",
             url="https://ai.google.dev/gemini-api/docs/models"),
           N(type="url_citation", title="Google Blog",
             url="https://blog.google/technology/google-deepmind/")] if grounded else []
    evs = [N(event_type="interaction.created", interaction=N(id="fake-1"))]
    if grounded:   # 掛了 tools 才會多出「想一下 → 去搜」這兩個 step
        evs += [N(event_type="step.start", step=N(type="thought")),
                N(event_type="step.start", step=N(type="google_search_call")),
                N(event_type="step.stop", index=1)]
    evs += [N(event_type="step.start", step=N(type="model_output")),
            N(event_type="step.delta", delta=N(type="text", text="最新的是 ")),
            N(event_type="step.delta", delta=N(type="text", text="Gemini 3.7 Flash。"))]
    if grounded:
        evs.append(N(event_type="step.delta",
                     delta=N(type="text_annotation_delta", annotations=ann)))
    evs += [N(event_type="step.stop", index=2),
            N(event_type="interaction.completed", interaction=N(steps=[
                N(type="model_output",
                  content=[N(type="text", annotations=ann or None)])]))]
    return evs


def aha():
    """離線對照：同一支 render()，事件流有沒有 google_search 差在哪。"""
    import contextlib
    import io
    import unicodedata

    def w(s):                                    # 中文全寬算 2 格，表格才不會排歪
        return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)

    def pad(s, n):
        return s + " " * max(0, n - w(s))

    def run(events):                             # 吃掉 render 印的答案，只留來源統計
        with contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()):
            return render(events)

    plain, grounded = _fixture(False), _fixture(True)

    print(f"{CYAN}[1] 一條 SSE 事件流上到底有什麼（掛了 tools 的那次）{RESET}")
    print(f"{pad('event_type', 26)}{pad('身上是什麼', 34)}render()")
    for ev in grounded:
        what = (f"step.type={ev.step.type}" if ev.event_type == "step.start" else
                f"delta.type={ev.delta.type}" if ev.event_type == "step.delta" else
                f"index={ev.index}" if ev.event_type == "step.stop" else
                f"interaction（{'有' if getattr(ev.interaction, 'steps', None) else '只有 id'}）")
        hit = "接住" if ev.event_type in HANDLED else f"{DIM}掉出 elif 鏈{RESET}"
        print(f"{pad(ev.event_type, 26)}{pad(what, 34)}{hit}")
    print(f"{DIM}思考、搜尋、講話是同一條流上的不同 step.type —— 這就是 agent 迴圈的最小版{RESET}")

    src_a, src_b = run(plain), run(grounded)
    rows = [("SSE 事件數", len(plain), len(grounded)),
            ("step 種類", len({e.step.type for e in plain if e.event_type == "step.start"}),
             len({e.step.type for e in grounded if e.event_type == "step.start"})),
            ("url_citation 標註", 0, sum(len(e.delta.annotations) for e in grounded
                                        if e.event_type == "step.delta"
                                        and e.delta.type == "text_annotation_delta")),
            ("列出的來源（去重後）", len(src_a), len(src_b))]
    k_w = max(w(k) for k, _, _ in rows) + 2
    print(f"\n{CYAN}[2] 差別只有 tools=[{{\"type\": \"google_search\"}}] 這一行{RESET}")
    print(f"{pad('指標', k_w)}{pad('沒有 tools', 16)}{pad('有 tools', 16)}差")
    for k, a, b in rows:
        d = f"{b / a:.0f}×" if a else (f"0 → {b}" if b else "—")
        print(f"{pad(k, k_w)}{pad(str(a), 16)}{pad(str(b), 16)}{d}")
    print(f"{DIM}假事件流（欄位名取自 SDK 型別，內容寫死）—— 真的問一次要 key，"
          f"數字更誇張：../google-slide/test5.py{RESET}")


def self_check():
    from types import SimpleNamespace as N

    cite = N(type="url_citation", title="Gemini docs", url="https://ai.google.dev/a")
    events = [
        N(event_type="step.start", step=N(type="google_search_call")),
        N(event_type="step.delta", delta=N(type="text", text="答案")),
        N(event_type="step.delta", delta=N(type="text", text="在此")),
        N(event_type="step.delta", delta=N(type="text_annotation_delta",
                                          annotations=[cite])),
        N(event_type="step.stop", index=0),               # 沒有 .step，碰它會 AttributeError
        N(event_type="interaction.status_update", interaction_id="x", status="in_progress"),
        N(event_type="interaction.completed", interaction=N(steps=[
            N(type="google_search_call"),                 # 這型別根本沒有 content 屬性
            N(type="model_output", content=None),         # 有屬性但是 None 也不能炸
            N(type="model_output", content=[N(type="text", annotations=[cite])]),
        ])),
    ]
    assert render(events) == [("Gemini docs", "https://ai.google.dev/a")], "重複來源要去重"
    assert render([]) == []
    # 串流版本沒帶 steps（SSE 的 interaction 是 partial resource）也要能收工
    assert render([N(event_type="interaction.completed", interaction=N(steps=None))]) == []
    # --aha 的假事件流：沒 tools 就沒來源，有 tools 才撈得到（去重後兩個）
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        assert render(_fixture(False)) == []
        assert len(render(_fixture(True))) == 2
    assert HANDLED == {"step.start", "step.delta", "interaction.completed", "error"}
    print("self-check ok")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--self-check" in args:
        self_check()
    elif "--aha" in args:
        aha()
    else:
        q = " ".join(a for a in args if not a.startswith("--"))
        if not q:
            sys.exit(__doc__)
        (ask_json if "--json" in args else ask)(q)
