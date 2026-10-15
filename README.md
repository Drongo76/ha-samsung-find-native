# Samsung Find Native

Home Assistant custom integration for Samsung SmartTag2 via Samsung Find: Samsung Account login, no cookies or YAML.
Entities per tag: device_tracker, battery (percent estimate and level), last seen, accuracy, nearby, online, ring start/stop, firmware.
Requires the official SmartThings integration and the Android bridge app (login callback). **The Samsung sign-in works only on the Android phone with the bridge installed, not on a PC**: run the setup in the Home Assistant app on that phone. Without the bridge APK the login will not work.

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

## Disclaimer

Unofficial, private project. Not affiliated with, endorsed by or supported by Samsung. It uses an unofficial way to access Samsung Find and may stop working at any time.
Provided "as is", without warranty of any kind. Use at your own risk: the author takes no responsibility or liability for any damage, data loss, account problems or other consequences. See also sections 15 and 16 of the [LICENSE](LICENSE).

Неофициальный личный проект, не связан с Samsung. Используется на свой страх и риск, автор не несёт никакой ответственности за последствия.

## License

GPL-3.0, see [LICENSE](LICENSE). Free to use, change and share.
