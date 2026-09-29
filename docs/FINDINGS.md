# How the ScreenPad was found

[Version française](FINDINGS.fr.md)

Diagnostic notes, for anyone who wants to repeat the process on another ASUS
model.

## The initial trap

The ScreenPad does not appear anywhere:

```
card1-DP-1      disconnected   modes=[]
card1-DP-2      disconnected   modes=[]
card1-eDP-1     connected      modes=[2880x1800]
```

The first lead was to force `DP-1` and `DP-2`: writing to
`/sys/class/drm/*/status`, then building an EDID and injecting it through
`drm.edid_firmware`. The connector did switch to `connected`, but only exposed
generic VESA modes, with no display behind it.

Two mistakes to avoid:

1. The panel is not on DisplayPort but on HDMI-A-2.
2. A `disconnected` connector proves nothing while the panel is off.

## The right method: read the firmware

```sh
sudo pacman -S acpica
sudo acpidump -b && iasl -d dsdt.dat
```

Look in `dsdt.dsl` for the ASUS WMI method, `\_SB.ATKD.WMNB`. It dispatches
calls based on a method id encoded in ASCII:

| Id | ASCII | Role |
|---|---|---|
| `0x53545344` | `DSTS` | read a device |
| `0x53564544` | `DEVS` | write |

Then find the device ids of the `0x000500xx` family:

| Device id | Role | Known to the kernel |
|---|---|---|
| `0x00050031` | ScreenPad power | yes, but poorly exposed |
| `0x00050032` | brightness | yes |
| `0x00050033` | presence (returns a constant) | no |
| `0x00050034` | unknown, bit in the EC | no |
| `0x00050035` | unknown, EC commands `5`/`6` | no |

## Calling the method

`asus-wmi` does not expose a usable write on `0x00050031`, so the call goes
through `acpi_call`:

```sh
echo '\_SB.ATKD.WMNB 0x0 0x53564544 b3100050001000000' > /proc/acpi/call
```

The buffer holds the device id followed by the value, each on 4 bytes,
little-endian.

## The kernel driver bug

The `bl_power` attribute of the `asus_screenpad` backlight does not reflect the
real state and cannot power the panel back on:

| Step | `bl_power` | firmware state | display visible |
|---|---|---|---|
| panel on | 0 | `0x100a0` | yes |
| turned off by the firmware | 0 | `0x10000` | no |
| write `bl_power` 0/1/0 | 0 | `0x10000` | no |
| direct WMI call | 0 | `0x100a0` | yes |

The driver believes the panel is on while it is off, and its interface has no
effect. Worth reporting upstream.

## Touch

The HID descriptor declares two collections, `Touch Pad` (report 17) and
`Touch Screen` (report 1), plus an `Input Mode` (report 9, 3 bytes). Writing
`09 02 00` to request touchscreen mode is accepted without error but has no
effect: the collection is not implemented in the firmware.

What works: the pad already sends absolute multitouch coordinates
(`ABS_MT_POSITION_X/Y`) over 128×64 mm, exactly the 2:1 ratio of its display.
Reclassifying it through udev is enough.

## Brightness trap: a driver bug, not the firmware

Writing to `/sys/class/backlight/asus_screenpad/brightness` turns the panel
off: `0x00050031` drops to 0 and the connector disappears. This first looked
like a firmware limit ("low values turn it off, 200 is safe"). In fact a write
of 249 turns the panel off too, and the firmware accepts every value from 1 to
255 when called directly.

The culprit is `update_screenpad_bl_status()` in `asus-wmi` (Linux 7.1):

```c
if (bd->props.power) {            /* taken to mean "on"...               */
        /* power on, then set the brightness */
}
if (!bd->props.power) {           /* ...but 0 is BACKLIGHT_POWER_ON      */
        asus_wmi_set_devstate(ASUS_WMI_DEVID_SCREENPAD_POWER, 0, NULL);
}
```

`bl_power` is `0` (`BACKLIGHT_POWER_ON`) when the pad is on, and the test is
inverted. Every brightness write therefore sends the power-off command.
Reported on `platform-driver-x86` in September 2026: Denis Benato's series
*"fix screenpad backlight regression"* fixes this test. Ilpo Järvinen applied
it on 2026-09-18 (commits 159e956fd4f9, 341b4769f5cf, 99215e618ff2,
854be60ed0e9). It is not in distribution kernels yet.

Until then, brightness is set through the firmware, like power: DEVS on
`0x00050032`, value 1 to 255. `screenpad-power brightness <1-255>` does this,
and `screenpad-power brightness` reads the value back (low byte of DSTS
`0x00050032`, with `0xff` hard-coded as the maximum).

Measured on UX5400EA: 128, 64, 16 and 1 applied and read back unchanged, pad
still on.
