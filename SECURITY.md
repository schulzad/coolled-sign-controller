# Security notes

- The API binds to localhost by default and has no built-in remote authentication.
- Do not expose it to a network without an authenticated reverse proxy and transport security.
- The `coolled` / `opensign-send` CLIs write to the panel by default; pass `--dry-run` to build a transfer plan without writing. The localhost API stays render-only until it is started with `--execute`.
- Transmitting accepts `experimental` profiles (a controlled live test is how evidence is promoted to `verified`); prefer `verified` profiles for unattended or API-exposed use.
- Treat imported captures as sensitive: they may contain device identifiers or unrelated traffic.
- Do not store pairing secrets, private keys, personal identifiers, or cloud credentials in profiles.
- Research endpoints that accept arbitrary raw packets are intentionally absent from the default API.
