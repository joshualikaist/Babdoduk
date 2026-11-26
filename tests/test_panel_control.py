"""On-demand panel: synthetic auth, private inbox and browser; never start a paid review."""
import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_panel import REPORT, browser, open_panel
from tests.test_panel_relay import NOW, ROOT

sys.path.insert(0, str(ROOT / 'scripts/panel'))
spec = importlib.util.spec_from_file_location('panel_control', ROOT / 'scripts/panel/control.py')
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)
ID = '11111111-1111-4111-8111-111111111111'
TOKEN = 'synthetic.private.access.token.' + 'x' * 40
READY = {'updatedAt': NOW.isoformat(), 'state': 'idle'}
RAW = {**READY, 'upload': '/object/upload/sign/panel-requests/pending.json?token=WRITE_ONLY',
       'uploadExpiresAt': '2026-11-26T08:00:00+00:00'}

RUN = r"""
const api = require(process.argv[1]); const input = JSON.parse(process.argv[2]);
Date.now = () => input.now;
const calls = [];
global.fetch = async (url, options={}) => {
  calls.push({url, ...options, signal: undefined});
  if (url.includes('/auth/v1/user')) return {ok: input.authOk !== false, json: async () => input.user || {id:'owner',app_metadata:{panel_operator:true}}};
  if (options.method === 'PUT') return {ok: input.uploadOk !== false};
  return {ok:true, json:async () => input.control};
};
const res = {headers:{},setHeader(k,v){this.headers[k]=v;},end(body){
  console.log(JSON.stringify({status:this.statusCode,headers:this.headers,body:body || '',calls}));
}};
api({method:input.method || 'GET',body:input.body,headers:input.headers || {
 host:'babdoduk-lab.vercel.app',origin:'https://babdoduk-lab.vercel.app',
 'content-type':'application/json',authorization:'Bearer '+input.token
}},res);
"""


