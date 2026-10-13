"""Real loopback TLS SMTP conversations; temporary certificates and fake recipients."""
import base64
import contextlib
import datetime
import io
import ipaddress
import json
import socket
import socketserver
import ssl
import tempfile
import threading
import unittest
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from backend.service import Invalid, Store, SendFailure, Denied
from backend.smtp import SMTPSender
from backend.worker import main, run_worker
from backend.tests.test_smtp import configuration, envelope


class TestMailServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def handle_error(self, request, client_address):
        # Expected handshake/disconnect faults never print private protocol data.
        pass


class SMTPHandler(socketserver.StreamRequestHandler):
    def setup(self):
        self.request.settimeout(3)
        self.tls = self.server.security == 'implicit_tls'
        if self.tls:
            self.request = self.server.context.wrap_socket(self.request, server_side=True)
        super().setup()

    def reply(self, data):
        self.wfile.write(data)
        self.wfile.flush()

    def finish(self):
        try:
            super().finish()
        finally:
            # The server owns the original raw socket; this handler owns its TLS wrapper.
            self.request.close()

    def handle(self):
        self.reply(b'220 local.test ESMTP\r\n')
        authenticated = False
        while True:
            line = self.rfile.readline(8192)
            if not line:
                return
            verb = line.split(b' ', 1)[0].strip().upper()
            self.server.verbs.append(verb)
            if verb == b'EHLO':
                self.reply(b'250-local.test\r\n' + (b'250-STARTTLS\r\n' if not self.tls and self.server.advertise_tls else b'') + b'250 AUTH PLAIN\r\n')
            elif verb == b'STARTTLS':
                self.reply(b'220 start TLS\r\n')
                self.rfile.close(); self.wfile.close()
                self.request = self.server.context.wrap_socket(self.request, server_side=True)
                self.connection = self.request
                self.rfile = self.request.makefile('rb'); self.wfile = self.request.makefile('wb')
                self.tls = True
            elif verb == b'AUTH':
                fields = line.strip().split()
                authenticated = len(fields) == 3 and base64.b64decode(fields[2]) == b'\0autofever-test\0private-test-password'
                self.server.auth_tls.append(self.tls)
                self.reply(b'235 authenticated\r\n' if authenticated else b'535 rejected\r\n')
            elif verb == b'MAIL':
                self.reply(b'250 sender ok\r\n' if authenticated else b'530 authentication required\r\n')
            elif verb == b'RCPT':
                self.server.recipients.append(line.strip())
                self.reply(b'250 recipient ok\r\n')
            elif verb == b'DATA':
                self.reply(b'354 send data\r\n')
                lines = []
                while True:
                    chunk = self.rfile.readline(8192)
                    if not chunk: return
                    if chunk == b'.\r\n': break
                    lines.append(chunk[1:] if chunk.startswith(b'..') else chunk)
                self.server.messages.append(b''.join(lines))
                if self.server.final_code is None:
                    self.request.shutdown(socket.SHUT_RDWR)
                    return
                self.reply(str(self.server.final_code).encode() + b' local result\r\n')
                if self.server.close_after_accept:
                    self.request.shutdown(socket.SHUT_RDWR)
                    return
            elif verb == b'QUIT':
                self.reply(b'221 bye\r\n')
                return
            else:
                self.reply(b'500 unknown command\r\n')


class SMTPIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.certs = tempfile.TemporaryDirectory(prefix='autofever-smtp-test-cert-')
        root = Path(cls.certs.name)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Autofever disposable local test')])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1))
                .not_valid_after(now+datetime.timedelta(hours=1))
                .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
                .sign(key, hashes.SHA256()))
        (root/'key.pem').write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        (root/'cert.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        cls.server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        cls.server_context.minimum_version = ssl.TLSVersion.TLSv1_2
        cls.server_context.load_cert_chain(root/'cert.pem', root/'key.pem')
        cls.client_context = ssl.create_default_context(cafile=str(root/'cert.pem'))

    @classmethod
    def tearDownClass(cls):
        cls.certs.cleanup()

    @contextlib.contextmanager
    def server(self, security='implicit_tls', final_code=250, advertise_tls=True, close_after_accept=False):
        with TestMailServer(('127.0.0.1',0), SMTPHandler) as server:
            server.context = self.server_context
            server.security, server.final_code = security, final_code
            server.advertise_tls, server.close_after_accept = advertise_tls, close_after_accept
            server.verbs, server.auth_tls, server.messages, server.recipients = [], [], [], []
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                config = configuration(host='127.0.0.1', port=server.server_address[1], security=security)
                yield server, SMTPSender(config,'private-test-password',context=self.client_context)
            finally:
                server.shutdown(); worker.join(timeout=5)
                self.assertFalse(worker.is_alive())

    def store(self, directory, *, clock=None, sms=False):
        store = Store(Path(directory)/'state.sqlite3', bytes(range(32)), **({'clock': clock} if clock else {}))
        owner = store.create_owner()
        recipients = [{'id':'alice','channel':'email','destination':'alice@example.invalid','message':'Private illness note'}]
        if sms: recipients.insert(0,{'id':'bob','channel':'sms','destination':'+31612345678','message':'SMS only'})
        eid = store.activate(owner,'test',{'recipients':recipients,'tasks':[]},link_ttl=3600)
        return store, owner, eid

    def test_both_tls_modes_send_one_private_message(self):
        for security in ['implicit_tls','starttls']:
            with self.subTest(security=security), self.server(security) as (server,sender):
                self.assertTrue(sender(envelope()).startswith('smtp-accepted:'))
                self.assertEqual(server.auth_tls,[True])
                self.assertEqual(len(server.recipients),1)
                self.assertEqual(len(server.messages),1)
                parsed = BytesParser(policy=policy.default).parsebytes(server.messages[0])
                self.assertIn('\n.Soep graag.',parsed.get_content().replace('\r\n','\n'))
                self.assertIn('☀',parsed.get_content())
                self.assertIn('/help#'+'a'*43,parsed.get_content())
                self.assertIsNone(parsed['Bcc']); self.assertIsNone(parsed['Cc'])

    def test_untrusted_certificate_never_authenticates(self):
        with self.server() as (server,sender):
            untrusted = SMTPSender(sender.config,'private-test-password')
            with self.assertRaises(SendFailure) as result: untrusted(envelope())
            self.assertEqual(result.exception.outcome,'permanent')
            self.assertEqual(server.auth_tls,[]); self.assertEqual(server.messages,[])

    def test_missing_starttls_never_sends_credentials_or_content(self):
        with self.server('starttls',advertise_tls=False) as (server,sender):
            with self.assertRaises(SendFailure) as result: sender(envelope())
            self.assertEqual(result.exception.outcome,'permanent')
            self.assertNotIn(b'AUTH',server.verbs); self.assertEqual(server.messages,[])

    def test_trusted_certificate_still_requires_matching_hostname(self):
        with self.server() as (server,sender):
            config=configuration(host='localhost',port=server.server_address[1])
            mismatch=SMTPSender(config,'private-test-password',context=self.client_context)
            with self.assertRaises(SendFailure) as result: mismatch(envelope())
            self.assertEqual(result.exception.outcome,'permanent')
            self.assertEqual(server.auth_tls,[]); self.assertEqual(server.messages,[])

    def test_wrong_password_is_definite_failure_without_message_body(self):
        with self.server() as (server,sender):
            wrong=SMTPSender(sender.config,'wrong-test-password',context=self.client_context)
            with self.assertRaises(SendFailure) as result: wrong(envelope())
            self.assertEqual(result.exception.outcome,'permanent')
            self.assertEqual(server.auth_tls,[True]); self.assertEqual(server.messages,[])

    def test_lost_final_reply_is_durable_uncertainty_not_retry(self):
        with self.server(final_code=None) as (server,sender), tempfile.TemporaryDirectory() as tmp:
            store,owner,eid = self.store(tmp)
            self.assertEqual(run_worker(store,sender,max_jobs=10),1)
            self.assertEqual(store.episode(owner,eid)['notifications'][0]['status'],'uncertain')
            self.assertEqual(run_worker(Store(store.path,bytes(range(32))),sender),0)
            self.assertEqual(len(server.messages),1)

    def test_final_rejection_retries_later_with_same_message_id(self):
        with self.server(final_code=451) as (server,sender), tempfile.TemporaryDirectory() as tmp:
            clock=[1800000000]
            store,owner,eid = self.store(tmp,clock=lambda:clock[0])
            self.assertEqual(run_worker(store,sender),1)
            self.assertEqual(run_worker(store,sender),0)
            clock[0]+=30; server.final_code=250
            self.assertEqual(run_worker(store,sender),1)
            self.assertEqual(store.episode(owner,eid)['notifications'][0]['status'],'accepted')
            parsed=[BytesParser(policy=policy.default).parsebytes(raw) for raw in server.messages]
            self.assertEqual(len(parsed),2)
            self.assertEqual(parsed[0]['Message-ID'],parsed[1]['Message-ID'])

    def test_quit_disconnect_preserves_acceptance_and_other_channels_are_untouched(self):
        with self.server(close_after_accept=True) as (server,sender), tempfile.TemporaryDirectory() as tmp:
            store,owner,eid = self.store(tmp,sms=True)
            self.assertEqual(run_worker(store,sender,max_jobs=10),1)
            jobs=store.episode(owner,eid)['notifications']
            self.assertEqual([(j['recipient'],j['status'],j['attempts']) for j in jobs],[('bob','queued',0),('alice','accepted',1)])
            self.assertEqual(len(server.messages),1)

    def test_configuration_check_has_no_network_or_queue_effect(self):
        with tempfile.TemporaryDirectory() as tmp:
            store,owner,eid=self.store(tmp)
            path=Path(tmp)/'smtp.json'
            path.write_text(json.dumps(configuration().__dict__),encoding='utf-8')
            before=store.episode(owner,eid)
            with patch.dict('os.environ',{'AUTOFEVER_SMTP_PASSWORD':'private-test-password','AUTOFEVER_STORE_KEY_HEX':bytes(range(32)).hex()}), patch('backend.smtp.smtplib.SMTP_SSL') as connection, contextlib.redirect_stdout(io.StringIO()) as output:
                result=main(['--database',str(store.path),'--smtp-config',str(path),'--check'])
            self.assertEqual(result,0)
            connection.assert_not_called()
            self.assertEqual(before,store.episode(owner,eid))
            self.assertNotIn('private-test-password',output.getvalue())
            self.assertIn('not verified',output.getvalue())
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(['--database',str(store.path),'--smtp-config',str(path)])

    def test_worker_stop_and_invalid_scope_do_not_claim(self):
        with self.server() as (server,sender), tempfile.TemporaryDirectory() as tmp:
            store,owner,eid=self.store(tmp)
            stop=threading.Event();stop.set()
            self.assertEqual(run_worker(store,sender,stop=stop),0)
            with self.assertRaises(Invalid): store.dispatch_one(sender,channels=())
            with self.assertRaises(Invalid): run_worker(store,sender,max_jobs=0)
            self.assertEqual(store.episode(owner,eid)['notifications'][0]['attempts'],0)
            self.assertEqual(server.messages,[])

    def test_send_cli_persists_outcomes_and_reports_account_failure_without_secrets(self):
        for password, expected_code, expected_status in [
                ('private-test-password', 0, 'accepted'), ('wrong-test-password', 3, 'failed')]:
            with self.subTest(status=expected_status), self.server() as (server,sender), tempfile.TemporaryDirectory() as tmp:
                store,owner,eid = self.store(tmp)
                path = Path(tmp) / 'smtp.json'
                path.write_text(json.dumps(sender.config.__dict__), encoding='utf-8')
                output, errors = io.StringIO(), io.StringIO()
                with patch.dict('os.environ', {'AUTOFEVER_SMTP_PASSWORD': password,
                                              'AUTOFEVER_STORE_KEY_HEX': bytes(range(32)).hex()}), \
                        patch('backend.smtp.ssl.create_default_context', return_value=self.client_context), \
                        contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                    result = main(['--database', str(store.path), '--smtp-config', str(path), '--send'])
                self.assertEqual(result, expected_code)
                self.assertEqual(store.episode(owner,eid)['notifications'][0]['status'], expected_status)
                self.assertEqual(len(server.messages), 1 if expected_code == 0 else 0)
                diagnostics = output.getvalue() + errors.getvalue()
                self.assertNotIn(password, diagnostics)
                self.assertNotIn(bytes(range(32)).hex(), diagnostics)
                self.assertNotIn('alice@example.invalid', diagnostics)
                self.assertIn('not delivery confirmation' if expected_code == 0 else 'needs attention', diagnostics)

    def test_recovery_is_a_separate_email_without_reusable_help_link(self):
        with self.server() as (server,sender), tempfile.TemporaryDirectory() as tmp:
            store,owner,eid=self.store(tmp)
            self.assertEqual(run_worker(store,sender),1)
            first=BytesParser(policy=policy.default).parsebytes(server.messages[0])
            token=first.get_content().split('/help#',1)[1].split()[0]
            self.assertEqual(store.recipient(token)['message'],'Private illness note')
            store.close(owner,eid,'recovered','Ik ben weer hersteld.')
            self.assertEqual(run_worker(store,sender),1)
            recovery=BytesParser(policy=policy.default).parsebytes(server.messages[1])
            self.assertIn('Ik ben weer hersteld.',recovery.get_content())
            self.assertNotIn('/help#',recovery.get_content())
            with self.assertRaises(Denied): store.recipient(token)
            self.assertEqual([j['status'] for j in store.episode(owner,eid)['notifications']],['accepted','accepted'])

    def test_queued_update_crosses_real_local_tls_smtp_without_another_helper_link(self):
        with self.server() as (server,sender), tempfile.TemporaryDirectory() as tmp:
            store,owner,eid=self.store(tmp)
            self.assertEqual(run_worker(store,sender),1)
            store.update(owner,eid,'still-ill','Ik neem nog een dag rust.',['alice'])
            self.assertEqual(run_worker(store,sender),1)
            self.assertEqual(len(server.messages),2)
            message=BytesParser(policy=policy.default).parsebytes(server.messages[1])
            self.assertEqual(message['Subject'],'Update via Autofever')
            self.assertEqual(message['To'],'alice@example.invalid')
            self.assertIsNone(message['Cc']); self.assertIsNone(message['Bcc'])
            self.assertIn('Ik neem nog een dag rust.',message.get_content())
            self.assertNotIn('/help#',message.get_content())
            self.assertEqual(store.episode(owner,eid)['notifications'][-1]['status'],'accepted')
            store.update(owner,eid,'still-ill','Ik neem nog een dag rust.',['alice'])
            self.assertEqual(run_worker(store,sender),0)

    def test_bad_account_stops_worker_before_consuming_other_jobs(self):
        with self.server() as (server,sender), tempfile.TemporaryDirectory() as tmp:
            store,owner,eid=self.store(tmp)
            other=store.create_owner()
            other_id=store.activate(other,'other',{'recipients':[{'id':'alice','channel':'email','destination':'alice@example.invalid','message':'Another notification'}],'tasks':[]},link_ttl=3600)
            wrong=SMTPSender(sender.config,'wrong-password',context=self.client_context)
            with self.assertRaises(Invalid): run_worker(store,wrong,max_jobs=10)
            self.assertTrue(wrong.halted)
            self.assertEqual(store.episode(owner,eid)['notifications'][0]['status'],'failed')
            self.assertEqual(store.episode(other,other_id)['notifications'][0]['attempts'],0)
            self.assertEqual(len(server.auth_tls),1)

    def test_temporary_provider_failure_stops_batch_and_throttles_continuous_worker(self):
        with self.server(final_code=451) as (server,sender), tempfile.TemporaryDirectory() as tmp:
            store,owner,eid=self.store(tmp)
            stop=threading.Event()
            with patch.object(stop,'wait',side_effect=lambda _: stop.set()) as wait:
                self.assertEqual(run_worker(store,sender,max_jobs=None,stop=stop),1)
                wait.assert_called_once_with(30)
            self.assertEqual(store.episode(owner,eid)['notifications'][0]['status'],'queued')

    def test_continuous_worker_waits_when_empty_and_stops_gracefully(self):
        with self.server() as (server,sender), tempfile.TemporaryDirectory() as tmp:
            store,owner,eid=self.store(tmp)
            stop=threading.Event()
            with patch.object(stop,'wait',side_effect=lambda _: stop.set()) as wait:
                self.assertEqual(run_worker(store,sender,max_jobs=None,stop=stop,poll_seconds=1),1)
                wait.assert_called_once_with(1)
            self.assertEqual(store.episode(owner,eid)['notifications'][0]['status'],'accepted')


if __name__ == '__main__':
    unittest.main()
