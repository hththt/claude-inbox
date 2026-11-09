#!/usr/bin/env python3
"""收件匣：讓 Claude Code 的 agent 把要你決定的事集中到一個網頁，你回答後答案自動回到 agent 手上。

只用 Python 標準庫（3.9 以上），支援 macOS、Linux 與原生 Windows。資料放在 $CLAUDE_INBOX_HOME（預設 ~/.claude-inbox）。
新題目可用 Bark 推播到手機（inbox bark），推播網址只讀環境變數 BARK_URL，不寫進任何檔案。

hook 每次送出訊息都會跑，所以頂層只載入最輕的模組，其餘用到時才 import。
"""
import errno
import functools
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

IS_WINDOWS = os.name == 'nt'
if IS_WINDOWS:
    import msvcrt
else:
    import fcntl

HERE = Path(__file__).resolve().parent
PAGE = HERE / 'page.html'
DEFAULT_PORT = 7799
MAX_BODY = 64 * 1024
MAX_TEXT = 4000
ORPHAN_SECONDS = 30 * 60  # 提問的 session 30 分鐘沒來拿，同專案其他 session 可以拿
TAIPEI = timezone(timedelta(hours=8), 'Asia/Taipei')  # 台灣沒有日光節約，用固定 +8 免裝 tzdata

BARK_LEVELS = ('critical', 'timeSensitive', 'active', 'passive')
BARK_DEFAULTS = {'enabled': False, 'sound': 'chime', 'volume': 2, 'call': False,
                 'level': 'critical', 'info_level': 'active'}


# ---------- 路徑、鎖與設定 ----------

def home():
    # Windows 沒有 700/600 權限位元，mode 會被忽略，保護靠使用者資料夾本身的 ACL
    root = Path(os.environ.get('CLAUDE_INBOX_HOME') or Path.home() / '.claude-inbox')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    (root / 'questions').mkdir(mode=0o700, exist_ok=True)
    return root


class FileLock:
    """跨平台獨佔鎖，鎖的是專用的 .lock 檔：POSIX 用 flock，Windows 用 msvcrt 鎖第一個位元組。

    Windows 的位元組鎖是強制性的，鎖在資料檔上會擋住別人讀，所以一律鎖另一個檔。
    """

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.fh = open(self.path, 'a+b')
        try:
            if not IS_WINDOWS:
                fcntl.flock(self.fh, fcntl.LOCK_EX)
                return self
            while True:  # LK_LOCK 只重試約 10 秒就丟錯，改用不等待的 LK_NBLCK 自己輪詢
                self.fh.seek(0)
                try:
                    msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
                    return self
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EDEADLOCK):  # 只有「被別人鎖著」才重試
                        raise
                    time.sleep(0.05)
        except BaseException:
            self.fh.close()
            raise

    def __exit__(self, *exc):
        try:
            if IS_WINDOWS:
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(self.fh, fcntl.LOCK_UN)
        finally:
            self.fh.close()  # 關檔本身也會放掉鎖，解鎖失敗時仍要關


def read_config(path):
    config = {'host': '127.0.0.1', 'port': DEFAULT_PORT, 'token': ''}
    if path.exists():
        config.update(json.loads(path.read_text(encoding='utf-8')))
    return config


def load_config():
    path = home() / 'config.json'
    config = read_config(path)
    if not config.get('token'):
        import secrets
        with FileLock(home() / 'config.lock'):
            config = read_config(path)  # 搶到鎖後重讀，別人可能已經產生過
            if not config.get('token'):
                config['token'] = secrets.token_urlsafe(24)
                write_json(path, config)
    return config


def is_loopback(host):
    import ipaddress
    if host == 'localhost':
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def write_json(path, data):
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + '.')  # 預設權限 600
    with os.fdopen(fd, 'w', encoding='utf-8') as fh:
        fh.write(json.dumps(data, ensure_ascii=False, indent=2))
    os.replace(tmp, path)


def now_iso():
    return datetime.now(TAIPEI).isoformat(timespec='seconds')


