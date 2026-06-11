"""Migrations-Engine: überträgt Freshdesk-Daten in eine bestehende Zammad-Instanz.

Bewusst Qt-frei gehalten, damit sie ohne GUI getestet werden kann.
Fortschritt und Log laufen über Callbacks, Abbruch über cancel().

Duplikat-Strategie:
- Organisationen: exakte Namenssuche in Zammad
- Benutzer: exakte E-Mail-Suche in Zammad
- Tickets: lokale Zustandsdatei (migration_state.json) + Tag "fd-<id>" in Zammad

Artikel werden grundsätzlich als Typ "note" angelegt, damit Zammad in der
produktiven Instanz keine E-Mails an Kunden verschickt.
"""
import base64
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("migrator.engine")

SYNTH_EMAIL_DOMAIN = "freshdesk-import.invalid"


class MigrationCancelled(Exception):
    """Wird intern geworfen, wenn der Benutzer abbricht."""


@dataclass
class MigrationOptions:
    migrate_organizations: bool = True
    migrate_contacts: bool = True
    migrate_agents: bool = True
    create_agents: bool = False  # False: nur per E-Mail auf bestehende Agents mappen
    migrate_tickets: bool = True
    group_id: int | None = None
    status_map: dict = field(default_factory=dict)    # FD-Status-ID -> Zammad state_id
    priority_map: dict = field(default_factory=dict)  # FD-Prio-ID -> Zammad priority_id
    fallback_state_id: int | None = None
    fallback_priority_id: int | None = None
    dry_run: bool = False


class MigrationState:
    """Lokaler Zustand für Wiederaufnahme: Freshdesk-ID -> Zammad-ID."""

    def __init__(self, path):
        self.path = Path(path)
        self.data = {"organizations": {}, "users": {}, "tickets": {}}
        if self.path.exists():
            try:
                self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                log.warning("Konnte %s nicht lesen – starte mit leerem Zustand", self.path)

    def get(self, kind: str, fd_id) -> int | None:
        return self.data.get(kind, {}).get(str(fd_id))

    def set(self, kind: str, fd_id, zammad_id) -> None:
        self.data.setdefault(kind, {})[str(fd_id)] = zammad_id
        self.save()

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")


