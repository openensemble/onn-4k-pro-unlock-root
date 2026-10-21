package local.onn.secureread;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.Process;
import java.io.File;
import java.io.FileOutputStream;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.json.JSONArray;
import org.json.JSONObject;

/**
 * One-use bounded runtime code read; retains the stock boot path and verification.
 * Restricts writes to one known record on one exact firmware.
 * Does not reboot, flash firmware, alter other keys, or wipe data.
 */
public final class SecureReadReceiver extends BroadcastReceiver {
    private static final String FINGERPRINT =
            "onn/jarvis/SNA:14/URO4.260304.011.B1/15051976:user/release-keys";
    private static final String PREFIX = "local.onn.secureread.";
    private static final String KEY = "ubootenv.var.storeboot";
    private static final String ORIGINAL = "run storeboot_base;";
    private static final String CANDIDATE = "setenv onn23_reset no; setenv onn23_gate not_consumed; if usb start; then if fatsize usb 0:1 ONN23/ONNARM23.TXT; then if fatrm usb 0:1 ONN23/ONNARM23.TXT; then if fatsize usb 0:1 ONN23/ONNARM23.TXT; then setenv onn23_gate removal_unverified; else setenv onn23_gate consumed; setenv onn23_load failed; setenv onn23_start skipped; setenv onn23_checkpoint skipped; setenv onn23_go skipped; setenv onn23_saved no; setenv onn23_stage before_load; if env export -t 0x3100000; then if fatwrite usb 0:1 0x3100000 ONN23/ONNST23.TXT ${filesize}; then if load usb 0:1 0x3000000 ONN23/ONNPRO23.IMG; then setenv onn23_load ok; if test ${filesize} = 840; then if itest.l *0x3000040 == 0x10003002; then if itest.l *0x3000640 == 0x5a5a5a5a; then if dcache flush; then if icache flush; then setenv onn23_start failed; if bootm start 0x3000000; then setenv onn23_start ok; setenv onn23_stage before_entry; if env export -t 0x3100000; then if fatwrite usb 0:1 0x3100000 ONN23/ONNST23.TXT ${filesize}; then setenv onn23_early_trace updated; fi; fi; setenv onn23_checkpoint write_failed; if fatwrite usb 0:1 0x3000000 ONN23/ONNBEG23.BIN 0x840; then setenv onn23_checkpoint size_failed; if fatsize usb 0:1 ONN23/ONNBEG23.BIN; then if test ${filesize} = 840; then setenv onn23_checkpoint saved; setenv autostart yes; setenv onn23_go entered; if bootm go; then setenv onn23_go returned_zero; fi; fi; fi; fi; fi; if itest.l *0x3000644 == 5; then setenv onn23_reset yes; fi; dcache flush; icache flush; if usb start; then if fatwrite usb 0:1 0x3000000 ONN23/ONNRET23.BIN 0x840; then setenv onn23_saved yes; fi; fi; fi; fi; fi; fi; fi; fi; fi; fi; if env export -t 0x3000000; then if fatwrite usb 0:1 0x3000000 ONN23/ONNCAP23.TXT ${filesize}; then setenv onn23_capture saved; fi; fi; fi; fi; fi; fi; if test ${onn23_reset} = yes; then reset; else run storeboot_base; fi;";

    private static String read(Object service, Class<?> api) throws Exception {
        return readValue(service, api, "getBootEnv", KEY);
    }

    private static String readValue(Object service, Class<?> api,
                                    String name, String argument) throws Exception {
        Method method = null;
        for (Method candidate : api.getMethods()) {
            if (candidate.getName().equals(name)
                    && candidate.getParameterTypes().length == 2) {
                method = candidate;
                break;
            }
        }
        if (method == null) throw new NoSuchMethodException(name);
        final String[] result = {null};
        Class<?> callbackType = method.getParameterTypes()[1];
        Object callback = Proxy.newProxyInstance(callbackType.getClassLoader(),
                new Class<?>[]{callbackType}, (proxy, called, args) -> {
                    if (called.getName().equals("onValues")) {
                        if (((Number) args[0]).intValue() != 0) {
                            throw new IllegalStateException(name + " read failed");
                        }
                        result[0] = (String) args[1];
                    }
                    return null;
                });
        method.invoke(service, argument, callback);
        if (result[0] == null) throw new IllegalStateException("No read result");
        return result[0];
    }

    private static JSONObject diskPrefix(Object service, Class<?> api) {
        JSONObject result = new JSONObject();
        try {
            // This endpoint replaces embedded NUL bytes with spaces and reads at
            // most 4096 bytes. It is a lossy observation, never a partition backup.
            String prefix = readValue(service, api, "readSysfs", "/dev/block/by-name/env");
            byte[] hash = MessageDigest.getInstance("SHA-256")
                    .digest(prefix.getBytes(StandardCharsets.UTF_8));
            StringBuilder hex = new StringBuilder();
            for (byte b : hash) hex.append(String.format("%02x", b & 255));
            result.put("characters", prefix.length());
            result.put("transformed_prefix_sha256", hex.toString());
            result.put("is_raw_backup", false);
            JSONArray locks = new JSONArray();
            Matcher matcher = Pattern.compile("(?:^| )lock=([01]{8})(?: |$)").matcher(prefix);
            while (matcher.find()) locks.put(matcher.group(1));
            result.put("lock_values_in_prefix", locks);
        } catch (Throwable error) {
            try {
                result.put("error", error.toString());
                if (error.getCause() != null) result.put("cause", error.getCause().toString());
            } catch (Exception ignored) { }
        }
        return result;
    }

