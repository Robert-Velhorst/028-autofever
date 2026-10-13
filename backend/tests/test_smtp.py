import smtplib
import ssl
import tempfile
import unittest
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import patch

from backend.service import Invalid, SendFailure
from backend.smtp import SMTPConfig, SMTPSender
from backend.worker import load_config


def configuration(**changes):
    value = dict(host='smtp.example.invalid', port=465, security='implicit_tls',
                 username='autofever-test', from_address='sender@example.invalid',
                 help_origin='https://autofever.example.invalid',
                 allowed_recipients=['alice@example.invalid'])
    value.update(changes)
    return SMTPConfig.from_dict(value)


def envelope(**changes):
    value = dict(id='40a2d44f-54bc-4f4a-9b6b-6bc304b02f10', recipient_id='alice',
                 episode_id='0e407e61-9890-4bda-a1b6-3d3024ed33c5', kind='illness',
                 idempotency_key='40a2d44f-54bc-4f4a-9b6b-6bc304b02f10', channel='email',
                 destination='alice@example.invalid', message='Ik ben ziek.\n.Soep graag.\nDankjewel! ☀',
                 action_token='a'*43)
    value.update(changes)
    return value


class FakeSMTP:
    def __init__(self, failure=None, reply=(250,b'accepted'), codes=None):
        self.calls = []
        self.failure, self.reply, self.codes = failure, reply, codes or {}
        self.bytes = b''
    def step(self, name):
        self.calls.append(name)
        if self.failure and self.failure[0] == name:
            raise self.failure[1]
    def ehlo(self): self.step('ehlo'); return self.codes.get('ehlo', (250,b'ok'))
    def starttls(self, **kwargs): self.step('starttls'); return (220,b'ready')
    def login(self, username, password): self.step('login'); return (235,b'ok')
    def mail(self, address): self.step('mail'); return self.codes.get('mail', (250,b'ok'))
    def rcpt(self, address): self.step('rcpt'); return self.codes.get('rcpt', (250,b'ok'))
    def docmd(self, command): self.step(command); return self.codes.get(command, (354,b'ready'))
    def send(self, data): self.step('send'); self.bytes = data
    def getreply(self): self.step('getreply'); return self.reply
    def quit(self): self.step('quit'); return (221,b'bye')
    def close(self): self.calls.append('close')


