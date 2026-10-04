# apt and unattended-upgrades

## Regular updates are automatic too

Until 2026-08-24, unattended-upgrades only installed from `noble-security`
and ESM. Since 2026-08-24 it also installs from `noble-updates`, so regular
updates arrive automatically every evening at 20:45. Kernel updates still
wait for the Sunday reboot.

## Checking what was installed

`less /var/log/unattended-upgrades/unattended-upgrades.log` lists every
package each run installed.
