"""最小可跑的多模態範例。跑法：uv run test1.py

三個新手一定踩的坑，這裡都躲掉了（詳細流程看 muti-modal.py）：
  1. input 不能放 dict —— 會被 SDK 當 UNKNOWN 靜默丟掉，模型「看不到圖」
  2. data 不能放 raw bytes —— 要 base64 字串，或直接給 Path 讓 SDK 自己編
  3. Client 要綁變數 / 用 with —— 暫時物件會先被 GC 關掉
"""

from pathlib import Path

from google import genai
from google.genai._gaos.types.interactions import ImageContent, TextContent

with genai.Client() as client:
    interaction = client.interactions.create(
        model="gemini-3.7-flash",
        input=[
            TextContent(text="這張架構圖有什麼單點故障風險？"),
            ImageContent(data=Path("image(1).png"), mime_type="image/png"),
        ],
    )
print(interaction.output_text)

# 影片 / 音訊 / PDF 同理：換成 VideoContent / AudioContent / DocumentContent + 對應 mime_type
# 大檔案（>20MB）先用 client.files.upload() 再引用