def project_of(cwd):
    import subprocess
    try:
        out = subprocess.run(['git', '-C', str(cwd), 'rev-parse', '--show-toplevel'],
                             capture_output=True, encoding='utf-8', errors='replace', timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            return os.path.realpath(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return os.path.realpath(str(cwd))


def same_path(a, b):
    # Windows 路徑不分大小寫，比較前先 normcase；POSIX 上 normcase 不做事
    return bool(a) and bool(b) and os.path.normcase(a) == os.path.normcase(b)


def connect_host(config):
    # localhost 改寫成 127.0.0.1：Windows 上 localhost 先試 IPv6，只綁 IPv4 的服務要多等約 2 秒（實測）
    # 其他位址（含 127.0.0.2 這類 loopback）照設定，服務實際綁在哪就連哪
    return '127.0.0.1' if config['host'] == 'localhost' else config['host']


def base_url(config):
    return 'http://%s:%s/' % (connect_host(config), config['port'])


def page_url(config):
    return base_url(config) + ('?t=' + config['token'] if config.get('token') else '')


# ---------- 題目與事件 ----------

def load_questions():
    items = []
    for path in sorted((home() / 'questions').glob('*.json')):
        try:
            items.append(json.loads(path.read_text(encoding='utf-8')))
        except (OSError, ValueError):
            continue
    return items


def events_path():
    return home() / 'events.jsonl'


class EventLog:
    """events.jsonl 的讀寫，全部包在同一把檔案鎖（events.lock）裡。"""

    def __enter__(self):
        self.lock = FileLock(home() / 'events.lock')
        self.lock.__enter__()
        try:
            # O_BINARY：Windows 的 os.open 預設是文字模式，會把換行再轉一次；統一用 \n
            flags = os.O_RDWR | os.O_APPEND | os.O_CREAT | getattr(os, 'O_BINARY', 0)
            self.fh = os.fdopen(os.open(events_path(), flags, 0o600), 'a+', encoding='utf-8', newline='\n')
        except BaseException:
            self.lock.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exc):
        try:
            self.fh.close()  # 磁碟滿時 flush 會在這裡丟錯，鎖仍要放
        finally:
            self.lock.__exit__(*exc)

    def read(self):
        self.fh.seek(0)
        out = []
        for line in self.fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
        return out

    def append(self, events):
        for event in events:
            self.fh.write(json.dumps(event, ensure_ascii=False) + '\n')
        self.fh.flush()
        os.fsync(self.fh.fileno())


def new_id():
    import uuid
    return str(uuid.uuid4())


def read_events():
    if not events_path().exists():
        return []
    with EventLog() as log:
        return log.read()


def build_state(events=None):
    questions = {q['id']: dict(q, answers=[], closed=False) for q in load_questions()}
    delivered = set()
    if events is None:
        events = read_events()
    for e in events:
        if e.get('kind') == 'delivered':
            delivered.add(e.get('ref'))
    for e in events:
        q = questions.get(e.get('question_id'))
        if not q:
            continue
        if e.get('kind') == 'answer':
            q['answers'].append(dict(e, delivered=e['event_id'] in delivered))
        elif e.get('kind') == 'closed':
            q['closed'] = True
    items = sorted(questions.values(), key=lambda q: q['created'])
    return {'questions': items}


def deliverable(session_id, cwd, events=None):
    """這個 session 該拿到、還沒拿過的回答。

    git 只在真的有別的 session 的待送回答時才叫：hook 每輪都跑，平常省下約 60ms。
    """
    now = time.time()
    project = None
    out = []
    for q in build_state(events)['questions']:
        pending = [a for a in q['answers'] if not a['delivered']]
        if not pending:
            continue
        asker = q.get('session')
        own = bool(asker) and asker == session_id  # 出題的就是這個 session：不管現在在哪個資料夾
        if not own:
            if project is None:
                project = project_of(cwd)
            if not same_path(q.get('project'), project):
                continue
        for a in pending:
            age = now - datetime.fromisoformat(a['at']).timestamp()
            if own or not asker or age > ORPHAN_SECONDS:
                out.append((q, a))
    return out


def format_answers(pairs):
    lines = ['收件匣：使用者回覆了 %d 則。' % len(pairs)]
    for q, a in pairs:
        lines.append('')
        lines.append('【%s】%s' % (q['id'], q['title']))
        if a.get('choice') == 'ack':
            lines.append('使用者：我知道了')
        elif a.get('choice'):
            lines.append('使用者選：%s %s' % (a['choice'], a.get('choice_label', '')))
        if a.get('text'):
            lines.append('補充：' + a['text'])
    lines.append('')
    lines.append('照回覆繼續做；這件處理完可跑 inbox close <題號> 把它收起來。')
    return '\n'.join(lines)


def take(session_id, cwd):
    """取出回答並標成已送達；同一把鎖裡做，兩個 session 不會拿到同一則。"""
    with EventLog() as log:
        pairs = deliverable(session_id, cwd, log.read())
        if pairs:
            log.append([{'event_id': new_id(), 'kind': 'delivered', 'ref': a['event_id'],
                         'session': session_id, 'at': now_iso()} for _, a in pairs])
    return pairs


def validate_answers(payload, questions):
    answers = payload.get('answers') if isinstance(payload, dict) else None
    if not isinstance(answers, list) or not answers:
        raise ValueError('answers 必須是非空陣列')
    events = []
    for item in answers:
        q = questions.get(item.get('question_id')) if isinstance(item, dict) else None
        if not q:
            raise ValueError('找不到題目')
        choice = item.get('choice') or ''
        text = item.get('text') or ''
        if not isinstance(choice, str) or not isinstance(text, str) or len(text) > MAX_TEXT:
            raise ValueError('欄位格式不對')
        labels = {o['key']: o['label'] for o in q.get('options', [])}
        if q.get('kind') == 'info':
            if choice not in ('', 'ack'):
                raise ValueError('知會題只能按「我知道了」')
            choice = 'ack'
        elif choice and choice not in labels:
            raise ValueError('選項不存在')
        if not choice and not text.strip():
            raise ValueError('沒有選擇也沒有補充')
        events.append({'event_id': new_id(), 'kind': 'answer', 'question_id': q['id'],
                       'choice': choice, 'choice_label': labels.get(choice, ''),
                       'text': text.strip(), 'at': now_iso()})
    return events


# ---------- Bark 推播 ----------

class BarkError(Exception):
    pass


def bark_settings(config):
    """config.json 的 bark 段。沒寫的欄位用 BARK_DEFAULTS；寫錯一律報錯，不默默換成預設值。"""
    raw = config.get('bark', {})
    if not isinstance(raw, dict):
        raise ValueError('bark 必須是物件')
    unknown = sorted(set(raw) - set(BARK_DEFAULTS))
    if unknown:
        raise ValueError('bark 有不認得的欄位：' + '、'.join(unknown))
    s = dict(BARK_DEFAULTS, **raw)
    if not isinstance(s['enabled'], bool) or not isinstance(s['call'], bool):
        raise ValueError('enabled 與 call 只能是 true 或 false')
    if not isinstance(s['sound'], str) or not s['sound'].strip():
        raise ValueError('sound 不得為空')
    if type(s['volume']) is not int or not 0 <= s['volume'] <= 10:
        raise ValueError('volume 須是 0-10 的整數（目前 %r）' % (s['volume'],))
    for key in ('level', 'info_level'):
        if s[key] not in BARK_LEVELS:
            raise ValueError('%s 只能是 %s（目前 %r）' % (key, '、'.join(BARK_LEVELS), s[key]))
    return s


def bark_url():
    """讀環境變數 BARK_URL 並先驗格式；格式錯時的訊息不含網址本身（裡面有 device key）。"""
    from urllib.parse import urlsplit
    url = os.environ.get('BARK_URL', '').strip()
    if not url:
        raise BarkError('沒有設定環境變數 BARK_URL（格式 https://api.day.app/<device_key>）')
    try:
        parts = urlsplit(url)
    except ValueError:
        parts = None
    if not parts or parts.scheme not in ('http', 'https') or not parts.netloc or not parts.path.strip('/'):
        raise BarkError('環境變數 BARK_URL 格式不對，應該像 https://api.day.app/<device_key>')
    return url


def redact(text, url):
    """錯誤訊息遮掉 BARK_URL 與 device key，免得進到 agent 的上下文或 log。

    key 從網址路徑逐段取（不含 ?query），太短的段落（如 push）不遮，免得把一般字詞也換掉。
    """
    from urllib.parse import urlsplit
    text = str(text).replace(url, '<BARK_URL>')
    for part in urlsplit(url).path.split('/'):
        if len(part) >= 8:
            text = text.replace(part, '<device_key>')
    return text


def bark_link(config):
    """點推播要開的收件匣網址，不含 token（token 由網頁存在手機的 localStorage）。

    服務只開在本機時手機連不到，就不帶網址。
    """
    return '' if is_loopback(config['host']) else base_url(config)


def bark_payload(s, title, body, info, link=''):
    """待決定題用 level（預設 critical，靜音也響）；知會題用 info_level（預設 active），一律單響。"""
    level = s['info_level'] if info else s['level']
    payload = {'title': title, 'body': body, 'group': 'inbox', 'level': level, 'sound': s['sound']}
    if link:
        payload['url'] = link
    if level == 'critical':
        payload['volume'] = s['volume']  # 音量只對重要警示有效
    if s['call'] and not info:
        payload['call'] = '1'  # Bark 只支援單響或連響約 30 秒，不能指定秒數
    return payload


def send_bark(url, payload):
    import http.client
    import urllib.error
    import urllib.request
    try:  # 建 Request 也要包進來：網址格式錯時 urllib 的例外訊息會含整串網址
        req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                                     headers={'Content-Type': 'application/json; charset=utf-8'})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                status, raw = resp.status, resp.read(4096)
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read(4096)
    except (OSError, ValueError, http.client.HTTPException) as exc:  # 連不上、逾時、網址格式錯、回應壞掉
        raise BarkError(redact(exc, url)) from None
    try:
        ok = status == 200 and json.loads(raw.decode('utf-8')).get('code') == 200
    except (ValueError, AttributeError):
        ok = False
    if not ok:
        raise BarkError(redact('HTTP %s：%s' % (status, raw.decode('utf-8', 'replace').strip()), url))


