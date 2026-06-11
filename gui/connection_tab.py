"""Tab 1: Verbindungs-Setup für Freshdesk und Zammad."""
from PySide6.QtWidgets import (
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout, QWidget,
)

import config
from api.freshdesk import FreshdeskClient
from api.zammad import ZammadClient
from gui.workers import FunctionWorker

STYLE_OK = "color: #2e7d32; font-weight: bold;"
STYLE_ERR = "color: #c62828; font-weight: bold;"
STYLE_BUSY = "color: #f57f17;"


class ConnectionTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.mw = main_window
        self._workers = []
        self._build_ui()
        self._load_config()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        warn = QLabel(
            "⚠️ Hinweis: Die Zugangsdaten werden unverschlüsselt (Klartext) in "
            "config.json im Programmordner gespeichert. Datei entsprechend schützen."
        )
        warn.setWordWrap(True)
        warn.setStyleSheet("color: #b26a00; background: #fff8e1; padding: 8px; border-radius: 4px;")
        layout.addWidget(warn)

        # --- Freshdesk ---
        fd_box = QGroupBox("Freshdesk (Quelle)")
        fd_form = QFormLayout(fd_box)
        self.fd_subdomain = QLineEdit()
        self.fd_subdomain.setPlaceholderText("z. B. meinefirma (für meinefirma.freshdesk.com)")
        self.fd_api_key = QLineEdit()
        self.fd_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        fd_form.addRow("Subdomain:", self.fd_subdomain)
        fd_form.addRow("API-Key:", self.fd_api_key)
        fd_row = QHBoxLayout()
        self.fd_test_btn = QPushButton("Freshdesk-Verbindung testen")
        self.fd_status = QLabel("Noch nicht getestet")
        fd_row.addWidget(self.fd_test_btn)
        fd_row.addWidget(self.fd_status, stretch=1)
        fd_form.addRow(fd_row)
        layout.addWidget(fd_box)

        # --- Zammad ---
        zd_box = QGroupBox("Zammad (Ziel – bestehende Instanz)")
        zd_form = QFormLayout(zd_box)
        self.zd_url = QLineEdit()
        self.zd_url.setPlaceholderText("z. B. https://zammad.meinefirma.de")
        self.zd_token = QLineEdit()
        self.zd_token.setEchoMode(QLineEdit.EchoMode.Password)
        zd_form.addRow("URL:", self.zd_url)
        zd_form.addRow("API-Token:", self.zd_token)
        zd_row = QHBoxLayout()
        self.zd_test_btn = QPushButton("Zammad-Verbindung testen")
        self.zd_status = QLabel("Noch nicht getestet")
        zd_row.addWidget(self.zd_test_btn)
        zd_row.addWidget(self.zd_status, stretch=1)
        zd_form.addRow(zd_row)
        layout.addWidget(zd_box)

        self.save_btn = QPushButton("Zugangsdaten speichern (config.json)")
        layout.addWidget(self.save_btn)
        layout.addStretch()

        self.fd_test_btn.clicked.connect(self._test_freshdesk)
        self.zd_test_btn.clicked.connect(self._test_zammad)
        self.save_btn.clicked.connect(self._save_config)

    # ---------- Konfiguration ----------

    def _load_config(self):
        cfg = config.load_config()
        self.fd_subdomain.setText(cfg.get("freshdesk_subdomain", ""))
        self.fd_api_key.setText(cfg.get("freshdesk_api_key", ""))
        self.zd_url.setText(cfg.get("zammad_url", ""))
        self.zd_token.setText(cfg.get("zammad_token", ""))

    def _save_config(self):
        config.save_config({
            "freshdesk_subdomain": self.fd_subdomain.text().strip(),
            "freshdesk_api_key": self.fd_api_key.text().strip(),
            "zammad_url": self.zd_url.text().strip(),
            "zammad_token": self.zd_token.text().strip(),
        })
        self.mw.statusBar().showMessage("Zugangsdaten in config.json gespeichert", 5000)

    # ---------- Client-Fabriken ----------

    def make_freshdesk_client(self) -> FreshdeskClient | None:
        sub = self.fd_subdomain.text().strip()
        key = self.fd_api_key.text().strip()
        if not sub or not key:
            return None
        return FreshdeskClient(sub, key)

    def make_zammad_client(self) -> ZammadClient | None:
        url = self.zd_url.text().strip()
        token = self.zd_token.text().strip()
        if not url or not token:
            return None
        return ZammadClient(url, token)

    # ---------- Verbindungstests ----------

    def _test_freshdesk(self):
        client = self.make_freshdesk_client()
        if not client:
            self._set_status(self.fd_status, False, "Subdomain und API-Key eingeben")
            return
        self._run_test(client, self.fd_status, self.fd_test_btn)

    def _test_zammad(self):
        client = self.make_zammad_client()
        if not client:
            self._set_status(self.zd_status, False, "URL und Token eingeben")
            return
        self._run_test(client, self.zd_status, self.zd_test_btn)

    def _run_test(self, client, status_label, button):
        status_label.setText("Teste …")
        status_label.setStyleSheet(STYLE_BUSY)
        button.setEnabled(False)
        worker = FunctionWorker(client.test_connection, parent=self)
        worker.result.connect(lambda res: self._set_status(status_label, *res))
        worker.error.connect(lambda msg: self._set_status(status_label, False, msg))
        worker.finished.connect(lambda: button.setEnabled(True))
        worker.finished.connect(lambda: self._workers.remove(worker))
        self._workers.append(worker)
        worker.start()

    @staticmethod
    def _set_status(label, ok, msg):
        label.setText(("✅ " if ok else "❌ ") + msg)
        label.setStyleSheet(STYLE_OK if ok else STYLE_ERR)
