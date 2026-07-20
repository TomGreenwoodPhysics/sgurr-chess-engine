# Sgurr — Remote (phone) Command Reference

SSH in via **Termius → "Sgurr rig"** (host `100.109.36.8`, user `Tom Greenwood`).
The shell is **PowerShell**. Tailscale must be connected on the phone first.

View this file from the phone any time:
    Get-Content REMOTE_COMMANDS.md

---

## 0. First command, every session — go to the project

    cd "$env:USERPROFILE\Desktop\Coding Projects\Sgurr"

Everything below assumes you have run this first.

---

## 1. LOOK — read-only, always safe

**The one you'll use most — everything at a glance:**

    .\status.ps1

**Latest datagen line:**

    Get-Content runs\gen7_datagen\worker_1.log -Tail 3

**Follow datagen live** (updates as it runs; press `Ctrl+C` to stop watching):

    Get-Content runs\gen7_datagen\worker_1.log -Tail 5 -Wait

**Exact position count:**

    [long]((Get-ChildItem data\gen7_raw\data_*.bin | Measure-Object Length -Sum).Sum / 32)

**Are the workers alive? (expect 6)**

    (Get-Process datagen -ErrorAction SilentlyContinue).Count

**Disk free (GB) — watch this while away:**

    [math]::Round((Get-PSDrive C).Free / 1GB, 1)

**Recent git history (read-only):**

    git log --oneline -10

---

## 2. STOP — clean pause of datagen (SSH-safe)

Do NOT run `pause_gen7_datagen.bat` over SSH — it ends with a "press any key"
prompt that will hang the session. Use this direct command instead; it does the
same thing (kills only the gen7 workers; complete records are always safe):

    Get-CimInstance Win32_Process -Filter "Name='datagen.exe'" |
      Where-Object { $_.CommandLine -like '*gen7_raw*' } |
      ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

Confirm they're stopped:

    (Get-Process datagen -ErrorAction SilentlyContinue).Count   # expect 0

---

## 3. TERMINAL BASICS

- `Ctrl+C`  — stop the current command (e.g. a live `-Wait` follow)
- `exit`    — close the SSH session (running jobs keep going)
- `cls`     — clear the screen
- Up arrow  — recall the previous command

---

## 4. TO BE ADDED / TESTED BEFORE THE HOLIDAY

These are NOT finalised yet — they behave differently over SSH than when
double-clicked, and must be tested from the phone before you rely on them:

- [ ] RESUME datagen remotely (relaunching workers over SSH needs verifying)
- [ ] Check / resume the holiday PIPELINE run (king-bucket run — not set up yet)
- [ ] Recover after an unexpected reboot (auto-restart hardening)
- [ ] A `sgurr` shortcut so you don't type the full `cd` each time

Ask before departure and these will be filled in and tested end-to-end.
