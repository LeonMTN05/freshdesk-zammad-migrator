"""Einstiegspunkt: Freshdesk → Zammad Migrator (PySide6-GUI)."""
import logging
import sys

from PySide6.QtWidgets import QApplication

from config import LOG_FILE
from gui.main_window import MainWindow


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def main():
    setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("Freshdesk → Zammad Migrator")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
