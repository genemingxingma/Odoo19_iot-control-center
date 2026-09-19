"""Temporary TLS-to-SSH proxy for one device and one isolated Odoo database.

Only the catalog and telemetry routes are exposed. No web login, production
database, public listener, arbitrary destination, or credential logging.
"""
import argparse
import hmac
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import ssl
import sys

sys.path.insert(0,r'D:/Codex/laboratory_management/_deploy/native_pdf_fonts_310_20260901')
from run_release import connect, read_config

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--private-dir',type=Path,required=True)
    p.add_argument('--bind',required=True)
    a=p.parse_args()
    assert a.bind=='192.168.20.200'
    config=json.loads((a.private_dir/'data/network.json').read_text())
    base='/iot_control_center/instrument/'+config['uid']
    client=connect('192.168.10.15',read_config())
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self): self.forward()
        def do_POST(self): self.forward()
        def forward(self):
            if self.path not in (base+'/programs',base+'/exchange') or not hmac.compare_digest(
                self.headers.get('X-Instrument-Token',''),config['token']):
                self.send_error(403); return
            if (self.command=='GET') != self.path.endswith('/programs'):
                self.send_error(405); return
            size=int(self.headers.get('Content-Length','0'))
            if not 0<=size<=32768: self.send_error(413); return
            body=self.rfile.read(size)
            connection=http.client.HTTPConnection('127.0.0.1',18769,timeout=12)
            try:
                connection.sock=client.get_transport().open_channel('direct-tcpip',('127.0.0.1',18769),('127.0.0.1',0),timeout=12)
                connection.sock.settimeout(12)
                headers={'X-Instrument-Token':config['token'],'Content-Type':'application/json','Host':'localhost',
                         'Connection':'close'}
                if 'If-None-Match' in self.headers: headers['If-None-Match']=self.headers['If-None-Match']
                connection.request(self.command,self.path,body=body,headers=headers)
                reply=connection.getresponse(); content=reply.read(32769)
                if len(content)>32768: raise RuntimeError('Oversized isolated reply')
                self.send_response(reply.status)
                for name in ('Content-Type','ETag','X-Catalog-SHA256'):
                    value=reply.getheader(name)
                    if value: self.send_header(name,value)
                self.send_header('Content-Length',str(len(content))); self.send_header('Connection','close')
                self.end_headers(); self.wfile.write(content)
                print('ISOLATED_REQUEST '+json.dumps({'route':self.path.rsplit('/',1)[-1],
                    'status':reply.status,'bytes':len(content)}),flush=True)
            except Exception:
                self.send_error(503)
            finally: connection.close()
    server=ThreadingHTTPServer((a.bind,18443),Handler)
    server.daemon_threads=True
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(a.private_dir/'proxy-cert.pem',a.private_dir/'proxy-key.pem')
    server.socket=context.wrap_socket(server.socket,server_side=True)
    print('ISOLATED_TLS_PROXY_READY',flush=True)
    try: server.serve_forever()
    finally: server.server_close(); client.close()

if __name__=='__main__': main()
