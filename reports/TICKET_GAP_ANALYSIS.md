# Ticket gap analysis

_Generated 2026-11-03 19:47 by `python scripts/13_ticket_gaps.py`. Method and limits are in the script's docstring._

* 13092 indexed tickets; **66 excluded as leakage** (65 held-out source tickets; 1 near-copy titles (Jaccard >= 0.7)).
* 105 error groups with at least 4 tickets, covering 846 tickets (6% of the store).
* **37 gap candidates** (the KB contains under 60% of the error's wording in its best five chunks); the other 68 look documented.
* 25 draft cards written to `data/curated/cards.jsonl` (status `draft`; nothing is loaded into the system until a person approves).

`kb_contained` is a ranking aid: wording overlap cannot reliably tell a gap from a hit (it lists the socket-permission error as a gap although `linux-postinstall.md` documents the fix, in words that do not quote the error). The CSV has a VERDICT column for a person to fill.

## Read the cards with care

Tickets are grouped by their first error line, nothing more. A generic line groups tickets that share a message but not a cause: the biggest group (`: executable file not found in $path`, 22 tickets) is about 22 different programs, and its draft card quotes one ticket's workaround (pin `registry:2.7.0`), which is right for that ticket and wrong for the rest. Title similarity inside a group is too low to catch this automatically (median 0.04 even for related tickets). So the cards are **drafts to be triaged by a person**, many to be rejected or narrowed; the ranked CSV is the real output: it shows which errors customers hit most that the KB seems not to cover. Only 6% of the store falls in an error group of four or more tickets: the long tail is wide, so this reaches the head of the distribution only.

## Biggest gap candidates

| tickets | error (normalised) | kb_contained | closest KB issue |
|---|---|---|---|
| 22 | `: executable file not found in $path` | 0.5 | dhi-openshift.md > Confirm the image is distroless (0.60) |
| 21 | `got permission denied while trying to connect to the docker daemon socket` | 0.44 | apparmor.md > Nginx example profile (0.64) |
| 18 | `d#: is the vm networking working? network checks failed: failed to ping` | 0.29 | release-notes.md > Bug fixes and enhancements (0.57) |
| 16 | `failed to solve: rpc error: code = unknown desc = failed to` | 0.57 | errors.md > Read an error response (0.56) |
| 15 | `failed to deploy distro docker-desktop to <path><user>\appdata\local\docker\wsl\` | 0.58 | 2.x-windows.md > Bug fixes and minor changes (0.65) |
| 12 | `users/<user><path> is not valid: failed to fetch metadata: fork/exec /users/<use` | 0.5 | troubleshoot.md > Errors when starting the Docker daemon (0.60) |
| 10 | `failed to solve with frontend dockerfile.v#: failed to create llb definition: fa` | 0.57 | edge-releases-windows.md > Bug fixes and minor changes (0.62) |
| 10 | `curl: (#) failed to connect to # port #: connection refused` | 0.5 | _index.md > SDK and API quickstart (0.62) |
| 8 | `error: failed to solve: rpc error: code = unknown desc = failed` | 0.57 | errors.md > Read an error response (0.57) |
| 8 | `error: failed to solve: rpc error: code = unknown desc = executor` | 0.5 | errors.md > Read an error response (0.56) |
| 8 | `error response from daemon: get https://registry-#.docker.io/v#/: net/http: requ` | 0.5 | topics.md > Certificates not set up correctly (0.65) |
| 7 | `failed to solve with frontend dockerfile.v#: failed to create llb definition: rp` | 0.5 | context.md > How to build without a context (0.62) |
| 7 | `includes invalid characters for a local volume name, only` | 0.57 | volumes.md > `external` (0.58) |
| 7 | `t connect to local mysql server through socket` | 0.5 | databases.md > Connect to a containerized database from your host (0.5 |
| 6 | `docker: error response from daemon: could not select device driver with capabili` | 0.38 | 17.06.md > Networking (0.64) |
| 5 | `failed to solve with frontend dockerfile.v#: failed to read dockerfile: open <pa` | 0.43 | wasm.md > Failed to start shim: failed to resolve runtime path (0.62) |
| 5 | `failed to solve with frontend dockerfile.v#: failed to solve with frontend gatew` | 0.2 | edge-releases-windows.md > Bug fixes and minor changes (0.63) |
| 5 | `t find any package by glob` | 0.5 | nextjs.md > Run tests during development (0.56) |
| 5 | `<path> is not valid: failed to fetch metadata: fork/exec <path>: no such` | 0.25 | troubleshoot.md > Unable to remove filesystem (0.59) |
| 5 | `<id> cleanup: failed to delete container from containerd: no such container` | 0.29 | NavigationIntents.md > viewContainer (0.62) |
