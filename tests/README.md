# tests

```bash
python3 -m unittest discover tests   # Windows 用 python
```

測試會把 `CLAUDE_INBOX_HOME` 指到暫存資料夾，並移除環境變數 `BARK_URL`；Bark 測試只打本機的假伺服器，不會推到真手機。
