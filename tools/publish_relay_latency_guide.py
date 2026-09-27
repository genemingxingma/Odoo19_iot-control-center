"""Append the verified feedback instructions to the existing internal guides."""
import base64
import hashlib
import html
import json
from pathlib import Path
import re
import shlex
import sys

sys.path.insert(0, "D:/Codex/laboratory_management/_deploy/native_pdf_fonts_310_20260901")
from run_release import connect, execute_sudo, read_config

ROOT = Path(__file__).resolve().parents[1]
MARKER = "Relay feedback update 19.0.2.6.1"
REMOTE = r'''
import hashlib, json
from pathlib import Path
from lxml import html
assert env.cr.dbname == 'odoo-26-1-16'
module = env['ir.module.module'].sudo().search([('name','=','iot_control_center')])
assert module.state == 'installed' and module.latest_version == '19.0.2.6.1'
model = env['knowledge.article'].sudo().with_context(tracking_disable=True, mail_notrack=True, mail_create_nosubscribe=True)
articles = model.browse([1183,1184,1185]).exists()
assert len(articles) == 3
assert all(a.active and a.name.startswith('IoT Control Center ') for a in articles)
before = [{'id':a.id,'name':a.name,'body':a.body or ''} for a in articles]
backup = Path(BACKUP)
if not backup.exists():
    with backup.open('x') as handle:
        json.dump(before,handle,ensure_ascii=False)
    backup.chmod(0o600)
for article in articles:
    if MARKER not in (article.body or ''):
        # Append inside the existing document, not after a closing HTML/body.
        body = html.fragment_fromstring(article.body or '', create_parent='div')
        for fragment in html.fragments_fromstring(SECTIONS[str(article.id)]):
            body.append(fragment)
        article.write({'body':html.tostring(body,encoding='unicode')})
env.flush_all()
def visible_text(value):
    return ' '.join(' '.join(html.fromstring(value).itertext()).split())
for article in articles:
    assert MARKER in article.body and visible_text(SECTIONS[str(article.id)]) in visible_text(article.body)
env.cr.commit()
env.invalidate_all()
assert all(visible_text(SECTIONS[str(a.id)]) in visible_text(a.body) for a in articles)
print('RELAY_GUIDES_VERIFIED '+json.dumps({'ids':articles.ids,'version':module.latest_version,'body_sha256':{str(a.id):hashlib.sha256(a.body.encode()).hexdigest() for a in articles}}))
'''


def main():
    stage = sys.argv[1]
    if not re.fullmatch(r"/home/mamingxing/iot-relay-latency-[0-9a-f]{12}", stage):
        raise ValueError("Use the already published, hash-bound stage")
    document = (ROOT / "docs/RELAY_LATENCY_19_0_2_6_1.md").read_text(encoding="utf-8")
    sections = {}
    for article, heading in ((1183, "中文"), (1184, "English"), (1185, "ภาษาไทย")):
        content = document.split("## " + heading + "\n", 1)[1].split("\n## ", 1)[0].strip()
        sections[str(article)] = "<h2>" + MARKER + "</h2>" + "".join(
            "<p>" + html.escape(paragraph.replace("\n", " ")) + "</p>" for paragraph in content.split("\n\n"))
    cfg = read_config()
    client = connect("192.168.10.15", cfg)
    try:
        # Only a matching production receipt permits this supplementary write.
        preflight = "from pathlib import Path; import json,os,pwd; s=Path(" + repr(stage) + "); r=json.loads((s/'production-receipt.json').read_text()); assert r['status']=='published' and r['version']=='19.0.2.6.1'; p=Path('/tmp/iot_relay_guide_" + stage[-12:] + "'); p.mkdir(mode=0o700,exist_ok=True); u=pwd.getpwnam('odoo'); os.chown(p,u.pw_uid,u.pw_gid); os.chmod(p,0o700)"
        code, _ = execute_sudo(client, "python3 -c " + shlex.quote(preflight), cfg["REMOTE_PASSWORD"], 30)
        if code:
            raise RuntimeError("Guide publication requires a successful matching release")
        backup = "/tmp/iot_relay_guide_" + stage[-12:] + "/before.json"
        source = "SECTIONS=" + repr(sections) + "\nMARKER=" + repr(MARKER) + "\nBACKUP=" + repr(backup) + "\n" + REMOTE
        encoded = base64.b64encode(source.encode()).decode()
        command = shlex.join(["/opt/odoo/venv/bin/python3", "/opt/odoo/odoo19/odoo-bin", "shell", "-c",
            "/opt/odoo/config/odoo.conf", "-d", "odoo-26-1-16", "--no-http", "--max-cron-threads=0", "--logfile=/dev/null"])
        pipeline = "printf %s " + shlex.quote(encoded) + " | base64 -d | " + command
        code, output = execute_sudo(client, shlex.join(["systemd-run", "--quiet", "--wait", "--pipe", "--collect", "-p", "User=odoo",
            "-p", "IPAddressDeny=any", "-p", "IPAddressAllow=192.168.10.20", "bash", "-c", pipeline]), cfg["REMOTE_PASSWORD"], 90)
        line = next((line for line in output.splitlines() if line.startswith("RELAY_GUIDES_VERIFIED ")), None)
        if code or not line:
            with client.open_sftp() as sftp:
                with sftp.open(stage + "/guide-diagnostic.log", "w") as handle:
                    handle.write(output)
                sftp.chmod(stage + "/guide-diagnostic.log", 0o600)
            print(json.dumps({"guide_result": "failed", "code": code,
                "source_lines": re.findall(r'File "<(?:stdin|string)>", line (\d+)', output),
                "error_types": re.findall(r"^(\w*Error)(?::|$)", output, re.M)}))
            raise RuntimeError("Guide verification failed; inspect the protected backup, not arbitrary logs")
        receipt = json.loads(line.split(" ", 1)[1])
        # Preserve the original article bodies alongside the release rollback package.
        save = "from pathlib import Path; import json,shutil; s=Path(" + repr(stage) + "); r=json.loads((s/'production-receipt.json').read_text()); p=Path(r['backup'])/'knowledge-before.json'; shutil.copy2(" + repr(backup) + ",p); p.chmod(0o600)"
        code, _ = execute_sudo(client, "python3 -c " + shlex.quote(save), cfg["REMOTE_PASSWORD"], 30)
        assert code == 0
        print(json.dumps(receipt))
    finally:
        client.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
