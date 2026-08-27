"""Lab 2 對照組：技術文章 → 繁中摘要器（單檔 FastAPI ＋ 一頁 HTML）。

    export GEMINI_API_KEY="..."
    uv run app.py                 # 開 http://localhost:8080
    uv run app.py --self-check    # 不連網、不打 API、不花錢，只驗邏輯
    uv run app.py --aha           # scale-to-zero 帳單試算（純算術，不連網）

這不是「標準答案」。AI Studio Build mode 生成的版本是 React + TypeScript，
檔案數十倍、長得完全不一樣。這份的用途有兩個：
  1. 對照 —— 看清「貼 URL → 摘要」這件事，最少需要哪幾行；
  2. 保底 —— Build mode 生成失敗或配額用完時，你手上還有一份能跑的東西。
"""

import json
import os
import sys
import urllib.parse

MODEL = "gemini-3.7-flash"  # 型號名以課程投影片為準；若 404 用 client.models.list() 確認

SYSTEM = """你是技術文章摘要器。只根據 url_context 真正抓到的網頁內容回答，抓不到就把欄位留空，不要憑印象編。
所有輸出用繁體中文（台灣用語），專有名詞保留英文原文。
terms 只放「一般工程師看了會停下來查」的名詞，不要解釋 HTTP、API 這種常識。
quotes 直接抄原文句子，不要改寫、不要翻譯。"""

LENGTHS = {"short": "3", "medium": "5", "long": "8"}  # 步驟 3 的迭代一：摘要長度選項

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "文章標題，翻成繁體中文"},
        "bullets": {"type": "array", "items": {"type": "string"}, "description": "重點摘要"},
        "terms": {
            "type": "array",
            "description": "名詞解釋",
            "items": {
                "type": "object",
                "properties": {"term": {"type": "string"}, "explain": {"type": "string"}},
                "required": ["term", "explain"],
            },
        },
        "quotes": {"type": "array", "items": {"type": "string"}, "description": "值得引用的原文句子，保持原文語言"},
    },
    "required": ["title", "bullets", "terms", "quotes"],
}


def check_url(raw):
    """只放行 http/https 的絕對網址；不合格丟 ValueError。

    這是 trust boundary，不能偷懶：使用者輸入會被原封不動塞進 prompt。
    不驗的話 `file:///etc/passwd`、`javascript:` 都進得來。
    """
    u = (raw or "").strip()
    p = urllib.parse.urlparse(u)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ValueError("請貼 http:// 或 https:// 開頭的完整網址")
    return u


def parse_result(it):
    """把 interaction 拆成前端要的 dict。

    重點是 url_context_result 的 status：模型讀不到文章（paywall / error / unsafe）時
    照樣會生一份「看起來很專業」的摘要。不檢查 status，你就把幻覺當摘要送給使用者。
    """
    fetched = [
        (getattr(r, "url", None), getattr(r, "status", None))
        for s in (getattr(it, "steps", None) or [])
        if getattr(s, "type", None) == "url_context_result"
        for r in (getattr(s, "result", None) or [])
    ]
    ok = [u for u, st in fetched if st == "success"]
    data = json.loads(it.output_text or "{}")
    return {
        "title": data.get("title") or "（無標題）",
        "bullets": data.get("bullets") or [],
        "terms": data.get("terms") or [],
        "quotes": data.get("quotes") or [],
        "sources": ok,
        "warning": None if ok else f"模型沒有成功讀到網頁內容（抓取紀錄：{fetched or '無'}），以下摘要不可信",
    }


def summarize(url, length="medium"):
    from google import genai

    n = LENGTHS.get(length, LENGTHS["medium"])
    with genai.Client() as client:  # 一定要 with 或綁變數，鏈式呼叫會被 GC 關掉連線
        it = client.interactions.create(
            model=MODEL,
            system_instruction=SYSTEM,
            input=f"讀這篇文章並摘要，bullets 給我 {n} 條：{url}",
            tools=[{"type": "url_context"}],  # 少了這個它就只看得到那串網址本身
            response_mime_type="application/json",  # 有 response_format 就必填
            response_format={"type": "text", "mime_type": "application/json", "schema": SCHEMA},
        )
    return parse_result(it)


