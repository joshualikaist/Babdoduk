"""Lab live panel: mocked backend, fixed clock, synthetic agent records only."""
import copy
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests.test_panel import TIMELINE, browser, open_panel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/panel'))
spec = importlib.util.spec_from_file_location('panel_relay', ROOT / 'scripts/panel/relay.py')
relay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relay)
NOW = datetime(2026, 11, 26, 6, 0, tzinfo=timezone.utc)


def body(*, complete=False, at='2026-11-26T06:00:00+00:00'):
    timeline = copy.deepcopy(TIMELINE)
    timeline.update(run='0123456789abcdef', complete=complete)
    timeline.pop('live', None)
    if not complete:
        timeline['events'] = timeline['events'][:2]
        timeline['end'] = 3
    return {'updatedAt': at, 'timeline': timeline}


def test_a_lab_page_follows_a_running_review_and_reports_outages(browser):
    current = [body()]
    context, page, errors = open_panel(browser, timeline=TIMELINE, remote=lambda: current[0], now=NOW)
    root = page.locator('#pnLive')
    page.wait_for_function("document.querySelector('#pnLive').dataset.connection === 'live'")
    assert root.get_attribute('data-mode') == 'live'
    assert root.locator('.pn-line').count() == 2
    assert '5초' in root.inner_text()
    current[0] = False
    page.clock.fast_forward(5000)
    page.wait_for_function("document.querySelector('#pnLive').dataset.connection === 'stale'")
    assert '연결 확인 필요' in root.inner_text() and root.locator('.pn-line').count() == 2
    assert root.locator('.pn-term--designer1 .pn-term-status').get_attribute('data-status') == 'paused'
    current[0] = body()
    page.clock.fast_forward(5000)
    page.wait_for_function("document.querySelector('#pnLive').dataset.connection === 'live'")
    assert root.locator('.pn-term--designer1 .pn-term-status').get_attribute('data-status') == 'work'
    # Time advances from the same fixed reference as the synthetic data.
    page.clock.fast_forward(91000)
    page.wait_for_function("document.querySelector('#pnLive').dataset.connection === 'stale'")
    assert '새 진행 기록을 받지 못하고 있어요' in root.inner_text()
    assert errors == []
    context.close()


def test_an_open_replay_switches_to_a_new_run_then_the_finished_review(browser):
    current = [False]
    context, page, errors = open_panel(browser, timeline=TIMELINE, remote=lambda: current[0], now=NOW, lang='en', width=768)
    page.wait_for_function("document.querySelector('#pnLive').dataset.mode === 'replay'")
    current[0] = body()
    page.clock.fast_forward(5000)
    page.wait_for_function("document.querySelector('#pnLive').dataset.mode === 'live'")
    assert 'Live' in page.locator('.pn-live-badge').inner_text()
    current[0] = body(complete=True)
    page.clock.fast_forward(5000)
    page.wait_for_function("document.querySelector('#pnLive').dataset.mode === 'replay'")
    assert page.locator('.pn-live-phase').inner_text() == 'The review is over'
    assert page.locator('.pn-line').count() == len(TIMELINE['events'])
    assert page.locator('.pn-live-badge--on').count() == 0
    assert page.locator('.pn-term--designer1 .pn-term-status').get_attribute('data-status') == 'done'
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert errors == []
    context.close()


def test_parallel_events_inserted_before_existing_lines_are_rebuilt(browser):
    current = [body()]
    context, page, errors = open_panel(browser, remote=lambda: current[0], now=NOW, width=360)
    page.wait_for_function("document.querySelector('#pnLive').dataset.mode === 'live'")
    current[0] = body()
    current[0]['timeline']['events'].insert(1, {'t': 1, 'pane': 'critic', 'kind': 'say', 'text': '증거를 확인해요.'})
    page.clock.fast_forward(5000)
    page.wait_for_function("document.querySelectorAll('#pnLive .pn-line').length === 3")
    assert page.locator('.pn-term--critic .pn-line').inner_text() == '증거를 확인해요.'
    assert page.locator('.pn-term--designer1 .pn-line').count() == 2
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert errors == []
    context.close()


RUN = r"""
const api = require(process.argv[1]);
const input = JSON.parse(process.argv[2]);
const calls = [];
global.fetch = async (url, options) => {
  calls.push({url, method: options.method});
  if (input.fail) throw new Error('SECRET BACKEND ERROR');
  return {ok: true, json: async () => input.body};
};
const res = {headers: {}, statusCode: 0, setHeader(k,v) {this.headers[k]=v;},
  end(body) {console.log(JSON.stringify({status: this.statusCode, headers:this.headers, body:body || '', calls}));}};
api({method:input.method || 'GET', headers:input.headers || {host:'babdoduk-lab.vercel.app'}},res);
"""


