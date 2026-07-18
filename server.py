#!/usr/bin/env python3
"""Static file server + Yahoo Finance proxy for Les Notes de Laurette."""

from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from urllib.request import urlopen, Request
import json, os, sys

PORT = 8080
SITE_DIR = os.path.dirname(os.path.abspath(__file__))


class ProxyHandler(SimpleHTTPRequestHandler):
    """Serves static files and proxies /api/yahoo requests."""

    def do_GET(self):
        if self.path.startswith('/api/yahoo'):
            self.proxy_yahoo()
        else:
            # Serve static files from site/ directory
            super().do_GET()

    def proxy_yahoo(self):
        qs = parse_qs(urlparse(self.path).query)
        symbol = qs.get('symbol', [''])[0]
        interval = qs.get('interval', ['5m'])[0]
        range_ = qs.get('range', ['1d'])[0]

        if not symbol:
            self.send_json({'error': 'missing symbol'}, 400)
            return

        url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval={interval}&range={range_}'
        req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})

        try:
            with urlopen(req, timeout=10) as resp:
                data = resp.read()
                # Parse and re-serialize to ensure valid JSON
                parsed = json.loads(data)
                self.send_json(parsed)
        except Exception as e:
            self.send_json({'error': str(e)}, 502)

    def send_json(self, data, status=200):
        body = json.dumps(data).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # Suppress default logging to stderr (optional)
    def log_message(self, format, *args):
        pass


if __name__ == '__main__':
    os.chdir(SITE_DIR)
    server = HTTPServer(('0.0.0.0', PORT), ProxyHandler)
    print(f'Serving at http://localhost:{PORT}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
