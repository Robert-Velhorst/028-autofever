"""Explicit TLS-only, single-recipient SMTP adapter for the durable queue.

Final DATA 250 means server acceptance, not inbox delivery. A lost final reply
is uncertain; Message-ID does not make SMTP retries idempotent at the provider.
"""
import ipaddress
import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.policy import SMTP as SMTP_POLICY
from email.utils import formatdate
from urllib.parse import urlsplit

from backend.service import Invalid, SendFailure


def mailbox(value):
    if not isinstance(value, str) or len(value) > 254 or not value.isascii():
        raise Invalid('Unsupported mailbox')
    if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", value):
        raise Invalid('Use a single plain ASCII mailbox')
    local, domain = value.rsplit('@', 1)
    if len(local) > 64 or local.startswith('.') or local.endswith('.') or '..' in local:
        raise Invalid('Unsupported mailbox')
    if any(len(label) > 63 or label.startswith('-') or label.endswith('-') for label in domain.split('.')):
        raise Invalid('Invalid mail domain')
    return local + '@' + domain.lower()


@dataclass(frozen=True, repr=False)
class SMTPConfig:
    host: str
    port: int
    security: str
    username: str
    from_address: str
    help_origin: str
    allowed_recipients: tuple

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise Invalid('Missing or unknown SMTP configuration fields')
        if not isinstance(value['allowed_recipients'], list):
            raise Invalid('Explicit recipient allowlist required')
        return cls(**{**value, 'allowed_recipients': tuple(value['allowed_recipients'])})

    def __post_init__(self):
        if not isinstance(self.host, str) or not 1 <= len(self.host) <= 253 or not self.host.isascii():
            raise Invalid('Invalid SMTP host')
        try:
            ipaddress.ip_address(self.host)
        except ValueError:
            if not re.fullmatch(r'[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*', self.host):
                raise Invalid('Invalid SMTP host') from None
        if type(self.port) is not int or not 1 <= self.port <= 65535 or self.security not in ('implicit_tls', 'starttls'):
            raise Invalid('Choose an explicit TLS mode and port')
        if (not isinstance(self.username, str) or not 1 <= len(self.username) <= 320 or
                not self.username.isascii() or any(ord(c) < 32 or ord(c) == 127 for c in self.username)):
            raise Invalid('Invalid SMTP username')
        object.__setattr__(self, 'from_address', mailbox(self.from_address))
        if not isinstance(self.allowed_recipients, tuple) or not 1 <= len(self.allowed_recipients) <= 1000:
            raise Invalid('Explicit recipient allowlist required')
        allowed = tuple(mailbox(address) for address in self.allowed_recipients)
        if len(set(allowed)) != len(allowed):
            raise Invalid('Duplicate allowlist mailbox')
        object.__setattr__(self, 'allowed_recipients', allowed)
        try:
            parsed = urlsplit(self.help_origin)
            host = parsed.hostname or ''
            if (parsed.scheme != 'https' or not re.fullmatch(r'[a-z0-9-]+(?:\.[a-z0-9-]+)+', host) or
                    self.help_origin != 'https://' + host + (f':{parsed.port}' if parsed.port else '') or
                    re.fullmatch(r'[0-9.]+', host)):
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise Invalid('Use the verified public HTTPS app origin, without path/query/credentials') from None