class MigrationEngine:
    def __init__(self, freshdesk, zammad, options: MigrationOptions,
                 state_path, failed_path, progress_cb=None, log_cb=None):
        self.freshdesk = freshdesk
        self.zammad = zammad
        self.options = options
        self.state = MigrationState(state_path)
        self.failed_path = Path(failed_path)
        self.progress_cb = progress_cb
        self.log_cb = log_cb
        self._cancelled = False
        self._done = 0
        self._total = 0
        self.failed_records: list[dict] = []
        self.summary = {"created": 0, "skipped": 0, "failed": 0, "cancelled": False}

    # ---------- Infrastruktur ----------

    def cancel(self) -> None:
        self._cancelled = True

    def _check_cancel(self) -> None:
        if self._cancelled:
            raise MigrationCancelled()

    def _log(self, msg: str) -> None:
        log.info(msg)
        if self.log_cb:
            self.log_cb(msg)

    def _step(self, msg: str = "") -> None:
        self._done += 1
        if self.progress_cb:
            self.progress_cb(self._done, self._total, msg)

    def _fail(self, kind: str, fd_id, error: Exception) -> None:
        self.summary["failed"] += 1
        entry = {
            "type": kind,
            "freshdesk_id": fd_id,
            "error": str(error),
            "time": datetime.now(timezone.utc).isoformat(),
        }
        self.failed_records.append(entry)
        log.error("Fehler bei %s fd-%s: %s", kind, fd_id, error)
        if self.log_cb:
            self.log_cb(f"FEHLER bei {kind} fd-{fd_id}: {error}")

    def _write_failed(self) -> None:
        if self.options.dry_run:
            return
        self.failed_path.write_text(
            json.dumps(self.failed_records, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ---------- Ablauf ----------

    def run(self, data: dict) -> dict:
        opt = self.options
        prefix = "[DRY RUN] " if opt.dry_run else ""
        plan = []
        if opt.migrate_organizations:
            plan.append(("organization", data.get("companies", []), self._migrate_organization))
        if opt.migrate_contacts:
            plan.append(("contact", data.get("contacts", []), self._migrate_contact))
        if opt.migrate_agents:
            plan.append(("agent", data.get("agents", []), self._migrate_agent))
        if opt.migrate_tickets:
            plan.append(("ticket", data.get("tickets", []), self._migrate_ticket))

        self._total = sum(len(records) for _, records, _ in plan)
        self._log(f"{prefix}Starte Migration: {self._total} Datensätze")

        try:
            for kind, records, handler in plan:
                if not records:
                    continue
                self._log(f"{prefix}--- {kind}: {len(records)} Datensätze ---")
                for record in records:
                    self._check_cancel()
                    try:
                        handler(record)
                    except MigrationCancelled:
                        raise
                    except Exception as e:  # noqa: BLE001
                        self._fail(kind, record.get("id"), e)
                    self._step(kind)
        except MigrationCancelled:
            self.summary["cancelled"] = True
            self._log("Migration abgebrochen.")

        self._write_failed()
        self._log(
            f"{prefix}Fertig: {self.summary['created']} angelegt, "
            f"{self.summary['skipped']} übersprungen, {self.summary['failed']} fehlgeschlagen"
        )
        return self.summary

    # ---------- Organisationen ----------

    def _migrate_organization(self, company: dict) -> None:
        fd_id = company["id"]
        name = (company.get("name") or "").strip()
        if self.state.get("organizations", fd_id):
            self.summary["skipped"] += 1
            return
        existing = self.zammad.search_organization_by_name(name)
        if existing:
            if not self.options.dry_run:
                self.state.set("organizations", fd_id, existing["id"])
            self.summary["skipped"] += 1
            self._log(f"Organisation '{name}' existiert bereits (Zammad #{existing['id']})")
            return
        if self.options.dry_run:
            self.summary["created"] += 1
            self._log(f"[DRY RUN] Organisation '{name}' würde angelegt")
            return
        org = self.zammad.create_organization({
            "name": name,
            "note": company.get("description") or "",
        })
        self.state.set("organizations", fd_id, org["id"])
        self.summary["created"] += 1
        self._log(f"Organisation '{name}' angelegt (Zammad #{org['id']})")

    # ---------- Kontakte / Benutzer ----------

    @staticmethod
    def _split_name(name: str | None) -> tuple[str, str]:
        parts = (name or "").strip().split()
        if not parts:
            return "", ""
        if len(parts) == 1:
            return parts[0], ""
        return " ".join(parts[:-1]), parts[-1]

    def _migrate_contact(self, contact: dict) -> None:
        fd_id = contact["id"]
        if self.state.get("users", fd_id):
            self.summary["skipped"] += 1
            return
        email = (contact.get("email") or "").strip() or f"fd-contact-{fd_id}@{SYNTH_EMAIL_DOMAIN}"
        existing = self.zammad.search_user_by_email(email)
        if existing:
            if not self.options.dry_run:
                self.state.set("users", fd_id, existing["id"])
            self.summary["skipped"] += 1
            self._log(f"Kontakt {email} existiert bereits (Zammad #{existing['id']})")
            return
        if self.options.dry_run:
            self.summary["created"] += 1
            self._log(f"[DRY RUN] Kunde {email} würde angelegt")
            return
        firstname, lastname = self._split_name(contact.get("name"))
        payload = {
            "firstname": firstname,
            "lastname": lastname,
            "email": email,
            "phone": contact.get("phone") or "",
            "mobile": contact.get("mobile") or "",
            "note": f"Migriert aus Freshdesk (Contact #{fd_id})",
            "roles": ["Customer"],
        }
        org_zid = self.state.get("organizations", contact.get("company_id"))
        if org_zid:
            payload["organization_id"] = org_zid
        user = self.zammad.create_user(payload)
        self.state.set("users", fd_id, user["id"])
        self.summary["created"] += 1
        self._log(f"Kunde {email} angelegt (Zammad #{user['id']})")

    # ---------- Agents ----------

    def _migrate_agent(self, agent: dict) -> None:
        fd_id = agent["id"]
        contact = agent.get("contact") or {}
        email = (contact.get("email") or "").strip()
        if self.state.get("users", fd_id):
            self.summary["skipped"] += 1
            return
        existing = self.zammad.search_user_by_email(email)
        if existing:
            if not self.options.dry_run:
                self.state.set("users", fd_id, existing["id"])
            self.summary["skipped"] += 1
            self._log(f"Agent {email} auf bestehenden Zammad-Benutzer #{existing['id']} gemappt")
            return
        if not self.options.create_agents:
            self.summary["skipped"] += 1
            self._log(
                f"Agent {email or f'fd-{fd_id}'}: kein Zammad-Benutzer mit dieser E-Mail "
                "gefunden – wird nicht angelegt (nur Mapping aktiv)"
            )
            return
        if self.options.dry_run:
            self.summary["created"] += 1
            self._log(f"[DRY RUN] Agent {email} würde angelegt")
            return
        firstname, lastname = self._split_name(contact.get("name"))
        user = self.zammad.create_user({
            "firstname": firstname,
            "lastname": lastname,
            "email": email or f"fd-agent-{fd_id}@{SYNTH_EMAIL_DOMAIN}",
            "note": f"Migriert aus Freshdesk (Agent #{fd_id})",
            "roles": ["Agent"],
        })
        self.state.set("users", fd_id, user["id"])
        self.summary["created"] += 1
        self._log(f"Agent {email} angelegt (Zammad #{user['id']})")

    # ---------- Tickets ----------

    def _resolve_customer(self, ticket: dict) -> int | None:
        """Liefert die Zammad-User-ID des Requesters, legt ihn notfalls an.

        Im Dry Run wird nichts angelegt; None bedeutet 'würde mit angelegt'.
        """
        fd_uid = ticket.get("requester_id")
        zid = self.state.get("users", fd_uid)
        if zid:
            return zid
        requester = ticket.get("requester") or {}
        email = (requester.get("email") or "").strip() or f"fd-contact-{fd_uid}@{SYNTH_EMAIL_DOMAIN}"
        existing = self.zammad.search_user_by_email(email)
        if existing:
            if not self.options.dry_run:
                self.state.set("users", fd_uid, existing["id"])
            return existing["id"]
        if self.options.dry_run:
            return None
        firstname, lastname = self._split_name(requester.get("name"))
        user = self.zammad.create_user({
            "firstname": firstname,
            "lastname": lastname,
            "email": email,
            "note": f"Migriert aus Freshdesk (Requester von Ticket #{ticket.get('id')})",
            "roles": ["Customer"],
        })
        self.state.set("users", fd_uid, user["id"])
        self._log(f"Kunde {email} bei Ticket-Migration angelegt (Zammad #{user['id']})")
        return user["id"]

    def _attachments_payload(self, fd_attachments: list | None) -> list:
        out = []
        for att in fd_attachments or []:
            self._check_cancel()
            url = att.get("attachment_url")
            if not url:
                continue
            try:
                content = self.freshdesk.download_attachment(url)
                out.append({
                    "filename": att.get("name") or "anhang",
                    "data": base64.b64encode(content).decode("ascii"),
                    "mime-type": att.get("content_type") or "application/octet-stream",
                })
            except Exception as e:  # noqa: BLE001
                self._log(f"  Anhang '{att.get('name')}' fehlgeschlagen: {e}")
        return out

    def _conversation_article(self, zammad_ticket_id: int, conv: dict) -> dict:
        sender = "Customer" if conv.get("incoming") else "Agent"
        article = {
            "ticket_id": zammad_ticket_id,
            "body": conv.get("body") or conv.get("body_text") or "(kein Inhalt)",
            "content_type": "text/html",
            "type": "note",
            "sender": sender,
            "internal": bool(conv.get("private")),
            "created_at": conv.get("created_at"),
        }
        if conv.get("from_email"):
            article["from"] = conv["from_email"]
        # Autor zuordnen, falls der Freshdesk-Benutzer gemappt ist
        author_zid = self.state.get("users", conv.get("user_id"))
        if author_zid:
            article["origin_by_id"] = author_zid
        atts = self._attachments_payload(conv.get("attachments"))
        if atts:
            article["attachments"] = atts
        return article

    def _migrate_ticket(self, t: dict) -> None:
        fd_id = t["id"]
        title = (t.get("subject") or "").strip() or f"Freshdesk-Ticket {fd_id}"

        # 1. Lokale Zustandsdatei
        if self.state.get("tickets", fd_id):
            self.summary["skipped"] += 1
            self._log(f"Ticket fd-{fd_id} bereits migriert (laut Zustandsdatei)")
            return

        # 2. Tag-Suche in Zammad (falls die Zustandsdatei verloren ging)
        try:
            found = self.zammad.search_tickets(f'tags:"fd-{fd_id}"', limit=1)
        except Exception as e:  # noqa: BLE001
            self._log(f"  Hinweis: Ticket-Suche fehlgeschlagen ({e}), verlasse mich auf Zustandsdatei")
            found = []
        if found:
            existing_id = found[0]["id"] if isinstance(found[0], dict) else found[0]
            if not self.options.dry_run:
                self.state.set("tickets", fd_id, existing_id)
            self.summary["skipped"] += 1
            self._log(f"Ticket fd-{fd_id} bereits in Zammad vorhanden (#{existing_id})")
            return

        customer_id = self._resolve_customer(t)

        if self.options.dry_run:
            self.summary["created"] += 1
            extra = " (Kunde würde mit angelegt)" if customer_id is None else ""
            self._log(f"[DRY RUN] Ticket fd-{fd_id} '{title[:60]}' würde angelegt{extra}")
            return

        state_id = self.options.status_map.get(t.get("status")) or self.options.fallback_state_id
        priority_id = self.options.priority_map.get(t.get("priority")) or self.options.fallback_priority_id

        first_article = {
            "body": t.get("description") or t.get("description_text") or "(kein Inhalt)",
            "content_type": "text/html",
            "type": "note",
            "sender": "Customer",
            "internal": False,
            "created_at": t.get("created_at"),
        }
        atts = self._attachments_payload(t.get("attachments"))
        if atts:
            first_article["attachments"] = atts

        payload = {
            "title": title,
            "group_id": self.options.group_id,
            "customer_id": customer_id,
            "state_id": state_id,
            "priority_id": priority_id,
            "created_at": t.get("created_at"),
            "updated_at": t.get("updated_at"),
            "note": f"Migriert aus Freshdesk (Ticket #{fd_id})",
            "article": first_article,
        }
        ticket = self.zammad.create_ticket(payload)
        zid = ticket["id"]

        # Marker-Tag für Duplikat-Erkennung, dazu die originalen Freshdesk-Tags
        self.zammad.add_tag(zid, f"fd-{fd_id}")
        for tag in t.get("tags") or []:
            try:
                self.zammad.add_tag(zid, tag)
            except Exception as e:  # noqa: BLE001
                self._log(f"  Tag '{tag}' fehlgeschlagen: {e}")

        # Komplette Konversation als Artikel übernehmen
        conversations = self.freshdesk.get_conversations(fd_id)
        for conv in conversations:
            self._check_cancel()
            try:
                self.zammad.create_article(self._conversation_article(zid, conv))
            except Exception as e:  # noqa: BLE001
                self._log(f"  Artikel (Conversation {conv.get('id')}) fehlgeschlagen: {e}")

        # updated_at zum Schluss noch einmal setzen (wird durch Artikel/Tags verschoben)
        try:
            self.zammad.update_ticket(zid, {"updated_at": t.get("updated_at")})
        except Exception as e:  # noqa: BLE001
            self._log(f"  updated_at konnte nicht gesetzt werden: {e}")

        self.state.set("tickets", fd_id, zid)
        self.summary["created"] += 1
        self._log(
            f"Ticket fd-{fd_id} '{title[:60]}' angelegt (Zammad #{zid}, "
            f"{len(conversations)} Artikel aus Konversation)"
        )
