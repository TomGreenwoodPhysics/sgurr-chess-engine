# Auto-resume gen8 datagen on login, but ONLY if it isn't already running.
# The guard is essential: without it, logging in while datagen is already
# going would spawn a second set of 12 workers (24 total, oversubscribed).
# Hooked in via a shortcut in the Startup folder, so any reboot/power-cut
# self-heals on the next login instead of idling for days.
if (Get-Process datagen -ErrorAction SilentlyContinue) {
    # already generating -- do nothing
    exit 0
}
& "$PSScriptRoot\mum_start_datagen.ps1" | Out-Null
