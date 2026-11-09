"""收件匣單元測試：python3 -m unittest discover tests（Windows 用 python）"""
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'inbox'))
import inbox  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
INBOX_PY = ROOT / 'inbox' / 'inbox.py'
DEVICE_KEY = 'testdevicekey12345'  # 假的 device key，用來驗證錯誤訊息有遮蔽

REAL_ENSURE_SERVER = inbox.ensure_server  # Base 會把它換成替身，這裡先留一份真的


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name) / 'proj'
        self.project.mkdir()
        self.env = mock.patch.dict(os.environ, {'CLAUDE_INBOX_HOME': str(Path(self.tmp.name) / 'home'),
                                                'CLAUDE_CODE_SESSION_ID': 'sess-1'})
        self.env.start()
        os.environ.pop('BARK_URL', None)  # 本機若設了真的 BARK_URL，測試絕不能推到手機（patch.dict 結束時會還原）
        self.cwd = os.getcwd()
        os.chdir(self.project)
        self.no_server = mock.patch.object(inbox, 'ensure_server', return_value=True)
        self.no_server.start()

    def tearDown(self):
        self.no_server.stop()
        os.chdir(self.cwd)
        self.env.stop()
        self.tmp.cleanup()

    def ask(self, *argv):
        with redirect_stdout(io.StringIO()) as out:
            inbox.main(['ask'] + list(argv))
        return out.getvalue().split('已放進收件匣：')[1].split()[0]

    def answer(self, qid, choice='A', text=''):
        questions = {q['id']: q for q in inbox.load_questions()}
        events = inbox.validate_answers({'answers': [{'question_id': qid, 'choice': choice, 'text': text}]}, questions)
        with inbox.EventLog() as log:
            log.append(events)
        return events[0]


class AskAndAnswer(Base):
    def test_ask_writes_question_with_session_and_project(self):
        qid = self.ask('--title', '要哪個？', '--option', 'A=甲', '--option', 'B=乙', '--recommend', 'B')
        q = inbox.load_questions()[0]
        self.assertEqual(q['id'], qid)
        self.assertEqual(q['session'], 'sess-1')
        self.assertEqual(q['project'], os.path.realpath(str(self.project)))
        self.assertEqual([o['recommended'] for o in q['options']], [False, True])

    def test_bad_option_and_bad_recommend_rejected(self):
        with self.assertRaises(SystemExit):
            self.ask('--title', 't', '--option', 'A')
        with self.assertRaises(SystemExit):
            self.ask('--title', 't', '--option', 'A=甲', '--recommend', 'Z')

    def test_validate_rejects_unknown_choice_empty_answer_and_long_text(self):
        qid = self.ask('--title', 't', '--option', 'A=甲')
        qs = {q['id']: q for q in inbox.load_questions()}
        for bad in ({'question_id': qid, 'choice': 'Z'}, {'question_id': qid},
                    {'question_id': qid, 'text': 'x' * 4001}, {'question_id': 'nope', 'choice': 'A'}):
            with self.assertRaises(ValueError):
                inbox.validate_answers({'answers': [bad]}, qs)

    def test_info_question_only_accepts_ack(self):
        qid = self.ask('--info', '--title', '知會')
        qs = {q['id']: q for q in inbox.load_questions()}
        self.assertEqual(inbox.validate_answers({'answers': [{'question_id': qid}]}, qs)[0]['choice'], 'ack')
        with self.assertRaises(ValueError):
            inbox.validate_answers({'answers': [{'question_id': qid, 'choice': 'A'}]}, qs)


