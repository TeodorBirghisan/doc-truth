# Photos and media

## Immich

Immich (`ghcr.io/immich-app/immich-server:v1.142.1`) serves the family's
photos at `https://photos.example.org`. Phones upload over the tailnet or the
public address.

Photos that arrive in `/srv/uploads/shared` some other way, from a camera's SD
card or the scanner, are imported every morning at 07:00 by
`photo-import.timer`, which runs `immich-go` against the Immich API.

The database is dumped every night at 02:40, ten minutes after the Nextcloud
dump, by `immich-db-dump.timer`.

## Jellyfin

Jellyfin 10.10 serves films and music from `/srv/media`. It is only
reachable on the tailnet, through `tailscale serve`, because the family's
media doesn't need to be on the internet.

Hardware transcoding uses the N100's Quick Sync. If playback stutters, check
that `/dev/dri` is still passed through to the container.
