# Changelog

🌍 **Deutsch** | [English](#english)

---

## Deutsch

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
