"""Hauptfenster mit den drei Tabs."""
from PySide6.QtWidgets import QMainWindow, QTabWidget

from gui.connection_tab import ConnectionTab
from gui.data_tab import DataTab
from gui.migration_tab import MigrationTab


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Freshdesk → Zammad Migrator")
        self.resize(1100, 750)
        self.statusBar()

        tabs = QTabWidget()
        self.connection_tab = ConnectionTab(self)
        self.data_tab = DataTab(self)
        self.migration_tab = MigrationTab(self)
        tabs.addTab(self.connection_tab, "1. Verbindung")
        tabs.addTab(self.data_tab, "2. Daten && Auswahl")
        tabs.addTab(self.migration_tab, "3. Migration")
        self.setCentralWidget(tabs)
