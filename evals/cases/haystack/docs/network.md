# Network

## Addresses

- On the LAN, the server has a fixed DHCP lease from the router, and the router
  forwards ports 80 and 443 to it. Nothing else is forwarded.
- On the tailnet, the server is `homeserver`, with MagicDNS. SSH, Jellyfin and
  Uptime Kuma are reached this way.
- The public names `cloud.example.org`, `photos.example.org` and
  `vault.example.org` point at the home connection's address. The router
  updates the DNS records when the address changes.

## TLS

Caddy gets and renews certificates from Let's Encrypt by itself, using the
HTTP challenge on port 80. Nothing else on the server handles certificates. If
a certificate expires anyway, look at `docker compose logs caddy`: the usual
cause is port 80 not being forwarded after a router reset.

## Firewall

ufw denies all incoming traffic by default and allows:

| Port | From | For |
|---|---|---|
| 22/tcp | the tailnet, 100.64.0.0/10 | SSH |
| 80/tcp | anywhere | Caddy: the HTTP challenge and redirects |
| 443/tcp | anywhere | Caddy: HTTPS |

Docker publishes container ports with its own iptables rules, which bypass
ufw. That is why every container port except Caddy's is published on
127.0.0.1 only.
