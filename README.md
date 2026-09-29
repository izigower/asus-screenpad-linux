# asus-screenpad-linux

[Version française](README.fr.md)

Makes the ScreenPad of an ASUS ZenBook work on Linux, both as a second display
and as a touch surface.

Tested on a ZenBook 14X OLED UX5400EA (ScreenPad 2.0, 2160×1080).

![ScreenPad home screen](docs/captures/home.png)

## Problem

On Linux the ScreenPad does not show up. No extra display appears and every
DisplayPort connector reports `disconnected`, exactly like an empty port.

No driver is missing: the firmware leaves the panel powered off, and a panel
that is off cannot be told apart from one that is absent.

Existing projects (`asus-wmi-screenpad`, `screenpad-tools`,
`asus-screenpad-control`) only handle the brightness of a ScreenPad that is
already on, or work at the compositor level. None of them powers the panel on.

## Solution

The firmware has an ACPI method for it, which the kernel `asus-wmi` driver does
not expose:

```
\_SB.ATKD.WMNB → DEVS method → device id 0x00050031 ← ScreenPad power
```

Once the panel is powered, the connector becomes `connected` and the display
can be used like any other.

## Installation

```sh
sudo ./install.sh
```

Requires `acpi_call-dkms` (Arch) or `acpi-call-dkms` (Debian/Ubuntu).

## Usage

```sh
screenpad-power on               # power the panel on
screenpad-power off              # power it off
screenpad-power status           # 0x100a0 = on, 0x10000 = off
screenpad-power brightness 128   # brightness, 1 to 255 (no value: read it)

screenpad-touchmode touch        # the pad acts as a touchscreen
screenpad-touchmode pointer      # the pad acts as a touchpad again
```

`screenpad.service` powers the panel on at boot and after every resume, since
the firmware turns it off each time.

## Display setup

The panel reports itself as portrait 1080×2160 and needs to be rotated. With
Hyprland:

```lua
hl.monitor({ output = "HDMI-A-2", mode = "1080x2160@60",
             position = "0x900", scale = 2, transform = 3 })
```

The connector is HDMI-A-2, not a DisplayPort one. Check yours with
`hyprctl monitors` or `drm_info` once the panel is on.

## Touch

The pad cannot be a touchpad and a touchscreen at the same time. Windows has
the same limitation and switches between the two with a three-finger gesture.

`screenpad-touchmode` reclassifies the device through udev. The firmware
ignores the standard method (the `Input Mode` field of the HID descriptor is
accepted, then ignored), so this is the only way.

In touch mode, the compositor also needs to know which display the surface
maps to:

```lua
hl.device({ name = "gdx1515:00-27c6:01f4-touchpad", output = "HDMI-A-2" })
```

## Hyprland tools

The [`hyprland/`](hyprland/) folder contains a launcher inspired by ASUS
ScreenXpert: home screen over the desktop wallpaper, navigation bar, Control
Center, Number Key, Quick Key, App Navigator and a touchpad mode. A three-state
cycle reproduces `Fn+F6` from Windows.

| Number Key | Touchpad mode |
|---|---|
| ![Number Key](docs/captures/number-key.png) | ![Touchpad mode](docs/captures/mode-trackpad.png) |

[`docs/FINDINGS.md`](docs/FINDINGS.md) describes how the method was
found: decompiling the DSDT to get the WMI ids, and what the other undocumented
ids do.

## Brightness warning

Do not write to `/sys/class/backlight/asus_screenpad` (`brightnessctl`, desktop
brightness slider…). Up to at least Linux 7.1, `asus-wmi` reads the power state
inverted, so every brightness change through sysfs powers the panel off,
whatever the value. The connector and the display disappear.

Use `screenpad-power brightness <1-255>` instead, which goes through the
firmware. The kernel fix has been accepted (see
[`docs/FINDINGS.md`](docs/FINDINGS.md#brightness-trap-a-driver-bug-not-the-firmware)).
If the pad went off, run `screenpad-power on`.

## License

GPL-2.0-or-later, like the projects this work builds on.

This project is not affiliated with or endorsed by ASUS. ASUS, ZenBook,
ScreenPad and ScreenXpert are trademarks of ASUSTeK Computer Inc. No ASUS code
or assets are included: the interface is a reimplementation.

---

*Co-written with Claude Opus 5.5.*
