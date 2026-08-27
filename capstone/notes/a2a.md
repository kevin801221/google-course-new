# A2A 1.0 筆記
Agent Card 放在 /.well-known/agent-card.json，是 agent 的名片。
Task 有生命週期狀態機：submitted / working / completed / failed。
跨框架委派用 SendMessage；ADK 端用 to_a2a() 曝露、RemoteA2aAgent 消費。
