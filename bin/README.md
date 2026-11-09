# bin

`inbox` 指令入口。plugin 啟用時 Claude Code 會把這個資料夾放進 PATH。

| 檔 | 用途 |
|---|---|
| `inbox` | sh 腳本（macOS、Linux、Git Bash）；hook 也走這裡。依序找 `python3`、`python`、`py`，落在 `WindowsApps` 的先試跑以避開 Store 空殼 |
| `inbox.cmd` | PowerShell／cmd 用的入口 |
| `.gitattributes` | `inbox` 固定 LF、`*.cmd` 固定 CRLF，避免 Windows 的 autocrlf 把 sh 腳本弄壞 |
