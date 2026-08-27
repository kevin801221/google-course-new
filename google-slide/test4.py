import numpy as np
from google import genai

client = genai.Client()

docs = [
    "Cloud Run 是 serverless 容器平台",
    "ADK 是 Google 的 agent 開發框架",
    "台北的珍珠奶茶很好喝",
]
res = client.models.embed_content(
    model="gemini-embedding-2", contents=docs)
vecs = np.array([e.values for e in res.embeddings])

q = client.models.embed_content(
    model="gemini-embedding-2",
    contents="哪個框架可以拿來寫 AI agent?")
qv = np.array(q.embeddings[0].values)

scores = vecs @ qv / (np.linalg.norm(vecs, axis=1) * np.linalg.norm(qv))
print(docs[int(scores.argmax())])   # -> ADK 是 Google 的 agent 開發框架