def notify_question(q, s, url, link):
    # 推播只帶題目標題、期限與不含 token 的網址：token 不經過 Bark 伺服器與 Apple
    info = q['kind'] == 'info'
    title = '[收件匣/%s] %s' % (q['from'], '知會' if info else '待你決定')
    body = q['title'] + ('\n期限：' + q['deadline'] if q['deadline'] else '')
    send_bark(url, bark_payload(s, title, body, info, link))


def bark_status(s):
    return '\n'.join([
        'Bark 推播：%s' % ('開啟' if s['enabled'] else '關閉'),
        '  鈴聲 %s，待決定題%s' % (s['sound'], '連響約 30 秒' if s['call'] else '單響'),
        '  待決定題等級 %s（音量 %d，只對 critical 有效）' % (s['level'], s['volume']),
        '  知會題等級 %s（一律單響）' % s['info_level'],
        '  BARK_URL：%s' % ('已設定' if os.environ.get('BARK_URL', '').strip() else '沒有設定'),
    ])


# ---------- 網頁服務 ----------

@functools.lru_cache(maxsize=None)
def handler_class():
    """網頁服務的 handler。http.server 載入要約 30ms，hook 用不到，所以要開服務時才建。"""
    import secrets
    from http.server import BaseHTTPRequestHandler

    class Handler(BaseHTTPRequestHandler):
        config = None

        def log_message(self, fmt, *args):
            pass

        def allowed_hosts(self):
            port = self.config['port']
            hosts = {'%s:%s' % (self.config['host'], port)}
            if is_loopback(self.config['host']):
                hosts |= {'localhost:%s' % port, '127.0.0.1:%s' % port}
            return hosts

        def check(self, api):
            host = self.headers.get('Host', '')
            if host not in self.allowed_hosts():
                return self.send_text(403, 'Host 不符')
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + host:
                return self.send_text(403, 'Origin 不符')
            token = self.config.get('token')
            if api and token and not secrets.compare_digest(self.headers.get('X-Inbox-Token', ''), token):
                return self.send_text(401, '需要 token')
            return True

        def send_text(self, code, text, ctype='text/plain; charset=utf-8'):
            body = text.encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(body)
            return False

        def do_GET(self):
            path = self.path.split('?', 1)[0]
            if path == '/':
                if self.check(api=False):
                    self.send_text(200, PAGE.read_text(encoding='utf-8'), 'text/html; charset=utf-8')
            elif path == '/api/state':
                if self.check(api=True):
                    self.send_text(200, json.dumps(build_state(), ensure_ascii=False),
                                   'application/json; charset=utf-8')
            else:
                self.send_text(404, 'not found')

        def do_POST(self):
            try:
                length = int(self.headers.get('Content-Length') or 0)
            except ValueError:
                length = -1
            # 先把本文讀完再回錯：Windows 關掉還有未讀資料的連線會送 RST，用戶端收不到錯誤碼
            raw = self.rfile.read(length) if 0 < length <= MAX_BODY else None
            if self.path != '/api/answer':
                return self.send_text(404, 'not found')
            if not self.check(api=True):
                return
            if not self.headers.get('Content-Type', '').startswith('application/json'):
                return self.send_text(415, '只收 JSON')
            if raw is None:
                return self.send_text(413, '內容太大或是空的')
            try:
                payload = json.loads(raw.decode('utf-8'))
                questions = {q['id']: q for q in load_questions()}
                events = validate_answers(payload, questions)
            except ValueError as exc:
                return self.send_text(400, str(exc))
            with EventLog() as log:
                log.append(events)
            self.send_text(200, json.dumps({'stored': len(events)}), 'application/json')

    return Handler


