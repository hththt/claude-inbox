# 決策紀錄
日期 | 決策 | 原因 | 否決的替代方案
---|---|---|---
2026-11-09 | 從 chenjackle45/claude-inbox fork，保留上游目錄結構（`inbox/inbox.py` 不搬進 core） | 保持能合併上游修正；plugin 結構由 Claude Code 規範 | 搬進 core 目錄（與上游分家）
2026-11-09 | 維持 Python，做 hook 快速路徑（延後 import、hook 不走 argparse、沒有別人的待送回答不叫 git） | 實測 Go 只省約 100ms／次與 14MB；改寫要把各平台執行檔 commit 進公開 repo（無法審查的供應鏈風險）且與上游分家 | 改寫 Go、改寫 Rust
2026-11-09 | Windows 的檔案鎖改鎖專用 `.lock` 檔，POSIX 也一起改 | Windows 位元組鎖是強制性的，鎖在資料檔上會擋住讀取；兩平台同一套邏輯較單純 | 只在 Windows 用 `.lock`、POSIX 照舊鎖 events.jsonl
2026-11-09 | 本機網址一律 127.0.0.1；Windows 關閉 allow_reuse_address | 實測 Windows 連 localhost 多等 2.06 秒；SO_REUSEADDR 讓第二個服務也綁得上同一埠 | 維持 localhost 與預設 reuse
2026-11-09 | hook 走 `sh bin/inbox`，只有 WindowsApps 下的 Python 才先試跑 | Store 空殼存在但不能執行；每次都試跑在 Windows 多 65ms | hook 寫死 python3、每個候選都試跑
2026-11-09 | Bark 網址只讀環境變數 BARK_URL，設定放 config.json 的 bark 段，用 `inbox bark` 改 | 與 claude-session-monitor 一致，金鑰不進任何檔案；設定在 repo 外 | 網址寫進 config.json、網頁設定面板
2026-11-09 | 「持續時間」只做單響／call 連響約 30 秒，不做未回答重推 | 使用者選擇；Bark 本身不能指定秒數 | 未回答定時重推、兩者都做
2026-11-09 | 待決定題預設 critical＋音量 2＋chime，知會題預設 active 一律單響 | 使用者既有偏好（chime、音量 2）；知會不該穿透勿擾 | 知會題同等級、知會題不推
2026-11-09 | 推播不帶網址與 token，只帶標題、來源、期限 | token 等於能指揮 agent，不得經過 Bark 伺服器與 Apple | 帶含 token 網址、帶網址＋localStorage 記 token
2026-11-09 | Bark 開著卻缺 BARK_URL 或設定錯：ask 報錯不放題；推播失敗：題目已存、報錯並提示不要重出 | 參數異常一律報錯，不默默只出題不推；避免 agent 重試造成重複題 | 推播失敗只警告不報錯
2026-11-09 | Codex 審查後不處理「升級期間新舊版鎖不同可能雙送」與「launcher 遇到 Python 2 不再往下找」 | 前者要剛好舊版 wait 還在跑又來答案，使用者尚無舊版安裝；後者 2026 年 Windows 幾乎不會有 Python 2，且會直接報錯而非靜默 | POSIX 過渡期同時鎖兩個檔、每個候選都試跑版本
2026-11-09 | 推播改帶不含 token 的收件匣網址（只在服務綁非本機位址時），網頁 token 由 sessionStorage 改 localStorage | 使用者要從手機經 Tailscale 操作，原本「不帶網址」的前提（手機連不到）已不成立；token 仍不經 Bark 與 Apple | 維持不帶網址、帶含 token 完整網址
2026-11-09 | 開關模式：config 的 switch=true 時以「服務有沒有開」判斷使用者在不在；開著由 plugin 的 PreToolUse guard 把 AskUserQuestion 導去收件匣，關著 inbox ask 報錯且不自動啟動；桌面捷徑跑 inbox toggle | 使用者要用桌面捷徑明確切換；閒置偵測會把盯著畫面看當離開；guard 放在 plugin 內兩個帳號自動同步 | 鍵盤滑鼠閒置 10 分鐘、只靠使用者口頭說要離開、guard 放 ~/.claude/hooks