# ---------- web ----------

PAGE = """<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TL;DR TW — 技術文章繁中摘要器</title>
<style>
:root{color-scheme:light dark;--bg:#fff;--fg:#1a1a1a;--dim:#666;--line:#e3e3e3;--card:#f7f7f8;--accent:#1a73e8}
@media (prefers-color-scheme:dark){html:not([data-theme=light]){--bg:#16181c;--fg:#e8eaed;--dim:#9aa0a6;--line:#2e3136;--card:#1e2126;--accent:#8ab4f8}}
html[data-theme=dark]{--bg:#16181c;--fg:#e8eaed;--dim:#9aa0a6;--line:#2e3136;--card:#1e2126;--accent:#8ab4f8}
*{box-sizing:border-box}
body{margin:0;padding:2rem 1rem;background:var(--bg);color:var(--fg);
  font:16px/1.7 -apple-system,"Noto Sans TC","Microsoft JhengHei",sans-serif}
main{max-width:44rem;margin:auto}
h1{font-size:1.4rem;margin:0}
header{display:flex;align-items:center;gap:1rem;margin-bottom:1.5rem}
#theme{margin-left:auto;background:none;border:1px solid var(--line);color:var(--fg);
  border-radius:99px;padding:.4rem .8rem;cursor:pointer}
form{display:flex;flex-wrap:wrap;gap:.5rem}
input,select,button[type=submit]{padding:.7rem;border:1px solid var(--line);border-radius:8px;
  background:var(--card);color:var(--fg);font-size:1rem}
input{flex:1 1 18rem}
button[type=submit]{background:var(--accent);color:#fff;border:0;cursor:pointer;padding:.7rem 1.4rem}
button[disabled]{opacity:.5;cursor:progress}
#warn{background:#8a3b0022;border-left:4px solid #e37400;padding:.8rem;border-radius:4px;margin-top:1.5rem}
h2{font-size:1.1rem;margin:2rem 0 .5rem;color:var(--dim);letter-spacing:.05em}
blockquote{margin:.8rem 0;padding:.6rem 1rem;border-left:4px solid var(--accent);
  background:var(--card);border-radius:0 8px 8px 0;font-style:italic}
dt{font-weight:600;margin-top:.8rem}dd{margin:0 0 0 1rem;color:var(--dim)}
a{color:var(--accent)}.dim{color:var(--dim);font-size:.9rem}
</style></head><body><main>
<header><h1>TL;DR TW</h1><button id="theme">🌓 主題</button></header>
<form id="f">
  <input id="url" type="url" required placeholder="https://ai.google.dev/gemini-api/docs/models">
  <select id="len"><option value="short">短（3 條）</option>
    <option value="medium" selected>中（5 條）</option><option value="long">長（8 條）</option></select>
  <button type="submit">摘要</button>
</form>
<div id="out"></div>
<script>
const T=document.documentElement, K="tldr-theme";
try{ if(localStorage[K]) T.dataset.theme=localStorage[K]; }catch(e){}
theme.onclick=()=>{ const v=T.dataset.theme==="dark"?"light":"dark";
  T.dataset.theme=v; try{localStorage[K]=v}catch(e){} };
// 連引號一起逃：來源網址是塞進 href="..." 裡的，只逃 <>& 的話一個 " 就能跳出屬性
const esc=s=>String(s).replace(/[<>&"']/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;',"'":'&#39;'}[c]));
f.onsubmit=async e=>{
  e.preventDefault();
  const btn=f.querySelector("button[type=submit]"); btn.disabled=true;
  out.innerHTML='<p class=dim>讀取並摘要中，通常 10–30 秒…</p>';
  try{
    const r=await fetch("/api/summarize",{method:"POST",headers:{"content-type":"application/json"},
      body:JSON.stringify({url:url.value,length:len.value})});
    const d=await r.json();
    if(!r.ok){ out.innerHTML='<div id=warn>'+esc(d.detail||d.error||r.status)+'</div>'; return; }
    out.innerHTML=
      (d.warning?'<div id=warn>⚠️ '+esc(d.warning)+'</div>':'')
      +'<h2>'+esc(d.title)+'</h2><ul>'+d.bullets.map(b=>'<li>'+esc(b)+'</li>').join('')+'</ul>'
      +(d.terms.length?'<h2>名詞解釋</h2><dl>'+d.terms.map(t=>'<dt>'+esc(t.term)+'</dt><dd>'+esc(t.explain)+'</dd>').join('')+'</dl>':'')
      +(d.quotes.length?'<h2>原文引用</h2>'+d.quotes.map(q=>'<blockquote>'+esc(q)+'</blockquote>').join(''):'')
      +(d.sources.length?'<h2>來源</h2><p class=dim>'+d.sources.map(u=>'<a href="'+esc(u)+'">'+esc(u)+'</a>').join('<br>')+'</p>':'');
  }catch(err){ out.innerHTML='<div id=warn>'+esc(err)+'</div>'; }
  finally{ btn.disabled=false; }
};
</script></main></body></html>"""