class Delivery(Base):
    def test_answer_goes_to_asking_session_once(self):
        qid = self.ask('--title', 't', '--option', 'A=甲')
        self.answer(qid, 'A', '補充')
        self.assertEqual(inbox.take('sess-2', str(self.project)), [])  # 別的 session 拿不到
        pairs = inbox.take('sess-1', str(self.project))
        self.assertEqual(len(pairs), 1)
        self.assertIn('使用者選：A 甲', inbox.format_answers(pairs))
        self.assertIn('補充：補充', inbox.format_answers(pairs))
        self.assertEqual(inbox.take('sess-1', str(self.project)), [])  # 只送一次

    def test_asking_session_gets_answer_even_from_another_directory(self):
        sub_dir = self.project / 'a' / 'b'
        sub_dir.mkdir(parents=True)
        os.chdir(sub_dir)  # 非 git 資料夾：出題與 hook 的 cwd 不同，專案根就不同
        qid = self.ask('--title', 't', '--option', 'A=甲')
        self.answer(qid)
        self.assertEqual(len(inbox.take('sess-1', str(self.project))), 1)

    def test_other_project_cannot_take_over_even_old_answers_or_empty_sessions(self):
        qid = self.ask('--title', 't', '--option', 'A=甲')
        event = self.answer(qid)
        other = Path(self.tmp.name) / 'other'
        other.mkdir()
        later = datetime.fromisoformat(event['at']).timestamp() + inbox.ORPHAN_SECONDS + 1
        with mock.patch.object(inbox.time, 'time', return_value=later):
            self.assertEqual(inbox.take('sess-2', str(other)), [])  # 過了 30 分鐘也只限同專案
        with mock.patch.dict(os.environ, {'CLAUDE_CODE_SESSION_ID': ''}):
            anon = self.ask('--title', '匿名', '--option', 'A=甲')
        self.answer(anon)
        self.assertEqual(inbox.take('', str(other)), [])  # 空 session 對空 session 不算同一個

    def test_other_project_never_gets_it(self):
        qid = self.ask('--title', 't', '--option', 'A=甲')
        self.answer(qid)
        other = Path(self.tmp.name) / 'other'
        other.mkdir()
        self.assertEqual(inbox.take('sess-2', str(other)), [])  # 別的專案、別的 session

    def test_orphan_answer_goes_to_same_project_after_30_minutes(self):
        qid = self.ask('--title', 't', '--option', 'A=甲')
        event = self.answer(qid)
        self.assertEqual(inbox.take('sess-2', str(self.project)), [])
        later = datetime.fromisoformat(event['at']).timestamp() + inbox.ORPHAN_SECONDS + 1
        with mock.patch.object(inbox.time, 'time', return_value=later):
            self.assertEqual(len(inbox.take('sess-2', str(self.project))), 1)

    def test_hook_reads_stdin_and_prints_answers(self):
        qid = self.ask('--title', '問題標題', '--option', 'A=甲')
        self.answer(qid)
        stdin = io.StringIO(json.dumps({'session_id': 'sess-1', 'cwd': str(self.project)}))
        with mock.patch.object(sys, 'stdin', stdin), redirect_stdout(io.StringIO()) as out:
            inbox.main(['hook'])
        self.assertIn('問題標題', out.getvalue())
        with mock.patch.object(sys, 'stdin', io.StringIO('{}')), redirect_stdout(io.StringIO()) as out:
            inbox.main(['hook'])
        self.assertEqual(out.getvalue(), '')  # 沒有新回覆時什麼都不印

    def test_close_hides_question_from_list(self):
        qid = self.ask('--title', '要收的題')
        with redirect_stdout(io.StringIO()):
            inbox.main(['close', qid])
        with redirect_stdout(io.StringIO()) as out:
            inbox.main(['list'])
        self.assertNotIn('要收的題', out.getvalue())
        self.assertTrue(inbox.build_state()['questions'][0]['closed'])


