"""Request and static-file boundaries shared by live and offline loopback servers."""
import ipaddress
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit


class LocalOnlyHTTPMixin:
    def parse_request(self):
        if not super().parse_request():
            return False
        port = self.server.server_port
        hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
        origins = {'http://' + host for host in hosts}
        origin = self.headers.get('Origin')
        referer = self.headers.get('Referer')
        try:
            parsed_referer = urlsplit(referer) if referer else None
        except ValueError:
            self.send_error(403, 'Invalid request origin')
            return False
        try:
            local = ipaddress.ip_address(self.client_address[0]).is_loopback
        except ValueError:
            local = False
        allowed = (local and len(self.headers.get_all('Host', [])) == 1
                   and self.headers.get('Host') in hosts
                   and (origin is None or origin in origins)
                   and self.headers.get('Sec-Fetch-Site') != 'cross-site'
                   and (parsed_referer is None or
                        f'{parsed_referer.scheme}://{parsed_referer.netloc}' in origins))
        if not allowed:
            self.close_connection = True
            self.send_error(403, 'Local same-origin request required')
            return False
        try:
            target = urlsplit(self.path)
        except ValueError:
            self.send_error(400, 'Invalid request target')
            return False
        if target.scheme or target.netloc:
            self.send_error(400, 'Relative request target required')
            return False
        return True

    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        super().end_headers()

    def list_directory(self, path):
        self.send_error(404, 'Directory listing disabled')
        return None

    def send_head(self):
        parts = PurePosixPath(unquote(urlsplit(self.path).path)).parts
        directory = Path(self.directory).resolve()
        target = Path(self.translate_path(self.path)).resolve()
        if any(part.startswith('.') for part in parts) or not target.is_relative_to(directory):
            self.send_error(404, 'File not found')
            return None
        return super().send_head()
