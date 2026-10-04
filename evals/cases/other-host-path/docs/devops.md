# DevOps notes

- Infrastructure code lives in `~/projects/homelab-iac` and is applied from
  the workstation with OpenTofu.
- Secrets are encrypted with SOPS and age. The age key is at
  `~/.config/sops/age/keys.txt`, mode 0600.
- restic reads its repository password from `/etc/restic/env`.
- Paths left out of the backup are listed in `/etc/restic/excludes.txt`.
