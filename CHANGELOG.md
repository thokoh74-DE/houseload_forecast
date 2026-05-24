# Changelog

🌍 **Deutsch** | [English](#english)

---

## Deutsch

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