class Server(Base):
    def start(self, host='127.0.0.1', token=''):
        port = free_port()
        handler = inbox.handler_class()
        handler.config = {'host': host, 'port': port, 'token': token}
        httpd = ThreadingHTTPServer((host, port), handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.shutdown)
        return port

    def req(self, port, path, data=None, headers=None):
        h = {'Content-Type': 'application/json'}
        h.update(headers or {})
        r = urllib.request.Request('http://127.0.0.1:%d%s' % (port, path),
                                   data=json.dumps(data).encode() if data is not None else None, headers=h)
        try:
            with urllib.request.urlopen(r, timeout=5) as resp:
                return resp.status, resp.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def test_answer_round_trip(self):
        qid = self.ask('--title', 't', '--option', 'A=甲')
        port = self.start()
        self.assertEqual(self.req(port, '/')[0], 200)
        code, body = self.req(port, '/api/answer', {'answers': [{'question_id': qid, 'choice': 'A'}]})
        self.assertEqual((code, json.loads(body)), (200, {'stored': 1}))
        state = json.loads(self.req(port, '/api/state')[1])
        self.assertEqual(state['questions'][0]['answers'][0]['choice'], 'A')

    def test_bad_host_origin_and_invalid_answer_rejected(self):
        qid = self.ask('--title', 't', '--option', 'A=甲')
        port = self.start()
        self.assertEqual(self.req(port, '/api/state', headers={'Host': 'evil.example:80'})[0], 403)
        self.assertEqual(self.req(port, '/api/answer', {'answers': [{'question_id': qid, 'choice': 'A'}]},
                                  headers={'Origin': 'http://evil.example'})[0], 403)
        self.assertEqual(self.req(port, '/api/answer', {'answers': [{'question_id': qid, 'choice': 'Z'}]})[0], 400)
        self.assertEqual(inbox.read_events(), [])

    def test_token_required_when_configured(self):
        port = self.start(token='secret-token')
        self.assertEqual(self.req(port, '/api/state')[0], 401)
        self.assertEqual(self.req(port, '/api/state', headers={'X-Inbox-Token': 'secret-token'})[0], 200)

    def test_other_program_returning_200_is_not_taken_for_inbox(self):
        from http.server import BaseHTTPRequestHandler

        class Fake(BaseHTTPRequestHandler):
            body = b'<html>spa fallback</html>'

            def do_GET(self):
                body = Fake.body
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        port = free_port()
        httpd = ThreadingHTTPServer(('127.0.0.1', port), Fake)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.shutdown)
        self.assertFalse(inbox.server_alive({'host': '127.0.0.1', 'port': port, 'token': ''}))
        for body in (b'{}', b'["questions"]', b'"questions"'):
            Fake.body = body
            self.assertFalse(inbox.server_alive({'host': '127.0.0.1', 'port': port, 'token': ''}))
        Fake.body = b'<html>spa fallback</html>'
        real = self.start()
        self.assertTrue(inbox.server_alive({'host': '127.0.0.1', 'port': real, 'token': ''}))

    def test_background_server_log_never_contains_token(self):
        import signal
        port = free_port()
        inbox.home()
        (Path(os.environ['CLAUDE_INBOX_HOME']) / 'config.json').write_text(json.dumps({'port': port}))
        config = inbox.load_config()
        pid_file = Path(os.environ['CLAUDE_INBOX_HOME']) / 'server.pid'

        try:
            with mock.patch.object(inbox, 'ensure_server', REAL_ENSURE_SERVER):
                self.assertTrue(inbox.ensure_server(config))
            log = (Path(os.environ['CLAUDE_INBOX_HOME']) / 'server.log').read_text(encoding='utf-8')
            self.assertIn('收件匣服務已啟動', log)
            self.assertNotIn(config['token'], log)
        finally:  # 必須在測試本體清：tearDown 會先刪掉暫存資料夾與 PID 檔
            if pid_file.exists():
                try:
                    os.kill(int(pid_file.read_text()), signal.SIGTERM)
                except (OSError, ValueError):
                    pass
            # Windows：被終止的服務要一下子才放開 server.log，tearDown 刪資料夾前先等它放開
            log_file = Path(os.environ['CLAUDE_INBOX_HOME']) / 'server.log'
            for _ in range(80):
                try:
                    log_file.unlink()
                    break
                except FileNotFoundError:
                    break
                except PermissionError:
                    time.sleep(0.05)

    def test_loopback_default_also_gets_private_token_and_folder(self):
        old = os.umask(0o022)  # 在寬鬆的 umask 下測，權限被放寬時才會變紅
        self.addCleanup(os.umask, old)
        config = inbox.load_config()
        path = Path(os.environ['CLAUDE_INBOX_HOME']) / 'config.json'
        self.assertTrue(config['token'])
        self.assertMode(path, '0o600')
        self.assertMode(path.parent, '0o700')
        self.assertEqual(inbox.load_config()['token'], config['token'])  # 第二次不重產
        qid = self.ask('--title', 't')
        self.answer(qid, choice='', text='x')
        self.assertMode(inbox.events_path(), '0o600')
        self.assertMode(path.parent / 'questions', '0o700')

    def assertMode(self, path, mode):
        # Windows 沒有 POSIX 權限位元（st_mode 一律 0o666／0o777），保護靠使用者資料夾的 ACL
        if os.name != 'nt':
            self.assertEqual(oct(path.stat().st_mode & 0o777), mode)

    def test_non_loopback_host_gets_token_generated(self):
        path = Path(os.environ['CLAUDE_INBOX_HOME']) / 'config.json'
        inbox.home()
        path.write_text(json.dumps({'host': '100.64.0.1'}))
        config = inbox.load_config()
        self.assertTrue(config['token'])
        self.assertMode(path, '0o600')
        self.assertIn('?t=' + config['token'], inbox.page_url(config))

    def test_urls_use_configured_loopback_and_rewrite_only_localhost(self):
        self.assertEqual(inbox.base_url({'host': 'localhost', 'port': 1}), 'http://127.0.0.1:1/')
        self.assertEqual(inbox.base_url({'host': '127.0.0.2', 'port': 1}), 'http://127.0.0.2:1/')
        self.assertEqual(inbox.base_url({'host': '100.64.0.1', 'port': 1}), 'http://100.64.0.1:1/')


