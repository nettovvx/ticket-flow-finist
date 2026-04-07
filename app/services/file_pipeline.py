from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import shutil
import xml.etree.ElementTree as ET
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, func, insert, literal, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.archive import (
    ArchivedDocument,
    ArchivedDocumentEvent,
    ArchivedDocumentLink,
    ArchivedDocumentPayload,
    ArchivedDocumentUserState,
)
from app.models.document import Document, DocumentEvent, DocumentLink, DocumentPayload, DocumentUserState


logger = logging.getLogger(__name__)
MOM_REF_PATTERN = re.compile(r"[MМ][OО][MМ]-\d{7}")
REALIZATION_NS = {"x": "http://www.gridnine.com/export/xml"}
TICKET_SUCCESS_CHECKPOINTS = ("ticket_seen_by_mom", "realization_copied_to_smb")
REALIZATION_RESULT_STATUSES = {
    "archive": {
        "step_status": "success",
        "document_status": "success",
        "message": "Реализация обработана 1С и попала в archive",
        "ticket_message": "Связанная реализация обработана 1С успешно",
        "error_message": None,
    },
    "bad": {
        "step_status": "error",
        "document_status": "error",
        "message": "Реализация попала в папку bad после обработки 1С",
        "ticket_message": "Связанная реализация попала в папку bad после обработки 1С",
        "error_message": "1С поместила реализацию в папку bad",
    },
    "del_bad": {
        "step_status": "error",
        "document_status": "error",
        "message": "Реализация попала в папку del_bad после обработки 1С",
        "ticket_message": "Связанная реализация попала в папку del_bad после обработки 1С",
        "error_message": "1С поместила реализацию в папку del_bad",
    },
    "empty": {
        "step_status": "error",
        "document_status": "error",
        "message": "Реализация попала в папку empty после обработки 1С",
        "ticket_message": "Связанная реализация попала в папку empty после обработки 1С",
        "error_message": "1С поместила реализацию в папку empty",
    },
}