def make_app():
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse
    from pydantic import BaseModel

    class Req(BaseModel):
        url: str
        length: str = "medium"

    app = FastAPI(title="TL;DR TW")

    @app.get("/", response_class=HTMLResponse)
    def index():
        return PAGE

    @app.get("/healthz")  # Cloud Run 排錯用：不打 Gemini 也能確認容器活著
    def healthz():
        return {"ok": True, "has_key": bool(os.environ.get("GEMINI_API_KEY"))}

    @app.post("/api/summarize")
    def api(req: Req):
        try:
            url = check_url(req.url)
        except ValueError as e:
            raise HTTPException(400, str(e))
        # 這裡不能跟上面共用一個 try：SDK 沒 key 也是丟 ValueError，混在一起會把
        # 「忘了設 GEMINI_API_KEY」誤報成「網址格式錯」，學生會找錯方向找很久
        try:
            return summarize(url, req.length)
        except Exception as e:  # ponytail: 一律 500 帶原文訊息, 要分類重試就上 M10 的錯誤處理
            raise HTTPException(500, f"{type(e).__name__}: {e}")

    return app


# ---------- aha：scale-to-zero 的帳單長什麼樣 ----------
# 單價抄自 Lab 10 的費用表：vCPU-小時 $0.085、GiB-小時 $0.009，免費層每月 50 vCPU-h + 100 GiB-h。
# 這是「算術」不是「帳單」——實際金額以 GCP 帳單頁為準。
VCPU_H, GIB_H, FREE_VCPU_H, FREE_GIB_H = 0.085, 0.009, 50, 100
MONTH_H, REQS_PER_DAY, CPU_SEC, RAM_GIB = 730, 100, 20, 0.5  # 730 小時＝一個帳單月；512Mi＝0.5GiB


def bill(vcpu_h, gib_h):
    """只有超出免費層的部分才收錢。"""
    return max(0.0, vcpu_h - FREE_VCPU_H) * VCPU_H + max(0.0, gib_h - FREE_GIB_H) * GIB_H