class Platform(Base):
    def test_file_lock_is_exclusive(self):
        inbox.home()
        lock = Path(os.environ['CLAUDE_INBOX_HOME']) / 't.lock'
        order, held = [], threading.Event()

        def first():
            with inbox.FileLock(lock):
                order.append('first-in')
                held.set()
                time.sleep(0.3)
                order.append('first-out')

        t = threading.Thread(target=first)
        t.start()
        held.wait(5)
        with inbox.FileLock(lock):
            order.append('second-in')
        t.join()
        self.assertEqual(order, ['first-in', 'first-out', 'second-in'])

    def test_hook_output_is_utf8_on_pipes_and_accepts_bom(self):
        qid = self.ask('--title', '中文題目', '--option', 'A=甲')
        self.answer(qid)
        env = dict(os.environ)
        for k in ('PYTHONIOENCODING', 'PYTHONUTF8'):  # 模擬沒設這些的預設環境（Windows 會是 cp950）
            env.pop(k, None)
        stdin = ('\ufeff' + json.dumps({'session_id': 'sess-1', 'cwd': str(self.project)})).encode('utf-8')
        out = subprocess.run([sys.executable, str(INBOX_PY), 'hook'], input=stdin, capture_output=True,
                             env=env, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr.decode('utf-8', 'replace'))
        self.assertIn('中文題目', out.stdout.decode('utf-8'))

    def test_hook_rejects_non_json_stdin(self):
        with mock.patch.object(sys, 'stdin', io.StringIO('not json')):
            with self.assertRaises(SystemExit):
                inbox.main(['hook'])

    def test_hook_only_calls_git_when_another_sessions_answer_is_pending(self):
        mine = self.ask('--title', '我的', '--option', 'A=甲')
        with mock.patch.dict(os.environ, {'CLAUDE_CODE_SESSION_ID': 'sess-other'}):
            theirs = self.ask('--title', '別人的', '--option', 'A=甲')
        with mock.patch.object(inbox, 'project_of', wraps=inbox.project_of) as spy:
            inbox.take('sess-1', str(self.project))  # 還沒有任何回答
            self.answer(mine)
            self.assertEqual(len(inbox.take('sess-1', str(self.project))), 1)  # 自己的回答不用比專案
            self.assertEqual(spy.call_count, 0)
            self.answer(theirs)
            inbox.take('sess-1', str(self.project))  # 別人的待送回答才要查專案根
            self.assertEqual(spy.call_count, 1)

    @unittest.skipUnless(os.name == 'nt', 'Windows 路徑才不分大小寫')
    def test_same_project_matches_regardless_of_case(self):
        qid = self.ask('--title', 't', '--option', 'A=甲')
        event = self.answer(qid)
        later = datetime.fromisoformat(event['at']).timestamp() + inbox.ORPHAN_SECONDS + 1
        with mock.patch.object(inbox.time, 'time', return_value=later):
            self.assertEqual(len(inbox.take('sess-2', str(self.project).upper())), 1)

    @unittest.skipUnless(shutil.which('sh'), '沒有 sh')
    def test_sh_launcher_runs(self):
        # 跟 hooks.json 一樣用「plugin 根目錄 + /bin/inbox」；檔案若被轉成 CRLF，這裡會失敗
        out = subprocess.run(['sh', str(ROOT) + '/bin/inbox', 'list'], capture_output=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr.decode('utf-8', 'replace'))


