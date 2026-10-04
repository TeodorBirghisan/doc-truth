# Services

- Nextcloud answers at `https://cloud.example.org`.
  `https://cloud.example.org/status.php` returns JSON, which the uptime
  monitor checks every minute.
- restic is version 0.18.1, installed from the GitHub release binary rather
  than from apt, because apt's version is too old for `restic copy`.
