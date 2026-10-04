# Caddy

Caddy is the only container with ports on all interfaces, 80 and 443. Its
configuration is `/srv/compose/caddy/Caddyfile`:

- `cloud.example.org` proxies to `nextcloud:80`.
- `photos.example.org` proxies to `immich-server:2283`.
- `vault.example.org` proxies to `vaultwarden:80`.

The container names resolve on the `web` Docker network, so Caddy doesn't use
the ports published on 127.0.0.1.

Certificates and their keys are kept in the `caddy_data` volume, under `/srv`,
so they are part of the backup. After a restore, Caddy reuses them instead of
asking Let's Encrypt again.

To reload after editing the Caddyfile, run
`docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile`.
