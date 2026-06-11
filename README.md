<div align="center">

# 🎫 Freshdesk → Zammad Migrator

**Desktop-Tool zur Migration von Freshdesk in eine bestehende, produktive Zammad-Instanz**

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![GUI](https://img.shields.io/badge/GUI-PySide6%20(Qt)-41CD52?style=for-the-badge&logo=qt&logoColor=white)](https://doc.qt.io/qtforpython-6/)
[![Plattform](https://img.shields.io/badge/Plattform-Windows%20%7C%20Linux%20%7C%20macOS-555555?style=for-the-badge)](#-setup)
[![Tests](https://img.shields.io/badge/Tests-22%20passing-2ea44f?style=for-the-badge&logo=pytest&logoColor=white)](#-tests)

[![Freshdesk](https://img.shields.io/badge/Quelle-Freshdesk%20REST%20API%20v2-25C16F?style=flat-square)](https://developers.freshdesk.com/api/)
[![Zammad](https://img.shields.io/badge/Ziel-Zammad%20REST%20API-FFCE00?style=flat-square)](https://docs.zammad.org/en/latest/api/intro.html)
[![Modus](https://img.shields.io/badge/Schreibzugriffe-nur%20additiv-blue?style=flat-square)](#%EF%B8%8F-wie-das-tool-die-bestehende-instanz-schützt)

---

*Der eingebaute Zammad-Importer funktioniert nur bei frischen Installationen.*
*Dieses Tool migriert per API in eine **laufende** Instanz – ohne Bestandsdaten anzufassen.*

</div>

## ✨ Features

| | Feature |
|---|---|
| 🔌 | **Verbindungs-Setup** mit Live-Test für Freshdesk & Zammad |
| 📥 | **Daten laden & auswählen:** Companies, Contacts, Agents, Ticket-Felder, Tickets (mit Zeitraum- & Statusfilter) |
| 🗺️ | **Mapping-Editor:** Status & Priorität frei zuordnen, Ziel-Gruppe live aus Zammad geladen |
| 🔍 | **Dry Run:** komplette Simulation ohne einen einzigen Schreibzugriff |
| 🧵 | **Migration im eigenen Thread:** Progressbar, Live-Log, jederzeit abbrechbar |
| 💬 | **Komplette Konversationen:** Beschreibung + alle Antworten als Artikel, korrekter Absender, originale Zeitstempel |
| 📎 | **Anhänge** werden heruntergeladen und base64-codiert mit übernommen |
| 🔁 | **Wiederholbar & fortsetzbar:** Duplikat-Erkennung über E-Mail, Name, Tag `fd-<id>` und lokale Zustandsdatei |
| 🚦 | **Rate-Limit-fest:** wertet `X-RateLimit-Remaining` aus, wartet bei HTTP 429 (`Retry-After`), paginiert mit `per_page=100` |
| 🛡️ | **Fehlertolerant:** Einzelfehler stoppen nichts – sie landen in `failed_records.json` + `migration.log` |

## 🚀 Setup

> Voraussetzung: [Python 3.11+](https://www.python.org/downloads/)

**Windows – der einfache Weg:**

```
Doppelklick auf start.bat
```

Die Batch-Datei erstellt beim ersten Start automatisch eine virtuelle Umgebung,
installiert alle Abhängigkeiten und startet die App.

**Manuell (alle Plattformen):**

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  |  Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

## 🔑 Zugangsdaten

| System | Wo finde ich den Key? | Wichtig |
|---|---|---|
| **Freshdesk** | Profilbild → *Profile Settings* → *View API Key* | Key eines **Administrators** verwenden – Agents & Ticket-Felder sind sonst gesperrt (HTTP 403) |
| **Zammad** | Avatar → *Profil* → *Token-Zugriff* | Token eines **Admin-Benutzers** – nur dann übernimmt Zammad originale Zeitstempel & Absender |

Zum Ausprobieren kann `config.example.json` nach `config.json` kopiert und
ausgefüllt werden – oder einfach alles direkt in der GUI eintragen.

> ⚠️ **Sicherheitshinweis:** Die Zugangsdaten werden **im Klartext** in
> `config.json` gespeichert. Die Datei steht deshalb in der `.gitignore` und
> darf niemals committet oder weitergegeben werden.

## 🧭 Ablauf einer Migration

```
1. Verbindung  →  2. Daten & Auswahl  →  3. Migration
   Keys testen     Laden, Filtern,         Erst Dry Run,
   & speichern     Mapping festlegen       dann migrieren
```

1. **Tab 1 – Verbindung:** Zugangsdaten eintragen, beide Verbindungen testen.
2. **Tab 2 – Daten & Auswahl:** „Daten aus Freshdesk laden“, Kategorien anhaken,
   Status-/Prioritäts-Mapping und Ziel-Gruppe prüfen.
3. **Tab 3 – Migration:** Erst **🔍 Dry Run** (zeigt, was angelegt bzw.
   übersprungen würde – ohne Schreibzugriffe), dann **🚀 Migration starten**.

## 🛡️ Wie das Tool die bestehende Instanz schützt

- **Nur additive API-Aufrufe** – Suchen und Anlegen, niemals Löschen oder Überschreiben.
- **Duplikat-Erkennung:** Benutzer per exakter E-Mail-Suche, Organisationen per
  exaktem Namen, Tickets per Tag `fd-<Freshdesk-ID>` **und** lokaler
  Zustandsdatei `migration_state.json`. Abbruch oder Fehler? Einfach erneut
  starten – bereits Migriertes wird übersprungen.
- **Keine E-Mails an Kunden:** Alle Artikel werden als Typ `note` angelegt
  (Absender und intern-Flag bleiben korrekt) – Zammad verschickt während der
  Migration nichts.
- **Agents werden standardmäßig nur gemappt**, nicht neu angelegt (neue Agents
  belegen Lizenzplätze). Anlegen ist optional zuschaltbar.

## ⚙️ Technische Details

<details>
<summary><b>Rate Limits & Pagination (Freshdesk)</b></summary>

`X-RateLimit-Remaining` wird nach jeder Antwort ausgewertet (Drosselung bei
niedrigem Kontingent), bei HTTP 429 wird `Retry-After` respektiert und
automatisch wiederholt. Listen werden mit `per_page=100` paginiert.
Freshdesk liefert maximal 300 Seiten pro Endpunkt (≈ 30.000 Tickets) – bei
größeren Beständen den Filter „Geändert seit“ nutzen und in Zeitscheiben
migrieren; dank Duplikat-Erkennung ist das gefahrlos.
</details>

<details>
<summary><b>Zeitstempel & Absender</b></summary>

`created_at` von Tickets und Artikeln wird übernommen, Artikel-Autoren werden
über `origin_by_id` zugeordnet – beides setzt ein **Admin-Token** in Zammad
voraus. `updated_at` wird nach dem Anlegen aller Artikel noch einmal gesetzt
(Best-Effort). Kontakte ohne E-Mail erhalten eine synthetische Adresse
`fd-contact-<id>@freshdesk-import.invalid`.
</details>

<details>
<summary><b>Erzeugte Dateien (lokal, nicht im Repo)</b></summary>

| Datei | Zweck |
|---|---|
| `config.json` | Zugangsdaten (Klartext!) |
| `migration_state.json` | Mapping Freshdesk-ID → Zammad-ID, ermöglicht Fortsetzen |
| `failed_records.json` | Fehlgeschlagene Datensätze des letzten Laufs |
| `migration.log` | Ausführliches Logfile |
</details>

## 🧪 Tests

API-Clients und Engine sind vollständig mit Mock-Daten getestet – es sind
**keine echten Instanzen** nötig:

```bash
python -m unittest discover tests -v
```

## 📁 Projektstruktur

```
├── main.py                 # Einstiegspunkt
├── start.bat               # Windows: Setup + Start per Doppelklick
├── config.py               # config.json, Pfade, Standard-Mappings
├── config.example.json     # Vorlage für die Zugangsdaten
├── api/
│   ├── freshdesk.py        # Freshdesk-Client (Rate Limits, Pagination)
│   └── zammad.py           # Zammad-Client (nur additive Operationen)
├── migration/
│   └── engine.py           # Migrations-Engine (Qt-frei, testbar)
├── gui/
│   ├── main_window.py      # Hauptfenster mit drei Tabs
│   ├── connection_tab.py   # Tab 1: Verbindung
│   ├── data_tab.py         # Tab 2: Daten, Auswahl, Mapping
│   ├── migration_tab.py    # Tab 3: Dry Run / Migration
│   └── workers.py          # QThread-Worker
└── tests/                  # Mock-Tests für Clients und Engine
```

## ⚖️ Haftungsausschluss

> **Nutzung auf eigene Gefahr.**
>
> Diese Software wird **„wie besehen“ (as is)** und ohne jegliche
> ausdrückliche oder stillschweigende Gewährleistung bereitgestellt –
> insbesondere ohne Gewährleistung der Marktgängigkeit, der Eignung für einen
> bestimmten Zweck oder der Fehlerfreiheit.
>
> Die Autoren und Mitwirkenden übernehmen **keine Haftung** für direkte oder
> indirekte Schäden, Datenverluste, Betriebsunterbrechungen oder sonstige
> Folgen, die aus der Nutzung dieser Software entstehen – auch nicht bei der
> Verwendung gegen produktive Freshdesk- oder Zammad-Instanzen.
>
> **Vor jeder Migration gilt:**
> - ✅ Aktuelles **Backup** der Zammad-Instanz erstellen
> - ✅ Migration zuerst per **Dry Run** simulieren
> - ✅ Idealerweise gegen eine **Testinstanz/Staging-Umgebung** prüfen
>
> Freshdesk® und Zammad® sind eingetragene Marken der jeweiligen Inhaber.
> Dieses Projekt steht in keiner Verbindung zu Freshworks Inc. oder zur
> Zammad GmbH.

---

<div align="center">

**Viel Erfolg bei der Migration! --- #saveyourtokens** 🎉

*Bei Problemen bitte ein Issue öffnen – `migration.log` und die Fehlermeldung helfen bei der Diagnose.*

</div>
