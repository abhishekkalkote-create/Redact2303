"""specs/05-redaction-pipeline.md Stage 1: "EML/MSG: parse headers/body/attachments into
a Request with child documents (body rendered to PDF)." .eml tests build real RFC822
messages via the stdlib `email` module (no approximation). .msg tests stub
extract_msg.openMsg with a duck-typed object matching its documented Message interface
(subject/sender/to/messageId/body/htmlBody/attachments/close) — the goal is to verify
OUR field-mapping and error-handling, not extract-msg's own OLE binary parsing, which is
that library's job to test."""

from email.message import EmailMessage

import fitz
import pytest

from app.pipeline.email_intake import (
    EmailIntakeError,
    is_eml_mime,
    is_msg_container_mime,
    parse_eml,
    parse_msg,
    render_email_body_to_pdf,
)


def _sample_eml(*, html: bool = False, attachment: bool = True) -> bytes:
    msg = EmailMessage()
    msg["From"] = "requester@example.com"
    msg["To"] = "records@agency.gov"
    msg["Subject"] = "Public records request #99"
    msg["Message-ID"] = "<abc123@example.com>"
    if html:
        msg.set_content("plain fallback")
        msg.add_alternative("<html><body><p>Please provide <b>all</b> incident reports.</p></body></html>", subtype="html")
    else:
        msg.set_content("Please provide all incident reports from January 2026.")
    if attachment:
        msg.add_attachment(b"%PDF-1.4 fake pdf content", maintype="application", subtype="pdf", filename="incident.pdf")
    return msg.as_bytes()


class _FakeAttachment:
    def __init__(self, name: str, data: bytes) -> None:
        self.name = name
        self.data = data


class _FakeMsg:
    def __init__(self, **kwargs) -> None:
        self.subject = kwargs.get("subject", "Subject line")
        self.sender = kwargs.get("sender", "sender@example.com")
        self.to = kwargs.get("to", "recipient@example.com")
        self.messageId = kwargs.get("messageId", "<xyz@example.com>")
        self.body = kwargs.get("body", "Plain text body")
        self.htmlBody = kwargs.get("htmlBody", None)
        self.attachments = kwargs.get("attachments", [])
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _NonEmailMsg:
    """Stands in for an Outlook item type that lacks MessageBase's fields (Appointment,
    Contact, Task, ...) — accessing .subject should raise AttributeError, same as the
    real MSGFile base class."""

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_mime_predicates() -> None:
    assert is_eml_mime("message/rfc822")
    assert not is_eml_mime("application/pdf")
    assert is_msg_container_mime("application/vnd.ms-outlook")
    assert is_msg_container_mime("application/CDFV2")
    assert not is_msg_container_mime("application/pdf")


def test_parse_eml_extracts_headers_body_and_attachment() -> None:
    parsed = parse_eml(_sample_eml())
    assert parsed.subject == "Public records request #99"
    assert parsed.sender == "requester@example.com"
    assert parsed.recipients == "records@agency.gov"
    assert parsed.message_id == "<abc123@example.com>"
    assert "January 2026" in parsed.body_text
    assert len(parsed.attachments) == 1
    filename, data = parsed.attachments[0]
    assert filename == "incident.pdf"
    assert data == b"%PDF-1.4 fake pdf content"


def test_parse_eml_prefers_plain_text_over_html() -> None:
    parsed = parse_eml(_sample_eml(html=True))
    assert parsed.body_text.strip() == "plain fallback"


def test_parse_eml_with_no_attachments() -> None:
    parsed = parse_eml(_sample_eml(attachment=False))
    assert parsed.attachments == []


def test_render_email_body_to_pdf_produces_readable_pdf() -> None:
    parsed = parse_eml(_sample_eml())
    pdf_bytes = render_email_body_to_pdf(parsed)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text = "".join(page.get_text() for page in doc)
    doc.close()
    assert "Public records request #99" in text
    assert "January 2026" in text


def test_parse_msg_maps_fields_and_closes(monkeypatch) -> None:
    fake = _FakeMsg(
        subject="MSG subject", sender="msg-sender@example.com", to="msg-to@example.com",
        attachments=[_FakeAttachment("report.pdf", b"%PDF-1.4 msg attachment")],
    )
    monkeypatch.setattr("extract_msg.openMsg", lambda data, strict=True: fake)

    parsed = parse_msg(b"irrelevant-bytes-for-this-stub")

    assert parsed.subject == "MSG subject"
    assert parsed.sender == "msg-sender@example.com"
    assert parsed.recipients == "msg-to@example.com"
    assert parsed.attachments == [("report.pdf", b"%PDF-1.4 msg attachment")]
    assert fake.closed is True


def test_parse_msg_falls_back_to_html_body_when_plain_is_empty(monkeypatch) -> None:
    fake = _FakeMsg(body="", htmlBody="<p>HTML only <b>body</b></p>")
    monkeypatch.setattr("extract_msg.openMsg", lambda data, strict=True: fake)

    parsed = parse_msg(b"irrelevant")
    assert parsed.body_text == "HTML only body"


def test_parse_msg_raises_on_unsupported_item_type(monkeypatch) -> None:
    non_email = _NonEmailMsg()
    monkeypatch.setattr("extract_msg.openMsg", lambda data, strict=True: non_email)

    with pytest.raises(EmailIntakeError):
        parse_msg(b"irrelevant")
    assert non_email.closed is True


def test_parse_msg_raises_on_malformed_msg_file(monkeypatch) -> None:
    from extract_msg.exceptions import InvalidFileFormatError

    def _raise(data, strict=True):
        raise InvalidFileFormatError("not an OLE file")

    monkeypatch.setattr("extract_msg.openMsg", _raise)

    with pytest.raises(EmailIntakeError):
        parse_msg(b"not a real msg file")