def serve(config):
    from http.server import ThreadingHTTPServer

    class InboxServer(ThreadingHTTPServer):
        # Windows 的 SO_REUSEADDR 允許兩個服務綁同一個埠（實測可行），搶輸的也會綁成功並蓋掉 server.pid
        allow_reuse_address = not IS_WINDOWS

    handler = handler_class()
    handler.config = config
    try:
        server = InboxServer((config['host'], config['port']), handler)
    except PermissionError:
        if IS_WINDOWS:  # WinError 10013：埠落在 Hyper-V／WSL 保留範圍，沒人在用也綁不到
            print('綁不到埠 %s：可能在 Windows 保留範圍內（netsh interface ipv4 show excludedportrange '
                  'protocol=tcp），請在 %s 改 port' % (config['port'], home() / 'config.json'), flush=True)
        raise
    (home() / 'server.pid').write_text(str(os.getpid()))  # 綁埠成功才寫：搶輸的不會蓋掉活著的那個
    print('收件匣服務已啟動：' + base_url(config), flush=True)  # 服務的 log 不放 token
    server.serve_forever()


def server_alive(config):
    import urllib.request
    req = urllib.request.Request('http://%s:%s/api/state' % (connect_host(config), config['port']),
                                 headers={'X-Inbox-Token': config.get('token', '')})
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            body = json.loads(resp.read().decode('utf-8'))
            return resp.status == 200 and isinstance(body, dict) and 'questions' in body
    except Exception:
        return False


