# hooks

`hooks.json`：SessionStart 與 UserPromptSubmit 時跑 `sh bin/inbox hook`，把使用者在收件匣的新回覆印到 stdout，進到 agent 的上下文。沒有新回覆時什麼都不印。