class SMTPSender:
    channels = ('email',)

    def __init__(self, config, password, *, context=None):
        if not isinstance(config, SMTPConfig):
            raise Invalid('Validated SMTP configuration required')
        if (not isinstance(password, str) or not 1 <= len(password) <= 4096 or
                not password.isascii() or any(ord(c) < 32 or ord(c) == 127 for c in password)):
            raise Invalid('Supply SMTP password privately, not in the configuration file')
        self.config, self._password = config, password
        self.halted, self.retry_after = False, 0
        self.context = context or ssl.create_default_context()
        if (not self.context.check_hostname or self.context.verify_mode != ssl.CERT_REQUIRED or
                self.context.minimum_version < ssl.TLSVersion.TLSv1_2):
            raise Invalid('TLS 1.2+, trusted certificates and hostname verification are required')

    def compose(self, envelope):
        if envelope.get('channel') != 'email' or envelope.get('kind') not in ('illness', 'recovery', 'update'):
            raise Invalid('Unsupported message kind/channel')
        destination = mailbox(envelope.get('destination'))
        if destination not in self.config.allowed_recipients:
            raise Invalid('Recipient is not operator-authorized')
        job = envelope.get('id')
        if (not isinstance(job, str) or not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', job) or
                envelope.get('idempotency_key') != job):
            raise Invalid('Invalid queue identity')
        text = envelope.get('message')
        if not isinstance(text, str) or not text.strip() or len(text) > 10000 or '\x00' in text:
            raise Invalid('Invalid message')
        if envelope['kind'] == 'illness':
            token = envelope.get('action_token')
            if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
                raise Invalid('Valid recipient capability required')
            text += '\n\nLees je persoonlijke bericht en reageer op hulpvragen:\n' + self.config.help_origin + '/help#' + token
            text += '\n\nDeze persoonlijke link geeft toegang tot jouw bericht. Deel hem niet. Je hebt geen account nodig.'
        elif 'action_token' in envelope:
            raise Invalid('Follow-up must not include a recipient capability')
        text += '\n\nVerstuurd via Autofever volgens de ingestelde melding. Dit is geen medische noodhulpdienst.\n'
        message = EmailMessage(policy=SMTP_POLICY)
        message['From'] = 'Autofever <' + self.config.from_address + '>'
        message['To'] = destination
        message['Subject'] = {'illness': 'Bericht via Autofever', 'recovery': 'Herstelbericht via Autofever',
                              'update': 'Update via Autofever'}[envelope['kind']]
        message['Date'] = formatdate(usegmt=True)
        message_id = '<' + job + '@' + self.config.from_address.rsplit('@', 1)[1] + '>'
        message['Message-ID'] = message_id
        message['Auto-Submitted'] = 'auto-generated'
        message.set_content(text, charset='utf-8', cte='quoted-printable')
        return destination, message.as_bytes(), message_id

    @staticmethod
    def expect(code, allowed, *, after_body=False):
        if code in allowed:
            return
        outcome = 'retryable' if 400 <= code <= 499 else 'permanent' if 500 <= code <= 599 else ('uncertain' if after_body else 'permanent')
        raise SendFailure(outcome)

    def __call__(self, envelope):
        self.retry_after = 0
        try:
            destination, data, message_id = self.compose(envelope)
        except (Invalid, ValueError, TypeError, AttributeError):
            raise SendFailure('permanent') from None
        client, body_started, stage = None, False, 'connection'

        def fail(outcome):
            if outcome == 'retryable':
                self.retry_after = 30
            if outcome == 'permanent' and not body_started and stage in ('connection','greeting','tls','auth','sender'):
                self.halted = True
            raise SendFailure(outcome) from None

        try:
            options = dict(host=self.config.host, port=self.config.port, timeout=10, local_hostname='autofever.local')
            if self.config.security == 'implicit_tls':
                client = smtplib.SMTP_SSL(**options, context=self.context)
            else:
                client = smtplib.SMTP(**options)
            stage = 'greeting'
            self.expect(client.ehlo()[0], (250,))
            if self.config.security == 'starttls':
                stage = 'tls'
                client.starttls(context=self.context)  # Missing STARTTLS never falls back to plaintext.
                self.expect(client.ehlo()[0], (250,))
            stage = 'auth'
            client.login(self.config.username, self._password)
            stage = 'sender'
            self.expect(client.mail(self.config.from_address)[0], (250,))
            stage = 'recipient'
            self.expect(client.rcpt(destination)[0], (250, 251))
            stage = 'data'
            self.expect(client.docmd('DATA')[0], (354,))
            # After this point a disconnect/timeout can hide positive acceptance.
            body_started = True
            stuffed = re.sub(br'(?m)^\.', b'..', data)
            client.send(stuffed + (b'' if stuffed.endswith(b'\r\n') else b'\r\n') + b'.\r\n')
            self.expect(client.getreply()[0], (250,), after_body=True)
            return 'smtp-accepted:' + message_id
        except SendFailure as error:
            fail(error.outcome)
        except (ssl.SSLCertVerificationError, smtplib.SMTPNotSupportedError):
            fail('uncertain' if body_started else 'permanent')
        except smtplib.SMTPAuthenticationError as error:
            self.halted = True  # Do not consume the rest of the queue with bad account credentials.
            fail('retryable' if 400 <= error.smtp_code <= 499 else 'permanent')
        except smtplib.SMTPResponseException as error:
            fail('retryable' if 400 <= error.smtp_code <= 499 else 'permanent' if 500 <= error.smtp_code <= 599 else ('uncertain' if body_started else 'permanent'))
        except (OSError, smtplib.SMTPException):
            fail('uncertain' if body_started else 'retryable')
        except Exception:
            fail('uncertain' if body_started else 'permanent')
        finally:
            if client is not None:
                # Failure after positive DATA acceptance cannot retract acceptance.
                try:
                    client.quit()
                except Exception:
                    pass
                try:
                    client.close()
                except Exception:
                    pass