def request(**kw):
    args = dict(now=NOW.timestamp() * 1000, control=copy.deepcopy(RAW), token=TOKEN,
                body={'action': 'start', 'requestId': ID})
    args.update(kw)
    result = subprocess.run(['node', '-e', RUN, str(ROOT / 'api/panel-control.js'), json.dumps(args)],
                            check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def test_api_is_lab_only_and_never_exposes_private_ingress_or_tokens():
    for host in ('www.babdodukms.com', 'preview.vercel.app', 'babdoduk-lab.vercel.app.evil', ''):
        r = request(headers={'host': host, 'x-forwarded-host': 'babdoduk-lab.vercel.app'})
        assert r['status'] == 404 and r['calls'] == []
    r = request()
    assert r['status'] == 200 and json.loads(r['body']) == READY
    assert TOKEN not in r['body'] and 'upload' not in r['body'] and 'WRITE_ONLY' not in r['body']
    assert r['headers']['Cache-Control'] == 'no-store'


def test_start_requires_verified_server_owned_role_and_same_origin():
    assert request(method='POST', token='')['status'] == 401
    for user in ({'id': 'guest', 'user_metadata': {'panel_operator': True}},
                 {'id': 'guest', 'app_metadata': {'panel_operator': 'true'}}):
        r = request(method='POST', user=user)
        assert r['status'] == 403 and len(r['calls']) == 1
    assert request(method='POST', authOk=False)['status'] == 401
    r = request(method='POST', headers={'host': 'babdoduk-lab.vercel.app', 'origin': 'https://evil.invalid',
                                       'content-type': 'application/json', 'authorization': 'Bearer ' + TOKEN})
    assert r['status'] == 403 and r['calls'] == []
    assert request(method='POST', body={'action': 'shell', 'requestId': ID})['status'] == 400


def test_start_only_uploads_a_fixed_private_request_and_waits_for_worker_ack():
    r = request(method='POST')
    assert r['status'] == 202 and json.loads(r['body']) == {'state': 'requested', 'requestId': ID}
    upload = r['calls'][-1]
    assert upload['method'] == 'PUT' and '/storage/v1/object/upload/sign/panel-requests/pending.json?' in upload['url']
    body = json.loads(upload['body'])
    assert set(body) == {'requestId', 'createdAt', 'accessToken'} and body['accessToken'] == TOKEN
    assert TOKEN not in r['body']
    for state, expected in [('running', 409), ('starting', 409), ('publishing', 409), ('rate_limit', 429)]:
        raw = {**RAW, 'state': state, 'retryAt': '2026-11-26T19:55:00+09:00'}
        blocked = request(method='POST', control=raw)
        assert blocked['status'] == expected and len(blocked['calls']) == 2
    assert request(method='POST', control={**RAW, 'upload': 'https://evil.invalid/steal'})['status'] == 503
    assert request(method='POST', control={**RAW, 'updatedAt': '2026-11-25T00:00:00Z'})['status'] == 503


class Storage:
    def __init__(self, pending=None):
        self.pending, self.public = pending, None
        self.deleted = False

    def request(self, method, path, body=None, **kwargs):
        if method == 'GET':
            return self.pending
        if method == 'DELETE':
            self.pending = None
            self.deleted = True
        elif '/upload/sign/' in path:
            return {'url': RAW['upload']}
        else:
            self.public = body


def pending(**kw):
    return {'requestId': ID, 'createdAt': NOW.isoformat(), 'accessToken': TOKEN, **kw}


def test_worker_independently_checks_auth_and_never_replays_a_request(tmp_path):
    storage = Storage(pending())
    starts = []
    c = control.Controller(storage, tmp_path, verify=lambda token: token == TOKEN, busy=lambda: False,
                           start=lambda: starts.append('fixed service only'))
    state = c.tick(NOW.timestamp())
    assert state['state'] == 'starting' and len(starts) == 1 and storage.deleted
    assert TOKEN not in json.dumps(storage.public) and TOKEN not in (tmp_path / 'control-state.json').read_text()
    storage.pending = pending()
    restarted = control.Controller(storage, tmp_path, verify=lambda token: True, busy=lambda: False,
                                   start=lambda: starts.append('duplicate'))
    restarted.tick(NOW.timestamp() + 20)
    assert len(starts) == 1


@pytest.mark.parametrize('case', ['anonymous', 'stale', 'busy', 'limited', 'extra_command'])
def test_worker_rejects_untrusted_stale_duplicate_or_blocked_work(tmp_path, case):
    body = pending()
    if case == 'stale': body['createdAt'] = '2026-11-25T00:00:00Z'
    if case == 'extra_command': body['command'] = 'run anything'
    if case == 'limited':
        control.save(tmp_path / 'status.json', {'code': 'rate_limit', 'retryAt': '2026-11-26T19:55:00+09:00'})
    starts = []
    c = control.Controller(Storage(body), tmp_path, verify=lambda token: case != 'anonymous',
                           busy=lambda: case == 'busy', start=lambda: starts.append(True))
    c.tick(NOW.timestamp())
    assert starts == []


def test_button_only_starts_on_click_and_handles_ack_limit_outage_and_language(browser):
    current = [dict(READY)]
    posts = []
    def endpoint(req):
        if req.method == 'POST':
            posts.append(req.post_data_json)
            return 202, {'state': 'requested', 'requestId': posts[-1]['requestId']}
        return (503, {}) if current[0] is False else (200, current[0])
    context, page, errors = open_panel(browser, control=endpoint, now=NOW, width=360)
    start = page.locator('#pnStart')
    page.wait_for_function("!document.querySelector('#pnStart').disabled")
    assert posts == []
    start.click()
    assert page.locator('#pnControlLogin').is_visible() and posts == []
    page.evaluate("""() => { window.BabdodukAccount = {hasSession:()=>true, client:()=>Promise.resolve({auth:{
      getSession:()=>Promise.resolve({data:{session:{access_token:'synthetic-token'}}})}})}; }""")
    start.click()
    page.wait_for_function("document.querySelector('#pnControl').dataset.state === 'requested'")
    assert len(posts) == 1 and start.is_disabled()
    current[0] = {**READY, 'state': 'running', 'requestId': posts[0]['requestId']}
    page.clock.fast_forward(5000)
    page.wait_for_function("document.querySelector('#pnControl').dataset.state === 'running'")
    assert '평가 중' in start.inner_text() and start.is_disabled()
    report = copy.deepcopy(REPORT)
    report['run']['at'] = '2026-11-26T15:01:00+09:00'
    report['overall'] = '새 평가 결과가 도착했어요.'
    page.route('**/data/panel/latest.json', lambda route: route.fulfill(json=report))
    current[0] = {**READY, 'state': 'complete', 'requestId': posts[0]['requestId']}
    page.clock.fast_forward(5000)
    page.wait_for_function("document.querySelector('.pn-overall').textContent.includes('새 평가 결과')")
    assert start.is_enabled()
    current[0] = {**READY, 'state': 'rate_limit', 'retryAt': '2026-11-26T19:55:00+09:00'}
    page.clock.fast_forward(5000)
    page.wait_for_function("document.querySelector('#pnControl').dataset.state === 'rate_limit'")
    assert '이후에 다시 눌러' in page.locator('#pnControlStatus').inner_text() and start.is_disabled()
    page.locator('#langToggle').click()
    assert 'usage limit' in page.locator('#pnControlStatus').inner_text()
    current[0] = False
    page.clock.fast_forward(5000)
    page.wait_for_function("document.querySelector('#pnControl').dataset.state === 'offline'")
    assert 'Cannot reach' in page.locator('#pnControlStatus').inner_text() and start.is_disabled()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth') and errors == []
    context.close()