class FakeBark:
    """本機假的 Bark 伺服器：記下收到的推播，回 reply 指定的狀態碼與內容。"""

    def __init__(self, test):
        from http.server import BaseHTTPRequestHandler
        outer = self
        self.received = []
        self.reply = (200, {'code': 200, 'message': 'success'})

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get('Content-Length') or 0)
                outer.received.append((self.path, json.loads(self.rfile.read(n).decode('utf-8'))))
                code, body = outer.reply
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), H)
        self.url = 'http://127.0.0.1:%d/%s' % (self.httpd.server_address[1], DEVICE_KEY)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        test.addCleanup(self.httpd.server_close)
        test.addCleanup(self.httpd.shutdown)


class Bark(Base):
    def setUp(self):
        super().setUp()
        self.fake = FakeBark(self)
        os.environ['BARK_URL'] = self.fake.url  # Base 的 patch.dict 結束時會還原

    def bark(self, *argv):
        with redirect_stdout(io.StringIO()) as out:
            inbox.main(['bark'] + list(argv))
        return out.getvalue()

    def exit_message(self, argv):
        with self.assertRaises(SystemExit) as cm, redirect_stdout(io.StringIO()):
            inbox.main(argv)
        return str(cm.exception.code)

    def saved_bark(self):
        return inbox.read_config(Path(os.environ['CLAUDE_INBOX_HOME']) / 'config.json').get('bark', {})

    def test_default_off_ask_does_not_push(self):
        self.ask('--title', 't')
        self.assertEqual(self.fake.received, [])
        self.assertIn('關閉', self.bark())

    def test_decision_question_push_uses_settings(self):
        self.bark('on', '--sound', 'glass', '--volume', '4', '--call', 'on')
        self.ask('--title', '要哪個？', '--option', 'A=甲', '--deadline', '今天 18:00')
        path, payload = self.fake.received[0]
        self.assertEqual(path, '/' + DEVICE_KEY)
        self.assertEqual(payload['title'], '[收件匣/proj] 待你決定')
        self.assertIn('要哪個？', payload['body'])
        self.assertIn('期限：今天 18:00', payload['body'])
        self.assertEqual((payload['level'], payload['volume'], payload['sound'], payload['call']),
                         ('critical', 4, 'glass', '1'))
        self.assertNotIn('?t=', json.dumps(payload))  # 推播不帶收件匣網址與 token

    def test_info_question_push_is_active_and_single_ring(self):
        self.bark('on', '--call', 'on')
        self.ask('--info', '--title', '知會一下')
        payload = self.fake.received[0][1]
        self.assertEqual(payload['title'], '[收件匣/proj] 知會')
        self.assertEqual(payload['level'], 'active')
        self.assertNotIn('volume', payload)
        self.assertNotIn('call', payload)

    def test_on_requires_bark_url(self):
        os.environ.pop('BARK_URL')
        self.assertIn('BARK_URL', self.exit_message(['bark', 'on']))
        self.assertNotIn('enabled', self.saved_bark())

    def test_invalid_settings_rejected_and_not_saved(self):
        self.bark('set', '--volume', '3')
        for argv in (['bark', 'set', '--volume', '11'], ['bark', 'set', '--sound', '  '], ['bark', 'set']):
            self.exit_message(argv)
        self.assertEqual(self.saved_bark(), {'volume': 3})

    def test_bad_config_blocks_ask_before_saving(self):
        inbox.home()
        path = Path(os.environ['CLAUDE_INBOX_HOME']) / 'config.json'
        for bad in ({'enabled': True, 'volume': 'loud'}, {'enabled': True, 'volum': 2}, {'enabled': 'yes'}):
            path.write_text(json.dumps({'bark': bad}), encoding='utf-8')
            self.assertIn('題目沒有放進收件匣', self.exit_message(['ask', '--title', 't']))
        self.assertEqual(inbox.load_questions(), [])

    def test_enabled_without_bark_url_fails_before_saving(self):
        self.bark('on')
        os.environ.pop('BARK_URL')
        self.assertIn('BARK_URL', self.exit_message(['ask', '--title', 't']))
        self.assertEqual(inbox.load_questions(), [])

    def test_push_failure_keeps_question_and_hides_key(self):
        self.bark('on')
        self.fake.reply = (400, {'code': 400, 'message': 'failed to get device token: ' + DEVICE_KEY})
        msg = self.exit_message(['ask', '--title', 't'])
        self.assertIn('不要重出', msg)
        self.assertNotIn(DEVICE_KEY, msg)
        self.assertEqual(len(inbox.load_questions()), 1)

    def test_unreachable_bark_hides_url(self):
        url = 'http://127.0.0.1:%d/%s' % (free_port(), DEVICE_KEY)
        os.environ['BARK_URL'] = url
        msg = self.exit_message(['bark', 'test'])
        self.assertNotIn(DEVICE_KEY, msg)
        self.assertNotIn(url, msg)

    def test_bark_test_uses_overrides_without_saving(self):
        out = self.bark('test', '--sound', 'bell')
        self.assertIn('已送出測試推播', out)
        self.assertEqual(self.fake.received[0][1]['sound'], 'bell')
        self.assertEqual(self.saved_bark(), {})

    def test_status_never_prints_bark_url(self):
        out = self.bark('status')
        self.assertIn('BARK_URL：已設定', out)
        self.assertNotIn(DEVICE_KEY, out)
        self.assertIn('status 不接受', self.exit_message(['bark', 'status', '--sound', 'x']))


    def test_push_links_to_inbox_without_token_only_when_reachable(self):
        self.bark('on')
        self.ask('--title', '本機')
        self.assertNotIn('url', self.fake.received[-1][1])  # 只開在本機：手機連不到，不帶網址
        path = Path(os.environ['CLAUDE_INBOX_HOME']) / 'config.json'
        config = json.loads(path.read_text(encoding='utf-8'))
        config['host'] = '100.64.0.1'
        path.write_text(json.dumps(config), encoding='utf-8')
        self.ask('--title', 'Tailscale')
        payload = self.fake.received[-1][1]
        self.assertEqual(payload['url'], 'http://100.64.0.1:7799/')
        self.assertNotIn(inbox.load_config()['token'], json.dumps(payload))

    def test_malformed_bark_url_never_leaks_key(self):
        os.environ['BARK_URL'] = 'api.day.app/' + DEVICE_KEY  # 漏掉 https://
        for argv in (['bark', 'test'], ['bark', 'on']):
            msg = self.exit_message(argv)
            self.assertIn('格式不對', msg)
            self.assertNotIn(DEVICE_KEY, msg)
        inbox.home()
        (Path(os.environ['CLAUDE_INBOX_HOME']) / 'config.json').write_text(
            json.dumps({'bark': {'enabled': True}}), encoding='utf-8')
        msg = self.exit_message(['ask', '--title', 't'])
        self.assertNotIn(DEVICE_KEY, msg)
        self.assertEqual(inbox.load_questions(), [])  # 格式錯在出題前就擋下

    def test_query_in_bark_url_does_not_break_redaction(self):
        os.environ['BARK_URL'] = self.fake.url + '?group=x'
        self.fake.reply = (400, {'code': 400, 'message': 'bad device ' + DEVICE_KEY})
        msg = self.exit_message(['bark', 'test'])
        self.assertIn('HTTP 400', msg)
        self.assertNotIn(DEVICE_KEY, msg)


