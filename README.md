<div align="center">

# 📥 收件匣

### 讓你的 agent 別再停在那邊等你回一句「好」

Claude Code 專用的「決定信箱」：agent 要你拍板的事，統一放進一個網頁。<br>
你有空時一次看完、一次回答，**答案自動回到 agent 手上**。

![license MIT](https://img.shields.io/badge/license-MIT-green) ![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue) ![Claude Code plugin](https://img.shields.io/badge/Claude_Code-plugin-d97757)

<img src="docs/demo.gif" alt="示範：在收件匣網頁選答案、寫補充、送出，agent 立刻收到" width="760">

</div>

---

## 你是不是也遇過這些事？

- 讓 agent 跑起來就去吃飯，回來發現它 20 分鐘前就停在「要用 A 還是 B？」
- 同時開了三個對話，每一個都在問你問題，你得一個一個切過去回
- 答案打在對話裡，換個對話它就不知道，隔天又得再解釋一次

**收件匣把「問你」這件事從對話裡拿出來。** agent 繼續做不需要你的部分，要你決定的事排隊放好，你方便的時候再處理。

<div align="center">
<img src="docs/flow.png" alt="流程：agent 出題，你在網頁回答，答案自動回到 agent" width="900">
</div>

## 長這樣

<div align="center">
<img src="docs/shot-answering.png" alt="收件匣網頁：題目、選項、推薦標記與補充欄" width="760">
</div>

每一題都附上**來源**（哪個專案問的）、**期限**、**推薦選項**和一個補充欄。選好、寫幾句，按「送出全部已答」就好。

<table>
<tr>
<td width="62%" valign="top">
<img src="docs/shot-received.png" alt="送出後，每題顯示「agent 已收到」">
<p align="center"><sub>送出後看得到每題有沒有被 agent 收走</sub></p>
</td>
<td width="38%" valign="top">
<img src="docs/shot-mobile.png" alt="手機版畫面">
<p align="center"><sub>手機版（寬度 390 的實際畫面）</sub></p>
</td>
</tr>
</table>

## 為什麼好用

| | |
|---|---|
| **題目集中** | 所有對話的問題在同一個網頁，來源、期限、推薦選項一眼看完，不用切視窗 |
| **一次回完** | 逐題先送，或一次「送出全部已答」。草稿會自動保存，重新整理也不會掉 |
| **答案自動回去** | 用 Claude Code 的 hook：你送出後，agent 下一輪開始時答案就已經在它的上下文裡，不用你再貼 |
| **不叫 AI、不上雲** | 只用 Python 標準庫。題目就是 agent 寫的那一份，資料全部放在你自己的電腦 |
| **預設安全** | 只開在本機，所有操作都要 token；題目文字一律當純文字顯示，不會被執行 |
| **手機也能回** | 把位址改成你的 Tailscale 或內網位址，就能在手機上回答（見下方進階說明） |
| **手機推播** | 開了 Bark 推播，有新題目時 iPhone 會響，可選鈴聲、單響或連響、推播等級（見下方說明） |
| **原生 Windows** | 不用 WSL：PowerShell、cmd、Git Bash 都能跑（本 fork 新增） |

## 30 秒開始

在 Claude Code 裡輸入：

```
/plugin marketplace add hththt/claude-inbox
/plugin install inbox@claude-inbox
```

裝好後重開一次 Claude Code，然後對 agent 說：

> 有要我決定的事，就放進收件匣。

就這樣。agent 會自己用 `inbox ask` 出題，並印出網頁網址。想長期生效，把上面那句寫進專案的 `CLAUDE.md`。

**你送出之後，agent 看到的是這樣：**

```
收件匣：使用者回覆了 2 則。

【q-20261107-144835-480d】登入頁要不要保留帳密登入？
使用者選：A 保留帳密登入，兩種並存
補充：先留著，下個月再看有沒有人還在用。

照回覆繼續做；這件處理完可跑 inbox close <題號> 把它收起來。
```

想自己出一題試試看：

```bash
inbox ask --title "要不要上新版？" --option "A=上" --option "B=不上" --recommend A
```

> `inbox` 指令是給 agent 的 Bash 用的。你自己在終端機試的話，改用 `sh <plugin 資料夾>/bin/inbox`（PowerShell／cmd 用 `<plugin 資料夾>\bin\inbox.cmd`），後面的參數一樣。

## 📱 Bark 手機推播（本 fork 新增）

有新題目時用 [Bark](https://github.com/Finb/Bark) 推到 iPhone，不用一直開著網頁。預設關閉。

1. 把 Bark App 給的推播網址設成環境變數 `BARK_URL`（例如 `https://api.day.app/<device_key>`）。網址只從環境變數讀，**不會寫進任何檔案**。設完要重開終端機與 Claude Code。
2. 開啟並試聽：

```bash
inbox bark on              # 開啟（沒有 BARK_URL 會直接報錯，不會假裝開好）
inbox bark test            # 用目前設定發一則測試推播
inbox bark test --sound glass --volume 4   # 試聽別的鈴聲，不存
inbox bark set --sound glass --call on     # 改設定
inbox bark                 # 看目前設定
inbox bark off             # 關閉
```

| 設定 | 預設 | 說明 |
|---|---|---|
| `--sound` | `chime` | Bark 鈴聲名稱（內建如 `chime` `glass` `bell` `bloom`，或 Bark App 自訂鈴聲） |
| `--call` | `off` | `on` 連響約 30 秒、`off` 單響；只套用在待決定題（Bark 只支援這兩種長度，不能指定秒數） |
| `--level` | `critical` | 待決定題的推播等級：`critical` 靜音或勿擾也會響，`timeSensitive`、`active`、`passive` 照手機設定 |
| `--volume` | `2` | 重要警示音量 0-10，只對 `critical` 有效 |
| `--info-level` | `active` | 知會題（`inbox ask --info`）的推播等級；知會題一律單響 |

- 推播標題是 `[收件匣/<來源>] 待你決定` 或 `知會`，內文是題目標題與期限。推播**不帶網址**：token 在網址裡，不能經過 Bark 伺服器與 Apple。收件匣從手機的書籤或主畫面捷徑開。
- 設定存在 `~/.claude-inbox/config.json` 的 `bark` 段，改了立刻生效，不用重啟服務。欄位填錯會直接報錯，不會默默改用預設值。
- 開著推播但缺 `BARK_URL` 或設定填錯時，`inbox ask` 會報錯、不放題目；推播送出失敗時題目已經放好，錯誤訊息會提醒 agent 不要重出。錯誤訊息裡的推播網址與 device key 一律遮蔽。
- `critical` 要先在 iPhone 允許 Bark 的「重要警示」（設定 → Bark → 通知 → 重要警示）。

## 🔀 開關模式（本 fork 新增）

想要「人在電腦前就照常在對話裡問，離開時才用收件匣」：在 `~/.claude-inbox/config.json` 加 `"switch": true`，之後**收件匣服務有沒有開**就是開關。

| 服務 | Claude 怎麼問你 |
|---|---|
| 開著 | plugin 的 PreToolUse hook 擋下 AskUserQuestion，要它改用 `inbox ask`（有開 Bark 就推到手機） |
| 關著 | 照常用 AskUserQuestion；`inbox ask` 會報錯、不放題目，也**不會自動把服務打開** |

```bash
inbox toggle   # 開著就關、關著就開；開啟時用知會題等級推一則「[收件匣] 已開啟」確認手機收得到
```

可以把 `inbox toggle` 做成桌面捷徑，出門點一下、回來再點一下。電腦重開機後服務不會自己起來，等於回到平常模式。更新 plugin 後若舊版服務還開著，`inbox toggle` 會先停掉它再開新版（只認用目前 token 打得通舊版 API 的服務，別的程式佔著埠照常報錯）。開關模式下 agent 不該自己開關服務（skill 有寫）。

## 你已經有自己的開發規則？疊上去，不要換掉

收件匣不會動你的 `CLAUDE.md`、`AGENTS.md` 或任何現有流程。它只加三樣東西：一個 `inbox` 指令、一個網頁，和一個在每輪開始時把答案送進 agent 的 hook。

所以你原本的規則照舊：哪些事要先問你、哪些事 agent 可以自己決定，都沒有改變，只是「問你」的地方從對話換成收件匣。想讓 agent 這樣用，把下面這段貼進你的 `CLAUDE.md`：

```markdown
## 收件匣
需要問我的事（照上面的規則本來就要問我的那些），一律用 `inbox ask` 放進收件匣，不要在對話裡停下來等。
不需要問我的事，照原本的規則自己決定，不要因為有收件匣就多問。
```

沒有自己的規則也沒關係，直接用預設就行。

## 🎁 附贈：總PM 模式

一個常駐的對話帶好幾條工作線、自己不寫程式，只負責派工、裁決、追進度，而你**只看收件匣**。輸入 `/inbox:pm` 就能看到完整的操作說明，包含狀態檔怎麼寫、什麼事該出題給你、哪些事一定要先問你。

這是給還沒有自己流程的人用的預設做法。你已經有自己的總PM、狀態檔或審查流程時，agent 會沿用你的，只補收件匣那一塊，不會另建一套。

## 不用 Claude Code 也能用（Codex 等其他 agent）

收件匣的核心是一支 Python 指令加一個網頁，不綁 Claude Code。plugin 只是 Claude Code 專用的打包。其他 agent 能在 shell 裡直接跑同一支指令：

```bash
git clone https://github.com/hththt/claude-inbox
python3 claude-inbox/inbox/inbox.py ask --title "要不要上新版？" --option "A=上" --option "B=不上"
python3 claude-inbox/inbox/inbox.py wait --timeout 1800   # 有回覆時印出答案並結束
```

其他 agent 沒有 Claude Code 的 hook，答案不會自動出現在上下文，要靠它自己跑 `wait` 或 `take` 去拿。把下面這段貼進它的規則檔（例如 `AGENTS.md`），路徑換成你放的位置：

```markdown
## 收件匣
需要問我的事，用下面的指令放進收件匣，不要在對話裡停下來等：
python3 /path/to/claude-inbox/inbox/inbox.py ask --title "..." --option "A=..." --option "B=..."
先做不受這題影響的工作。一定要等答案時，在背景跑 `... inbox.py wait --timeout 1800`。
處理完一題後跑 `... inbox.py close <題號>`。
```

兩個限制：
- 程式靠環境變數 `CLAUDE_CODE_SESSION_ID` 認出題的對話。其他 agent 沒有它，題目會變成匿名，同一個專案資料夾裡的任何 agent 都拿得到答案。兩個 agent 同時在同一個專案出題時，可能拿到對方的答案。
- 這個用法還沒有拿 Codex 等實際跑過，是依程式行為寫的。

## 覺得有用？

按個 ⭐ **Star** 讓更多人看到，也歡迎開 Issue 告訴我哪裡卡住、哪裡想要更好。

---

<details>
<summary><b>進階：從手機看、資料放哪、答案送給哪個對話</b></summary>

### 從手機看

預設只開在本機。要用手機看，編輯 `~/.claude-inbox/config.json`：

```json
{ "host": "你的 Tailscale 或內網位址", "port": 7799 }
```

位址只支援 IPv4，網址要用 IP（用 MagicDNS 名稱連會被 Host 檢查擋下）。token 放在網址路徑裡：`http://<IP>:<埠>/<token>/`。用 `inbox url` 印出來，在手機上加成書籤或主畫面捷徑就能一直用；token 不對或少了這一段一律回 404。Windows 上 Tailscale 安裝時自帶 `Tailscale-In` 防火牆規則，已放行整個 tailnet 連任何埠，所以不用另開；也因為允許規則是「任一條符合就放行」，想只讓手機連，加允許規則沒用，要加封鎖規則擋掉其他來源。token 不分本機或遠端，第一次使用時自動產生，寫進同一個檔（macOS／Linux 上檔案權限 600，資料夾權限 700；Windows 靠使用者資料夾本身的存取控制）。改位址或換 token 後都要重新啟動服務：`inbox stop` 再 `inbox start`。執行中的服務不會自動套用新設定，舊 token 在它重啟前仍然有效。用 `inbox url` 可以印出帶 token 的完整網址。

### 資料放哪

`~/.claude-inbox/`（可用環境變數 `CLAUDE_INBOX_HOME` 改）：

| 檔 | 內容 |
|---|---|
| `questions/*.json` | 題目，一題一檔 |
| `events.jsonl` | 你的回答、送達紀錄、收起紀錄，只增不改 |
| `config.json` | 位址、埠、token、Bark 推播設定（`BARK_URL` 不在這裡，只讀環境變數） |

題目與答案都是明文，不要放密碼或金鑰。

### 答案送給哪個對話

答案送回出題的那個對話，不管它現在在哪個資料夾。那個對話 30 分鐘內沒來拿，同一個專案（同一個 git 根目錄）裡的其他對話也拿得到。每則答案只送出一次。

### 安全

- 只收 `Host` 與 `Origin` 符合的請求，擋掉別的網頁偷打你的本機服務。
- 所有 API 都要 token，本機也一樣：答案會被放進 agent 的上下文，不能讓同一台機器上的其他程式隨便寫入。
- 頁面把題目文字當純文字顯示，只有網址會變成連結；回應一律帶 `Referrer-Policy: no-referrer`，點出去的連結不會帶走含 token 的網址。
- 回答只在你的機器上流動，沒有任何外送。開了 Bark 推播時，只有題目標題、來源與期限會經過 Bark 伺服器與 Apple 推播服務；網址、token、題目內文與回答都不會送出。

### 需求

Python 3.9 以上。答案自動送回 agent 需要 Claude Code；其他 agent 的用法見上方。支援 macOS、Linux、WSL 與原生 Windows。沒有其他依賴。

### 原生 Windows

- hook 與 `inbox` 指令都走 `bin/inbox`（sh 腳本，Claude Code 在 Windows 用 Git Bash 跑 hook 與 Bash 工具）。PowerShell 或 cmd 用 `bin\inbox.cmd`。
- 依序找 `python3`、`python`、`py`。落在 `WindowsApps` 的 Python 可能只是 Microsoft Store 的「去安裝」空殼，會先試跑一次，跑不動就換下一個；都找不到時直接報錯。
- `bin/.gitattributes` 讓 `bin/inbox` 一律用 LF 換行，`git config core.autocrlf true` 也不會把它轉成 CRLF 而跑不動。
- 本機位址一律用 `127.0.0.1`：Windows 上連 `localhost` 會先試 IPv6，只綁 IPv4 的服務要多等約 2 秒。
- Windows 允許兩個程式用 `SO_REUSEADDR` 綁同一個埠，所以服務在 Windows 上改成獨佔綁定。
- 背景服務用脫離主控台的獨立行程啟動，不跳視窗，關掉終端機或 Claude Code 也不會被一起關掉。要停用 `inbox stop`。
- 預設埠 7799 若落在 Windows 保留的埠範圍（Hyper-V／WSL／Docker），沒人在用也綁不到，`server.log` 會寫出原因。用 `netsh interface ipv4 show excludedportrange protocol=tcp` 查，再在 `config.json` 換一個埠。

### 開發

```bash
python3 -m unittest discover tests   # Windows 用 python
```

</details>

## 授權

MIT