def ensure_server(config):
    if server_alive(config):
        return True
    import subprocess
    cmd = [sys.executable, str(Path(__file__).resolve()), 'serve']
    if IS_WINDOWS:  # 脫離目前的主控台：不跳視窗，hook 或終端機結束時也不會被一起關掉
        extra = {'creationflags': subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        extra = {'start_new_session': True}
    # 子行程拿到自己的 handle；這份要關掉，否則 Windows 上 server.log 會被鎖住
    with open(home() / 'server.log', 'a', encoding='utf-8') as log:
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=log, **extra)
    for _ in range(20):
        time.sleep(0.2)
        if server_alive(config):
            return True
    return False


# ---------- 指令 ----------

def cmd_ask(args):
    import secrets
    options = []
    for raw in args.option or []:
        key, sep, label = raw.partition('=')
        if not sep or not key.strip() or not label.strip():
            sys.exit('選項格式是 A=說明文字：' + raw)
        options.append({'key': key.strip(), 'label': label.strip(),
                        'recommended': key.strip() == args.recommend})
    if args.recommend and not any(o['recommended'] for o in options):
        sys.exit('--recommend 指的選項不存在')
    body = Path(args.body_file).read_text(encoding='utf-8') if args.body_file else (args.body or '')
    config = load_config()
    try:  # 推播設定先驗：開著卻缺 BARK_URL 或填錯，直接報錯，不默默只出題不推
        bark = bark_settings(config)
        url = bark_url() if bark['enabled'] else ''
    except (ValueError, BarkError) as exc:
        sys.exit('Bark 設定有問題，題目沒有放進收件匣：%s\n（看設定：inbox bark；不想推播：inbox bark off）' % exc)
    stamp = datetime.now(TAIPEI).strftime('%Y%m%d-%H%M%S')
    q = {'id': 'q-%s-%s' % (stamp, secrets.token_hex(2)), 'kind': 'info' if args.info else 'ask',
         'title': args.title, 'body': body, 'options': options, 'deadline': args.deadline or '',
         'from': args.source or os.path.basename(project_of(os.getcwd())),
         'project': project_of(os.getcwd()), 'session': os.environ.get('CLAUDE_CODE_SESSION_ID', ''),
         'created': now_iso()}
    write_json(home() / 'questions' / (q['id'] + '.json'), q)
    up = ensure_server(config)
    print('已放進收件匣：%s' % q['id'])
    print('網址：' + page_url(config) if up else '服務沒起來，請看 %s' % (home() / 'server.log'))
    if bark['enabled']:
        try:
            notify_question(q, bark, url, bark_link(config))
        except BarkError as exc:
            sys.exit('Bark 推播失敗（題目已經放進收件匣，不要重出）：%s' % exc)
        print('已用 Bark 推播到手機')