class Switch(Base):
    def set_config(self, **changes):
        inbox.home()
        path = Path(os.environ['CLAUDE_INBOX_HOME']) / 'config.json'
        config = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        config.update(changes)
        path.write_text(json.dumps(config), encoding='utf-8')

    def run_inbox_server(self):
        """執行緒內的真服務，並寫 server.pid（guard 先看 pid 檔才打 HTTP）。"""
        port = free_port()
        self.set_config(port=port, token='tok-switch-test')
        handler = inbox.handler_class()
        handler.config = inbox.load_config()
        httpd = ThreadingHTTPServer(('127.0.0.1', port), handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        (Path(os.environ['CLAUDE_INBOX_HOME']) / 'server.pid').write_text(str(os.getpid()))

    def guard(self):
        err = io.StringIO()
        with mock.patch.object(sys, 'stdin', io.StringIO('{"tool_name":"AskUserQuestion"}')), \
                redirect_stderr(err):
            try:
                inbox.main(['guard'])
            except SystemExit as exc:
                return exc.code, err.getvalue()
        return 0, err.getvalue()

    def test_guard_ignores_running_server_when_not_switch_mode(self):
        self.run_inbox_server()
        self.assertEqual(self.guard(), (0, ''))

    def test_guard_blocks_ask_user_question_while_inbox_is_on(self):
        self.set_config(switch=True)
        self.run_inbox_server()
        code, err = self.guard()
        self.assertEqual(code, 2)
        self.assertIn('inbox ask', err)

    def test_guard_allows_when_inbox_is_off(self):
        self.set_config(switch=True, port=free_port())
        self.assertEqual(self.guard(), (0, ''))  # 沒有 pid 檔
        (Path(os.environ['CLAUDE_INBOX_HOME']) / 'server.pid').write_text('1')
        self.assertEqual(self.guard(), (0, ''))  # 有殘留 pid 檔但服務不在

    def test_bad_switch_value_is_an_error(self):
        self.set_config(switch='yes')
        with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()):
            inbox.main(['ask', '--title', 't'])

    def test_ask_refuses_and_does_not_autostart_while_inbox_is_off(self):
        self.set_config(switch=True, port=free_port())
        with self.assertRaises(SystemExit) as cm, redirect_stdout(io.StringIO()):
            inbox.main(['ask', '--title', 't'])
        self.assertIn('AskUserQuestion', str(cm.exception.code))
        self.assertEqual(inbox.load_questions(), [])
        inbox.ensure_server.assert_not_called()

    def test_ask_works_while_inbox_is_on_without_starting_another_server(self):
        self.set_config(switch=True)
        self.run_inbox_server()
        self.ask('--title', '開著')
        self.assertEqual(len(inbox.load_questions()), 1)
        inbox.ensure_server.assert_not_called()

    def test_toggle_turns_on_with_push_then_off(self):
        fake = FakeBark(self)
        os.environ['BARK_URL'] = fake.url
        self.set_config(switch=True, port=free_port(), bark={'enabled': True})
        home = Path(os.environ['CLAUDE_INBOX_HOME'])
        try:
            with mock.patch.object(inbox, 'ensure_server', REAL_ENSURE_SERVER):
                with redirect_stdout(io.StringIO()) as out:
                    inbox.main(['toggle'])
                self.assertIn('收件匣已開啟', out.getvalue())
                self.assertTrue(inbox.server_alive(inbox.load_config()))
                payload = fake.received[0][1]
                self.assertEqual((payload['title'], payload['level']), ('[收件匣] 已開啟', 'active'))
                self.assertNotIn('call', payload)
                with redirect_stdout(io.StringIO()) as out:
                    inbox.main(['toggle'])
                self.assertIn('收件匣已關閉', out.getvalue())
                self.assertFalse(inbox.server_alive(inbox.load_config()))
        finally:  # 測試失敗時也要收掉背景服務，並等 Windows 放開 server.log
            if inbox.server_alive(inbox.load_config()):
                with redirect_stdout(io.StringIO()):
                    inbox.main(['stop'])
            for _ in range(80):
                try:
                    (home / 'server.log').unlink()
                    break
                except FileNotFoundError:
                    break
                except PermissionError:
                    time.sleep(0.05)


if __name__ == '__main__':
    unittest.main()
