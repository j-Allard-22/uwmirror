# Starting uwmirror automatically at logon

uwmirror ships two commands: `uwmirror` (console, shows logs) and `uwmirrorw`
(no console window — this is the one you want for autostart; it logs to
`%APPDATA%\uwmirror\uwmirror.log` instead).

## 1. Pin your display indices first

Display auto-detection is fine interactively, but autostart should be
deterministic. Run:

```
uwmirror diagnose
```

and save the suggested `source`/`target` lines into
`%APPDATA%\uwmirror\config.toml`. With the config in place, `uwmirrorw` needs
no arguments.

## 2. Find the executable path

```
where uwmirrorw
```

(For a pipx install this is typically `%USERPROFILE%\.local\bin\uwmirrorw.exe`.)

## 3. Create the scheduled task

Run in a regular (non-admin) prompt, substituting the path from step 2:

```
schtasks /Create /TN "uwmirror" /TR "\"C:\Users\you\.local\bin\uwmirrorw.exe\"" /SC ONLOGON /DELAY 0000:20 /F
```

**Why the 20-second delay:** at logon, Windows is still enumerating displays.
Starting immediately can grab the wrong monitor indices or fail to find the
TV at all (OBS's projector has the same race). Twenty seconds is comfortably
after the display topology settles.

## 4. Optional: restart on failure

`schtasks` can't set the restart-on-failure supervisor from the command line.
If you want it: Task Scheduler → uwmirror → Properties → Settings tab →
check *"If the task fails, restart every"* → 1 minute, 3 attempts.

## Managing the task

```
schtasks /Run /TN "uwmirror"      # test it now
schtasks /End /TN "uwmirror"      # stop it
schtasks /Delete /TN "uwmirror" /F
```

## TV powered off at boot?

If the TV is off when you log on, Windows may not report it as a display and
uwmirror will exit (the task's restart-on-failure supervisor from step 4 will
keep retrying, and succeeds once the TV is on). Some TVs/receivers support
"HDMI always on" / EDID emulation to avoid this entirely — the same caveat
applies to OBS projectors.
