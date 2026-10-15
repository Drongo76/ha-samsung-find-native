from __future__ import annotations

DOMAIN = "samsung_find_native"
PLATFORMS = ["device_tracker", "sensor", "binary_sensor", "button"]

CONF_COUNTRY = "country"
CONF_LANGUAGE = "language"
CONF_PHYSICAL_ADDRESS = "physical_address"
CONF_AUTH_SERVER_URL = "auth_server_url"
CONF_USERAUTH_TOKEN = "userauth_token"
CONF_USER_ID = "user_id"
CONF_LOGIN_ID = "login_id"
CONF_FIND_TOKEN = "find_token"
CONF_IOT_TOKEN = "iot_token"
CONF_PIN = "pin"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_SMARTTHINGS_ENTRY_ID = "smartthings_entry_id"

DEFAULT_COUNTRY = "DE"
DEFAULT_LANGUAGE = "de"
DEFAULT_UPDATE_INTERVAL = 120
MIN_UPDATE_INTERVAL = 30
MAX_UPDATE_INTERVAL = 3600

AUTH_CLIENT_ID = "yfrtglt53o"
FIND_CLIENT_ID = "27zmg0v1oo"
IOT_CLIENT_ID = "6iado3s6jc"
FIND_SCOPE = "offline.access"
IOT_SCOPE = "iot.client"
REDIRECT_URI = "ms-app://s-1-15-2-4027708247-2189610-1983755848-2937435718-1578786913-2158692839-1974417358"
ENTRY_POINT_URL = "https://account.samsung.com/accounts/ANDROIDSDK/getEntryPoint"

SMARTTHINGS_APP_VERSION = "1.8.21.28"
SMARTTHINGS_USER_AGENT = (
    "Android/OneApp/1.8.21.28/Main "
    "(Google Pixel 8 Pro; Android 14/14) SmartKit/4.423.1"
)
FME_PLUGIN_ID = "com.samsung.android.plugin.fme"

BATTERY_LEVELS = ('very_low', 'low', 'medium', 'full', 'unknown')
BATTERY_PERCENT_ESTIMATE = {'very_low': 10, 'low': 30, 'medium': 60, 'full': 100}

CONF_OFFLINE_AFTER = 'offline_after'
DEFAULT_OFFLINE_AFTER = 180
MIN_OFFLINE_AFTER = 10
MAX_OFFLINE_AFTER = 1440

MODEL_NAMES = {'EI-T5600': 'Galaxy SmartTag2'}
SERVICE_RING = 'ring'
ATTR_ACTION = 'action'

BRIDGE_APK_URL = (
    "https://github.com/Drongo76/ha-samsung-find-native/blob/main/release/samsung-find-bridge.apk"
)

HINT_KEY = 'location_hint'
HINT_MAX_AGE_MINUTES = 30
HINT_MAX_ACCURACY = 200
