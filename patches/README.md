# Upstream patches

[Version française](README.fr.md)

Patches found during this work, intended for the projects concerned. They are
kept here so they can be cited and reproduced until they are submitted
upstream.

## `0001-elan-retry-on-transient-not-ready-status-for-all-dev.patch`

**Project:** [libfprint](https://gitlab.freedesktop.org/libfprint/libfprint)
**File:** `libfprint/drivers/elan.c`

In `CAPTURE_READ_DATA`, retrying on the transient states `0x00` (not ready)
and `0xaf` (busy) is hard-coded for the `ELAN_0C58` model only. The 60 other
sensors in the table get `FP_DEVICE_ERROR_PROTO`, which aborts enrollment.

Seen on an Elan `04f3:0c6e` (ASUS ZenBook 14X OLED UX5400EA), where enrollment
always failed:

```
[elan] CAPTURE_NUM_STATES entering state 2
[elan] SSM CAPTURE_NUM_STATES failed in state 2 with error:
       The driver encountered a protocol error with the device.
```

`libfprint-image_device` also reported the resulting illegal transition,
`AWAIT_FINGER_ON` → `AWAIT_FINGER_OFF`, repeated every ten seconds without ever
reaching `CAPTURE`.

With the patch, enrollment succeeds. The behaviour of the `0x0c58` is
unchanged.

### Applying

```sh
git clone https://gitlab.freedesktop.org/libfprint/libfprint.git
cd libfprint
git am < 0001-elan-retry-on-transient-not-ready-status-for-all-dev.patch
meson setup build -Ddoc=false -Dgtk-examples=false \
      -Dudev_rules=disabled -Dudev_hwdb=disabled -Dintrospection=false
ninja -C build
```

### Known limitation

This patch makes enrollment possible, not reliable: the `04f3:0c6e` is a
149×51 pixel strip, and the measured match scores stay well below the
threshold (0 to 19 for a threshold of 24). Usable for testing, not for
authentication.