def request(**args):
    p = subprocess.run(['node', '-e', RUN, str(ROOT / 'api/panel-live.js'), json.dumps(args)],
                       check=True, capture_output=True, text=True)
    return json.loads(p.stdout)


def test_relay_endpoint_is_read_only_and_fails_closed_outside_lab():
    for host in ('www.babdodukms.com', 'babdoduk.vercel.app', 'preview.vercel.app', '', 'babdoduk-lab.vercel.app.evil'):
        r = request(headers={'host': host, 'x-forwarded-host': 'babdoduk-lab.vercel.app'})
        assert r['status'] == 404 and r['calls'] == []
    for method in ('POST', 'PUT', 'DELETE', 'OPTIONS'):
        r = request(method=method)
        assert r['status'] == 405 and r['headers']['Allow'] == 'GET' and not r['calls']
    assert request(fail=True)['body'] == ''


def test_endpoint_validates_and_projects_only_public_fields():
    b = body()
    b['timeline']['panes'] = relay.live.PANES
    b['private'] = 'NEVER PUBLIC'
    b['timeline']['private'] = 'NEVER PUBLIC'
    b['timeline']['events'][0]['private'] = 'NEVER PUBLIC'
    r = request(body=b)
    assert r['status'] == 200 and 'NEVER PUBLIC' not in r['body']
    assert r['headers']['Cache-Control'] == 'no-store'
    assert '/storage/v1/object/public/panel-live/current.json?v=' in r['calls'][0]['url']
    assert r['calls'][0]['method'] == 'GET'
    for field, value in [('events', []), ('end', -1), ('run', '/home/private'), ('complete', 'yes')]:
        bad = copy.deepcopy(b)
        bad['timeline'][field] = value
        if field == 'events':
            bad['timeline'][field] = [{'t': 0, 'pane': 'unknown', 'kind': 'say', 'text': 'wrong'}]
        assert request(body=bad)['status'] == 503
    assert request(body={'updatedAt': 'invalid', 'timeline': b['timeline']})['status'] == 503


def synthetic_run(path, label='review:designer1', text='아이폰 화면을 볼게요.'):
    path.mkdir(parents=True)
    (path / 'journal.jsonl').write_text(json.dumps({'type': 'started', 'agentId': 'a1', 'label': label, 'phase': 'Review'}))
    (path / 'agent-a1.jsonl').write_text(json.dumps({'type': 'assistant', 'timestamp': NOW.isoformat(),
        'message': {'content': [{'type': 'text', 'text': text}]}}))
    for p in path.iterdir():
        os.utime(p, (NOW.timestamp(), NOW.timestamp()))
    return path


def test_publisher_redacts_private_material_and_never_uploads_raw_logs(tmp_path):
    run = synthetic_run(tmp_path / 'private-location', text='화면 확인 /home/user/private.txt https://private.example/foo a@b.com')
    b = relay.snapshot(run)
    serialized = json.dumps(b, ensure_ascii=False)
    for private in ('/home', 'private.example', 'a@b.com', 'private-location', 'agent-a1'):
        assert private not in serialized
    assert b['updatedAt'] == '2026-11-26T06:00:00.000+00:00'
    assert b['timeline']['complete'] is False
    assert relay.public_text('비밀번호는 hello 입니다') == '작업 내용을 확인하고 있어요.'
    calls = []
    class Backend:
        def publish(self, value):
            calls.append(value)
    relay.publish(Backend(), b)
    assert calls == [b]
    assert request(body=b)['status'] == 200, 'publisher and reader agree on the payload contract'


def test_other_workflows_are_not_selected_and_final_result_marks_completion(tmp_path, monkeypatch):
    panel = synthetic_run(tmp_path / 'p/session/subagents/workflows/wf_panel')
    other = synthetic_run(tmp_path / 'p/session/subagents/workflows/wf_other', label='other:work')
    os.utime(other / 'journal.jsonl', (NOW.timestamp() + 100, NOW.timestamp() + 100))
    monkeypatch.setattr(relay.live, 'PROJECTS', tmp_path)
    assert relay.live.newest_run() == panel
    journal = panel / 'journal.jsonl'
    journal.write_text('\n'.join(json.dumps(r) for r in [
        {'type': 'started', 'agentId': 'a1', 'label': 'critic:final', 'phase': 'Verdict'},
        {'type': 'result', 'agentId': 'a1', 'result': {'overall': '최종 판정을 마쳤어요.', 'verdicts': [], 'top': []}},
    ]))
    assert relay.snapshot(panel)['timeline']['complete'] is True
    # The workflow emits a null result when a reviewer fails (including a usage limit).
    lines = journal.read_text().splitlines()
    journal.write_text(lines[0] + '\n' + json.dumps({'type': 'result', 'agentId': 'a1', 'result': None}))
    failed = relay.live.build(panel)
    assert failed['complete'] is False and failed['state']['critic'] == 'working'
    assert not any(e['kind'] == 'done' for e in failed['events'])


