# IPTV Playlists

## NUC10 / 1905 CDN direct snapshot

`IPTV.m3u` is exported from the local IPTV service on port `1905`.
The service's `/relay`, `/proxy`, numeric channel IDs, and loopback logo URLs have
been resolved to absolute upstream CDN/HLS URLs. Channels that could only play
through the local reverse proxy are omitted because they cannot be used as direct
subscriptions.

Subscription URLs:

- GitHub Raw: <https://raw.githubusercontent.com/dfdfwff/iptv-playlists/main/IPTV.m3u>
- jsDelivr: <https://cdn.jsdelivr.net/gh/dfdfwff/iptv-playlists@main/IPTV.m3u>

EPG: <https://epg.zsdc.eu.org/t.xml.gz>

Some provider URLs contain short-lived signatures. Re-export this file when those
channels stop playing.
