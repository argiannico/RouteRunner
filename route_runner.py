#!/usr/bin/env python3
"""
RouteRunner - Field sales companion app
GPS tracking, proximity alerts for accounts that haven't bought, route optimization.

Usage:
  python3 route_runner.py

Then open http://localhost:5151 on your laptop or phone (same WiFi).
"""

import http.server
import json
import os
import re
import threading
import time
import urllib.request
import urllib.parse
import webbrowser
import socket

PORT = 5151
DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.expanduser('~/.routerunner_cache.json')

try:
    with open(CACHE_FILE) as f:
        geocache = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    geocache = {}

last_geocode = 0


def save_cache():
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(geocache, f)
    except OSError:
        pass


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


class Handler(http.server.BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path == '/' or self.path == '/index.html':
            self.serve_file('index.html', 'text/html')
        elif self.path == '/manifest.json':
            self.serve_file('manifest.json', 'application/json')
        elif self.path.startswith('/api/fetch-sheet'):
            self.handle_fetch_sheet()
        elif self.path.startswith('/api/geocode'):
            self.handle_geocode()
        else:
            self.send_error(404)

    def serve_file(self, filename, content_type):
        path = os.path.join(DIR, filename)
        try:
            with open(path, 'rb') as f:
                data = f.read()
            self.send_response(200)
            self.send_header('Content-Type', f'{content_type}; charset=utf-8')
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self.send_error(404, f'{filename} not found')

    def handle_fetch_sheet(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        url = params.get('url', [''])[0]

        match = re.search(r'/spreadsheets/d/([a-zA-Z0-9_-]+)', url)
        if not match:
            self.respond_json(400, {'error': 'Invalid Google Sheets URL'})
            return

        sheet_id = match.group(1)
        gid_match = re.search(r'[#&?]gid=(\d+)', url)
        gid = gid_match.group(1) if gid_match else '0'

        export_url = f'https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}'

        try:
            req = urllib.request.Request(export_url, headers={
                'User-Agent': 'RouteRunner/1.0'
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
                text = data.decode('utf-8-sig')
                if text.strip().startswith('<!') or text.strip().startswith('<html'):
                    self.respond_json(403, {
                        'error': 'Sheet not shared. Set sharing to "Anyone with the link" > Viewer.'
                    })
                    return
                self.respond_json(200, {'csv': text})
        except urllib.error.HTTPError as e:
            self.respond_json(e.code, {'error': f'Google returned HTTP {e.code}'})
        except Exception as e:
            self.respond_json(500, {'error': str(e)})

    def handle_geocode(self):
        global last_geocode
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        address = params.get('q', [''])[0]

        if not address:
            self.respond_json(400, {'error': 'No address'})
            return

        cache_key = address.strip().lower()
        if cache_key in geocache:
            self.respond_json(200, geocache[cache_key])
            return

        now = time.time()
        wait = 1.1 - (now - last_geocode)
        if wait > 0:
            time.sleep(wait)
        last_geocode = time.time()

        try:
            encoded = urllib.parse.quote(address)
            nom_url = f'https://nominatim.openstreetmap.org/search?format=json&limit=1&q={encoded}'
            req = urllib.request.Request(nom_url, headers={
                'User-Agent': 'RouteRunner/1.0 (field-sales-tool)'
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                results = json.loads(resp.read())
                if results:
                    result = {
                        'lat': float(results[0]['lat']),
                        'lng': float(results[0]['lon']),
                        'display': results[0].get('display_name', '')
                    }
                    geocache[cache_key] = result
                    save_cache()
                    self.respond_json(200, result)
                else:
                    self.respond_json(404, {'error': f'Not found: {address}'})
        except Exception as e:
            self.respond_json(500, {'error': str(e)})

    def respond_json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


def main():
    server = http.server.HTTPServer(('0.0.0.0', PORT), Handler)
    local_ip = get_local_ip()
    print(f'''
  RouteRunner is running!

  Desktop:  http://localhost:{PORT}
  Phone:    http://{local_ip}:{PORT}  (same WiFi)

  Press Ctrl+C to stop.
''')
    threading.Timer(1.0, lambda: webbrowser.open(f'http://localhost:{PORT}')).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')
        server.shutdown()


if __name__ == '__main__':
    main()