def test_storage_setup_is_bounded_idempotent_and_preserves_unknown_configuration():
    from panel_storage import PanelStorage, StorageError, LIMIT
    calls = []
    class Storage(PanelStorage):
        def request(self, method, path, body=None, **kwargs):
            calls.append((method, path, body, kwargs))
            if len(calls) == 1:
                raise StorageError(404)
            return {'public': True, 'file_size_limit': LIMIT, 'allowed_mime_types': ['application/json']}
    storage = Storage('https://test.invalid', 'fake-key')
    storage.setup()
    assert [c[0] for c in calls] == ['GET', 'POST', 'GET']
    assert calls[1][2] == {'id': 'panel-live', 'name': 'panel-live', 'public': True,
                         'file_size_limit': LIMIT, 'allowed_mime_types': ['application/json']}
    calls.clear()
    storage.request = lambda *a, **kw: {'public': False}
    with pytest.raises(StorageError, match='configuration mismatch'):
        storage.setup()


def test_storage_upload_only_updates_the_dedicated_object():
    from panel_storage import PanelStorage, StorageError, LIMIT
    calls = []
    storage = PanelStorage('https://test.invalid', 'fake-key')
    storage.request = lambda *a, **kw: calls.append((a, kw))
    b = body()
    storage.publish(b)
    assert calls == [(('POST', '/object/panel-live/current.json', b), {'upload': True})]
    with pytest.raises(StorageError, match='too large'):
        storage.publish({'x': 'z' * LIMIT})


def test_usage_limit_status_is_shown_on_lab_with_a_fixed_retry_time(browser):
    b = body()
    b['status'] = {'code': 'rate_limit', 'retryAt': '2026-11-26T19:55:00+09:00'}
    context, page, errors = open_panel(browser, remote=b, now=NOW)
    page.wait_for_function("document.querySelector('#pnLive').dataset.connection === 'limited'")
    assert '사용량 한도 대기' in page.locator('.pn-live-badge').inner_text()
    assert '07:55' in page.locator('.pn-live-phase').inner_text()
    assert page.locator('.pn-live-badge--on').count() == 0
    assert page.locator('.pn-term--designer1 .pn-term-status').get_attribute('data-status') == 'paused'
    assert '지금 진행 중인 평가' not in page.locator('.pn-live-lead').inner_text()
    assert errors == []
    context.close()


def test_failed_runs_are_retryable_and_quota_reset_is_not_a_completed_day(tmp_path):
    import auto_state
    failure = {'api_error': 'usage_limit_reached', 'api_error_type': 'rate_limit_error',
               'result': "You've hit your 5-hour limit · resets 7:50pm (Asia/Seoul)"}
    state = auto_state.failure(failure, NOW)
    assert state == {'code': 'rate_limit', 'retryAt': '2026-11-26T19:55:00+09:00'}
    assert auto_state.failure({'api_error_status': 401}, NOW) == {'code': 'auth_failed'}
    assert auto_state.failure({}, NOW) == {'code': 'failed'}
    result = tmp_path / 'result.json'
    result.write_text(json.dumps(failure))
    assert auto_state.main(['--result', str(result), '--state-dir', str(tmp_path)]) == 75
    assert not (tmp_path / 'ran-on').exists()
    script = (ROOT / 'scripts/panel/auto.sh').read_text()
    assert 'worktree remove' not in script and 'branch -D' not in script
    assert 'worktree add -q --detach' in script
    assert script.index('git push -q') < script.index('echo "$today" > "$STATE/ran-on"')


def test_retry_calendar_uses_korea_time_and_handles_midnight(tmp_path, capsys):
    import auto_state
    state = {'code': 'rate_limit', 'retryAt': '2026-11-26T19:55:00+09:00'}
    (tmp_path / 'status.json').write_text(json.dumps(state))
    assert auto_state.main(['--state-dir', str(tmp_path), '--retry-calendar']) == 0
    assert capsys.readouterr().out.strip() == '2026-11-26 19:55:00 Asia/Seoul'
    failure = {'api_error': 'usage_limit_reached', 'result': 'resets 12:10am (Asia/Seoul)'}
    assert auto_state.failure(failure, NOW)['retryAt'] == '2026-11-27T00:15:00+09:00'