def aha():
    tty = sys.stdout.isatty()
    bold, dim, green, reset = ("\033[1m", "\033[2m", "\033[32m", "\033[0m") if tty else ("",) * 4
    w = lambda s: sum(2 if __import__("unicodedata").east_asian_width(c) in "WF" else 1 for c in s)
    pad = lambda s, n: s + " " * max(0, n - w(s))

    used_h = REQS_PER_DAY * CPU_SEC * (MONTH_H / 24) / 3600  # 只有處理請求的那幾秒在計費
    rows = [
        ("每月 vCPU-小時", MONTH_H, used_h, "h"),
        ("每月 GiB-小時", MONTH_H * RAM_GIB, used_h * RAM_GIB, "h"),
        ("超出免費層", max(0, MONTH_H - FREE_VCPU_H), max(0, used_h - FREE_VCPU_H), "vCPU-h"),
        ("每月帳單", bill(MONTH_H, MONTH_H * RAM_GIB), bill(used_h, used_h * RAM_GIB), "$"),
    ]
    print(f"\n{bold}同一份程式碼、同一個 image，只差一個 --min-instances{reset}")
    print(f"{dim}假設：1 vCPU / 512Mi，每天 {REQS_PER_DAY} 次摘要，每次佔 CPU {CPU_SEC} 秒{reset}")
    print(f"\n{bold}{pad('指標', 18)}{pad('--min-instances 1', 22)}{pad('scale-to-zero（預設）', 26)}差距{reset}")
    print(dim + "─" * 74 + reset)
    for name, a, b, unit in rows:
        fmt = (lambda v: f"${v:,.2f}") if unit == "$" else (lambda v: f"{v:,.1f} {unit}")
        gap = f"{green}{fmt(a)} → 0{reset}" if b == 0 else f"÷{a / b:.0f}"
        print(f"{pad(name, 18)}{pad(fmt(a), 22)}{pad(fmt(b), 26)}{gap}")
    free_reqs = FREE_VCPU_H * 3600 / CPU_SEC
    print(f"\n免費層打完為止：每月 {free_reqs:,.0f} 次摘要"
          f"（約每天 {free_reqs / (MONTH_H / 24):,.0f} 次）以內，這一列都還是 $0.00")
    print(f"{dim}單價來自 Lab 10 費用表；這是算術不是帳單，實際以 GCP 帳單頁為準{reset}")


def self_check():
    from types import SimpleNamespace as N

    for bad in ["", "   ", "file:///etc/passwd", "javascript:alert(1)", "ai.google.dev", "http://"]:
        try:
            check_url(bad)
            raise AssertionError(f"{bad!r} 應該被擋掉")
        except ValueError:
            pass
    assert check_url("  https://ai.google.dev/x?a=1  ") == "https://ai.google.dev/x?a=1"

    body = json.dumps({"title": "T", "bullets": ["a"],
                       "terms": [{"term": "x", "explain": "y"}], "quotes": ["q"]})
    ok = parse_result(N(output_text=body, steps=[
        N(type="url_context_call"),                                        # 沒有 result 欄位也不能炸
        N(type="url_context_result", result=[N(url="https://a/", status="success")]),
        N(type="model_output", result=None),
    ]))
    assert ok["sources"] == ["https://a/"], ok
    assert ok["warning"] is None and ok["bullets"] == ["a"], ok

    wall = parse_result(N(output_text=body, steps=[
        N(type="url_context_result", result=[N(url="https://a/", status="paywall")])]))
    assert wall["warning"], "paywall 沒警告 = 把幻覺當摘要送出去"

    blank = parse_result(N(output_text="{}", steps=None))
    assert blank["bullets"] == [] and blank["terms"] == [] and blank["warning"], blank
    assert blank["title"] == "（無標題）", blank

    assert LENGTHS["short"] != LENGTHS["long"]

    assert round(bill(730, 365), 2) == 60.19, "常駐一個月要 (730-50)*0.085 + (365-100)*0.009"
    assert bill(16.9, 8.4) == 0, "落在免費層內就該是 0，不是「很便宜」"
    assert bill(50, 100) == 0 and bill(51, 100) > 0  # 免費層邊界
    print("self-check ok")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        self_check()
    elif "--aha" in sys.argv:
        aha()
    elif bad := [a for a in sys.argv[1:] if a.startswith("-")]:
        sys.exit(f"不認識的旗標 {bad}。可用：--aha / --self-check（不給旗標＝起伺服器）")
    else:
        import uvicorn

        # Cloud Run 從 $PORT 告訴你要聽哪個 port；寫死 8080 在別的平台會被判定啟動失敗
        uvicorn.run(make_app(), host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
