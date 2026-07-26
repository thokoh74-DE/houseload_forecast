# Changelog / Änderungsprotokoll

🌍 **Deutsch** | [English](#english)

---

## Deutsch

### v2.1.2

**🆕 Zwei neue Sensoren: Prognose Aktuelle Stunde & Nächste Stunde**
- **`sensor.hlf_forecast_current_hour`** – Prognostizierter Hauslast-Verbrauch der aktuellen Stunde (kWh). Liest den `load_estimate` der aktuellen vollen Stunde aus `forecast_heute`.
  - Attribute: `hour` (aktuelle Stunde), `load_estimate_w` (Prognosewert in Watt)
  - Entity-Name (EN): *Forecast Current Hour* / (DE): *Hauslast-Prognose Aktuelle Stunde*
  - Icon: `mdi:home-clock`
- **`sensor.hlf_forecast_next_hour`** – Prognostizierter Hauslast-Verbrauch der nächsten Stunde (kWh). Liest den `load_estimate` der nächsten vollen Stunde aus `forecast_heute` – bei Stunde 23 wird automatisch auf `forecast_morgen[0]` (= 00:00 Uhr morgen) zurückgegriffen.
  - Attribute: `hour` (nächste Stunde), `is_tomorrow` (true wenn Übergang auf morgen), `load_estimate_w` (Prognosewert in Watt)
  - Entity-Name (EN): *Forecast Next Hour* / (DE): *Hauslast-Prognose Nächste Stunde*
  - Icon: `mdi:home-clock-outline`
- Beide Sensoren sind `state_class: MEASUREMENT` und erscheinen in der HA-Langzeitstatistik.
- Übersetzungen in allen Sprach-Dateien (strings.json, translations/de.json, translations/en.json) ergänzt.

### v2.1.1

**🐛 Kritischer Bugfix: Write-Throttle aus v2.1.0 griff nicht (Feedback-Loop über den Coordinator)**
- **Ursache:** `hlf_hauslast_stundlich`/`hlf_hauslast_taglich` waren zusätzlich beim `HauslastCoordinator` registriert. Dessen `async_refresh()` schreibt bedingungslos `async_write_ha_state()` auf **alle** registrierten Entities – ein zweiter, vom v2.1.0-Throttle komplett unabhängiger Schreibpfad. Da die eigene Entity-ID dieser Sensoren zusätzlich in `watch_forecast` steht, löste jeder Schreibvorgang nach 5s Debounce den nächsten Coordinator-Refresh aus, der sie erneut schrieb – ein sich selbst antreibender Feedback-Loop im ~5-Sekunden-Takt, der den 60s-Throttle aus v2.1.0 faktisch wirkungslos machte.
- **Fix:** `hauslast_stundlich_sensor`/`hauslast_taeglich_sensor` werden nicht mehr bei `coordinator.async_register_entities()` registriert. Sie verwalten ihren Recorder-Write bereits vollständig eigenständig über `handle_power_update` (inkl. Throttle aus v2.1.0) und brauchen den Blanket-Write des Coordinators nicht.
- **Effekt:** Der in v2.1.0 vorgesehene 60-Sekunden-Throttle greift jetzt tatsächlich. Kein Verhaltensunterschied bei den übrigen Sensoren (Prognose, Diagnose etc.) – die werden weiterhin normal vom Coordinator aktualisiert.

### v2.1.0

**⚡ Recorder-Entlastung: Write-Throttle für `hlf_hauslast_stundlich` / `hlf_hauslast_taglich`**
- **Ursache:** Beide Sensoren akkumulieren den Hauslast-Leistungssensor per Riemann-Integral und riefen bei *jeder* Zustandsänderung des Quellsensors (sekündlich) `async_write_ha_state()` auf. Ergebnis: ~46.000 Recorder-Zeilen/Tag pro Sensor, ~90.000/Tag zusammen.
- **Fix:** Die Akkumulation (`_total_kwh`) läuft weiterhin bei jedem Tick unverändert exakt weiter. Der Recorder-Write ist jetzt auf max. 1×/60s gedrosselt (`WRITE_MIN_INTERVAL_S`), zusätzlich wird beim Stunden- bzw. Tageswechsel sofort geschrieben, damit `hourly_history`/`daily_history` (und die darauf basierende MAE-Berechnung) ohne Verzögerung aktuell bleiben.
- **Effekt:** Reduziert die Recorder-Last dieser beiden Sensoren um ca. 98 %, ohne Genauigkeitsverlust bei der Energiebilanz. Dashboards, die den aktuellen Zählerstand live im Sekundentakt anzeigen wollen, sehen jetzt Aktualisierungen im 60-Sekunden-Rhythmus statt sekündlich.

### v2.0.0

**🐛 Kritischer Bugfix: Restlaufzeit zeigt 48h bei leerem Akku**
- **Ursache:** Die Restlaufzeit-Berechnung durchsuchte den 72h-SOC-Forecast inkl. PV-Erzeugung. Wenn PV den Akku innerhalb der nächsten Stunde aufladen würde, zeigte die Simulation „Akku wird nie leer" → Fallback auf 2880 min (48h) – selbst bei 5% SOC und nur 47 Wh nutzbarer Energie.
- **Fix: Sofortprüfung** – Wenn der aktuelle SOC bereits am oder unter der Runtime-Schwelle (Cutoff + Puffer) liegt, wird sofort `Restlaufzeit = 0` gesetzt, unabhängig vom Forecast.
- **Sägezahn-Muster behoben** – Das oszillierende Muster (675→674→673→2880→…) in der History entfällt, da bei niedrigem Akku sofort 0 zurückgegeben wird.

**🔋 Neues Attribut: Akku-Only-Restlaufzeit (`bat_only_runtime_min`)**
- Berechnet, wie lange der Akku **allein** (ohne PV) die Hauslast versorgen kann: `nutzbare_kWh ÷ aktuelle_Hauslast_kW × 60`.
- Verwendet den Durchschnitt der nächsten 3 Forecast-Stunden für einen stabilen Wert.
- Verfügbar als Attribut im `sensor.hlf_battery_runtime`-Sensor.

**🏗️ Repository auf Produktionsqualität gebracht (Silver Quality Scale)**
- Diagnostics-Plattform (`diagnostics.py`) – Download über Geräteseite → ⋮ → Diagnose
- Quality Scale YAML (`quality_scale.yaml`) – Silver-Tier-Tracking
- CI/CD: GitHub Actions für Hassfest, HACS-Validierung, CodeQL, Ruff-Linting
- Release-Workflow: Versions-Nr. in `manifest.json` wird automatisch aus dem GitHub-Release-Tag gesetzt
- `pyproject.toml` mit Ruff-Konfiguration
- `hacs.json` bereinigt (kein `content_in_root`, kein `hide_default_branch`)
- `manifest.json`-Keys alphabetisch sortiert nach `domain`/`name`
- Issue-Templates (Bug Report, Feature Request)
- `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`, `SECURITY.md`
- Dependabot für GitHub Actions
- README-Badges (HACS, Release, License, CI-Status, Downloads)

### v1.2.1

**Restlaufzeit-Berechnung grundlegend überarbeitet**
- **Ursache des Fehlers:** Die Hauptsimulation begrenzt den SOC auf `max(cutoff_kwh, ...)` — dadurch konnte `entry["soc_kwh"]` nie unter den Cutoff fallen, und die Restlaufzeit wurde erst im allerletzten Moment erkannt (meist kurz bevor der Akku wirklich leer war).
- **Fix:** Separate, unkontrollierte Simulation für die Restlaufzeit ohne SOC-Clamping. Der SOC darf in dieser Hilfssimulation unter den Cutoff fallen — der erste Slot, wo das passiert, ist der echte Entladezeitpunkt.
- **Frühwarn-Puffer:** Die Schwelle liegt standardmäßig bei `Cutoff-SOC + 2 %`, damit die Warnung früh genug kommt.

**Neuer Einstellungsparameter: Restlaufzeit-Puffer (`runtime_buffer_pct`)**
- Unter **Einstellungen → Geräte & Dienste → Hauslast Prognose → Konfigurieren → Sensoren** erscheint ein neues Feld: **Restlaufzeit-Puffer (%)**.
- Slider: 0–20 %, Schrittweite 0,5 %, Standardwert **2,0 %**.
- Gibt an, wie viel Prozent über dem konfigurierten Cutoff-SOC die Frühwarnschwelle liegt. Bei 10 % Cutoff und 2 % Puffer wird die Restlaufzeit ab 12 % SOC berechnet.
- Wert 0 % = Verhalten wie vor v1.2.1 (Warnung exakt am Cutoff).

### v1.2.0

**Neuer Diagnosesensor: `sensor.hlf_diag_soc_prognose_midnight` – SOC-Tagesprognose eingefroren um Mitternacht**
- Täglich kurz nach 00:00 Uhr wird ein Snapshot der SOC-Simulation für die nächsten **72 Stunden** eingefroren.
- Der Sensor gibt stündlich den Prognosewert der jeweils aktuellen Stunde aus → vollständige Zeitreihe in der HA-Langzeitstatistik.
- Der Snapshot wird in `/config/.storage/houseload_forecast_midnight_snapshot.json` persistent gespeichert und überlebt HA-Neustarts.
- Ermöglicht ein Vergleichsdiagramm: *SOC-Prognose (Mitternacht) vs. tatsächlicher SOC-Verlauf*.
- Erscheint in der Geräteansicht unter **„Diagnose"** (`EntityCategory.DIAGNOSTIC`).

**Neuer Diagnosesensor: `sensor.hlf_diag_soc_aktuell` – Batterieladezustand für Statistik**
- Spiegelt den konfigurierten SOC-Sensor (%) als eigenständigen `MEASUREMENT`-Sensor in die HA-Langzeitstatistik.
- Ermöglicht den direkten stündlichen Vergleich mit `sensor.hlf_diag_soc_prognose_midnight` in ApexCharts via `statistics:`.
- Zusatzattribute: `quelle`, `bat_kwh`, `bat_max_kwh`, `aktualisiert`.
- Erscheint unter **„Diagnose"**.

**`sensor.hlf_diag_soc_pct_raw` entfernt**
- Wurde durch `sensor.hlf_diag_soc_aktuell` ersetzt, der denselben Wert liefert, aber zusätzlich `state_class: MEASUREMENT` für die HA-Statistik besitzt.
- ⚠️ **Migration:** Nach dem Update `sensor.hlf_diag_soc_pct_raw` manuell unter Einstellungen → Geräte & Dienste → Hauslast Prognose → Entitäten löschen. Bestehende Statistikdaten des alten Sensors bleiben im Recorder erhalten.

**ApexCharts-Vergleichsdiagramm (Beispiel)**
```yaml
type: custom:apexcharts-card
experimental:
  brush: true
graph_span: 7d
brush:
  selection_span: 24h
series:
  - entity: sensor.hlf_diag_soc_prognose_midnight
    name: SOC Prognose (00:00 Uhr)
    stroke_dash: 6
    statistics:
      type: mean
      period: hour
  - entity: sensor.hlf_diag_soc_aktuell
    name: SOC tatsächlich
    statistics:
      type: mean
      period: hour
```



**Verbrauchszähler intern erzeugt – kein externer Recorder-Sensor mehr nötig**
- Bisher musste ein externer Sensor (`sensor.hauslast_stundlich`) manuell konfiguriert und vom HA-Recorder aufgezeichnet werden.
- Ab v1.1.2 genügt die Auswahl eines **Leistungssensors in Watt** (z. B. `sensor.alphaess_inverter_current_house_load` der AlphaESS Modbus TCP - Home Assistant Integration von senalse).
- Die Integration erzeugt daraus automatisch den Verbrauchszähler `sensor.hlf_hauslast_stundlich` (kWh, stetig steigend, TOTAL_INCREASING).
- Der Zähler wird via Riemann-Integral (links-Rechteck) aus den Zustandsänderungen des Leistungssensors akkumuliert.
- Der Zählerstand überlebt HA-Neustarts dank `RestoreEntity`.
- Konfiguration unter: Einstellungen → Sensoren → **Hauslast aktuell / House Load Current (Sensor in W)**

**Force-Export: input_boolean und switch wählbar**
- Das Feld „Force-Export aktiv" akzeptiert jetzt sowohl `input_boolean`- als auch `switch`-Entitäten.
- Ermöglicht die direkte Nutzung des Force-Charge/Export-Schalters der AlphaESS Modbus TCP - Home Assistant Integration von senalse.

**Neue Standardsensoren aus der AlphaESS Modbus TCP - Home Assistant Integration von senalse**
- Voreingestellte Sensor-IDs wurden auf die typischen Entitäten der AlphaESS Modbus TCP - Home Assistant Integration von senalse angepasst:
  - Akku-Ladestand: `sensor.alphaess_soc_battery`
  - Entladeschluss: `sensor.alphaess_discharging_cutoff_soc`
  - Force-Export aktiv: `switch.alphaess_force_charge`
  - Hauslast aktuell: `sensor.alphaess_inverter_current_house_load`

### v1.1.1

**Akku-Restlaufzeit: Sprünge durch Debounce behoben**
- Der Sensor `sensor.hlf_battery_runtime` sprang kurz nach dem Neustart oder bei instabilen Sensorwerten zwischen dem Maximalwert (2880 min) und dem echten Prognosewert.
- Ursache: Vergangene Slots (00:00 bis aktuelle Stunde) wurden fälschlicherweise in die Restlaufzeit-Berechnung einbezogen.
- Fix: Nur Slots mit `is_forecast: true` werden für die Restlaufzeit-Berechnung herangezogen.

**SOC-Prognose: Zeitfenster ausgeweitet**
- Der `soc_hourly_forecast` beginnt jetzt immer bei **00:00 Uhr** des heutigen Tages (statt erst bei der aktuellen Stunde).
- Stunden von 00:00 bis zur aktuellen Stunde sind als `is_forecast: false` gekennzeichnet (Ist-Platzhalter mit aktuellem Akkustand).
- Die echte Prognose läuft ab der aktuellen Stunde für die nächsten **48 Stunden**.

**SOC-Prognose: Prozent-Werte ergänzt**
- Jeder Eintrag in `soc_hourly_forecast` enthält jetzt zusätzlich `soc_pct` (0–100 %).
- 100 % = volle Akkukapazität (`bat_max_kwh`), 0 % = 0 kWh (nicht Cutoff).

**Neuer Diagnosesensor: `battery_empty_at`**
- Zeigt den Zeitpunkt an, zu dem der Akku laut Prognose leer wird (Format: `YYYY-MM-DD HH:MM`).
- Wert `false` bedeutet: Der Akku reicht laut Prognose durch den gesamten 48-h-Horizont (entspricht 2880 min Restlaufzeit).
- Auch als Attribut `battery_empty_at` im `sensor.hlf_battery_runtime` verfügbar.

**Hauslast-Prognose: Fehlender 00:00-Wert behoben**
- Im `forecast`-Attribut von `sensor.hlf_forecast_today` fehlte bisher der Wert für 00:00 Uhr.
- Der Forecast enthält jetzt immer alle 24 Stunden ab 00:00 des jeweiligen Tages.

**Neuer optionaler Sensor: PV-Prognose Übermorgen**
- Bisher endete die Prognose immer um 23:00 Uhr des Folgetages – unabhängig von der aktuellen Uhrzeit.
- Mit dem neuen optionalen Sensor `pv_forecast_day_after_tomorrow_sensor` (Solcast-Sensor für übermorgen) wird die Simulation auf **72 Slots (3 Tage)** erweitert und dann auf **48 Stunden ab jetzt** zugeschnitten.
- Der Sensor ist optional – ohne ihn verhält sich die Integration wie bisher.
- Konfiguration unter: Einstellungen → Geräte & Dienste → Hauslast Prognose → Konfigurieren → Sensoren anpassen

**Vergangene Hauslast-Prognosewerte werden eingefroren**
- Bisher wurden bei jeder Neuberechnung (z. B. nach einer Parameteränderung wie dem Historienzeitraum) auch bereits vergangene Stunden des Hauslast-Forecasts neu berechnet.
- Ab sofort werden vergangene Stunden beim ersten Aufruf eingefroren (`_frozen_hl_past_slots`) und bei Folgeberechnungen unverändert wiederverwendet.
- Der Cache wird täglich um Mitternacht geleert, damit der neue Tag immer frisch startet.
- Nach einem HA-Neustart werden die Werte beim ersten Durchlauf neu gesetzt – das ist gewollt.

**Neuer Sensor: Hauslast-Prognose Übermorgen**
- `sensor.hlf_forecast_day_after_tomorrow` analog zu `sensor.hlf_forecast_today` und `sensor.hlf_forecast_tomorrow`.
- Enthält die stündliche Hauslast-Prognose für übermorgen als `forecast`-Attribut (24 Einträge).
- Ermöglicht die direkte Nutzung der Übermorgen-Prognose im Dashboard.

**SOC-Simulation: Entladeschluss als untere Grenze**
- Bisher konnte `soc_kwh` in der Prognose auf 0 kWh fallen, auch wenn ein Entladeschluss (`discharging_cutoff_soc`) konfiguriert ist.
- Ab sofort wird `soc_kwh` nie unter `cutoff_kwh` (= `bat_capacity × cutoff_pct / 100`) gerechnet.
- Damit stimmt die Prognose mit dem realen Verhalten des Wechselrichters überein.

**Translation-Fix: Klartextbezeichnung für PV-Prognose Übermorgen**
- In den Einstellungen unter „Sensoren anpassen" wurde statt des Klartextnamens der technische Key `pv_forecast_day_after_tomorrow_sensor` angezeigt.
- Ursache: Der Übersetzungskey fehlte im Step `options.sensors` (der Options-Flow nutzt einen eigenen Step, nicht `options.init`).
- Jetzt korrekt in allen Steps: `config.user`, `options.sensors` und `options.init`.

**Dashboard-Diagramme: Zeitfenster angepasst**
- Akku-Prognose-Diagramm: Zeigt 00:00 bis jetzt + 48 h.
- Hauslast-Prognose-Diagramm: Zeigt 00:00 bis jetzt + 48 h (inkl. 00:00-Wert).

---

### v1.1.0
**Sensor-Namen & Entity-IDs auf Englisch umgestellt**
- Alle Sensor-Anzeigenamen und Entity-IDs sind jetzt englisch:
  - `sensor.hauslast_prognose_heute` → `sensor.house_load_forecast_today`
  - `sensor.hauslast_prognose_morgen` → `sensor.house_load_forecast_tomorrow`
  - `sensor.pv_akku_restlaufzeit_prognose` → `sensor.pv_battery_runtime_forecast`
- ⚠️ **Wichtig:** Nach dem Update müssen Dashboard-Karten und Automationen auf die neuen Entity-IDs angepasst werden. Alte Entitäten bitte manuell unter Einstellungen → Geräte & Dienste → Hauslast Prognose → Entitäten löschen.

**Zweisprachige Einstellungen (Deutsch/Englisch)**
- Alle Felder in der Einrichtung und den Einstellungen sind jetzt zweisprachig beschriftet

**Zwei README-Dateien**
- `README.md` — Deutsch
- `README.en.md` — Englisch

---

### v1.0.0
**Erstveröffentlichung auf HACS**
- Stündliche Hauslast-Prognose für heute und morgen auf Basis historischer Verbrauchsdaten
- 7 individuelle Tagesprofile (Montag bis Sonntag) – kein pauschales Wochentag/Wochenende mehr
- IQR-Ausreißerfilter: Messartefakte und Zählerresets werden automatisch herausgefiltert
- Konfigurierbarer Datenzeitraum: Von 1 Woche bis unbegrenzt (0 = gesamte Datenbasis)
- Fallback-Profile: Manuelle Stundenprofile für Werktage und Wochenenden (< 10 Tage Daten)
- Akku-Restlaufzeit: Stundengenaue SOC-Prognose kombiniert PV-Vorhersage, Hauslast und Akkustand
- Restore nach Neustart: Letzter Restlaufzeit-Wert bleibt nach HA-Neustart erhalten
- Getrennte Einstellungsmenüs für Sensoren und Fallback-Profile
- Brand-Icon über `brand/`-Ordner (HA ≥ 2026.3)

---
---

<a name="english"></a>
## English

🌍 [Deutsch](#deutsch) | **English**

### v2.1.2

**🆕 Two new sensors: Forecast Current Hour & Forecast Next Hour**
- **`sensor.hlf_forecast_current_hour`** – Forecasted house load consumption for the current hour (kWh). Reads the `load_estimate` of the current full hour from `forecast_heute`.
  - Attributes: `hour` (current hour), `load_estimate_w` (forecast value in watts)
  - Entity name (EN): *Forecast Current Hour* / (DE): *Hauslast-Prognose Aktuelle Stunde*
  - Icon: `mdi:home-clock`
- **`sensor.hlf_forecast_next_hour`** – Forecasted house load consumption for the next hour (kWh). Reads the `load_estimate` of the next full hour from `forecast_heute` — at hour 23, it automatically falls back to `forecast_morgen[0]` (= 00:00 tomorrow).
  - Attributes: `hour` (next hour), `is_tomorrow` (true when crossing into tomorrow), `load_estimate_w` (forecast value in watts)
  - Entity name (EN): *Forecast Next Hour* / (DE): *Hauslast-Prognose Nächste Stunde*
  - Icon: `mdi:home-clock-outline`
- Both sensors use `state_class: MEASUREMENT` and appear in HA long-term statistics.
- Translations added to all language files (strings.json, translations/de.json, translations/en.json).

### v2.1.1

**🐛 Critical bugfix: the v2.1.0 write throttle didn't take effect (feedback loop via the coordinator)**
- **Cause:** `hlf_hauslast_stundlich`/`hlf_hauslast_taglich` were additionally registered with the `HauslastCoordinator`. Its `async_refresh()` unconditionally calls `async_write_ha_state()` on **all** registered entities — a second write path completely independent of the v2.1.0 throttle. Since these sensors' own entity IDs were also listed in `watch_forecast`, every write triggered the next coordinator refresh after a 5s debounce, which wrote them again — a self-sustaining feedback loop at roughly 5-second intervals that effectively neutralized the 60s throttle from v2.1.0.
- **Fix:** `hauslast_stundlich_sensor`/`hauslast_taeglich_sensor` are no longer registered with `coordinator.async_register_entities()`. They already manage their recorder writes entirely on their own via `handle_power_update` (including the v2.1.0 throttle) and don't need the coordinator's blanket write.
- **Effect:** The 60-second throttle intended in v2.1.0 now actually takes effect. No behavior change for the other sensors (forecast, diagnostics, etc.) — they continue to be refreshed normally by the coordinator.

### v2.1.0

**⚡ Recorder load reduction: write throttle for `hlf_hauslast_stundlich` / `hlf_hauslast_taglich`**
- **Cause:** Both sensors accumulate the house-load power sensor via Riemann integration and called `async_write_ha_state()` on *every* state change of the source sensor (roughly once per second). Result: ~46,000 recorder rows/day per sensor, ~90,000/day combined.
- **Fix:** The accumulation (`_total_kwh`) still runs on every tick with unchanged accuracy. The recorder write is now throttled to at most once per 60s (`WRITE_MIN_INTERVAL_S`), with an immediate write on hour/day rollover so `hourly_history`/`daily_history` (and the MAE calculation built on it) stay current without delay.
- **Effect:** Cuts recorder load from these two sensors by roughly 98% with no loss of energy-accounting accuracy. Dashboards expecting second-by-second updates of the running counter will now see updates roughly every 60 seconds instead.

### v2.0.0

**🐛 Critical bugfix: Runtime shows 48h with empty battery**
- **Root cause:** The runtime calculation searched the 72h SOC forecast including PV production. When PV would recharge the battery within the next hour, the simulation showed "battery will never be empty" → fallback to 2880 min (48h) – even at 5% SOC with only 47 Wh usable energy.
- **Fix: Immediate check** – If the current SOC is already at or below the runtime threshold (cutoff + buffer), the runtime is immediately set to 0, regardless of the forecast.
- **Sawtooth pattern eliminated** – The oscillating pattern (675→674→673→2880→…) in history is gone, since low battery now immediately returns 0.

**🔋 New attribute: Battery-only runtime (`bat_only_runtime_min`)**
- Calculates how long the battery **alone** (without PV) can power the house load: `usable_kWh ÷ current_load_kW × 60`.
- Uses the average of the next 3 forecast hours for a stable value.
- Available as attribute on the `sensor.hlf_battery_runtime` sensor.

**🏗️ Repository brought to production quality (Silver Quality Scale)**
- Diagnostics platform (`diagnostics.py`) – download via device page → ⋮ → Diagnostics
- Quality Scale YAML (`quality_scale.yaml`) – Silver-tier tracking
- CI/CD: GitHub Actions for Hassfest, HACS validation, CodeQL, Ruff linting
- Release workflow: version in `manifest.json` is automatically set from the GitHub release tag
- `pyproject.toml` with Ruff configuration
- `hacs.json` cleaned (no `content_in_root`, no `hide_default_branch`)
- `manifest.json` keys sorted alphabetically after `domain`/`name`
- Issue templates (Bug Report, Feature Request)
- `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`, `SECURITY.md`
- Dependabot for GitHub Actions
- README badges (HACS, Release, License, CI status, Downloads)

### v1.2.1

**Battery runtime calculation fundamentally reworked**
- **Root cause:** The main simulation clamps SOC to `max(cutoff_kwh, ...)` — so `entry["soc_kwh"]` could never fall below cutoff, and the runtime warning was only triggered at the very last moment.
- **Fix:** A separate, unclamped simulation is now used for runtime detection. The SOC is allowed to fall below cutoff in this auxiliary simulation — the first slot where this happens is the real discharge point.
- **Early warning buffer:** The threshold defaults to `cutoff SOC + 2 %` for timely warnings.

**New configuration parameter: Runtime buffer (`runtime_buffer_pct`)**
- Under **Settings → Devices & Services → House Load Forecast → Configure → Sensors**, a new field appears: **Runtime Buffer (%)**.
- Slider: 0–20 %, step 0.5 %, default **2.0 %**.
- Defines how many percent above the configured cutoff SOC the early warning threshold is set. With 10 % cutoff and 2 % buffer, the runtime is calculated from 12 % SOC.
- Value 0 % = behaviour as before v1.2.1 (warning exactly at cutoff).

### v1.2.0

**New diagnostic sensor: `sensor.hlf_diag_soc_prognose_midnight` – SOC forecast frozen at midnight**
- Every day shortly after 00:00, a snapshot of the SOC simulation for the next **72 hours** is frozen.
- The sensor outputs the forecast value for the current hour every hour → complete time series in HA long-term statistics.
- The snapshot is stored persistently in `/config/.storage/houseload_forecast_midnight_snapshot.json` and survives HA restarts.
- Enables a comparison chart: *SOC forecast (midnight) vs. actual SOC*.
- Appears in the device view under **"Diagnostics"** (`EntityCategory.DIAGNOSTIC`).

**New diagnostic sensor: `sensor.hlf_diag_soc_aktuell` – Battery SoC for statistics**
- Mirrors the configured SoC sensor (%) as a standalone `MEASUREMENT` sensor into HA long-term statistics.
- Enables direct hourly comparison with `sensor.hlf_diag_soc_prognose_midnight` in ApexCharts via `statistics:`.
- Additional attributes: `quelle`, `bat_kwh`, `bat_max_kwh`, `aktualisiert`.
- Appears under **"Diagnostics"**.

**`sensor.hlf_diag_soc_pct_raw` removed**
- Replaced by `sensor.hlf_diag_soc_aktuell`, which provides the same value but additionally has `state_class: MEASUREMENT` for HA statistics.
- ⚠️ **Migration:** After updating, manually delete `sensor.hlf_diag_soc_pct_raw` under Settings → Devices & Services → House Load Forecast → Entities. Existing statistics data of the old sensor remain in the recorder.



**Consumption counter generated internally – no external recorder sensor required**
- Previously, an external sensor (`sensor.hauslast_stundlich`) had to be configured manually and recorded by the HA recorder.
- From v1.1.2, all that is needed is selecting a **power sensor in watts** (e.g. `sensor.alphaess_inverter_current_house_load` from the AlphaESS Modbus TCP - Home Assistant Integration by senalse).
- The integration automatically generates the consumption counter `sensor.hlf_hauslast_stundlich` (kWh, monotonically increasing, TOTAL_INCREASING).
- The counter is accumulated via Riemann left-rectangle integration from state changes of the power sensor.
- The counter value survives HA restarts thanks to `RestoreEntity`.
- Configure under: Settings → Sensors → **Hauslast aktuell / House Load Current (Sensor in W)**

**Force Export: input_boolean and switch selectable**
- The "Force Export Active" field now accepts both `input_boolean` and `switch` entities.
- Enables direct use of the Force Charge/Export switch from the AlphaESS Modbus TCP - Home Assistant Integration by senalse.

**New default sensors from the AlphaESS Modbus TCP - Home Assistant Integration by senalse**
- Pre-filled sensor IDs have been updated to the typical entities of the AlphaESS Modbus TCP - Home Assistant Integration by senalse:
  - Battery State of Charge: `sensor.alphaess_soc_battery`
  - Discharging Cutoff SoC: `sensor.alphaess_discharging_cutoff_soc`
  - Force Export Active: `switch.alphaess_force_charge`
  - House Load Current: `sensor.alphaess_inverter_current_house_load`

### v1.1.1

**Battery runtime: Fixed value jumps via debounce**
- `sensor.hlf_battery_runtime` was briefly jumping between the maximum value (2880 min) and the real forecast value after restarts or with unstable sensor readings.
- Root cause: Past slots (00:00 to current hour) were incorrectly included in the runtime calculation.
- Fix: Only slots with `is_forecast: true` are used for the runtime calculation.

**SOC forecast: Extended time window**
- `soc_hourly_forecast` now always starts at **00:00** of the current day (instead of the current hour).
- Hours from 00:00 to the current hour are marked as `is_forecast: false` (placeholder with current battery level).
- The actual forecast runs from the current hour for the next **48 hours**.

**SOC forecast: Percentage values added**
- Each entry in `soc_hourly_forecast` now also contains `soc_pct` (0–100 %).
- 100 % = full battery capacity (`bat_max_kwh`), 0 % = 0 kWh (not cutoff).

**New diagnostic sensor: `battery_empty_at`**
- Shows the point in time when the battery is forecast to be empty (format: `YYYY-MM-DD HH:MM`).
- Value `false` means: the battery is forecast to last through the full 48-h horizon (equivalent to 2880 min runtime).
- Also available as attribute `battery_empty_at` on `sensor.hlf_battery_runtime`.

**House load forecast: Missing 00:00 value fixed**
- The `forecast` attribute of `sensor.hlf_forecast_today` was previously missing the 00:00 entry.
- The forecast now always includes all 24 hours starting from 00:00 of the respective day.

**New optional sensor: PV Forecast Day After Tomorrow**
- Previously the forecast always ended at 23:00 of the following day — regardless of the current time.
- The new optional sensor `pv_forecast_day_after_tomorrow_sensor` (Solcast sensor for the day after tomorrow) extends the simulation to **72 slots (3 days)** and then trims it to **48 hours from now**.
- The sensor is optional — without it the integration behaves as before.
- Configure under: Settings → Devices & Services → House Load Forecast → Configure → Update sensors

**Past house load forecast values are now frozen**
- Previously, every recalculation (e.g. after changing a parameter such as the history weeks) also recalculated already past hours of the house load forecast.
- From now on, past hours are frozen on first calculation (`_frozen_hl_past_slots`) and reused unchanged in subsequent calculations.
- The cache is cleared daily at midnight so each new day always starts fresh.
- After an HA restart, values are recalculated on the first run — this is intentional.

**New sensor: House Load Forecast Day After Tomorrow**
- `sensor.hlf_forecast_day_after_tomorrow` analogous to `sensor.hlf_forecast_today` and `sensor.hlf_forecast_tomorrow`.
- Contains the hourly house load forecast for the day after tomorrow as a `forecast` attribute (24 entries).
- Enables direct use of the day-after-tomorrow forecast on the dashboard.

**SOC simulation: Discharge cutoff as lower limit**
- Previously `soc_kwh` in the forecast could drop to 0 kWh even when a discharge cutoff (`discharging_cutoff_soc`) is configured.
- From now on `soc_kwh` never falls below `cutoff_kwh` (= `bat_capacity × cutoff_pct / 100`).
- The forecast now matches the real behaviour of the inverter.

**Translation fix: Plain-text label for PV Forecast Day After Tomorrow**
- In the settings under "Update sensors", the technical key `pv_forecast_day_after_tomorrow_sensor` was shown instead of the plain-text label.
- Root cause: The translation key was missing in the `options.sensors` step (the options flow uses its own step, not `options.init`).
- Now correctly present in all steps: `config.user`, `options.sensors` and `options.init`.

**Dashboard charts: Time window adjusted**
- Battery forecast chart: Shows 00:00 to now + 48 h.
- House load forecast chart: Shows 00:00 to now + 48 h (including 00:00 entry).
---

### v1.1.0
**Sensor names & entity IDs changed to English**
- All sensor display names and entity IDs are now in English:
  - `sensor.hauslast_prognose_heute` → `sensor.house_load_forecast_today`
  - `sensor.hauslast_prognose_morgen` → `sensor.house_load_forecast_tomorrow`
  - `sensor.pv_akku_restlaufzeit_prognose` → `sensor.pv_battery_runtime_forecast`
- ⚠️ **Important:** After updating, dashboard cards and automations must be updated to use the new entity IDs. Please delete old entities manually under Settings → Devices & Services → Hauslast Prognose → Entities.

**Bilingual settings (German/English)**
- All fields in the setup and options flow are now labeled in both German and English

**Two README files**
- `README.md` — German
- `README.en.md` — English

---

### v1.0.0
**Initial release on HACS**
- Hourly house load forecast for today and tomorrow based on historical consumption data
- 7 individual daily profiles (Monday to Sunday) — no more generic weekday/weekend grouping
- IQR outlier filter: Measurement artifacts and counter resets are automatically filtered out
- Configurable history period: From 1 week to unlimited (0 = entire data history)
- Fallback profiles: Manual hourly profiles for weekdays and weekends (< 10 days of data)
- Battery runtime: Hourly SOC forecast combining PV forecast, house load and battery charge
- Restore after restart: Last known runtime value is preserved after HA restart
- Separate settings menus for sensors and fallback profiles
- Brand icon via `brand/` folder (HA ≥ 2026.3)
