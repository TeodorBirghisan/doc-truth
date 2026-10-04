# Runbook: setting up the server from scratch

This is how the server was set up in March 2026. Follow it after replacing the
system disk, or to build a replacement machine.

1. Install Ubuntu 24.04 LTS Server from a USB stick. Use the whole NVMe disk,
   ext4, no LVM. Create the user `ops`.
2. Enable the OpenSSH server in the installer and import the SSH keys from
   the family's password manager.
3. After the first boot, run `sudo apt update && sudo apt full-upgrade`.
4. Install Tailscale from its apt repository and run `sudo tailscale up`.
   Check that SSH works over the tailnet before going further.
5. Turn off password login: `PasswordAuthentication no` and
   `PermitRootLogin no` in `/etc/ssh/sshd_config.d/10-hardening.conf`, then
   `sudo systemctl reload ssh`.
6. Set up ufw: deny incoming, allow 80 and 443 from anywhere, allow 22 from
   the tailnet's address range only, then `sudo ufw enable`.
7. Add the data and backup disks to `/etc/fstab` by label: `srv` on `/srv`
   and `backup` on `/mnt/backup`.
8. Install Docker Engine from Docker's apt repository and add `ops` to the
   `docker` group.
9. Clone the compose repository to `/srv/compose` and run
   `docker compose up -d`.
10. Install the restic release binary to `/usr/local/bin/restic` and create
    `/etc/restic/env` with the repository location and password (mode 0600).
11. Copy the unit files from `/srv/compose/systemd/` to `/etc/systemd/system/`,
    then `sudo systemctl daemon-reload` and enable every timer listed in
    section 4 of the operations manual.
12. Install Timeshift and apcupsd from apt, and copy their configuration from
    `/srv/compose/etc/`.
13. Run every check command in the operations manual once, by hand.

The whole setup takes about two hours. Restoring the data takes longer: about
six hours for `/srv` from the backup disk, or two days from B2.
