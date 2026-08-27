"""AI 日報電台產線（Lab 4.5 骨架，一個檔案裝完整條產線）。

在 ai-daily-radio/ 目錄下跑：
  uv run airadio --self-check                  # 離線邏輯檢查（assert，不連網、不花錢）
  uv run airadio run --dry-run                 # 假資料跑完十個步驟，不需任何憑證
  uv run airadio aha [lines|tools|quota]       # 三張離線對照表（見 walkthrough 的啊哈段）
  uv run airadio run                           # 真的跑（需 nlm login；上傳需 secrets/token.json）
  uv run airadio run --resume                  # 續跑：state 已有結果的步驟直接跳過
  uv run airadio fetch --hours 24 --out build/digest.md
  uv run airadio wait --notebook <nb-id> --artifact <artifact-id>
  uv run airadio validate-meta build/meta.json
  uv run airadio upload --video build/episode.mp4 --privacy unlisted --verify
  uv run airadio auth --client secrets/client_secret.json
  uv run airadio captions --video-id <id> --file build/podcast_norm.srt --language zh-TW

投影片把產線拆成 fetch/notebook/studio/post/youtube/run 六個模組；
# ponytail: 這裡先一個檔案裝完（約 726 行，含 self-check 與 aha），真的痛了再照投影片拆成六個模組。
"""
from __future__ import annotations

import argparse
import calendar
import json
import os
import re
import subprocess
import sys
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]      # ai-daily-radio/
BUILD, STATE, REPORTS = ROOT / "build", ROOT / "state", ROOT / "reports"
TOKEN = ROOT / "secrets" / "token.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.force-ssl"]  # 一次要齊，事後補要重走同意流程
MIN_ITEMS = 8            # 當日素材少於這個數就中止（RSS 邊緣快取會回空）
MAX_ITEMS = 40           # 一集講不完 120 則；全文來源優先，其餘截斷
PER_SOURCE = 5           # 每個 feed 最多幾則——arXiv 一天幾百篇，不設上限整集都是它
BANNED = ("震撼", "炸裂", "你不知道", "驚人", "必看", "史上最", "細思極恐", "秒懂")
DRY = False              # ponytail: 用全域旗標，不做 context 物件；只有 sh()/檔案落地會看它


class Pipeline(Exception):
    """產線的預期失敗：訊息要能直接讀懂，因為它會出現在 launchd 的 log 裡。"""


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)     # stdout 留給機器讀的 JSON


# ---------- 外部指令：dry-run 時不執行，直接回假資料 ----------

def sh(*args: str, want_json: bool = True, fake=None):
    if DRY:
        log(f"[dry-run] $ {' '.join(args)}")
        return fake if fake is not None else {}
    try:
        p = subprocess.run(args, capture_output=True, text=True)
    except FileNotFoundError:
        raise Pipeline(f"找不到指令 {args[0]}——nlm 用 `uv tool install notebooklm-mcp-cli`；"
                       f"ffmpeg 用 `brew install ffmpeg`；沒有憑證時先跑 --dry-run")
    if p.returncode != 0:
        raise Pipeline(f"{args[0]} 失敗（exit {p.returncode}）：{p.stderr.strip()[:400]}")
    if not want_json:
        return p.stdout
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        raise Pipeline(f"{args[0]} 沒有回 JSON（少了 --json？）：{p.stdout.strip()[:200]}")


def nlm(*args: str, want_json: bool = True, fake=None):
    # 只有帶 --json 的子指令才回 JSON；source add／download 回的是人類可讀文字，要 want_json=False
    return sh("nlm", *args, want_json=want_json, fake=fake)