def _safe_float(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp_future_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None

    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        value = value.replace(tzinfo=timezone.utc)

    now = _utc_now()
    return value if value <= now else now


def _parse_ticket_datetime(date_text: str | None, time_text: str | None) -> datetime | None:
    if not date_text:
        return None
    raw_time = time_text or "0000"
    try:
        return _clamp_future_datetime(datetime.strptime(f"{date_text}{raw_time}", "%d%m%Y%H%M").replace(tzinfo=timezone.utc))
    except ValueError:
        return None


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return _clamp_future_datetime(parsed)
    except ValueError:
        return None


def _normalize_mom_ref(value: str | None) -> str | None:
    if not value:
        return None
    match = MOM_REF_PATTERN.search(value)
    if not match:
        return None
    return match.group(0).replace("М", "M").replace("О", "O")


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _file_created_at(path: Path) -> datetime:
    stat = path.stat()
    timestamp = getattr(stat, "st_birthtime", None) or stat.st_mtime
    return _clamp_future_datetime(datetime.fromtimestamp(timestamp, tz=timezone.utc)) or _utc_now()


def _build_unique_destination(path: Path) -> Path:
    base = path.parent / path.stem
    suffix = path.suffix
    counter = 1
    candidate = path
    while candidate.exists():
        candidate = Path(f"{base}__dup{counter}{suffix}")
        counter += 1
    return candidate


def _append_event(
    document: Document,
    *,
    step_code: str,
    status: str,
    message: str,
    occurred_at: datetime | None,
    meta_json: dict | None = None,
) -> None:
    duplicate = next(
        (
            item
            for item in document.events
            if item.step_code == step_code and item.status == status and item.message == message
        ),
        None,
    )
    if duplicate:
        return
    document.events.append(
        DocumentEvent(
            event_type="pipeline",
            step_code=step_code,
            status=status,
            message=message,
            occurred_at=occurred_at,
            meta_json=meta_json,
        )
    )


def _has_step_status(document: Document, step_code: str, status: str) -> bool:
    return any(item.step_code == step_code and item.status == status for item in document.events)


def _latest_step_time(document: Document, step_code: str) -> datetime | None:
    timestamps = [item.occurred_at for item in document.events if item.step_code == step_code and item.occurred_at]
    if not timestamps:
        return None
    return max(timestamps)


def _ensure_link(
    db: Session,
    *,
    from_document_id: str,
    to_document_id: str,
    link_type: str,
    confidence: str,
    reason: str,
) -> None:
    existing = db.scalar(
        select(DocumentLink).where(
            DocumentLink.from_document_id == from_document_id,
            DocumentLink.to_document_id == to_document_id,
            DocumentLink.link_type == link_type,
        )
    )
    if existing:
        return
    db.add(
        DocumentLink(
            from_document_id=from_document_id,
            to_document_id=to_document_id,
            link_type=link_type,
            confidence=confidence,
            reason=reason,
        )
    )


def _select_archive_component_ids(candidate_ids: list[str], link_rows: list[tuple[str, str]], batch_size: int) -> list[str]:
    if not candidate_ids or batch_size <= 0:
        return []

    candidate_set = set(candidate_ids)
    adjacency: dict[str, set[str]] = {item: set() for item in candidate_ids}
    externally_linked: set[str] = set()

    for from_id, to_id in link_rows:
        from_in = from_id in candidate_set
        to_in = to_id in candidate_set
        if from_in and to_in:
            adjacency[from_id].add(to_id)
            adjacency[to_id].add(from_id)
            continue
        if from_in:
            externally_linked.add(from_id)
        if to_in:
            externally_linked.add(to_id)

    visited: set[str] = set()
    ordered_components: list[tuple[int, list[str]]] = []
    index_by_id = {item: index for index, item in enumerate(candidate_ids)}

    for document_id in candidate_ids:
        if document_id in visited:
            continue
        stack = [document_id]
        component: list[str] = []
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            component.append(current)
            stack.extend(adjacency[current] - visited)
        component.sort(key=index_by_id.__getitem__)
        ordered_components.append((index_by_id[component[0]], component))

    selected: list[str] = []
    for _, component in sorted(ordered_components, key=lambda item: item[0]):
        if any(item in externally_linked for item in component):
            continue
        if len(selected) + len(component) > batch_size:
            continue
        selected.extend(component)

    return selected


class FilePipelineService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._task: asyncio.Task | None = None
        self._stopped = asyncio.Event()
        self._stopped.set()
        self._queued_files: dict[str, deque[tuple[Path, tuple[int, int]]]] = {}
        self._processed_files: dict[str, dict[str, tuple[int, int]]] = {}

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stopped.clear()
        self._task = asyncio.create_task(self._run_loop(), name="ticketflow-file-pipeline")

    async def stop(self) -> None:
        if not self._task:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        self._stopped.set()

    async def _run_loop(self) -> None:
        logger.info("File pipeline started")
        while True:
            try:
                await asyncio.to_thread(self._process_once)
            except Exception:
                logger.exception("File pipeline iteration failed")
            await asyncio.sleep(max(1, self.settings.file_scan_interval_sec))

    def _is_stable(self, path: Path) -> bool:
        try:
            age = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
            return age >= max(0, self.settings.file_stable_age_sec)
        except FileNotFoundError:
            return False

    def _file_signature(self, path: Path) -> tuple[int, int]:
        stat = path.stat()
        return stat.st_size, stat.st_mtime_ns

    def _folder_key(self, folder: Path) -> str:
        return str(folder)

    def _queue_folder_candidates(self, folder: Path) -> None:
        folder_key = self._folder_key(folder)
        if self._queued_files.get(folder_key):
            return
        if not folder.exists() or not folder.is_dir():
            return

        known_files = self._processed_files.setdefault(folder_key, {})
        queued = self._queued_files.setdefault(folder_key, deque())
        queued_names = {item[0].name for item in queued}

        for item in folder.iterdir():
            if not item.is_file() or item.suffix.lower() != ".xml":
                continue
            if not self._is_stable(item):
                continue
            try:
                signature = self._file_signature(item)
            except FileNotFoundError:
                continue
            if known_files.get(item.name) == signature or item.name in queued_names:
                continue
            queued.append((item, signature))
            queued_names.add(item.name)

    def _iter_xml_files(self, folder: Path) -> list[Path]:
        self._queue_folder_candidates(folder)
        folder_key = self._folder_key(folder)
        queued = self._queued_files.setdefault(folder_key, deque())
        batch_size = max(1, self.settings.file_scan_batch_size)
        batch: list[Path] = []

        while queued and len(batch) < batch_size:
            path, _ = queued.popleft()
            if not path.exists():
                continue
            batch.append(path)

        return batch

    def _mark_file_processed(self, folder: Path, path: Path) -> None:
        folder_key = self._folder_key(folder)
        try:
            signature = self._file_signature(path)
        except FileNotFoundError:
            return
        self._processed_files.setdefault(folder_key, {})[path.name] = signature

    def _move_file(self, source: Path, destination_dir: Path) -> Path:
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / source.name
        if destination.exists():
            destination = _build_unique_destination(destination)
        return Path(shutil.move(str(source), str(destination)))

    def _ensure_document(self, db: Session, *, doc_type: str, flow_group: str, source_system: str, file_name: str) -> Document:
        document = db.scalar(
            select(Document)
            .where(
                Document.doc_type == doc_type,
                Document.flow_group == flow_group,
                Document.source_system == source_system,
                Document.file_name == file_name,
            )
            .options(selectinload(Document.payload), selectinload(Document.events), selectinload(Document.outgoing_links))
        )
        if document:
            return document
        document = Document(
            doc_type=doc_type,
            flow_group=flow_group,
            source_system=source_system,
            file_name=file_name,
            status="in_progress",
        )
        db.add(document)
        db.flush()
        return document

    def _touch_file_meta(self, document: Document, path: Path) -> None:
        document.file_path = str(path)
        document.file_size = path.stat().st_size
        document.sha256 = _hash_file(path)

    def _backfill_ticket_origin_steps(self, document: Document, occurred_at: datetime | None) -> None:
        _append_event(
            document,
            step_code="sirena_received",
            status="success",
            message="Ticket detected in Sirena",
            occurred_at=occurred_at,
        )
        _append_event(
            document,
            step_code="ticket_copied_to_ftp",
            status="success",
            message="Ticket moved to FTP tickets",
            occurred_at=occurred_at,
        )

    def _apply_realisation_payload(self, document: Document, parsed: dict[str, object], file_name: str) -> None:
        document.title = parsed["number"] or file_name
        document.business_key = parsed["number"]

        payload = self._ensure_payload(document)
        payload.mom_number = parsed["payload"].get("mom_number")
        payload.client_name = parsed["payload"].get("client_name")
        payload.currency = parsed["payload"].get("currency")
        payload.pnr = parsed["payload"].get("pnr")
        payload.document_date = parsed["payload"].get("document_date")
        payload.extra_json = parsed["payload"].get("extra_json")

    def _apply_realisation_result(
        self,
        document: Document,
        *,
        occurred_at: datetime | None,
        result_code: str,
    ) -> dict[str, str | None]:
        result = REALIZATION_RESULT_STATUSES[result_code]
        document.current_step = "realization_copied_to_smb"
        document.status = result["document_status"]
        document.error_message = result["error_message"]
        document.completed_at = occurred_at if result["document_status"] == "success" else None
        _append_event(
            document,
            step_code="realization_copied_to_smb",
            status=result["step_status"],
            message=result["message"],
            occurred_at=occurred_at,
            meta_json={"result_code": result_code},
        )
        return result

    def _ensure_payload(self, document: Document) -> DocumentPayload:
        payload = document.payload
        if payload:
            return payload
        payload = DocumentPayload(document_id=document.id)
        document.payload = payload
        return payload

    def _is_document_archived(
        self,
        db: Session,
        *,
        doc_type: str,
        flow_group: str,
        source_system: str,
        file_name: str,
    ) -> bool:
        archived_id = db.scalar(
            select(ArchivedDocument.id).where(
                ArchivedDocument.doc_type == doc_type,
                ArchivedDocument.flow_group == flow_group,
                ArchivedDocument.source_system == source_system,
                ArchivedDocument.file_name == file_name,
            )
        )
        return archived_id is not None

    def _apply_ticket_payload(self, document: Document, payload_data: dict[str, object]) -> None:
        payload = self._ensure_payload(document)
        payload.passenger_name = payload_data.get("passenger_name")
        payload.ticket_number = payload_data.get("ticket_number")
        payload.exchange_ticket_number = payload_data.get("exchange_ticket_number")
        payload.pnr = payload_data.get("pnr")
        payload.amount = payload_data.get("amount")
        payload.currency = payload_data.get("currency")
        payload.direction = payload_data.get("direction")
        payload.document_date = payload_data.get("document_date")
        payload.extra_json = payload_data.get("extra_json")

        document.title = payload.passenger_name or payload.ticket_number or document.file_name
        document.business_key = payload.pnr or payload.ticket_number

    def _sync_ticket_status(self, ticket: Document) -> None:
        if ticket.status == "error":
            ticket.completed_at = None
            return

        if all(_has_step_status(ticket, step_code, "success") for step_code in TICKET_SUCCESS_CHECKPOINTS):
            ticket.status = "success"
            ticket.current_step = "realization_copied_to_smb"
            ticket.error_message = None
            ticket.completed_at = _latest_step_time(ticket, "realization_copied_to_smb") or _latest_step_time(ticket, "ticket_seen_by_mom") or datetime.now(timezone.utc)
            return

        ticket.status = "in_progress"
        ticket.completed_at = None

    def _parse_ticket_payload(self, path: Path) -> dict[str, object]:
        root = ET.fromstring(path.read_text(encoding="utf-8"))
        ticket_node = root.find("TICKET")
        if ticket_node is None and root.tag == "TICKET":
            ticket_node = root
        if ticket_node is None:
            raise ValueError("Ticket node not found")

        deal_date = ticket_node.findtext("DEALDATE")
        deal_time = ticket_node.findtext("DEALTIME")
        return {
            "passenger_name": ticket_node.findtext("FIO"),
            "ticket_number": ticket_node.findtext("BSONUM"),
            "exchange_ticket_number": ticket_node.findtext("EX_BSONUM"),
            "pnr": ticket_node.findtext("PNR_LAT") or ticket_node.findtext("PNR"),
            "amount": _safe_float(ticket_node.findtext("FARE")),
            "currency": ticket_node.findtext("CURRENCY"),
            "direction": ticket_node.findtext("OPTYPE"),
            "document_date": _parse_ticket_datetime(deal_date, deal_time),
            "extra_json": {
                "op_type": ticket_node.findtext("OPTYPE"),
                "trans_type": ticket_node.findtext("TRANS_TYPE"),
            },
        }

    def _parse_realisation_payload(self, path: Path) -> dict[str, object]:
        root = ET.fromstring(path.read_text(encoding="utf-8"))
        customer = root.find("x:customer/x:shortName/x:item[@locale='ru']", REALIZATION_NS)
        currency = root.find("x:currency", REALIZATION_NS)
        reservations = {
            item.attrib.get("number")
            for item in root.findall(".//x:reservation", REALIZATION_NS)
            if item.attrib.get("number")
        }
        products = [
            item.attrib.get("number")
            for item in root.findall(".//x:product", REALIZATION_NS)
            if item.attrib.get("number")
        ]
        deleted = root.attrib.get("deleted") == "true"

        return {
            "deleted": deleted,
            "number": root.attrib.get("number"),
            "occurred_at": _parse_iso_datetime(root.attrib.get("time")),
            "payload": {
                "mom_number": root.attrib.get("number"),
                "client_name": customer.attrib.get("value") if customer is not None else None,
                "currency": currency.attrib.get("code") if currency is not None else None,
                "pnr": sorted(reservations)[0] if reservations else None,
                "document_date": _parse_iso_datetime(root.attrib.get("date")),
                "extra_json": {"deleted": deleted, "pnrs": sorted(reservations), "product_numbers": products},
            },
            "pnrs": sorted(reservations),
        }

    def _parse_payments(self, path: Path) -> list[dict[str, object]]:
        root = ET.fromstring(path.read_text(encoding="utf-8"))
        data_node = None
        for child in root:
            if child.tag.endswith("Data"):
                data_node = child
                break
        if data_node is None:
            return []

        parsed: list[dict[str, object]] = []
        for node in data_node:
            if node.tag not in {"DocumentObject.ПоступлениеНаРасчетныйСчет", "DocumentObject.СписаниеСРасчетногоСчета"}:
                continue
            direction = "incoming" if "Поступление" in node.tag else "outgoing"
            parsed.append(
                {
                    "direction": direction,
                    "number": node.findtext("Number"),
                    "amount": _safe_float(node.findtext("СуммаДокумента")),
                    "purpose": node.findtext("НазначениеПлатежа"),
                    "mom_ref": _normalize_mom_ref(node.findtext("НазначениеПлатежа")),
                    "operation_type": node.findtext("ВидОперации"),
                }
            )
        return parsed

    def _link_realisation_to_tickets(
        self,
        db: Session,
        realisation: Document,
        pnrs: list[str],
        occurred_at: datetime | None,
        *,
        received_status: str = "success",
        received_message: str | None = None,
        ticket_error_message: str | None = None,
    ) -> None:
        if not pnrs:
            return

        tickets = db.scalars(
            select(Document)
            .join(DocumentPayload, DocumentPayload.document_id == Document.id)
            .where(Document.doc_type == "ticket", DocumentPayload.pnr.in_(pnrs))
            .options(selectinload(Document.events))
        ).all()

        for ticket in tickets:
            _ensure_link(
                db,
                from_document_id=ticket.id,
                to_document_id=realisation.id,
                link_type="ticket_to_realization",
                confidence="high",
                reason="Связь по PNR в авто-конвейере",
            )
            ticket.current_step = "realization_received_from_mom"
            if received_status == "error":
                ticket.status = "error"
                ticket.completed_at = None
                ticket.error_message = "Связанная реализация MOM помечена ошибкой"
                _append_event(
                    ticket,
                    step_code="realization_received_from_mom",
                    status="error",
                    message="Получена ошибочная реализация из MOM",
                    occurred_at=occurred_at,
                )
            else:
                ticket.error_message = None
                _append_event(
                    ticket,
                    step_code="realization_received_from_mom",
                    status="success",
                    message="Найдена связанная реализация по PNR",
                    occurred_at=occurred_at,
                )
                self._sync_ticket_status(ticket)

    def _mark_realisation_copied_for_tickets(
        self,
        db: Session,
        realisation: Document,
        occurred_at: datetime | None,
        *,
        status: str = "success",
        message: str = "Realization moved to 1C",
        ticket_error_message: str | None = None,
        result_code: str | None = None,
    ) -> None:
        ticket_ids = db.scalars(
            select(DocumentLink.from_document_id).where(
                DocumentLink.to_document_id == realisation.id,
                DocumentLink.link_type == "ticket_to_realization",
            )
        ).all()
        if not ticket_ids:
            return

        tickets = db.scalars(
            select(Document)
            .where(Document.id.in_(ticket_ids))
            .options(selectinload(Document.events))
        ).all()

        for ticket in tickets:
            _append_event(
                ticket,
                step_code="realization_copied_to_smb",
                status=status,
                message="Реализация перемещена в каталог 1C",
                occurred_at=occurred_at,
                meta_json={"realization_id": realisation.id, "realization_file_name": realisation.file_name},
            )
            ticket.current_step = "realization_copied_to_smb"
            if status == "error":
                ticket.status = "error"
                ticket.completed_at = None
                ticket.error_message = ticket_error_message or "Linked realization finished with an error in 1C"
                continue
            if ticket.status != "error":
                ticket.error_message = None
            self._sync_ticket_status(ticket)

    def _link_payment_to_realisation(self, db: Session, payment: Document, mom_ref: str) -> None:
        realisation = db.scalar(
            select(Document)
            .join(DocumentPayload, DocumentPayload.document_id == Document.id)
            .where(Document.doc_type == "realization", DocumentPayload.mom_number == mom_ref)
        )
        if not realisation:
            return
        _ensure_link(
            db,
            from_document_id=payment.id,
            to_document_id=realisation.id,
            link_type="payment_to_realization",
            confidence="high",
            reason="Связь по номеру MOM из назначения платежа",
        )

    def _update_ticket_result(self, db: Session, file_path: Path, *, success: bool) -> None:
        occurred_at = _file_created_at(file_path)
        document = self._ensure_document(
            db,
            doc_type="ticket",
            flow_group="tickets",
            source_system="sirena",
            file_name=file_path.name,
        )
        self._touch_file_meta(document, file_path)
        if not document.occurred_at:
            document.occurred_at = occurred_at
        try:
            payload_data = self._parse_ticket_payload(file_path)
            self._apply_ticket_payload(document, payload_data)
        except Exception:
            logger.warning("Unable to parse ticket payload from %s", file_path, exc_info=True)
        self._backfill_ticket_origin_steps(document, document.occurred_at or occurred_at)
        document.current_step = "ticket_seen_by_mom"
        if success:
            if document.status != "error":
                document.error_message = None
            _append_event(
                document,
                step_code="ticket_seen_by_mom",
                status="success",
                message="Билет обработан MOM (файл в processed)",
                occurred_at=_file_created_at(file_path),
            )
            self._sync_ticket_status(document)
        else:
            document.status = "error"
            document.completed_at = None
            document.error_message = "MOM вернул билет в error"
            _append_event(
                document,
                step_code="ticket_seen_by_mom",
                status="error",
                message="Билет попал в FTP error",
                occurred_at=_file_created_at(file_path),
            )

    def _update_payment_result(self, db: Session, file_path: Path, *, success: bool) -> None:
        documents = db.scalars(
            select(Document)
            .where(Document.doc_type == "payment", Document.source_system == "1c", Document.file_name.like(f"{file_path.name}:%"))
            .options(selectinload(Document.events))
        ).all()
        if not documents:
            return

        occurred_at = _file_created_at(file_path)
        for document in documents:
            document.file_path = str(file_path)
            document.current_step = "payment_seen_by_mom"
            if success:
                if document.status != "error":
                    document.status = "success"
                    document.error_message = None
                _append_event(
                    document,
                    step_code="payment_seen_by_mom",
                    status="success",
                    message="Платежка обработана MOM (файл в processed)",
                    occurred_at=occurred_at,
                )
            else:
                document.status = "error"
                document.error_message = "Платежка попала в FTP error"
                _append_event(
                    document,
                    step_code="payment_seen_by_mom",
                    status="error",
                    message="Платежка попала в FTP error",
                    occurred_at=occurred_at,
                )

    def _process_ticket_inbox(self, db: Session) -> None:
        for source_file in self._iter_xml_files(self.settings.ticket_inbox_dir):
            if not self._is_stable(source_file):
                continue

            try:
                moved_file = self._move_file(source_file, self.settings.ftp_tickets_dir)
                occurred_at = _file_created_at(moved_file)
                document = self._ensure_document(
                    db,
                    doc_type="ticket",
                    flow_group="tickets",
                    source_system="sirena",
                    file_name=moved_file.name,
                )
                self._touch_file_meta(document, moved_file)
                document.occurred_at = occurred_at
                document.current_step = "ticket_copied_to_ftp"
                document.status = "in_progress"
                document.completed_at = None
                document.error_message = None

                payload_data = self._parse_ticket_payload(moved_file)
                self._apply_ticket_payload(document, payload_data)

                _append_event(
                    document,
                    step_code="sirena_received",
                    status="success",
                    message="Билет обнаружен в каталоге Sirena",
                    occurred_at=occurred_at,
                )
                _append_event(
                    document,
                    step_code="ticket_copied_to_ftp",
                    status="success",
                    message="Билет перемещен в FTP tickets",
                    occurred_at=occurred_at,
                )
                self._sync_ticket_status(document)
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("Failed to process ticket file: %s", source_file)

    def _process_ticket_results(self, db: Session) -> None:
        for file_path in self._iter_xml_files(self.settings.ftp_tickets_processed_dir):
            try:
                if self._is_document_archived(
                    db,
                    doc_type="ticket",
                    flow_group="tickets",
                    source_system="sirena",
                    file_name=file_path.name,
                ):
                    self._mark_file_processed(self.settings.ftp_tickets_processed_dir, file_path)
                    continue
                self._update_ticket_result(db, file_path, success=True)
                db.commit()
                self._mark_file_processed(self.settings.ftp_tickets_processed_dir, file_path)
            except Exception:
                db.rollback()
                logger.exception("Failed to process ticket processed-file: %s", file_path)

        for file_path in self._iter_xml_files(self.settings.ftp_tickets_error_dir):
            try:
                if self._is_document_archived(
                    db,
                    doc_type="ticket",
                    flow_group="tickets",
                    source_system="sirena",
                    file_name=file_path.name,
                ):
                    self._mark_file_processed(self.settings.ftp_tickets_error_dir, file_path)
                    continue
                self._update_ticket_result(db, file_path, success=False)
                db.commit()
                self._mark_file_processed(self.settings.ftp_tickets_error_dir, file_path)
            except Exception:
                db.rollback()
                logger.exception("Failed to process ticket error-file: %s", file_path)

    def _process_realisations(self, db: Session) -> None:
        for source_file in self._iter_xml_files(self.settings.ftp_realisations_dir):
            if not self._is_stable(source_file):
                continue

            try:
                parsed = self._parse_realisation_payload(source_file)
                occurred_at = parsed["occurred_at"] or _file_created_at(source_file)
                document = self._ensure_document(
                    db,
                    doc_type="realization",
                    flow_group="tickets",
                    source_system="mom",
                    file_name=source_file.name,
                )
                self._touch_file_meta(document, source_file)
                document.occurred_at = occurred_at
                document.current_step = "realization_received_from_mom"
                document.status = "error" if parsed["deleted"] else "success"
                document.error_message = "MOM пометил реализацию как deleted" if parsed["deleted"] else None
                document.title = parsed["number"] or source_file.name
                document.business_key = parsed["number"]

                payload = self._ensure_payload(document)
                payload.mom_number = parsed["payload"].get("mom_number")
                payload.client_name = parsed["payload"].get("client_name")
                payload.currency = parsed["payload"].get("currency")
                payload.pnr = parsed["payload"].get("pnr")
                payload.document_date = parsed["payload"].get("document_date")
                payload.extra_json = parsed["payload"].get("extra_json")

                _append_event(
                    document,
                    step_code="realization_received_from_mom",
                    status="error" if parsed["deleted"] else "success",
                    message="Реализация получена из MOM",
                    occurred_at=occurred_at,
                )

                self._link_realisation_to_tickets(
                    db,
                    document,
                    parsed["pnrs"],
                    occurred_at,
                    received_status="error" if parsed["deleted"] else "success",
                )

                moved_file = self._move_file(source_file, self.settings.onec_realisations_target_dir)
                moved_occurred_at = _file_created_at(moved_file)
                self._touch_file_meta(document, moved_file)
                _append_event(
                    document,
                    step_code="realization_copied_to_smb",
                    status="success",
                    message="Реализация перемещена в каталог 1C",
                    occurred_at=moved_occurred_at,
                )
                if document.status != "error":
                    document.current_step = "realization_copied_to_smb"
                    document.status = "success"
                    self._mark_realisation_copied_for_tickets(db, document, moved_occurred_at)
                db.commit()
                self._mark_file_processed(self.settings.onec_realisations_target_dir, moved_file)
            except Exception:
                db.rollback()
                logger.exception("Failed to process realization file: %s", source_file)

    def _process_existing_onec_realisations(self, db: Session) -> None:
        for file_path in self._iter_xml_files(self.settings.onec_realisations_target_dir):
            if not self._is_stable(file_path):
                continue
            try:
                if self._is_document_archived(
                    db,
                    doc_type="realization",
                    flow_group="tickets",
                    source_system="mom",
                    file_name=file_path.name,
                ):
                    self._mark_file_processed(self.settings.onec_realisations_target_dir, file_path)
                    continue
                parsed = self._parse_realisation_payload(file_path)
                occurred_at = parsed["occurred_at"] or _file_created_at(file_path)
                document = self._ensure_document(
                    db,
                    doc_type="realization",
                    flow_group="tickets",
                    source_system="mom",
                    file_name=file_path.name,
                )
                self._touch_file_meta(document, file_path)
                if not document.occurred_at:
                    document.occurred_at = occurred_at
                document.current_step = "realization_copied_to_smb"
                document.error_message = "MOM пометил реализацию как deleted" if parsed["deleted"] else None
                document.title = parsed["number"] or file_path.name
                document.business_key = parsed["number"]
                if parsed["deleted"]:
                    document.status = "error"
                    document.completed_at = None
                elif document.status != "error":
                    document.status = "success"
                    document.completed_at = occurred_at

                payload = self._ensure_payload(document)
                payload.mom_number = parsed["payload"].get("mom_number")
                payload.client_name = parsed["payload"].get("client_name")
                payload.currency = parsed["payload"].get("currency")
                payload.pnr = parsed["payload"].get("pnr")
                payload.document_date = parsed["payload"].get("document_date")
                payload.extra_json = parsed["payload"].get("extra_json")

                _append_event(
                    document,
                    step_code="realization_received_from_mom",
                    status="error" if parsed["deleted"] else "success",
                    message="Реализация получена из MOM",
                    occurred_at=occurred_at,
                )
                _append_event(
                    document,
                    step_code="realization_copied_to_smb",
                    status="success",
                    message="Реализация перемещена в каталог 1C",
                    occurred_at=occurred_at,
                )

                self._link_realisation_to_tickets(
                    db,
                    document,
                    parsed["pnrs"],
                    occurred_at,
                    received_status="error" if parsed["deleted"] else "success",
                )
                if document.status != "error":
                    self._mark_realisation_copied_for_tickets(db, document, occurred_at)
                db.commit()
                self._mark_file_processed(self.settings.onec_realisations_target_dir, file_path)
            except Exception:
                db.rollback()
                logger.exception("Failed to process existing realization in 1C target: %s", file_path)

    def _process_existing_onec_realisation_results(self, db: Session) -> None:
        result_folders = [
            ("archive", self.settings.onec_realisations_archive_dir),
            ("bad", self.settings.onec_realisations_bad_dir),
            ("del_bad", self.settings.onec_realisations_del_bad_dir),
            ("empty", self.settings.onec_realisations_empty_dir),
        ]

        for result_code, folder in result_folders:
            for file_path in self._iter_xml_files(folder):
                if not self._is_stable(file_path):
                    continue
                try:
                    if self._is_document_archived(
                        db,
                        doc_type="realization",
                        flow_group="tickets",
                        source_system="mom",
                        file_name=file_path.name,
                    ):
                        self._mark_file_processed(folder, file_path)
                        continue
                    parsed = self._parse_realisation_payload(file_path)
                    occurred_at = _file_created_at(file_path)
                    document = self._ensure_document(
                        db,
                        doc_type="realization",
                        flow_group="tickets",
                        source_system="mom",
                        file_name=file_path.name,
                    )
                    self._touch_file_meta(document, file_path)
                    if not document.occurred_at:
                        document.occurred_at = parsed["occurred_at"] or occurred_at
                    self._apply_realisation_payload(document, parsed, file_path.name)
                    _append_event(
                        document,
                        step_code="realization_received_from_mom",
                        status="success",
                        message="Realization received from MOM",
                        occurred_at=document.occurred_at or occurred_at,
                    )

                    result = self._apply_realisation_result(document, occurred_at=occurred_at, result_code=result_code)
                    self._link_realisation_to_tickets(
                        db,
                        document,
                        parsed["pnrs"],
                        document.occurred_at or occurred_at,
                    )
                    self._mark_realisation_copied_for_tickets(
                        db,
                        document,
                        occurred_at,
                        status=result["step_status"] or "success",
                        ticket_error_message=result["error_message"],
                        result_code=result_code,
                    )
                    db.commit()
                    self._mark_file_processed(folder, file_path)
                except Exception:
                    db.rollback()
                    logger.exception("Failed to process realization result-file: %s", file_path)

    def _process_payments(self, db: Session) -> None:
        for source_file in self._iter_xml_files(self.settings.onec_payments_source_dir):
            if not self._is_stable(source_file):
                continue

            try:
                moved_file = self._move_file(source_file, self.settings.ftp_payments_dir)
                occurred_at = _file_created_at(moved_file)
                entries = self._parse_payments(moved_file)
                if not entries:
                    entries = [{"number": "unknown", "amount": None, "purpose": None, "mom_ref": None, "direction": None, "operation_type": None}]

                for index, item in enumerate(entries):
                    number = item.get("number") or f"unknown_{index + 1}"
                    document = self._ensure_document(
                        db,
                        doc_type="payment",
                        flow_group="payments",
                        source_system="1c",
                        file_name=f"{moved_file.name}:{number}",
                    )
                    document.occurred_at = occurred_at
                    document.current_step = "payment_copied_to_ftp"
                    document.status = "in_progress"
                    document.error_message = None
                    document.title = f"{number} / {item.get('direction') or 'unknown'}"
                    document.business_key = number
                    self._touch_file_meta(document, moved_file)

                    payload = self._ensure_payload(document)
                    payload.payment_number = item.get("number")
                    payload.payment_purpose = item.get("purpose")
                    payload.mom_number = item.get("mom_ref")
                    payload.amount = item.get("amount")
                    payload.direction = item.get("direction")
                    payload.document_date = occurred_at
                    payload.extra_json = {"operation_type": item.get("operation_type")}

                    _append_event(
                        document,
                        step_code="payment_received_from_1c",
                        status="success",
                        message="Платежка обнаружена в 1C-каталоге",
                        occurred_at=occurred_at,
                    )
                    _append_event(
                        document,
                        step_code="payment_copied_to_ftp",
                        status="success",
                        message="Платежка перемещена в FTP payments",
                        occurred_at=occurred_at,
                    )
                    mom_ref = item.get("mom_ref")
                    if mom_ref:
                        self._link_payment_to_realisation(db, document, mom_ref)

                db.commit()
            except Exception:
                db.rollback()
                logger.exception("Failed to process payment file: %s", source_file)

    def _process_payment_results(self, db: Session) -> None:
        for file_path in self._iter_xml_files(self.settings.ftp_payments_processed_dir):
            try:
                self._update_payment_result(db, file_path, success=True)
                db.commit()
                self._mark_file_processed(self.settings.ftp_payments_processed_dir, file_path)
            except Exception:
                db.rollback()
                logger.exception("Failed to process payment processed-file: %s", file_path)

        for file_path in self._iter_xml_files(self.settings.ftp_payments_error_dir):
            try:
                self._update_payment_result(db, file_path, success=False)
                db.commit()
                self._mark_file_processed(self.settings.ftp_payments_error_dir, file_path)
            except Exception:
                db.rollback()
                logger.exception("Failed to process payment error-file: %s", file_path)

    def _archive_success_documents(self, db: Session) -> int:
        batch_size = max(1, self.settings.archive_batch_size)
        cutoff = _utc_now() - timedelta(seconds=max(0, self.settings.archive_success_delay_sec))
        scan_limit = max(batch_size * 8, batch_size)

        candidate_ids = db.scalars(
            select(Document.id)
            .where(
                Document.status == "success",
                func.coalesce(Document.completed_at, Document.updated_at) <= cutoff,
            )
            .order_by(func.coalesce(Document.completed_at, Document.updated_at).asc(), Document.created_at.asc())
            .limit(scan_limit)
        ).all()
        if not candidate_ids:
            return 0

        link_rows = [
            (row.from_document_id, row.to_document_id)
            for row in db.execute(
                select(DocumentLink.from_document_id, DocumentLink.to_document_id).where(
                    or_(
                        DocumentLink.from_document_id.in_(candidate_ids),
                        DocumentLink.to_document_id.in_(candidate_ids),
                    )
                )
            ).all()
        ]
        archive_ids = _select_archive_component_ids(candidate_ids, link_rows, batch_size)
        if not archive_ids:
            return 0

        archived_at = _utc_now()

        db.execute(
            insert(ArchivedDocument).from_select(
                [
                    "doc_type",
                    "flow_group",
                    "source_system",
                    "status",
                    "current_step",
                    "title",
                    "file_name",
                    "file_path",
                    "file_size",
                    "sha256",
                    "business_key",
                    "error_message",
                    "occurred_at",
                    "completed_at",
                    "archived_at",
                    "created_at",
                    "updated_at",
                    "id",
                ],
                select(
                    Document.doc_type,
                    Document.flow_group,
                    Document.source_system,
                    Document.status,
                    Document.current_step,
                    Document.title,
                    Document.file_name,
                    Document.file_path,
                    Document.file_size,
                    Document.sha256,
                    Document.business_key,
                    Document.error_message,
                    Document.occurred_at,
                    Document.completed_at,
                    literal(archived_at),
                    Document.created_at,
                    Document.updated_at,
                    Document.id,
                ).where(Document.id.in_(archive_ids)),
            )
        )
        db.execute(
            insert(ArchivedDocumentPayload).from_select(
                [
                    "document_id",
                    "passenger_name",
                    "ticket_number",
                    "exchange_ticket_number",
                    "pnr",
                    "mom_number",
                    "payment_number",
                    "payment_purpose",
                    "client_name",
                    "amount",
                    "currency",
                    "direction",
                    "document_date",
                    "route",
                    "extra_json",
                    "archived_at",
                    "created_at",
                    "updated_at",
                    "id",
                ],
                select(
                    DocumentPayload.document_id,
                    DocumentPayload.passenger_name,
                    DocumentPayload.ticket_number,
                    DocumentPayload.exchange_ticket_number,
                    DocumentPayload.pnr,
                    DocumentPayload.mom_number,
                    DocumentPayload.payment_number,
                    DocumentPayload.payment_purpose,
                    DocumentPayload.client_name,
                    DocumentPayload.amount,
                    DocumentPayload.currency,
                    DocumentPayload.direction,
                    DocumentPayload.document_date,
                    DocumentPayload.route,
                    DocumentPayload.extra_json,
                    literal(archived_at),
                    DocumentPayload.created_at,
                    DocumentPayload.updated_at,
                    DocumentPayload.id,
                ).where(DocumentPayload.document_id.in_(archive_ids)),
            )
        )
        db.execute(
            insert(ArchivedDocumentEvent).from_select(
                [
                    "document_id",
                    "event_type",
                    "step_code",
                    "status",
                    "message",
                    "occurred_at",
                    "duration_ms",
                    "meta_json",
                    "archived_at",
                    "created_at",
                    "updated_at",
                    "id",
                ],
                select(
                    DocumentEvent.document_id,
                    DocumentEvent.event_type,
                    DocumentEvent.step_code,
                    DocumentEvent.status,
                    DocumentEvent.message,
                    DocumentEvent.occurred_at,
                    DocumentEvent.duration_ms,
                    DocumentEvent.meta_json,
                    literal(archived_at),
                    DocumentEvent.created_at,
                    DocumentEvent.updated_at,
                    DocumentEvent.id,
                ).where(DocumentEvent.document_id.in_(archive_ids)),
            )
        )
        db.execute(
            insert(ArchivedDocumentUserState).from_select(
                [
                    "document_id",
                    "user_id",
                    "is_viewed",
                    "is_hidden",
                    "hidden_reason",
                    "viewed_at",
                    "hidden_at",
                    "archived_at",
                    "created_at",
                    "updated_at",
                    "id",
                ],
                select(
                    DocumentUserState.document_id,
                    DocumentUserState.user_id,
                    DocumentUserState.is_viewed,
                    DocumentUserState.is_hidden,
                    DocumentUserState.hidden_reason,
                    DocumentUserState.viewed_at,
                    DocumentUserState.hidden_at,
                    literal(archived_at),
                    DocumentUserState.created_at,
                    DocumentUserState.updated_at,
                    DocumentUserState.id,
                ).where(DocumentUserState.document_id.in_(archive_ids)),
            )
        )
        db.execute(
            insert(ArchivedDocumentLink).from_select(
                [
                    "from_document_id",
                    "to_document_id",
                    "link_type",
                    "confidence",
                    "reason",
                    "archived_at",
                    "created_at",
                    "updated_at",
                    "id",
                ],
                select(
                    DocumentLink.from_document_id,
                    DocumentLink.to_document_id,
                    DocumentLink.link_type,
                    DocumentLink.confidence,
                    DocumentLink.reason,
                    literal(archived_at),
                    DocumentLink.created_at,
                    DocumentLink.updated_at,
                    DocumentLink.id,
                ).where(
                    DocumentLink.from_document_id.in_(archive_ids),
                    DocumentLink.to_document_id.in_(archive_ids),
                ),
            )
        )

        db.execute(
            delete(DocumentLink).where(
                DocumentLink.from_document_id.in_(archive_ids),
                DocumentLink.to_document_id.in_(archive_ids),
            )
        )
        db.execute(delete(DocumentEvent).where(DocumentEvent.document_id.in_(archive_ids)))
        db.execute(delete(DocumentUserState).where(DocumentUserState.document_id.in_(archive_ids)))
        db.execute(delete(DocumentPayload).where(DocumentPayload.document_id.in_(archive_ids)))
        db.execute(delete(Document).where(Document.id.in_(archive_ids)))
        db.commit()

        logger.info("Archived %s successful documents", len(archive_ids))
        return len(archive_ids)

    def _process_once(self) -> None:
        with SessionLocal() as db:
            self._process_ticket_inbox(db)
            self._process_ticket_results(db)
            self._process_existing_onec_realisations(db)
            self._process_realisations(db)
            self._process_existing_onec_realisation_results(db)
            self._process_payments(db)
            self._process_payment_results(db)
            try:
                self._archive_success_documents(db)
            except Exception:
                db.rollback()
                logger.exception("Failed to archive successful documents")
