# Samsung Find Native

Home Assistant custom integration for Samsung SmartTag2 via Samsung Find: Samsung Account login, no cookies or YAML.
Entities per tag: device_tracker, battery (percent estimate and level), last seen, accuracy, nearby, online, ring start/stop, firmware.
Requires the official SmartThings integration and the Android bridge app (login callback).

## Install

1. HACS → Custom repositories → `https://github.com/Drongo76/ha-samsung-find-native` → type **Integration** → install.
2. Restart Home Assistant.
3. Install `release/samsung-find-bridge.apk` on the Samsung phone (package `de.timdrongo.samsungfindbridge`).
4. Settings → Devices & services → Add integration → **Samsung Find Native** and sign in with Samsung Account.
   Home Assistant needs an external HTTPS URL. The bridge reads the HA address from each start, so moving to another server needs no reinstall.

## Notes

- SmartThings reports only 4 battery levels; the percent is an estimate (`estimated: true`).
- Tokens are stored in the config entry and refreshed automatically; reauth is supported.
- Tag position is a hint only: it never confirms presence by itself.
- `android-bridge/` holds the bridge app source (plain Gradle, debug APK).