    private static void save(Context context, JSONObject report) throws Exception {
        try (FileOutputStream out = new FileOutputStream(
                new File(context.getFilesDir(), "report.json"))) {
            out.write(report.toString(2).getBytes(StandardCharsets.UTF_8));
            out.getFD().sync();
        }
    }

    @Override public void onReceive(Context context, Intent intent) {
        String action = intent.getAction();
        if (!(PREFIX + "INSPECT").equals(action)
                && !(PREFIX + "NOOP").equals(action)
                && !(PREFIX + "RESTART_SERVICE").equals(action)
                && !(PREFIX + "APPLY").equals(action)
                && !(PREFIX + "RESTORE").equals(action)) return;
        PendingResult pending = goAsync();
        new Thread(() -> {
            JSONObject report = new JSONObject();
            try {
                report.put("action", action);
                report.put("started_at_unix_ms", System.currentTimeMillis());
                report.put("uid", Process.myUid());
                report.put("fingerprint", Build.FINGERPRINT);
                report.put("key", KEY);
                report.put("set_boot_env_called", false);
                report.put("persistent_change_requested", false);
                report.put("service_restart_requested", false);
                report.put("persistence_verified", false);
                report.put("stage", "checking");
                save(context, report);
                if (!FINGERPRINT.equals(Build.FINGERPRINT)) {
                    throw new IllegalStateException("Firmware mismatch");
                }
                Class<?> api = Class.forName(
                        "vendor.amlogic.hardware.systemcontrol.V1_1.ISystemControl");
                Object service = api.getMethod("getService", String.class, boolean.class)
                        .invoke(null, "default", false);
                if (service == null) throw new IllegalStateException("No service");
                String before = read(service, api);
                report.put("before", before);
                report.put("disk_prefix_before", diskPrefix(service, api));
                String serviceStat = readValue(service, api, "readSysfs", "/proc/self/stat");
                report.put("service_pid", Integer.parseInt(serviceStat.substring(0, serviceStat.indexOf(' '))));
                if ((PREFIX + "RESTART_SERVICE").equals(action)) {
                    if (!"explicitly-authorized".equals(intent.getStringExtra("restart_authorization"))) {
                        throw new IllegalStateException("Explicit restart invocation required");
                    }
                    report.put("stage", "about_to_restart_service");
                    report.put("service_restart_requested", true);
                    save(context, report);
                    try {
                        api.getMethod("setProperty", String.class, String.class)
                                .invoke(service, "ctl.restart", "system_control");
                        report.put("restart_call_returned", true);
                    } catch (Throwable error) {
                        // A restarted service can die before replying. Host must
                        // confirm a new PID; this exception alone proves nothing.
                        report.put("restart_call_error", error.toString());
                        if (error.getCause() != null) report.put("restart_call_cause", error.getCause().toString());
                    }
                } else if (!(PREFIX + "INSPECT").equals(action)) {
                    boolean noop = (PREFIX + "NOOP").equals(action);
                    boolean apply = (PREFIX + "APPLY").equals(action);
                    String expected = (apply || noop) ? ORIGINAL : CANDIDATE;
                    String target = apply ? CANDIDATE : ORIGINAL;
                    if (!expected.equals(before)) {
                        throw new IllegalStateException("Unexpected current storeboot; no write");
                    }
                    if (!noop && !"explicitly-authorized".equals(intent.getStringExtra("write_authorization"))) {
                        throw new IllegalStateException("Explicit write invocation required");
                    }
                    report.put("target", target);
                    report.put("persistent_change_requested", !noop);
                    report.put("stage", "about_to_write");
                    save(context, report);
                    Method setter = api.getMethod("setBootEnv", String.class, String.class);
                    report.put("setter_return_type", setter.getReturnType().getName());
                    Object setterResult = setter.invoke(service, KEY, target);
                    report.put("set_boot_env_called", true);
                    report.put("setter_return_value", setterResult == null ? JSONObject.NULL : setterResult);
                    report.put("same_value_noop", noop);
                    String after = read(service, api);
                    report.put("after", after);
                    report.put("disk_prefix_after", diskPrefix(service, api));
                    report.put("readback_matches", target.equals(after));
                    if (!target.equals(after)) {
                        throw new IllegalStateException("Readback did not match target");
                    }
                }
                report.put("stage", "complete");
                report.put("bootloader_unlock_verified", false);
                report.put("reboot_performed", false);
            } catch (Throwable error) {
                try {
                    report.put("error", error.toString());
                    if (error.getCause() != null) {
                        report.put("cause", error.getCause().toString());
                    }
                    report.put("stage", "failed");
                } catch (Exception ignored) { }
            } finally {
                try { save(context, report); } catch (Exception ignored) { }
                pending.finish();
            }
        }, "usb-capability-experiment").start();
    }
}