class SMTPTests(unittest.TestCase):
    def test_example_and_duplicate_configuration_fields(self):
        config = load_config(Path(__file__).parents[1] / 'smtp.example.json')
        self.assertEqual(config.host, 'smtp.example.invalid')
        self.assertEqual(config.allowed_recipients, ('approved-recipient@example.invalid',))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'duplicate.json'
            path.write_text('{"host":"smtp.example.invalid","host":"other.invalid"}', encoding='utf-8')
            with self.assertRaises(Invalid):
                load_config(path)

    def send(self, fake, item=None, config=None):
        with patch('backend.smtp.smtplib.SMTP_SSL', return_value=fake):
            return SMTPSender(config or configuration(), 'private-test-password')(item or envelope())

    def test_single_recipient_mime_private_link_unicode_and_stable_message_id(self):
        smtp = FakeSMTP()
        receipt = self.send(smtp)
        self.assertTrue(receipt.startswith('smtp-accepted:'))
        self.assertEqual(smtp.calls.count('rcpt'), 1)
        self.assertTrue(smtp.bytes.endswith(b'\r\n.\r\n'))
        raw = smtp.bytes[:-3].replace(b'\r\n..', b'\r\n.')
        message = BytesParser(policy=policy.default).parsebytes(raw)
        self.assertEqual(message['To'], 'alice@example.invalid')
        self.assertEqual(message['From'], 'Autofever <sender@example.invalid>')
        self.assertIsNone(message['Cc']); self.assertIsNone(message['Bcc'])
        self.assertIn('https://autofever.example.invalid/help#'+'a'*43, message.get_content())
        self.assertIn('☀', message.get_content())
        self.assertNotIn('private-test-password', str(message))
        self.assertNotIn('a'*43, receipt)
        again = FakeSMTP(); self.send(again)
        self.assertEqual(message['Message-ID'], BytesParser(policy=policy.default).parsebytes(again.bytes[:-3])['Message-ID'])

    def test_recovery_has_no_action_link(self):
        smtp = FakeSMTP()
        item = envelope(kind='recovery'); item.pop('action_token')
        self.send(smtp, item)
        message = BytesParser(policy=policy.default).parsebytes(smtp.bytes[:-3])
        self.assertNotIn('/help#', message.get_content())
        self.assertEqual(message['Subject'], 'Herstelbericht via Autofever')

    def test_update_subject_plain_text_private_recipient_and_no_capability(self):
        smtp = FakeSMTP()
        item = envelope(kind='update',message='Nog een dag rust. <b>Geen HTML</b>')
        item.pop('action_token')
        self.send(smtp,item)
        message = BytesParser(policy=policy.default).parsebytes(smtp.bytes[:-3])
        self.assertEqual(message['Subject'],'Update via Autofever')
        self.assertEqual(message['To'],'alice@example.invalid')
        self.assertIsNone(message['Cc']); self.assertIsNone(message['Bcc'])
        self.assertEqual(message.get_content_type(),'text/plain')
        self.assertIn('<b>Geen HTML</b>',message.get_content())
        self.assertNotIn('/help#',message.get_content())
        with self.assertRaises(SendFailure): self.send(FakeSMTP(),envelope(kind='update'))

    def test_invalid_or_unapproved_envelope_never_connects(self):
        for changes in [dict(destination='bob@example.invalid'), dict(channel='sms'),
                        dict(destination='alice@example.invalid\r\nBcc: stolen@example.invalid'),
                        dict(action_token='invalid'), dict(id='bad\r\nheader'),
                        dict(idempotency_key='not-the-job'), dict(kind='other')]:
            with patch('backend.smtp.smtplib.SMTP_SSL') as connection:
                with self.assertRaises(SendFailure) as raised:
                    SMTPSender(configuration(), 'private')(envelope(**changes))
                self.assertEqual(raised.exception.outcome, 'permanent')
                connection.assert_not_called()

    def test_final_reply_classes_and_unknown_reply(self):
        for code, expected in [(451,'retryable'), (550,'permanent'), (421,'retryable'), (251,'uncertain')]:
            with self.assertRaises(SendFailure) as raised:
                self.send(FakeSMTP(reply=(code,b'sensitive remote diagnostics')))
            self.assertEqual(raised.exception.outcome, expected)
            self.assertNotIn('sensitive', str(raised.exception))

    def test_disconnect_phase_matters(self):
        for stage, expected in [('ehlo','retryable'),('login','retryable'),('mail','retryable'),
                                ('rcpt','retryable'),('DATA','retryable'),('send','uncertain'),('getreply','uncertain')]:
            with self.assertRaises(SendFailure) as raised:
                self.send(FakeSMTP(failure=(stage, smtplib.SMTPServerDisconnected('private diagnostic'))))
            self.assertEqual(raised.exception.outcome, expected)

    def test_definite_pre_body_rejection_never_sends_body(self):
        for stage, code in [('mail',450),('rcpt',550),('DATA',554)]:
            smtp = FakeSMTP(codes={stage:(code,b'rejected')})
            with self.assertRaises(SendFailure) as raised: self.send(smtp)
            self.assertEqual(raised.exception.outcome, 'retryable' if code==450 else 'permanent')
            self.assertNotIn('send',smtp.calls)

    def test_auth_tls_and_cleanup_failures(self):
        for error in [smtplib.SMTPAuthenticationError(535,b'private auth failure'), ssl.SSLCertVerificationError('bad certificate')]:
            with self.assertRaises(SendFailure) as raised: self.send(FakeSMTP(failure=('login',error)))
            self.assertEqual(raised.exception.outcome,'permanent')
        receipt = self.send(FakeSMTP(failure=('quit',OSError('quit connection lost'))))
        self.assertTrue(receipt.startswith('smtp-accepted:'))

    def test_starttls_re_ehlo_precedes_auth(self):
        smtp = FakeSMTP()
        with patch('backend.smtp.smtplib.SMTP',return_value=smtp), patch('backend.smtp.smtplib.SMTP_SSL') as implicit:
            SMTPSender(configuration(port=587,security='starttls'),'private')(envelope())
            self.assertEqual(smtp.calls[:4], ['ehlo','starttls','ehlo','login'])
            implicit.assert_not_called()

    def test_configuration_and_context_fail_closed(self):
        for changes in [dict(host='smtp.example.invalid\r\n'),dict(port=True),dict(security='plain'),
                        dict(help_origin='http://autofever.example.invalid'),dict(help_origin='https://user:pass@host.invalid'),
                        dict(help_origin='https://host.invalid/?token=secret'),dict(allowed_recipients=[]),
                        dict(from_address='sender@example.invalid,other@example.invalid'),dict(verify_tls=False)]:
            with self.assertRaises(Invalid): configuration(**changes)
        insecure=ssl._create_unverified_context()
        with self.assertRaises(Invalid): SMTPSender(configuration(),'private',context=insecure)
        with self.assertRaises(Invalid): SMTPSender(configuration(),'')
