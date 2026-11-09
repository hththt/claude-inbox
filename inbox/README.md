# inbox

收件匣本體，只用 Python 標準庫。

| 檔 | 用途 |
|---|---|
| `inbox.py` | 指令（ask、take、wait、close、list、bark、hook、serve、start、stop、url）、網頁服務、Bark 推播 |
| `page.html` | 收件匣網頁；題目文字一律跳脫後顯示 |

hook 每輪都會跑 `inbox.py hook`，所以頂層只載入輕量模組，其餘用到時才 import。
