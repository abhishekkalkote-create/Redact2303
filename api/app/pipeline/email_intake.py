"""specs/05-redaction-pipeline.md Stage 1: "EML/MSG: parse headers/body/attachments into
a Request with child documents (body rendered to PDF)." .eml uses the stdlib `email`
module; .msg (Outlook's OLE compound-file format) uses extract-msg — a real, maintained
parser, not an approximation."""

import re
from dataclasses import dataclass, field
from email import message_from_bytes, policy
from typing import Any

import fitz

from app.core.errors import ApiError

EML_MIME_TYPES = {"message/rfc822"}
# libmagic identifies the OLE Compound File container generically — it can't tell a .msg
# apart from a .doc/.xls/.ppt by content alone. The caller disambiguates with the
# filename's .msg extension; extract-msg itself still validates it's actually an Outlook
# message and raises if not, so this isn't "extension trust" for anything security-critical.
MSG_OLE_MIME_TYPES = {
    "application/x-ole-storage", "application/CDFV2", "application/CDFV2-corrupt",
    "application/vnd.ms-outlook",
}


class EmailIntakeError(ApiError):
    def __init__(self, detail: str) -> None:
        super().__init__(422, "Unprocessable Upload", detail)


@dataclass
class ParsedEmail:
    subject: str
    sender: str | None
    recipients: str | None
    message_id: str | None
    body_text: str
    attachments: list[tuple[str, bytes]] = field(default_factory=list)


def is_eml_mime(mime_type: str) -> bool:
    return mime_type in EML_MIME_TYPES


def is_msg_container_mime(mime_type: str) -> bool:
    return mime_type in MSG_OLE_MIME_TYPES


def _html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_eml(data: bytes) -> ParsedEmail:
    try:
        msg = message_from_bytes(data, policy=policy.default)
    except Exception as exc:
        raise EmailIntakeError(f"Malformed .eml file: {exc}") from exc

    body_text = "(no body)"
    body_part = msg.get_body(preferencelist=("plain", "html"))
    if body_part is not None:
        content = body_part.get_content()
        body_text = content if body_part.get_content_type() == "text/plain" else _html_to_text(content)

    attachments: list[tuple[str, bytes]] = []
    for part in msg.iter_attachments():
        filename = part.get_filename() or "attachment"
        payload = part.get_content()
        attachments.append((filename, payload if isinstance(payload, bytes) else payload.encode("utf-8", "ignore")))

    return ParsedEmail(
        subject=msg.get("subject") or "(no subject)",
        sender=msg.get("from"),
        recipients=msg.get("to"),
        message_id=msg.get("message-id"),
        body_text=body_text or "(no body)",
        attachments=attachments,
    )


def parse_msg(data: bytes) -> ParsedEmail:
    import extract_msg
    from extract_msg.exceptions import ExMsgBaseException

    try:
        msg = extract_msg.openMsg(data, strict=True)
    except ExMsgBaseException as exc:
        raise EmailIntakeError(f"Malformed .msg file: {exc}") from exc

    try:
        # openMsg's return type is the generic MSGFile; non-email Outlook items
        # (Appointment, Contact, Task, ...) extend it directly rather than MessageBase
        # and lack these fields — AttributeError here means "not actually an email", not
        # a parsing bug. `Any` sidesteps mypy's static MSGFile-only view for this block.
        email_msg: Any = msg
        try:
            subject, sender, recipients = email_msg.subject, email_msg.sender, email_msg.to
            message_id, body_text, html_body = email_msg.messageId, email_msg.body, email_msg.htmlBody
            raw_attachments = email_msg.attachments
        except AttributeError as exc:
            raise EmailIntakeError(
                f"Unsupported Outlook item type: {type(msg).__name__} (expected an email message)"
            ) from exc

        if not body_text and html_body:
            body_text = _html_to_text(html_body.decode("utf-8", "ignore") if isinstance(html_body, bytes) else html_body)

        attachments: list[tuple[str, bytes]] = []
        for attachment in raw_attachments:
            att_data = getattr(attachment, "data", None)
            if isinstance(att_data, bytes):
                filename = attachment.name or "attachment"
                attachments.append((filename, att_data))

        return ParsedEmail(
            subject=subject or "(no subject)",
            sender=sender,
            recipients=recipients,
            message_id=message_id,
            body_text=body_text or "(no body)",
            attachments=attachments,
        )
    finally:
        msg.close()


def render_email_body_to_pdf(parsed: ParsedEmail) -> bytes:
    lines = [
        f"Subject: {parsed.subject}",
        f"From: {parsed.sender or '(unknown)'}",
        f"To: {parsed.recipients or '(unknown)'}",
        "",
        *parsed.body_text.splitlines(),
    ]

    doc = fitz.open()
    page = doc.new_page()
    y = 72.0
    for line in lines:
        if y > 750:
            page = doc.new_page()
            y = 72.0
        page.insert_text((72, y), line[:110])
        y += 14

    data = doc.tobytes()
    doc.close()
    return data
