package de.timdrongo.samsungfindbridge;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.view.Gravity;
import android.view.ViewGroup;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URI;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity {
    private static final String PREFS = "bridge";
    private static final String PREF_HA_BASE = "ha_base";
    private static final String CALLBACK_HOST =
        "s-1-15-2-4027708247-2189610-1983755848-2937435718-1578786913-2158692839-1974417358";

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private TextView status;
    private ProgressBar progress;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        buildUi();
        handleIntent(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleIntent(intent);
    }

    @Override
    protected void onDestroy() {
        executor.shutdownNow();
        super.onDestroy();
    }

    private void buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER);
        int pad = dp(32);
        root.setPadding(pad, pad, pad, pad);

        progress = new ProgressBar(this);
        root.addView(progress, new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.WRAP_CONTENT,
            ViewGroup.LayoutParams.WRAP_CONTENT
        ));

        status = new TextView(this);
        status.setTextSize(18f);
        status.setTextColor(Color.WHITE);
        status.setGravity(Gravity.CENTER);
        status.setPadding(0, dp(24), 0, 0);
        status.setText("Samsung Find wird vorbereitet …");
        root.addView(status, new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.WRAP_CONTENT
        ));

        root.setBackgroundColor(Color.rgb(24, 24, 24));
        setContentView(root);
    }

    private void handleIntent(Intent intent) {
        Uri data = intent != null ? intent.getData() : null;
        if (data == null) {
            showError("Bitte die Einrichtung in Home Assistant starten.");
            return;
        }

        String scheme = data.getScheme();
        if ("samsungfindbridge".equalsIgnoreCase(scheme)
                && "start".equalsIgnoreCase(data.getHost())) {
            handleStart(data);
            return;
        }

        if ("ms-app".equalsIgnoreCase(scheme)
                && CALLBACK_HOST.equalsIgnoreCase(data.getHost())) {
            handleSamsungCallback(data.toString());
            return;
        }

        showError("Unbekannter Samsung-Find-Aufruf.");
    }

    private void handleStart(Uri data) {
        String flowId = safe(data.getQueryParameter("flow_id"));
        String nonce = safe(data.getQueryParameter("nonce"));
        String haBase = normalizeHttpsBase(safe(data.getQueryParameter("ha")));

        if (flowId.isEmpty() || nonce.isEmpty() || haBase == null) {
            showError("Ungültige Home-Assistant-Einrichtung.");
            return;
        }

        getSharedPreferences(PREFS, MODE_PRIVATE)
            .edit()
            .putString(PREF_HA_BASE, haBase)
            .apply();

        setStatus("Samsung-Anmeldung wird vorbereitet …");
        executor.execute(() -> {
            try {
                JSONObject request = new JSONObject();
                request.put("flow_id", flowId);
                request.put("nonce", nonce);
                request.put(
                    "device_id",
                    Settings.Secure.getString(
                        getContentResolver(),
                        Settings.Secure.ANDROID_ID
                    )
                );
                request.put("manufacturer", Build.MANUFACTURER);
                request.put("model", Build.MODEL);
                request.put("os_version", Integer.toString(Build.VERSION.SDK_INT));

                JSONObject response = postJson(
                    haBase + "/api/samsung_find_native/prepare",
                    request
                );
                String loginUrl = response.optString("login_url", "");
                if (!response.optBoolean("ok", false) || loginUrl.isEmpty()) {
                    throw new IllegalStateException("Keine Samsung-Anmeldeadresse erhalten");
                }

                runOnUiThread(() -> openSamsungLogin(loginUrl));
            } catch (Exception exc) {
                runOnUiThread(() ->
                    showError("Samsung-Anmeldung konnte nicht gestartet werden.")
                );
            }
        });
    }

    private void handleSamsungCallback(String redirectUri) {
        SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        String haBase = normalizeHttpsBase(prefs.getString(PREF_HA_BASE, ""));
        if (haBase == null) {
            showError("Bitte die Einrichtung zuerst in Home Assistant starten.");
            return;
        }

        setStatus("Samsung-Anmeldung wird abgeschlossen …");
        executor.execute(() -> {
            try {
                JSONObject request = new JSONObject();
                request.put("redirect_uri", redirectUri);

                JSONObject response = postJson(
                    haBase + "/api/samsung_find_native/callback",
                    request
                );
                if (!response.optBoolean("ok", false)) {
                    throw new IllegalStateException("Callback abgelehnt");
                }

                runOnUiThread(this::finishSuccess);
            } catch (Exception exc) {
                runOnUiThread(() ->
                    showError("Samsung-Anmeldung konnte nicht abgeschlossen werden.")
                );
            }
        });
    }

    private void openSamsungLogin(String loginUrl) {
        setStatus("Samsung Account wird geöffnet …");
        try {
            Intent browser = new Intent(Intent.ACTION_VIEW, Uri.parse(loginUrl));
            startActivity(browser);
            finish();
        } catch (Exception exc) {
            showError("Samsung Account konnte nicht geöffnet werden.");
        }
    }

    private void finishSuccess() {
        progress.setVisibility(ProgressBar.GONE);
        status.setText("Samsung Find verbunden");
        status.postDelayed(() -> {
            try {
                Intent ha = new Intent(
                    Intent.ACTION_VIEW,
                    Uri.parse("homeassistant://navigate/config/integrations")
                );
                ha.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                startActivity(ha);
            } catch (Exception ignored) {
                // Home Assistant will still finish the config flow server-side.
            }
            finishAndRemoveTask();
        }, 900);
    }

    private JSONObject postJson(String endpoint, JSONObject body) throws Exception {
        URL url = new URL(endpoint);
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        connection.setConnectTimeout(15000);
        connection.setReadTimeout(30000);
        connection.setInstanceFollowRedirects(false);
        connection.setRequestMethod("POST");
        connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
        connection.setRequestProperty("Accept", "application/json");
        connection.setDoOutput(true);

        byte[] payload = body.toString().getBytes(StandardCharsets.UTF_8);
        connection.setFixedLengthStreamingMode(payload.length);
        try (OutputStream out = connection.getOutputStream()) {
            out.write(payload);
        }

        int code = connection.getResponseCode();
        InputStream stream =
            code >= 200 && code < 300
                ? connection.getInputStream()
                : connection.getErrorStream();

        String responseBody = readAll(stream);
        connection.disconnect();

        if (code < 200 || code >= 300) {
            throw new IllegalStateException("HTTP " + code);
        }
        return new JSONObject(responseBody);
    }

    private static String readAll(InputStream stream) throws Exception {
        if (stream == null) {
            return "";
        }
        StringBuilder result = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(stream, StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                result.append(line);
            }
        }
        return result.toString();
    }

    private static String normalizeHttpsBase(String value) {
        try {
            URI uri = URI.create(value);
            if (!"https".equalsIgnoreCase(uri.getScheme()) || uri.getHost() == null) {
                return null;
            }
            String port =
                uri.getPort() > 0 && uri.getPort() != 443
                    ? ":" + uri.getPort()
                    : "";
            return "https://" + uri.getHost() + port;
        } catch (Exception exc) {
            return null;
        }
    }

    private static String safe(String value) {
        return value == null ? "" : value.trim();
    }

    private void setStatus(String text) {
        progress.setVisibility(ProgressBar.VISIBLE);
        status.setText(text);
    }

    private void showError(String text) {
        progress.setVisibility(ProgressBar.GONE);
        status.setText(text);
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}
