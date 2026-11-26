"""The panel's one public, sanitized JSON file. Only the ops backend key uploads it."""
import json
import urllib.error
import urllib.request

BUCKET = 'panel-live'
OBJECT = 'current.json'
LIMIT = 2_000_000


class StorageError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(f'Panel storage unavailable ({code})')


class PanelStorage:
    def __init__(self, url, key):
        self.base = url.rstrip('/') + '/storage/v1'
        self.key = key

    def request(self, method, path, body=None, *, upload=False):
        headers = {'apikey': self.key, 'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json'}
        if upload:
            headers.update({'x-upsert': 'true', 'cache-control': 'max-age=0', 'x-robots-tag': 'noindex'})
        raw = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data=raw, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                data = response.read()
                return json.loads(data) if data else None
        except urllib.error.HTTPError as exc:
            # Some Storage errors use HTTP 400 with a more precise JSON statusCode.
            try:
                code = int(json.loads(exc.read()).get('statusCode', exc.code))
            except (ValueError, TypeError):
                code = exc.code
            raise StorageError(code) from None
        except (OSError, ValueError):
            raise StorageError('transport') from None

    def setup(self):
        try:
            config = self.request('GET', '/bucket/' + BUCKET)
        except StorageError as exc:
            if exc.code != 404:
                raise
            self.request('POST', '/bucket', {'id': BUCKET, 'name': BUCKET, 'public': True,
                                           'file_size_limit': LIMIT, 'allowed_mime_types': ['application/json']})
            config = self.request('GET', '/bucket/' + BUCKET)
        if (not config or config.get('public') is not True or config.get('file_size_limit') != LIMIT
                or config.get('allowed_mime_types') != ['application/json']):
            raise StorageError('configuration mismatch')

    def publish(self, body):
        if len(json.dumps(body, ensure_ascii=False).encode()) > LIMIT:
            raise StorageError('snapshot too large')
        self.request('POST', '/object/' + BUCKET + '/' + OBJECT, body, upload=True)
