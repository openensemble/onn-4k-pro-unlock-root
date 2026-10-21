package local.onn.magiskusb;

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
 * One-use USB Magisk boot candidate; retains a gate-controlled stock fallback.
 * Restricts writes to one known record on one exact firmware.
 * Does not reboot, flash firmware, alter other keys, or wipe data.
 */
public final class MagiskUsbReceiver extends BroadcastReceiver {
    private static final String FINGERPRINT =
            "onn/jarvis/SNA:14/URO4.260304.011.B1/15051976:user/release-keys";
    private static final String PREFIX = "local.onn.magiskusb.";
    private static final String KEY = "ubootenv.var.storeboot";
    private static final String ORIGINAL = "run storeboot_base;";
    private static final String CANDIDATE = "setenv onn26_armed no; if usb start; then if fatsize usb 0:1 ONN26/ONNARM26.TXT; then if fatrm usb 0:1 ONN26/ONNARM26.TXT; then if fatsize usb 0:1 ONN26/ONNARM26.TXT; then setenv onn26_armed no; else setenv onn26_armed yes; fi; fi; fi; fi; if test ${onn26_armed} = yes; then run get_os_type;run storage_param;if test ${os_type} = rtos; then setenv loadaddr ${loadaddr_rtos};store read ${loadaddr} ${boot_part} 0 0x400000;bootm ${loadaddr};else if test ${os_type} = kernel; then get_system_as_root_mode;echo system_mode in storeboot: ${system_mode};echo active_slot in storeboot: ${active_slot};if test ${system_mode} = 1; then setenv bootargs \"${bootargs} ro rootwait skip_initramfs\";else setenv bootconfig \"${bootconfig} androidboot.force_normal_boot=1\";fi;if test ${active_slot} != normal; then setenv bootconfig \"${bootconfig} androidboot.slot_suffix=${active_slot}\";fi;setenv bootconfig \"${bootconfig} androidboot.rollback=${rollback_flag}\";if fdt addr ${dtb_mem_addr}; then test 1 = 1; else echo retry common dtb; run common_dtb_load; fi;setenv loadaddr ${loadaddr_kernel};if imgread kernel ${boot_part} ${loadaddr}; then if itest.l ${loadaddr} == 0x3000000; then if itest.l *0xbf621d24 == 0xa9bc7bfd; then if itest.l *0xbf7c047c == 0; then if load usb 0:1 ${loadaddr} ONN26/ONNRT26.IMG; then if test ${filesize} = dc4000; then if itest.l *0x3000000 == 0x52444e41; then if itest.l *0x3000004 == 0x2144494f; then if itest.l *0x3000008 == 0xc09944; then if itest.l *0x300000c == 0x1b8e5c; then if itest.l *0x3000028 == 0x4; then setenv bootargs \"${bootargs} androidboot.onn_rootprobe=ONN-MAGISK-26-20261021\"; setenv bootconfig \"${bootconfig} androidboot.onn_rootprobe=ONN-MAGISK-26-20261021\"; if dcache flush; then if icache flush; then if fatwrite usb 0:1 ${loadaddr} ONN26/ONNHD26.BIN 0x1000; then bootm ${loadaddr}; fi; fi; fi; fi; fi; fi; fi; fi; fi; fi; fi; fi; fi; reset; fi;else echo wrong OS format ${os_type}; fi;fi;reset; else run storeboot_base; fi;";

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
                report.put("storeboot_base", readValue(service, api, "getBootEnv", "ubootenv.var.storeboot_base"));
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
