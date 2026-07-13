# Security notes

- The API binds to localhost by default and has no built-in remote authentication.
- Do not expose it to a network without an authenticated reverse proxy and transport security.
- Physical writes require an explicit `--execute` flag and a verified profile entry.
- Treat imported captures as sensitive: they may contain device identifiers or unrelated traffic.
- Do not store pairing secrets, private keys, personal identifiers, or cloud credentials in profiles.
- Research endpoints that accept arbitrary raw packets are intentionally absent from the default API.