def test_storage_http_upload_uses_backend_auth_and_zero_cache_age(monkeypatch):
    import panel_storage
    requests = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return b'{}'
    def send(request, **kwargs):
        requests.append(request)
        return Response()
    monkeypatch.setattr(panel_storage.urllib.request, 'urlopen', send)
    panel_storage.PanelStorage('https://test.invalid', 'fake-backend-secret').publish({'timeline': {}})
    r = requests[0]
    assert r.full_url == 'https://test.invalid/storage/v1/object/panel-live/current.json'
    assert r.get_header('Authorization') == 'Bearer fake-backend-secret'
    assert r.get_header('X-upsert') == 'true' and r.get_header('Cache-control') == 'max-age=0'
    assert b'fake-backend-secret' not in r.data


def test_a_requested_review_shows_preparing_instead_of_the_old_stopped_run(browser):
    # Owner 2026-11-26: after pressing the button the page said "평가 중" while the old run still showed
    # "연결 확인 필요" and paused reviewers for the ~2 minutes of screen capture.
    state = [{'state': 'running', 'updatedAt': '2026-11-26T06:00:00+00:00', 'requestId': 'a' * 8}]
    current = [body(at='2026-11-26T03:00:00+00:00')]
    context, page, errors = open_panel(browser, timeline=TIMELINE, remote=lambda: current[0], now=NOW,
                                       control=lambda request: (200, state[0]))
    root = page.locator('#pnLive')
    page.wait_for_function("document.querySelector('#pnLive').dataset.connection === 'preparing'")
    assert '평가할 화면을 찍고 있어요' in root.inner_text()
    assert '새 평가를 준비하고 있어요' in root.inner_text()
    assert '연결 확인 필요' not in root.inner_text()
    assert page.locator('.pn-live-badge').inner_text() == '준비 중'
    assert page.locator('.pn-live-badge--on').count() == 0
    assert root.locator('.pn-term--designer1 .pn-term-status').get_attribute('data-status') == 'wait'
    # The first reviewer speaks: a fresh snapshot of a new run replaces the notice.
    fresh = body()
    fresh['timeline']['run'] = 'fedcba9876543210'
    current[0] = fresh
    page.clock.fast_forward(5000)
    page.wait_for_function("document.querySelector('#pnLive').dataset.connection === 'live'")
    assert '평가할 화면을 찍고 있어요' not in root.inner_text()
    # Not running and not requested: an old run is an interrupted connection, as before.
    state[0] = {'state': 'complete', 'updatedAt': '2026-11-26T06:00:00+00:00', 'requestId': 'a' * 8}
    current[0] = body(at='2026-11-26T03:00:00+00:00')
    page.clock.fast_forward(5000)
    page.wait_for_function("document.querySelector('#pnLive').dataset.connection === 'stale'")
    assert errors == []
    context.close()


def test_the_panel_has_one_designer_and_one_developer_and_the_api_still_accepts_older_runs():
    # Owner 2026-11-26: cut from two designers and two developers to one each to save usage.
    assert [p['id'] for p in relay.live.PANES] == ['designer1', 'developer1', 'copy1', 'founder1', 'critic']
    script = (ROOT / 'scripts/panel/workflow.js').read_text(encoding='utf-8')
    assert script.count("run: 1,") == 4 and "run: 2," not in script
    b = body()
    b['timeline']['panes'] = relay.live.PANES
    assert request(body=b)['status'] == 200
    old = copy.deepcopy(b)
    old['timeline']['panes'] = [{'id': i, 'name': i, 'emoji': ''} for i in
                                ('designer1', 'designer2', 'developer1', 'developer2', 'copy1', 'founder1', 'critic')]
    assert request(body=old)['status'] == 200
    odd = copy.deepcopy(b)
    odd['timeline']['panes'] = relay.live.PANES[:4]
    assert request(body=odd)['status'] == 503


def test_the_runner_waits_for_the_background_review_to_finish():
    # 2026-11-26 22:59: headless Claude Code stopped the running review after its default 10 minute wait.
    script = (ROOT / 'scripts/panel/auto.sh').read_text(encoding='utf-8')
    assert 'export CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0' in script
    assert script.index('CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0') < script.index('timeout -k 10')