def cmd_close(args):
    ids = {q['id'] for q in load_questions()}
    missing = [i for i in args.ids if i not in ids]
    if missing:
        sys.exit('找不到：' + ' '.join(missing))
    with EventLog() as log:
        log.append([{'event_id': new_id(), 'kind': 'closed', 'question_id': i,
                     'at': now_iso()} for i in args.ids])
    print('已收起 %d 題' % len(args.ids))


def cmd_take(args):
    pairs = take(os.environ.get('CLAUDE_CODE_SESSION_ID', ''), os.getcwd())
    print(format_answers(pairs) if pairs else '收件匣：沒有新的回覆。')


def cmd_wait(args):
    deadline = time.time() + args.timeout
    session = os.environ.get('CLAUDE_CODE_SESSION_ID', '')
    while time.time() < deadline:
        if deliverable(session, os.getcwd()):
            pairs = take(session, os.getcwd())
            if pairs:
                print(format_answers(pairs))
                return
        time.sleep(3)
    print('收件匣：等了 %d 秒沒有新回覆。' % args.timeout)
    sys.exit(2)


def cmd_hook(args):
    """給 Claude Code hook 用：stdin 是 hook 的 JSON，stdout 會進 agent 的上下文。"""
    raw = sys.stdin.read().lstrip('\ufeff')  # Windows PowerShell 5.1 往管道寫會先送 BOM
    try:
        data = json.loads(raw or '{}')
    except ValueError:
        sys.exit('收件匣 hook：stdin 不是 JSON：%r' % raw[:200])
    pairs = take(data.get('session_id', ''), data.get('cwd') or os.getcwd())
    if pairs:
        print(format_answers(pairs))


def cmd_list(args):
    for q in build_state()['questions']:
        if q['closed'] and not args.all:
            continue
        status = '已收起' if q['closed'] else ('已回答' if q['answers'] else '等回答')
        print('%s  %s  %s  （%s）' % (q['id'], status, q['title'], q['from']))


def cmd_stop(args):
    import signal
    pidfile = home() / 'server.pid'
    if not pidfile.exists():
        return print('沒有記錄中的服務')
    try:
        os.kill(int(pidfile.read_text()), signal.SIGTERM)
        print('已停止')
    except (OSError, ValueError):  # Windows 找不到 PID 丟的是 OSError，不是 ProcessLookupError
        print('服務本來就沒在跑')
    pidfile.unlink()


