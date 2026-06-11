"""Tab 2: Daten aus Freshdesk laden, auswählen und Mapping konfigurieren."""
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from config import (
    DEFAULT_PRIORITY_MAP, DEFAULT_STATUS_MAP, FD_PRIORITY_NAMES, FD_STATUS_NAMES,
)
from gui.workers import FunctionWorker
from migration.engine import MigrationOptions

PREVIEW_LIMIT = 200

PREVIEW_COLUMNS = {
    "companies": [("ID", "id"), ("Name", "name"), ("Domains", "domains")],
    "contacts": [("ID", "id"), ("Name", "name"), ("E-Mail", "email"), ("Company-ID", "company_id")],
    "agents": [("ID", "id"), ("Name", "contact.name"), ("E-Mail", "contact.email")],
    "ticket_fields": [("ID", "id"), ("Name", "name"), ("Label", "label"), ("Typ", "type")],
    "tickets": [("ID", "id"), ("Betreff", "subject"), ("Status", "status"),
                ("Priorität", "priority"), ("Erstellt", "created_at")],
}

PREVIEW_LABELS = [
    ("Companies", "companies"),
    ("Contacts", "contacts"),
    ("Agents", "agents"),
    ("Ticket-Felder", "ticket_fields"),
    ("Tickets", "tickets"),
]


class DataTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.mw = main_window
        self.data = {key: [] for _, key in PREVIEW_LABELS}
        self.zammad_refs = {"groups": [], "states": [], "priorities": []}
        self.status_combos: dict[int, QComboBox] = {}
        self.priority_combos: dict[int, QComboBox] = {}
        self._workers = []
        self._build_ui()

    # ---------- UI-Aufbau ----------

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # --- Laden + Filter ---
        top = QHBoxLayout()
        self.load_btn = QPushButton("📥 Daten aus Freshdesk laden")
        self.load_btn.clicked.connect(self._load_data)
        top.addWidget(self.load_btn)

        filter_box = QGroupBox("Ticket-Filter")
        filter_row = QHBoxLayout(filter_box)
        self.chk_since = QCheckBox("Geändert seit:")
        self.date_since = QDateEdit(QDate.currentDate().addYears(-1))
        self.date_since.setCalendarPopup(True)
        self.date_since.setEnabled(False)
        self.chk_since.toggled.connect(self.date_since.setEnabled)
        self.cmb_status_filter = QComboBox()
        self.cmb_status_filter.addItem("Alle Tickets", "all")
        self.cmb_status_filter.addItem("Nur offene (Open/Pending)", "open")
        filter_row.addWidget(self.chk_since)
        filter_row.addWidget(self.date_since)
        filter_row.addWidget(self.cmb_status_filter)
        top.addWidget(filter_box, stretch=1)
        layout.addLayout(top)

        middle = QHBoxLayout()

        # --- Kategorien ---
        cat_box = QGroupBox("Zu migrierende Kategorien")
        cat_layout = QVBoxLayout(cat_box)
        self.cb_companies = QCheckBox("Companies → Organisationen (–)")
        self.cb_contacts = QCheckBox("Contacts → Kunden (–)")
        self.cb_agents = QCheckBox("Agents (–)")
        self.cb_tickets = QCheckBox("Tickets inkl. Konversation + Anhänge (–)")
        for cb in (self.cb_companies, self.cb_contacts, self.cb_agents, self.cb_tickets):
            cb.setChecked(True)
            cb.setEnabled(False)
            cat_layout.addWidget(cb)
        self.cmb_agent_mode = QComboBox()
        self.cmb_agent_mode.addItem("Agents nur auf bestehende Zammad-Benutzer mappen (empfohlen)", False)
        self.cmb_agent_mode.addItem("Agents in Zammad neu anlegen (Achtung: Lizenzplätze!)", True)
        cat_layout.addWidget(QLabel("Agent-Behandlung:"))
        cat_layout.addWidget(self.cmb_agent_mode)
        self.lbl_fields = QLabel("Ticket-Felder: – (nur zur Ansicht)")
        cat_layout.addWidget(self.lbl_fields)
        cat_layout.addStretch()
        middle.addWidget(cat_box, stretch=1)

        # --- Mapping ---
        map_box = QGroupBox("Mapping (Freshdesk → Zammad)")
        map_layout = QVBoxLayout(map_box)
        group_form = QFormLayout()
        self.cmb_group = QComboBox()
        self.cmb_group.addItem("(zuerst Daten laden)", None)
        group_form.addRow("Ziel-Gruppe in Zammad:", self.cmb_group)
        map_layout.addLayout(group_form)

        map_layout.addWidget(QLabel("Status-Mapping:"))
        self.status_form = QFormLayout()
        map_layout.addLayout(self.status_form)
        map_layout.addWidget(QLabel("Prioritäts-Mapping:"))
        self.priority_form = QFormLayout()
        map_layout.addLayout(self.priority_form)
        map_layout.addStretch()
        middle.addWidget(map_box, stretch=1)

        layout.addLayout(middle)

        # --- Vorschau ---
        preview_box = QGroupBox("Vorschau")
        pv_layout = QVBoxLayout(preview_box)
        pv_top = QHBoxLayout()
        self.cmb_preview = QComboBox()
        for label, key in PREVIEW_LABELS:
            self.cmb_preview.addItem(label, key)
        self.cmb_preview.currentIndexChanged.connect(self._update_preview)
        self.lbl_preview_info = QLabel("")
        pv_top.addWidget(self.cmb_preview)
        pv_top.addWidget(self.lbl_preview_info, stretch=1)
        pv_layout.addLayout(pv_top)
        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        pv_layout.addWidget(self.table)
        layout.addWidget(preview_box, stretch=1)

    # ---------- Daten laden ----------

    def _load_data(self):
        fd = self.mw.connection_tab.make_freshdesk_client()
        zd = self.mw.connection_tab.make_zammad_client()
        if not fd or not zd:
            QMessageBox.warning(
                self, "Verbindung fehlt",
                "Bitte zuerst im Tab 'Verbindung' beide Systeme konfigurieren.",
            )
            return

        updated_since = None
        if self.chk_since.isChecked():
            updated_since = self.date_since.date().toString("yyyy-MM-dd") + "T00:00:00Z"
        only_open = self.cmb_status_filter.currentData() == "open"

        def job():
            warnings = []
            failed_keys = []

            def safe(key, label, fn):
                # Einzelne Kategorien dürfen scheitern (z. B. 403 bei
                # Nicht-Admin-API-Keys) – der Rest wird trotzdem geladen.
                try:
                    return fn()
                except Exception as e:  # noqa: BLE001
                    warnings.append(f"{label}: {e}")
                    failed_keys.append(key)
                    return []

            def load_tickets():
                tickets = fd.get_tickets(updated_since=updated_since)
                if only_open:
                    tickets = [t for t in tickets if t.get("status") in (2, 3)]
                return tickets

            res = {
                "companies": safe("companies", "Companies", fd.get_companies),
                "contacts": safe("contacts", "Contacts", fd.get_contacts),
                "agents": safe("agents", "Agents", fd.get_agents),
                "ticket_fields": safe("ticket_fields", "Ticket-Felder", fd.get_ticket_fields),
                "tickets": safe("tickets", "Tickets", load_tickets),
            }
            # Zammad-Referenzdaten sind Pflicht – ohne sie kein Mapping möglich
            res["groups"] = zd.get_groups()
            res["states"] = zd.get_ticket_states()
            res["priorities"] = zd.get_ticket_priorities()
            res["warnings"] = warnings
            res["failed_keys"] = failed_keys
            return res

        self.load_btn.setEnabled(False)
        self.load_btn.setText("Lade Daten … (siehe migration.log)")
        worker = FunctionWorker(job, parent=self)
        worker.result.connect(self._on_loaded)
        worker.error.connect(self._on_load_error)
        worker.finished.connect(lambda: self._workers.remove(worker))
        self._workers.append(worker)
        worker.start()

    def _on_load_error(self, msg):
        self.load_btn.setEnabled(True)
        self.load_btn.setText("📥 Daten aus Freshdesk laden")
        QMessageBox.critical(self, "Fehler beim Laden", msg)

    def _on_loaded(self, res):
        self.load_btn.setEnabled(True)
        self.load_btn.setText("📥 Daten aus Freshdesk laden")
        for key in self.data:
            self.data[key] = res.get(key, [])
        for key in self.zammad_refs:
            self.zammad_refs[key] = res.get(key, [])

        self.cb_companies.setText(f"Companies → Organisationen ({len(self.data['companies'])})")
        self.cb_contacts.setText(f"Contacts → Kunden ({len(self.data['contacts'])})")
        self.cb_agents.setText(f"Agents ({len(self.data['agents'])})")
        self.cb_tickets.setText(
            f"Tickets inkl. Konversation + Anhänge ({len(self.data['tickets'])})"
        )
        self.lbl_fields.setText(
            f"Ticket-Felder: {len(self.data['ticket_fields'])} (nur zur Ansicht)"
        )
        for cb in (self.cb_companies, self.cb_contacts, self.cb_agents, self.cb_tickets):
            cb.setEnabled(True)
            cb.setChecked(True)

        # Kategorien, die nicht geladen werden konnten, abwählen und sperren
        checkbox_by_key = {
            "companies": self.cb_companies,
            "contacts": self.cb_contacts,
            "agents": self.cb_agents,
            "tickets": self.cb_tickets,
        }
        for key in res.get("failed_keys", []):
            cb = checkbox_by_key.get(key)
            if cb:
                cb.setChecked(False)
                cb.setEnabled(False)

        self._fill_group_combo()
        self._build_mapping_rows()
        self._update_preview()

        warnings = res.get("warnings", [])
        if warnings:
            QMessageBox.warning(
                self, "Teilweise geladen",
                "Folgende Kategorien konnten nicht geladen werden und wurden "
                "abgewählt:\n\n" + "\n".join(f"• {w}" for w in warnings) +
                "\n\nHTTP 403 bedeutet: Der Freshdesk-API-Key hat dafür keine "
                "Berechtigung. Das Auflisten von Agents und Ticket-Feldern "
                "erlaubt Freshdesk nur Administratoren – dafür den API-Key "
                "eines Freshdesk-Admins verwenden.\n\n"
                "Alle anderen Kategorien wurden normal geladen und können "
                "migriert werden.",
            )
            self.mw.statusBar().showMessage("Daten teilweise geladen", 5000)
        else:
            self.mw.statusBar().showMessage("Daten geladen", 5000)

    # ---------- Mapping ----------

    def _fill_group_combo(self):
        self.cmb_group.clear()
        for g in self.zammad_refs["groups"]:
            self.cmb_group.addItem(g.get("name", f"Gruppe {g['id']}"), g["id"])

    @staticmethod
    def _clear_form(form: QFormLayout):
        while form.rowCount():
            form.removeRow(0)

    def _status_labels(self) -> dict[int, str]:
        """Status-IDs aus Standardwerten + tatsächlich vorkommenden Werten."""
        labels = dict(FD_STATUS_NAMES)
        for t in self.data["tickets"]:
            sid = t.get("status")
            if sid is not None and sid not in labels:
                labels[sid] = f"Status {sid} (custom)"
        # Labels aus den Ticket-Feldern ergänzen, falls vorhanden
        for fld in self.data["ticket_fields"]:
            if fld.get("name") == "status" and isinstance(fld.get("choices"), dict):
                for key, val in fld["choices"].items():
                    try:
                        sid = int(key)
                    except (TypeError, ValueError):
                        continue
                    if isinstance(val, list) and val:
                        labels[sid] = str(val[0])
                    elif isinstance(val, str):
                        labels[sid] = val
        return labels

    def _build_mapping_rows(self):
        self._clear_form(self.status_form)
        self._clear_form(self.priority_form)
        self.status_combos.clear()
        self.priority_combos.clear()

        states = self.zammad_refs["states"]
        priorities = self.zammad_refs["priorities"]

        for sid, label in sorted(self._status_labels().items()):
            combo = QComboBox()
            for st in states:
                combo.addItem(st.get("name", "?"), st["id"])
            default_name = DEFAULT_STATUS_MAP.get(sid, "open")
            idx = combo.findText(default_name, Qt.MatchFlag.MatchFixedString)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            self.status_combos[sid] = combo
            self.status_form.addRow(f"{label} ({sid}) →", combo)

        for pid, label in sorted(FD_PRIORITY_NAMES.items()):
            combo = QComboBox()
            for pr in priorities:
                combo.addItem(pr.get("name", "?"), pr["id"])
            default_name = DEFAULT_PRIORITY_MAP.get(pid, "2 normal")
            idx = combo.findText(default_name, Qt.MatchFlag.MatchFixedString)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            self.priority_combos[pid] = combo
            self.priority_form.addRow(f"{label} ({pid}) →", combo)

    # ---------- Vorschau ----------

    @staticmethod
    def _dig(record: dict, dotted: str):
        value = record
        for part in dotted.split("."):
            if not isinstance(value, dict):
                return ""
            value = value.get(part)
        return value

    def _update_preview(self):
        key = self.cmb_preview.currentData()
        records = self.data.get(key, [])
        columns = PREVIEW_COLUMNS[key]
        shown = records[:PREVIEW_LIMIT]

        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels([c[0] for c in columns])
        self.table.setRowCount(len(shown))
        for row, record in enumerate(shown):
            for col, (_, field) in enumerate(columns):
                value = self._dig(record, field)
                if isinstance(value, list):
                    value = ", ".join(str(v) for v in value)
                self.table.setItem(row, col, QTableWidgetItem("" if value is None else str(value)))
        self.table.resizeColumnsToContents()

        if len(records) > PREVIEW_LIMIT:
            self.lbl_preview_info.setText(f"Zeige erste {PREVIEW_LIMIT} von {len(records)} Datensätzen")
        else:
            self.lbl_preview_info.setText(f"{len(records)} Datensätze")

    # ---------- Schnittstelle für den Migrations-Tab ----------

    def has_data(self) -> bool:
        return any(self.data[key] for key in ("companies", "contacts", "agents", "tickets"))

    def get_selected_data(self) -> dict:
        return {
            "companies": self.data["companies"] if self.cb_companies.isChecked() else [],
            "contacts": self.data["contacts"] if self.cb_contacts.isChecked() else [],
            "agents": self.data["agents"] if self.cb_agents.isChecked() else [],
            "tickets": self.data["tickets"] if self.cb_tickets.isChecked() else [],
        }

    def get_options(self, dry_run: bool) -> MigrationOptions:
        states = self.zammad_refs["states"]
        priorities = self.zammad_refs["priorities"]

        def find_id(items, name, fallback_first=True):
            for item in items:
                if item.get("name") == name:
                    return item["id"]
            return items[0]["id"] if (items and fallback_first) else None

        return MigrationOptions(
            migrate_organizations=self.cb_companies.isChecked(),
            migrate_contacts=self.cb_contacts.isChecked(),
            migrate_agents=self.cb_agents.isChecked(),
            create_agents=bool(self.cmb_agent_mode.currentData()),
            migrate_tickets=self.cb_tickets.isChecked(),
            group_id=self.cmb_group.currentData(),
            status_map={sid: c.currentData() for sid, c in self.status_combos.items()},
            priority_map={pid: c.currentData() for pid, c in self.priority_combos.items()},
            fallback_state_id=find_id(states, "open"),
            fallback_priority_id=find_id(priorities, "2 normal"),
            dry_run=dry_run,
        )
