"""影像生成範例：文字 → 圖。跑法：uv run test2.py

坑：回傳的 block.data 是 base64 字串，不是 bytes，要先 b64decode 才能寫檔。
"""

import base64
from pathlib import Path

from google import genai

client = genai.Client()

interaction = client.interactions.create(
    model="gemini-3.1-flash-image",   # Nano Banana 2
    input=(
        "一張等距視角的插畫：多個 AI agents 在雲端資料中心"
        "協作，Google 風格配色，乾淨明亮"
    ),
    generation_config={
        "image_config": {"aspect_ratio": "16:9", "image_size": "2K"},
    },
)

# interaction.output_image 已經幫你從 steps 裡挑出最後一張圖，不用自己走迴圈
img = interaction.output_image
if img is None:  # 被安全政策擋掉時只會有文字，印出來才看得到原因
    raise SystemExit(f"沒有產生圖片，模型只回了：{interaction.output_text}")
Path("agents.png").write_bytes(base64.b64decode(img.data))
print(f"agents.png  {img.mime_type}  {len(base64.b64decode(img.data)) / 1024:.0f}KB")
