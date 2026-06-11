"""Tab 3: Dry Run / Migration mit Fortschritt, Live-Log und Abbruch."""
from datetime import datetime

from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QVBoxLayout, QWidget,
)

from config import FAILED_FILE, STATE_FILE
from gui.workers import MigrationWorker
from migration.engine import MigrationEngine


class MigrationTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.mw = main_window
        self.worker: MigrationWorker | None = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        buttons = QHBoxLayout()
        self.btn_dry = QPushButton("🔍 Dry Run (Simulation)")
        self.btn_start = QPushButton("🚀 Migration starten")
        self.btn_cancel = QPushButton("⏹ Abbrechen")
        self.btn_cancel.setEnabled(False)
        buttons.addWidget(self.btn_dry)
        buttons.addWidget(self.btn_start)
        buttons.addWidget(self.btn_cancel)
        buttons.addStretch()
        layout.addLayout(buttons)

        self.progress = QProgressBar()
        self.progress.setFormat("%v / %m")
        layout.addWidget(self.progress)
        self.lbl_status = QLabel("Bereit. Erst Dry Run ausführen, dann migrieren.")
        layout.addWidget(self.lbl_status)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(20000)
        layout.addWidget(self.log_view, stretch=1)

        self.btn_dry.clicked.connect(lambda: self._start(dry_run=True))
        self.btn_start.clicked.connect(lambda: self._start(dry_run=False))
        self.btn_cancel.clicked.connect(self._cancel)

    # ---------- Start / Abbruch ----------

    def _start(self, dry_run: bool):
        data_tab = self.mw.data_tab
        if not data_tab.has_data():
            QMessageBox.warning(
                self, "Keine Daten",
                "Bitte zuerst im Tab 'Daten & Auswahl' Daten aus Freshdesk laden.",
            )
            return

        options = data_tab.get_options(dry_run)
        data = data_tab.get_selected_data()

        if data["tickets"] and options.group_id is None:
            QMessageBox.warning(
                self, "Ziel-Gruppe fehlt",
                "Bitte im Tab 'Daten & Auswahl' eine Ziel-Gruppe in Zammad wählen.",
            )
            return

        if not dry_run:
            counts = ", ".join(
                f"{len(records)} {name}" for name, records in (
                    ("Organisationen", data["companies"]),
                    ("Kontakte", data["contacts"]),
                    ("Agents", data["agents"]),
                    ("Tickets", data["tickets"]),
                ) if records
            )
            answer = QMessageBox.question(
                self, "Migration starten?",
                f"Folgende Daten werden in die bestehende Zammad-Instanz geschrieben:\n\n"
                f"{counts}\n\nBereits vorhandene Datensätze werden übersprungen. Fortfahren?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        fd = self.mw.connection_tab.make_freshdesk_client()
        zd = self.mw.connection_tab.make_zammad_client()
        if not fd or not zd:
            QMessageBox.warning(self, "Verbindung fehlt", "Bitte Zugangsdaten im Tab 'Verbindung' prüfen.")
            return

        engine = MigrationEngine(fd, zd, options, STATE_FILE, FAILED_FILE)
        self.worker = MigrationWorker(engine, data, parent=self)
        self.worker.progress.connect(self._on_progress)
        self.worker.log_line.connect(self._on_log)
        self.worker.finished_ok.connect(self._on_finished)
        self.worker.error.connect(self._on_error)

        self.btn_dry.setEnabled(False)
        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress.setValue(0)
        self.lbl_status.setText("Dry Run läuft …" if dry_run else "Migration läuft …")
        self.log_view.clear()
        self.worker.start()

    def _cancel(self):
        if self.worker:
            self.worker.cancel()
            self._on_log("Abbruch angefordert – stoppe nach dem aktuellen Datensatz …")
            self.btn_cancel.setEnabled(False)

    # ---------- Signale ----------

    def _on_progress(self, done, total, _msg):
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(done)

    def _on_log(self, msg):
        self.log_view.appendPlainText(f"[{datetime.now():%H:%M:%S}] {msg}")

    def _finish_ui(self):
        self.btn_dry.setEnabled(True)
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.worker = None

    def _on_finished(self, summary):
        self._finish_ui()
        state = "abgebrochen" if summary.get("cancelled") else "abgeschlossen"
        text = (
            f"Lauf {state}:\n\n"
            f"  Angelegt:       {summary['created']}\n"
            f"  Übersprungen:   {summary['skipped']}\n"
            f"  Fehlgeschlagen: {summary['failed']}"
        )
        if summary["failed"]:
            text += f"\n\nDetails: {FAILED_FILE.name} und migration.log"
        self.lbl_status.setText(text.replace("\n", " ").replace("  ", " "))
        QMessageBox.information(self, "Ergebnis", text)

    def _on_error(self, msg):
        self._finish_ui()
        self.lbl_status.setText("Fehler – siehe Log.")
        QMessageBox.critical(self, "Schwerer Fehler", msg)