def touch(path: Path, text: str = "dry-run placeholder\n") -> Path:
    """dry-run 也要產出檔案，下游的 exists() 檢查才過得去。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(text, encoding="utf-8")
    return path


# ---------- 狀態機：冪等的全部祕密就這 10 行 ----------

def state_path(day: str) -> Path:
    return STATE / f"{day}.json"


def load_state(day: str, resume: bool) -> dict:
    p = state_path(day)
    if p.exists() and resume:
        return json.loads(p.read_text(encoding="utf-8"))
    return {"day": day, "dry_run": DRY, "steps": {}}


def save_state(st: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    state_path(st["day"]).write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def step(st: dict, name: str, fn):
    """已完成的步驟直接回舊結果——生成類步驟每天只有 3（免費）／20（AI Pro）次。"""
    if name in st["steps"]:
        log(f"  ↷ 跳過 {name}（state 已有結果）")
        return st["steps"][name]["result"]
    t0 = time.monotonic()
    try:
        result = fn()
    except Exception as e:
        st["steps"][name] = {"error": f"{type(e).__name__}: {e}", "elapsed_s": round(time.monotonic() - t0, 1)}
        save_state(st)
        raise
    st["steps"][name] = {"result": result, "elapsed_s": round(time.monotonic() - t0, 1)}
    save_state(st)                               # 每步就落地，Ctrl-C 才不會白跑
    log(f"  ✓ {name}（{st['steps'][name]['elapsed_s']}s）")
    return result


# ---------- ① fetch：抓、濾、去重、合併 ----------

def read_feeds() -> list[dict]:
    return tomllib.loads((ROOT / "feeds.toml").read_text(encoding="utf-8"))["feeds"]


FAKE_ENTRIES = [
    {"title": "Gemini 3.7 Flash 上線", "link": "https://blog.google/x1", "summary": "假資料摘要一。",
     "source": "Google AI", "ts": None, "full": True},
    {"title": "Gemini 3.7 Flash 上線", "link": "https://blog.google/x1-dup", "summary": "重複標題，會被去掉。",
     "source": "TechCrunch AI", "ts": None, "full": False},
    {"title": "A2A 1.0 定版", "link": "https://arxiv.org/abs/2601.00001", "summary": "假資料摘要二。",
     "source": "arXiv cs.AI", "ts": None, "full": True},
]


def fetch_entries(feeds: list[dict]) -> list[dict]:
    import feedparser                            # 延後 import：--dry-run 不需要裝任何依賴

    out = []
    for f in feeds:
        url = f["url"]
        if "arxiv" in url:
            url += ("&" if "?" in url else "?") + f"cb={int(time.time())}"   # 邊緣快取會回空
        d = feedparser.parse(url)
        for e in d.entries[:40]:
            tt = getattr(e, "published_parsed", None) or getattr(e, "updated_parsed", None)
            out.append({
                "title": (getattr(e, "title", "") or "").strip(),
                "link": getattr(e, "link", "") or "",
                "summary": re.sub(r"<[^>]+>", "", getattr(e, "summary", "") or "").strip(),
                "source": f["name"],
                "ts": calendar.timegm(tt) if tt else None,
                "full": bool(f.get("full_text")),
            })
    return out


def norm_title(t: str) -> str:
    return re.sub(r"[\W_]+", "", t.lower())[:60]


def select_items(items: list[dict], hours: int, now: float) -> list[dict]:
    """留 hours 小時內的、去重（同標題或同連結只留第一則）。"""
    cut = now - hours * 3600
    seen, out = set(), []
    for it in items:
        if it["ts"] is not None and it["ts"] < cut:
            continue
        # ponytail: 沒給日期的 feed 一律當新的收；要更嚴就改成丟掉並在 report 記數
        key = norm_title(it["title"]) or it["link"]
        if key in seen or not it["link"]:
            continue
        seen.add(key)
        out.append(it)
    return out


def cap_by_source(items: list[dict], limit: int = MAX_ITEMS, per_source: int = PER_SOURCE) -> list[dict]:
    """全文來源排前面，且每個 feed 最多 per_source 則。

    只排序不設上限的話，arXiv 一天幾百篇會把 40 個位置全吃掉（實測 40 則裡 35 則是 arXiv），
    節目就變成論文摘要朗讀 —— 投影片 p.206 的「全文來源至少要佔一半」根本達不到。
    """
    out, used = [], {}
    for it in sorted(items, key=lambda i: not i["full"]):     # 穩定排序，全文的先進來
        if used.get(it["source"], 0) >= per_source:
            continue
        used[it["source"]] = used.get(it["source"], 0) + 1
        out.append(it)
        if len(out) >= limit:
            break
    return out


def build_digest(day: str, items: list[dict]) -> str:
    lines = [f"# AI 日報素材包 {day}", "",
             f"共 {len(items)} 則。每則都附原始連結，節目內容只能以此為依據。", ""]
    for i, it in enumerate(items, 1):
        lines += [f"## {i}. {it['title']}", f"- 來源：{it['source']}", f"- 連結：{it['link']}",
                  "", (it["summary"] or "")[:1500], ""]
    return "\n".join(lines)


def do_fetch(day: str, hours: int, out: Path) -> dict:
    items = FAKE_ENTRIES if DRY else fetch_entries(read_feeds())
    picked = cap_by_source(select_items(items, hours, time.time()))
    if len(picked) < (2 if DRY else MIN_ITEMS):
        raise Pipeline(f"當日素材只有 {len(picked)} 則（門檻 {MIN_ITEMS}）——RSS 可能回空，今天不出刊")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_digest(day, picked), encoding="utf-8")
    return {"count": len(picked), "digest": str(out.relative_to(ROOT)),
            "top_picks": [i["link"] for i in picked if i["full"]][:5],
            "sources": [{"title": i["title"], "link": i["link"]} for i in picked]}


# ---------- ② notebook ＋ ③ 生成與輪詢 ----------

def do_notebook(day: str, digest: Path, top_picks: list[str]) -> str:
    nb = nlm("notebook", "create", f"AI 日報 {day}", "--json", fake={"id": "dry-nb-0001"})["id"]
    nlm("source", "add", nb, "--file", str(digest), want_json=False, fake="")  # 合併成 1 份，不是 30 個來源
    for url in top_picks:
        nlm("source", "add", nb, "--url", url, want_json=False, fake="")
    return nb


def create_audio(nb: str) -> str:
    out = nlm("audio", "create", nb, "--format", "deep_dive", "--language", "zh-TW",
              "--confirm", "--json", fake={"artifact_id": "dry-audio-1"})
    return out["artifact_id"]      # zh-TW 不能用 --length，長度控制是 English only


def create_video(nb: str) -> str:
    out = nlm("video", "create", nb, "--format", "explainer", "--style", "whiteboard",
              "--language", "zh-TW", "--confirm", "--json", fake={"artifact_id": "dry-video-1"})
    return out["artifact_id"]      # zh-TW 只有 explainer；cinematic／short 僅英文


def wait_artifact(nb: str, artifact_id: str, timeout_s: int = 3600) -> dict:
    """影片生成官方說可能超過 30 分鐘，所以只能輪詢，不能同步等。"""
    deadline, delay = time.monotonic() + timeout_s, 15
    while time.monotonic() < deadline:
        st = nlm("studio", "status", nb, "--artifact-id", artifact_id, "--json",
                 fake={"state": "ready"})
        if st.get("state") in ("ready", "failed"):
            if st["state"] == "failed":
                raise Pipeline(f"生成失敗 artifact={artifact_id}：{st.get('error', '無訊息')}")
            return st
        time.sleep(delay)
        delay = min(delay * 1.5, 120)            # 退避，別把對方打爆
    raise Pipeline(f"輪詢逾時（{timeout_s}s）artifact={artifact_id}——不算失敗，明天 --resume 續跑")


def do_download(nb: str, audio_art: str, video_art: str) -> dict:
    audio, video = BUILD / "podcast.m4a", BUILD / "episode.mp4"     # .mp3 會被 nlm 直接拒絕
    BUILD.mkdir(parents=True, exist_ok=True)
    # 用 p.210 的單檔形式：`--output` 自己指定檔名。`nlm download all` 的落地檔名沒有文件化，
    # 下面的 exists() 檢查就對不上（驗收③ 也是直接 ls build/podcast.m4a）。
    nlm("download", "audio", nb, audio_art, "--output", str(audio), want_json=False, fake="")
    nlm("download", "video", nb, video_art, "--output", str(video), want_json=False, fake="")
    if DRY:
        touch(audio), touch(video)
    for p in (audio, video):
        if not p.exists():
            raise Pipeline(f"下載後找不到 {p.name}——確認副檔名（音檔一定是 .m4a）")
    return {"audio": str(audio.relative_to(ROOT)), "video": str(video.relative_to(ROOT))}


# ---------- ④ post：響度、片頭、封面 ----------

def do_post(audio: Path, video: Path) -> dict:
    norm = BUILD / "podcast_norm.m4a"
    sh("ffmpeg", "-y", "-i", str(audio), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
       "-c:a", "aac", "-b:a", "128k", str(norm), want_json=False, fake="")
    final = video
    intro = ROOT / "assets" / "intro.mp4"
    if intro.exists():
        final = BUILD / "episode_final.mp4"
        sh("ffmpeg", "-y", "-i", str(intro), "-i", str(video), "-filter_complex",
           "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]", "-map", "[v]", "-map", "[a]",
           "-c:v", "libx264", "-crf", "20", "-c:a", "aac", str(final), want_json=False, fake="")
    thumb = BUILD / "thumb.jpg"
    sh("ffmpeg", "-y", "-i", str(final), "-ss", "00:00:30", "-vframes", "1",
       "-vf", "scale=1280:720", str(thumb), want_json=False, fake="")
    if DRY:
        touch(norm), touch(final), touch(thumb)
    return {"audio": str(norm.relative_to(ROOT)), "video": str(final.relative_to(ROOT)),
            "thumb": str(thumb.relative_to(ROOT))}


# ---------- ⑤ metadata：先產生，再用硬限制擋 ----------

def clamp_bytes(s: str, limit: int) -> str:
    b = s.encode()
    if len(b) <= limit:
        return s
    return b[:limit - 3].decode("utf-8", "ignore") + "…"     # 中文一個字 3 bytes，會切在字中間


def local_meta(day: str, sources: list[dict]) -> dict:
    """gemini CLI 不在或 dry-run 時的保底 metadata：同樣要過 validate_meta。"""
    head = [f"AI 日報 {day}：今天有 {len(sources)} 則值得知道的事。",
            "本集由 Gemini Notebook 生成 zh-TW 對談，內容僅依下列來源。",
            "有疑義處以原文為準，未證實的傳聞不下結論。", ""]
    body = [f"- {s['title']}｜{s['link']}" for s in sources]
    return {"title": f"AI 日報 {day}｜{len(sources)} 則重點",
            "description": clamp_bytes("\n".join(head + body), 5000),
            "tags": ["AI", "AI 新聞", "Gemini", "每日新聞", "科技"],
            "category_id": "28"}      # 28=Science & Technology（正式做法見 videoCategories.list）


def gemini_meta(day: str, digest: Path, sources: list[dict]) -> dict:
    prompt = (f"讀 {digest}，依 AGENTS.md 的『節目調性』章節產生今日影片 metadata。"
              "以 JSON 回覆，欄位：title, description, tags。title 不超過 100 字元且不得使用聳動詞彙；"
              "description 開頭三行是本集重點，之後列出所有來源連結；tags 總長不超過 500 字元。")
    if DRY:
        return local_meta(day, sources)          # dry-run 不呼叫 gemini（會花 token）
    try:
        raw = sh("gemini", "-p", prompt, "--output-format", "json", want_json=False, fake="")
        meta = json.loads(json.loads(raw)["response"])
        meta.setdefault("category_id", "28")
        validate_meta(meta)                      # LLM 產出一定要過驗證才准送
        return meta
    except (Pipeline, json.JSONDecodeError, KeyError, FileNotFoundError) as e:
        log(f"  ! gemini metadata 不可用（{type(e).__name__}），改用本地樣板：{e}")
        return local_meta(day, sources)


def validate_meta(m: dict) -> dict:
    t, d = m.get("title", ""), m.get("description", "")
    if not t or len(t) > 100:
        raise Pipeline(f"title 長度 {len(t)}，YouTube 上限 100 字元")
    if "<" in t or ">" in t:
        raise Pipeline("title 不可含 < 或 >")
    nb = len(d.encode())
    if nb > 5000:
        raise Pipeline(f"description {nb} bytes，上限 5000 bytes（中文一字約 3 bytes）")
    tags = m.get("tags") or []
    if sum(len(x) for x in tags) > 500:
        raise Pipeline("tags 加總超過 500 字元")
    hit = [w for w in BANNED if w in t or w in d]
    if hit:
        raise Pipeline(f"違反 AGENTS.md 節目調性，出現聳動詞彙：{hit}")
    return m


# ---------- ⑥ upload：沒頻道就只寫 payload ----------

def yt_body(meta: dict, privacy: str) -> dict:
    return {"snippet": {"title": meta["title"], "description": meta["description"],
                        "tags": meta.get("tags", []), "categoryId": meta.get("category_id", "28")},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False,
                       "containsSyntheticMedia": True}}      # AI 生成，據實申報


def check_privacy(yt, video_id: str, want: str = "unlisted") -> str:
    """未稽核專案上傳會被強制鎖成 private，而 API 回 200——只能讀回來比對。"""
    got = yt.videos().list(part="status", id=video_id).execute()
    items = got.get("items") or []
    if not items:
        raise Pipeline(f"videos.list 查不到 {video_id}")
    actual = items[0]["status"]["privacyStatus"]
    if actual != want:
        raise Pipeline(f"專案可能尚未通過稽核：privacyStatus={actual}（預期 {want}）")
    return actual


def do_upload(video: Path, thumb: Path | None, meta: dict, privacy: str, verify: bool) -> dict:
    validate_meta(meta)
    if DRY:
        log(f"[dry-run] videos.insert {video.name} privacy={privacy}")
        return {"video_id": "dry-run-video-id", "privacy": privacy, "verified": verify}
    if not TOKEN.exists():
        payload = BUILD / "upload_payload.json"                 # 沒有 YouTube 頻道的替代交付
        payload.write_text(json.dumps({"video": str(video), "thumbnail": str(thumb) if thumb else None,
                                       "body": yt_body(meta, privacy)}, ensure_ascii=False, indent=2),
                           encoding="utf-8")
        log(f"  ! 沒有 {TOKEN}，改寫 {payload.name}（驗收其餘六項）")
        return {"skipped": "no_youtube_channel", "payload": str(payload.relative_to(ROOT))}

    import random
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    yt = build("youtube", "v3", credentials=creds)
    media = MediaFileUpload(str(video), chunksize=1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=yt_body(meta, privacy), media_body=media)
    resp, retry = None, 0
    while resp is None:
        try:
            _, resp = req.next_chunk()
        except HttpError as e:
            if e.resp.status not in (500, 502, 503, 504) or retry >= 10:
                raise
            retry += 1
            time.sleep(random.random() * (2 ** retry))          # 指數退避加抖動
    vid = resp["id"]
    if thumb and thumb.exists():
        yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumb))).execute()
    out = {"video_id": vid, "url": f"https://youtu.be/{vid}", "privacy": privacy}
    if verify:
        out["verified_privacy"] = check_privacy(yt, vid, privacy)
    return out


# ---------- orchestrator ----------

def do_run(day: str, hours: int, resume: bool, privacy: str) -> dict:
    st = load_state(day, resume)
    st["status"] = "failed"      # 先假設失敗；跑到最後才改成 ok，稽核紀錄才不會謊報
    log(f"AI 日報 {day}｜dry_run={DRY} resume={resume}")
    try:
        f = step(st, "fetch", lambda: do_fetch(day, hours, BUILD / "digest.md"))
        nb = step(st, "notebook", lambda: do_notebook(day, ROOT / f["digest"], f["top_picks"]))
        aid = step(st, "audio_create", lambda: create_audio(nb))
        vid_art = step(st, "video_create", lambda: create_video(nb))      # 先都送出，再一起等
        step(st, "audio_wait", lambda: wait_artifact(nb, aid))
        step(st, "video_wait", lambda: wait_artifact(nb, vid_art))
        d = step(st, "download", lambda: do_download(nb, aid, vid_art))
        p = step(st, "post", lambda: do_post(ROOT / d["audio"], ROOT / d["video"]))
        meta = step(st, "meta", lambda: gemini_meta(day, ROOT / f["digest"], f["sources"]))
        # 落地一份給人看／給 validate-meta 用（驗收⑥ 驗的就是這個檔）；resume 也重寫，不吃配額
        (BUILD / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        up = step(st, "upload", lambda: do_upload(ROOT / p["video"], ROOT / p["thumb"],
                                                  meta, privacy, verify=True))
        st["status"] = "ok"
        return up
    finally:
        save_state(st)
        REPORTS.mkdir(parents=True, exist_ok=True)
        (REPORTS / f"{day}.json").write_text(json.dumps(st, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
        log(f"稽核紀錄：reports/{day}.json（status={st['status']}）")


# ---------- self-check：不連網、不花錢 ----------

def fake_yt(status: str):
    ex = SimpleNamespace(execute=lambda: {"items": [{"status": {"privacyStatus": status}}]})
    return SimpleNamespace(videos=lambda: SimpleNamespace(list=lambda **kw: ex))


def self_check() -> None:
    n = 0
    now = 1_800_000_000.0

    # 1) 去重＋時間窗
    items = [
        {"title": "Gemini 3.7 上線", "link": "a", "summary": "", "source": "x", "ts": now - 100, "full": True},
        {"title": "gemini 3.7  上線！", "link": "b", "summary": "", "source": "y", "ts": now - 200, "full": False},
        {"title": "三天前的舊聞", "link": "c", "summary": "", "source": "z", "ts": now - 3 * 86400, "full": False},
        {"title": "沒有日期", "link": "d", "summary": "", "source": "w", "ts": None, "full": False},
        {"title": "沒有連結", "link": "", "summary": "", "source": "w", "ts": None, "full": False},
    ]
    got = select_items(items, 24, now)
    assert [i["link"] for i in got] == ["a", "d"], got
    # 每來源上限：arXiv 塞 10 則也只能拿 2 席，且全文來源排在最前面
    flood = [{"title": f"arxiv {i}", "link": f"x{i}", "summary": "", "source": "arXiv cs.AI",
              "ts": now, "full": False} for i in range(10)]
    flood.append({"title": "全文", "link": "z", "summary": "", "source": "Simon Willison",
                  "ts": now, "full": True})
    capped = cap_by_source(flood, limit=MAX_ITEMS, per_source=2)
    assert [i["link"] for i in capped] == ["z", "x0", "x1"], capped
    assert len(cap_by_source(flood, limit=3, per_source=99)) == 3
    n += 1

    # 2) description 位元組截斷：中文不能切出亂碼
    long_zh = "字" * 3000
    cut = clamp_bytes(long_zh, 5000)
    assert len(cut.encode()) <= 5000 and cut.endswith("…"), len(cut.encode())
    assert clamp_bytes("短", 5000) == "短"
    n += 1

    # 3) metadata 硬限制
    ok = local_meta("2026-08-26", [{"title": "t", "link": "https://x/1"}])
    assert validate_meta(ok) is ok
    for bad, why in [
        ({"title": "x" * 101, "description": "d"}, "title 過長"),
        ({"title": "<b>x</b>", "description": "d"}, "title 有角括號"),
        ({"title": "t", "description": "字" * 2000}, "description 超 5000 bytes"),
        ({"title": "震撼！AI 大突破", "description": "d"}, "聳動詞彙"),
        ({"title": "t", "description": "d", "tags": ["x" * 501]}, "tags 過長"),
    ]:
        try:
            validate_meta(bad)
            raise AssertionError(f"應該要擋下來：{why}")
        except Pipeline:
            pass
    n += 1

    # 4) privacyStatus 讀回驗證（未稽核專案會變 private）
    assert check_privacy(fake_yt("unlisted"), "v1") == "unlisted"
    try:
        check_privacy(fake_yt("private"), "v1")
        raise AssertionError("private 應該要 raise")
    except Pipeline as e:
        assert "privacyStatus=private" in str(e), e
    n += 1

    # 5) 冪等：state 有結果就不再呼叫
    calls = []
    st = {"day": "2026-08-26", "steps": {}}
    global STATE
    keep, STATE = STATE, Path(os.environ.get("TMPDIR", "/tmp")) / "airadio-selfcheck"
    try:
        for _ in range(3):
            assert step(st, "audio_create", lambda: (calls.append(1), "art-1")[1]) == "art-1"
    finally:
        STATE = keep
    assert len(calls) == 1, calls
    n += 1

    # 6) digest 一定帶連結（不帶連結會被 AGENTS.md 的調性規則判違規）
    d = build_digest("2026-08-26", got)
    assert "連結：a" in d and d.startswith("# AI 日報素材包")
    n += 1

    # 7) 上傳 body 的三個固定欄位
    b = yt_body(ok, "unlisted")
    assert b["status"] == {"privacyStatus": "unlisted", "selfDeclaredMadeForKids": False,
                          "containsSyntheticMedia": True}, b["status"]
    n += 1

    print(f"self-check 通過（{n} 項）")


# ---------- aha：三張對照表（不連網、不需憑證、不吃配額） ----------

DIM, BOLD, CYAN, GREEN, RST = (("\033[2m", "\033[1m", "\033[36m", "\033[32m", "\033[0m")
                               if sys.stdout.isatty() else ("",) * 5)

# 改了 run.py 的函式名，aha_lines() 的 assert 會直接炸，提醒你回來更新分類
BUCKETS = [
    ("呼叫生成（nlm／gemini）", ("do_notebook", "create_audio", "create_video", "wait_artifact", "gemini_meta")),
    ("抓料、去重、合併", ("read_feeds", "fetch_entries", "norm_title", "select_items", "cap_by_source",
                     "build_digest", "do_fetch")),
    ("狀態機與冪等", ("state_path", "load_state", "save_state", "step", "do_run")),
    ("驗證與防錯", ("sh", "nlm", "touch", "clamp_bytes", "local_meta", "validate_meta", "check_privacy")),
    ("下載與後製", ("do_download", "do_post")),
    ("上傳與憑證", ("yt_body", "do_upload", "do_auth", "do_captions")),
    ("離線檢查、CLI、aha", ("fake_yt", "self_check", "main", "cli", "aha", "aha_lines", "aha_tools",
                        "aha_quota", "_w", "_pad", "_table", "log")),
]


def _w(s: str) -> int:
    import unicodedata                      # 中文是全寬字，一個算 2 格才不會排歪
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _pad(s: str, n: int) -> str:
    return s + " " * max(0, n - _w(s))


def _table(title: str, cols: list[str], rows: list[list[str]], note: str = "") -> None:
    ws = [max([_w(cols[i])] + [_w(r[i]) for r in rows]) + 2 for i in range(len(cols))]
    print(f"\n{BOLD}{CYAN}{title}{RST}")
    print(BOLD + "".join(_pad(c, w) for c, w in zip(cols, ws)).rstrip() + RST)
    print(DIM + "─" * (sum(ws) - 2) + RST)
    for r in rows:
        print("".join(_pad(c, w) for c, w in zip(r, ws)).rstrip())
    if note:
        print(f"{GREEN}{note}{RST}")


def aha_lines() -> None:
    """這條產線裡，真正「呼叫 AI」的程式碼佔多少？用 ast 實算，不是估的。"""
    import ast

    src = Path(__file__).read_text(encoding="utf-8")
    span = {n.name: n.end_lineno - n.lineno + 1
            for n in ast.parse(src).body if isinstance(n, ast.FunctionDef)}
    assert not set(span) - {f for _, fns in BUCKETS for f in fns}, \
        f"有沒歸類的函式：{set(span) - {f for _, fns in BUCKETS for f in fns}}"
    total = sum(span.values())
    rows = [[name, str(k := sum(span.get(f, 0) for f in fns)),
             f"{k / total * 100:4.1f}%", "█" * round(k / total * 36)]
            for name, fns in BUCKETS]
    by = {r[0]: int(r[1]) for r in rows}
    gen = by["呼叫生成（nlm／gemini）"]
    guard = by["狀態機與冪等"] + by["驗證與防錯"] + by["上傳與憑證"]
    rows.sort(key=lambda r: -int(r[1]))
    _table(f"這條產線的 {total} 行函式碼在做什麼（ast 實算）",
           ["職責", "行數", "佔比", ""], rows,
           note=f"真正叫 AI 生成的只有 {gen} 行（{gen / total * 100:.0f}%）。"
                f"為了讓這 {gen} 行能無人值守地活下去，"
                f"\n狀態機＋驗證防錯＋上傳憑證寫了 {guard} 行——{guard / gen:.1f} 倍。")


def aha_tools() -> None:
    """同一份能力的三種包裝：MCP 工具（給 agent）／CLI 子指令（給腳本）／本產線的函式。"""
    _table("一個能力，三種包裝——notebooklm-mcp-cli 這個套件同時裝出兩個門面",
           ["能力", "MCP 工具（給 agent）", "nlm 子指令（給腳本）", "本產線的函式"],
           [["生成音檔", "studio_create(type=audio)", "nlm audio create", "create_audio()"],
            ["生成影片", "studio_create(type=video)", "nlm video create", "create_video()"],
            ["查生成狀態", "studio_status", "nlm studio status", "wait_artifact()"],
            ["下載成果", "download_artifact", "nlm download audio/video", "do_download()"],
            ["建 notebook", "notebook_create", "nlm notebook create", "do_notebook()"],
            ["加來源", "source_add", "nlm source add", "do_notebook()"]],
           note="MCP server 有 43 個工具、我們只開 5 個、產線實際只呼叫 6 個子指令。"
                "\n排程選 CLI 不選 MCP：MCP 的授權對話框半夜沒人按。")


def aha_quota() -> None:
    """網路上流傳的「一天只能傳 6 支」已經作廢兩次了。"""
    _table("YouTube 上傳配額：流傳的說法 vs 2026-06 現制",
           ["項目", "舊說法（已作廢）", "現在", "差距"],
           [["videos.insert 每次", "1,600 units", "1 unit", "1600× 便宜"],
            ["每日可上傳", "6 支", "100 支", "16×"],
            ["配額桶", "與全部 API 擠 10,000", "自己一桶", "—"]])
    use = [["videos.insert", "1", "上傳桶 100／日", "1.0%"],
           ["thumbnails.set", "50", "共用桶 10,000／日", "0.5%"],
           ["captions.insert", "400", "共用桶 10,000／日", "4.0%"]]
    _table("這條產線一天實際用掉多少", ["呼叫", "units", "所屬桶", "佔該桶"], use,
           note=f"共 {sum(int(r[1]) for r in use)} units——配額完全不是問題。"
                "\n真正擋住你的是未稽核專案的私人鎖定，而它消耗 0 units、也不會回錯誤。")


def aha(topic: str | None = None) -> None:
    fns = {"lines": aha_lines, "tools": aha_tools, "quota": aha_quota}
    for name, fn in fns.items():
        if topic in (None, "all", name):
            fn()
    if topic not in (None, "all", *fns):
        raise Pipeline(f"aha 的主題只有 {'／'.join(fns)}（或 all）")
    print()


# ---------- CLI ----------

def main() -> None:
    global DRY
    ap = argparse.ArgumentParser(prog="airadio", description="AI 日報電台產線")
    ap.add_argument("cmd", nargs="?", default="run",
                    choices=["run", "fetch", "wait", "validate-meta", "upload", "auth", "captions", "aha"])
    ap.add_argument("target", nargs="?")                 # validate-meta 的檔案路徑／aha 的主題
    ap.add_argument("--date", default="today")
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--out", default="build/digest.md")
    ap.add_argument("--notebook")
    ap.add_argument("--artifact")
    ap.add_argument("--video")
    ap.add_argument("--video-id")
    ap.add_argument("--file")
    ap.add_argument("--language", default="zh-TW")
    ap.add_argument("--client", default="secrets/client_secret.json")
    ap.add_argument("--privacy", default="unlisted")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="用假資料跑完整條產線，不需任何憑證")
    ap.add_argument("--self-check", action="store_true", help="離線邏輯檢查")
    a = ap.parse_args()

    if a.self_check:
        return self_check()
    if a.cmd == "aha":
        return aha(a.target)                             # 三張離線對照表，不連網、不吃配額
    DRY = a.dry_run
    day = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d") if a.date == "today" else a.date

    if a.cmd == "run":
        out = do_run(day, a.hours, a.resume, a.privacy)
    elif a.cmd == "fetch":
        out = do_fetch(day, a.hours, ROOT / a.out)
    elif a.cmd == "wait":
        if not (a.notebook and a.artifact):
            raise Pipeline("wait 需要 --notebook 與 --artifact")
        out = wait_artifact(a.notebook, a.artifact)
    elif a.cmd == "validate-meta":
        out = validate_meta(json.loads(Path(a.target or "build/meta.json").read_text(encoding="utf-8")))
    elif a.cmd == "upload":
        meta_p = ROOT / "build" / "meta.json"
        meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else local_meta(day, [])
        thumb = ROOT / "build" / "thumb.jpg"
        out = do_upload(Path(a.video), thumb if thumb.exists() else None, meta, a.privacy, a.verify)
    elif a.cmd == "auth":
        out = do_auth(Path(a.client))
    else:
        out = do_captions(a.video_id, Path(a.file), a.language)
    print(json.dumps(out, ensure_ascii=False, indent=2))


def do_auth(client_secret: Path) -> dict:
    """一次性取得 refresh token。同意畫面必須是 In production，否則 token 只活 7 天。"""
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    TOKEN.parent.mkdir(parents=True, exist_ok=True)
    TOKEN.write_text(creds.to_json(), encoding="utf-8")
    TOKEN.chmod(0o600)
    return {"token": str(TOKEN.relative_to(ROOT)), "scopes": SCOPES}


def do_captions(video_id: str, srt: Path, language: str) -> dict:
    """captions.insert 需要 youtube.force-ssl，光有 upload scope 會 403。"""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    yt = build("youtube", "v3", credentials=Credentials.from_authorized_user_file(str(TOKEN), SCOPES))
    r = yt.captions().insert(part="snippet",
                             body={"snippet": {"videoId": video_id, "language": language,
                                               "name": "zh-TW", "isDraft": False}},
                             media_body=MediaFileUpload(str(srt))).execute()
    return {"caption_id": r["id"]}


def cli() -> None:
    """uv run airadio 的入口：預期失敗印一行就退，不要噴 traceback 給 launchd 的 log。"""
    try:
        main()
    except (Pipeline, OSError, json.JSONDecodeError) as e:
        # 檔案不存在／JSON 壞掉也走這裡：launchd 的 log 裡只要一行看得懂的話，不要 20 行 traceback
        log(f"✗ {e}")
        sys.exit(1)


if __name__ == "__main__":
    cli()
