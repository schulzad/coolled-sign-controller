# Evidence workspace

- `advertisements/`: raw scan reports.
- `gatt/`: service/characteristic/descriptor maps and safe reads.
- `captures/`: PCAP, btsnoop, monitor logs, and sidecar provenance JSON.
- `hardware/`: PCB photographs, markings, connector notes, and board revisions.
- `hypotheses/`: differential reports and rejected/active protocol hypotheses.

Use immutable capture IDs and SHA-256 hashes. Do not overwrite original captures; create a normalized derivative with a reference to the source file.