def cmd_bark(args):
    changes = {k: v for k, v in (('sound', args.sound), ('volume', args.volume), ('level', args.level),
                                  ('info_level', args.info_level)) if v is not None}
    if 'sound' in changes:
        changes['sound'] = changes['sound'].strip()
    if args.call is not None:
        changes['call'] = args.call == 'on'
    if args.action in ('on', 'off'):
        changes['enabled'] = args.action == 'on'
    if args.action == 'status' and changes:
        sys.exit('status 不接受設定選項；要改設定用 inbox bark set')
    if args.action == 'set' and not changes:
        sys.exit('set 至少要帶一個選項，例如 --sound glass')
    path = home() / 'config.json'
    try:
        if args.action == 'test':  # 試聽：這次帶的選項只用一次，不存
            s = bark_settings({'bark': dict(read_config(path).get('bark', {}), **changes)})
            body = '鈴聲 %s，%s，等級 %s，音量 %d（%s）' % (
                s['sound'], '連響約 30 秒' if s['call'] else '單響', s['level'], s['volume'],
                datetime.now(TAIPEI).strftime('%H:%M:%S'))
            send_bark(bark_url(), bark_payload(s, '[收件匣] 測試推播', body, False, bark_link(read_config(path))))
            return print('已送出測試推播：' + body)
        if args.action == 'status':
            return print(bark_status(bark_settings(read_config(path))))
        with FileLock(home() / 'config.lock'):
            config = read_config(path)
            config['bark'] = dict(config.get('bark', {}), **changes)
            s = bark_settings(config)  # 先驗證再寫，填錯不會存進去
            if s['enabled']:
                bark_url()  # 開著卻沒有 BARK_URL，之後每次出題都會失敗，現在就擋
            write_json(path, config)
    except (ValueError, BarkError) as exc:
        sys.exit('Bark：%s' % exc)
    print(bark_status(s))


def use_utf8_stdio():
    """Windows 的管道預設用系統碼頁（如 cp950）；hook 的輸出要是 UTF-8，agent 才讀得懂中文。"""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')


def main(argv=None):
    use_utf8_stdio()
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv == ['hook']:  # 每輪都跑的 hook 不經 argparse，省載入時間
        return cmd_hook(None)
    import argparse
    parser = argparse.ArgumentParser(prog='inbox', description='Claude Code 收件匣')
    sub = parser.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('ask', help='放一題進收件匣')
    p.add_argument('--title', required=True)
    p.add_argument('--body')
    p.add_argument('--body-file')
    p.add_argument('--option', action='append', help='A=說明，可重複')
    p.add_argument('--recommend', help='推薦的選項代號')
    p.add_argument('--info', action='store_true', help='只是知會，使用者按「我知道了」')
    p.add_argument('--deadline')
    p.add_argument('--from', dest='source', help='顯示的來源名稱，預設是專案資料夾名')
    p.set_defaults(func=cmd_ask)
    p = sub.add_parser('take', help='取出這個 session 的新回覆')
    p.set_defaults(func=cmd_take)
    p = sub.add_parser('wait', help='等到有新回覆才結束')
    p.add_argument('--timeout', type=int, default=1800)
    p.set_defaults(func=cmd_wait)
    p = sub.add_parser('close', help='把處理完的題目收起來')
    p.add_argument('ids', nargs='+')
    p.set_defaults(func=cmd_close)
    p = sub.add_parser('list', help='列出題目')
    p.add_argument('--all', action='store_true')
    p.set_defaults(func=cmd_list)
    p = sub.add_parser('bark', help='Bark 手機推播：status（預設）、on、off、set、test')
    p.add_argument('action', nargs='?', default='status', choices=('status', 'on', 'off', 'set', 'test'))
    p.add_argument('--sound', help='Bark 鈴聲名稱，例如 chime、glass、bell 或自訂鈴聲')
    p.add_argument('--volume', type=int, help='重要警示（critical）音量 0-10')
    p.add_argument('--call', choices=('on', 'off'), help='on 連響約 30 秒、off 單響（只套用在待決定題）')
    p.add_argument('--level', choices=BARK_LEVELS, help='待決定題的推播等級')
    p.add_argument('--info-level', choices=BARK_LEVELS, help='知會題的推播等級')
    p.set_defaults(func=cmd_bark)
    sub.add_parser('hook', help='給 Claude Code hook 用').set_defaults(func=cmd_hook)
    sub.add_parser('serve', help='前景執行網頁服務').set_defaults(func=lambda a: serve(load_config()))
    sub.add_parser('start', help='背景啟動網頁服務').set_defaults(
        func=lambda a: print(page_url(load_config()) if ensure_server(load_config()) else '啟動失敗'))
    sub.add_parser('stop', help='停止背景服務').set_defaults(func=cmd_stop)
    sub.add_parser('url', help='印出網址').set_defaults(func=lambda a: print(page_url(load_config())))
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == '__main__':
    main()
