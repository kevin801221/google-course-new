"""多模態輸入教學範例：一張圖 + 一句問題 → 模型回答。

CLI 視覺化每一步，讓學生看得到「檔案 → bytes → parts → 請求 → 回答」的流程。

    uv run muti-modal.py architecture.png "這張架構圖有什麼單點故障風險？"
    uv run muti-modal.py architecture.png --dry-run   # 沒有 API key 也能跑，只看流程
    uv run muti-modal.py --self-check                 # 跑內建 assert

依賴在 pyproject.toml（uv add google-genai），uv run 會自己準備好環境。
"""

import base64
import mimetypes
import os
import sys

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.7-flash")
INLINE_LIMIT = 20 * 1024 * 1024  # 超過就要走 files.upload()

# ── CLI 視覺化（只用 ANSI，不裝任何套件）────────────────────────────
DIM, BOLD, CYAN, GREEN, YELLOW, RESET = (
    ("\033[2m", "\033[1m", "\033[36m", "\033[32m", "\033[33m", "\033[0m")
    if sys.stdout.isatty() else ("",) * 6
)
_n = [0]


def step(title, *lines):
    _n[0] += 1
    print(f"\n{CYAN}{BOLD}[{_n[0]}] {title}{RESET}")
    for line in lines:
        print(f"    {DIM}│{RESET} {line}")


def bar(nbytes, limit=INLINE_LIMIT, width=32):
    """把檔案大小畫成佔 inline 上限的比例條。"""
    filled = min(width, max(1, round(nbytes / limit * width)))
    color = YELLOW if nbytes > limit else GREEN
    return f"{color}{'█' * filled}{DIM}{'░' * (width - filled)}{RESET}"


def human(nbytes):
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024 or unit == "GB":
            return f"{nbytes:.1f}{unit}"
        nbytes /= 1024


# ── 流程 ────────────────────────────────────────────────────────────
# mime 大類 → SDK content block 的 type。PDF/CSV 走 "document"，不是 "file"。
KIND = {"image": "image", "video": "video", "audio": "audio",
        "application": "document", "text": "document"}


def build_parts(path, prompt):
    """讀檔 → 猜 mime → 組成 input content blocks。

    教學重點：SDK 的 data 欄位吃的是 base64 字串（或 Path / 檔案物件），
    直接塞 raw bytes 會在 pydantic 序列化時炸掉。
    """
    with open(path, "rb") as f:
        data = f.read()
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    kind = KIND.get(mime.split("/")[0], "document")
    return data, mime, kind, [
        {"type": "text", "text": prompt},
        {"type": kind,
         "data": base64.b64encode(data).decode(),  # ← 不是 bytes
         "mime_type": mime},
    ]


def to_sdk(parts):
    """dict → SDK 的 content 物件。

    教學重點（也是最容易中的坑）：這個 SDK 不吃 dict。
    傳 dict 進去不會報錯，會被當成 UNKNOWN block 原樣送出，
    模型於是「看不到圖」，只回答文字問題。必須用型別化的 content 類別。
    """
    from google.genai._gaos.types.interactions import (
        AudioContent, DocumentContent, ImageContent, TextContent, VideoContent)

    cls = {"text": TextContent, "image": ImageContent, "video": VideoContent,
           "audio": AudioContent, "document": DocumentContent}
    return [cls[p["type"]](**{k: v for k, v in p.items() if k != "type"})
            for p in parts]


def run(path, prompt, dry_run=False):
    step("讀入檔案", f"path = {path}")
    data, mime, kind, parts = build_parts(path, prompt)

    step("檔案 → bytes",
         f"size = {human(len(data))}  {bar(len(data))}",
         f"inline 上限 20MB{'（超過！請改用 client.files.upload()）' if len(data) > INLINE_LIMIT else ''}")

    step("猜出 mime_type",
         f"mime_type = {BOLD}{mime}{RESET}  →  block type = {BOLD}{kind}{RESET}",
         f"base64 後 = {human(len(parts[1]['data']))}（比原檔大約 4/3 倍）",
         "影片 / 音訊 / PDF 同理：只是換 mime_type，程式碼一行都不用改")

    step("組成 input parts（模型眼中的樣子）")
    for p in parts:
        body = p.get("text") or f"<base64 {human(len(p['data']))} of {p['mime_type']}>"
        print(f"      {DIM}-{RESET} type={p['type']:<6} {body}")

    step("送出請求", f"model = {MODEL}",
         "dict → TextContent / ImageContent 物件（dict 會被當 UNKNOWN 丟掉）")
    if dry_run:
        print(f"    {DIM}│{RESET} {YELLOW}--dry-run：不呼叫 API{RESET}")
        return None

    from google import genai  # 放在這裡：--dry-run 不需要裝套件

    # Client 一定要綁在變數上（或用 with）：寫成 genai.Client().interactions.create(...)
    # 的話 Client 是暫時物件，會在請求送出前被 GC 關掉 → "client has been closed"。
    with genai.Client() as client:
        interaction = client.interactions.create(model=MODEL, input=to_sdk(parts))

    step("模型回答")
    print(f"\n{interaction.output_text}\n")
    return interaction.output_text


# ── 內建自我檢查 ─────────────────────────────────────────────────────
def self_check():
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"\x89PNG" + b"\x00" * 100)
    data, mime, kind, parts = build_parts(f.name, "hi")
    assert mime == "image/png" and kind == "image", (mime, kind)
    assert len(data) == 104 and parts[0]["text"] == "hi"
    assert base64.b64decode(parts[1]["data"]) == data  # data 必須是 base64 字串
    assert isinstance(parts[1]["data"], str)
    pdf = f.name.replace(".png", ".pdf")
    os.rename(f.name, pdf)
    _, mime, kind, parts = build_parts(pdf, "hi")
    assert (mime, kind, parts[1]["type"]) == ("application/pdf", "document", "document")
    from google.genai._gaos import models, utils
    req = utils.unmarshal({"api_version": "v1beta",
                           "body": {"model": MODEL, "input": to_sdk(parts)}},
                          models.CreateInteractionRequest)
    blocks = req.body.model_dump(by_alias=True, mode="json", exclude_none=True)["input"]
    assert [b["type"] for b in blocks] == ["text", "document"], blocks  # 不能是 UNKNOWN
    assert human(1536) == "1.5KB" and human(500) == "500.0B"
    assert "█" in bar(1) and "░" in bar(1)
    os.unlink(pdf)
    print(f"{GREEN}self-check ok{RESET}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--self-check" in args:
        self_check()
    elif not args:
        print(__doc__)
    else:
        dry = "--dry-run" in args
        args = [a for a in args if not a.startswith("--")]
        run(args[0], args[1] if len(args) > 1 else "描述這個檔案的內容與風險。", dry)
