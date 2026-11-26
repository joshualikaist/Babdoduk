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
    current[0] = body()
    page.clock.fast_forward(5000)
    page.wait_for_function("document.querySelector('#pnLive').dataset.connection === 'live'")
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
  calls.push({url, method: options.method, body: options.body});
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
    assert r['calls'][0]['url'].endswith('/rest/v1/rpc/panel_live_read')
    assert r['calls'][0]['method'] == 'POST' and r['calls'][0]['body'] == '{}'
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
        def rpc(self, name, args):
            calls.append((name, args))
    relay.publish(Backend(), b)
    assert calls == [('panel_live_publish', {'p_timeline': b['timeline'], 'p_updated_at': b['updatedAt']})]
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
        {'type': 'result', 'agentId': 'a1', 'result': {'overall': '最終 판정을 마쳤어요.'}},
    ]))
    assert relay.snapshot(panel)['timeline']['complete'] is True


def test_backend_proposal_keeps_table_private_and_only_service_role_may_publish():
    sql = (ROOT / 'docs/proposals/panel-live.sql').read_text()
    assert 'PROPOSAL ONLY' in sql
    assert 'enable row level security' in sql
    assert 'revoke all on table public.panel_live_snapshot from public, anon, authenticated' in sql
    assert 'grant execute on function public.panel_live_publish(jsonb, timestamptz) to service_role' in sql
    assert 'where s.updated_at <= excluded.updated_at' in sql
    assert 'grant execute on function public.panel_live_read() to anon, authenticated' in sql
    assert 'security definer set search_path' in sql
