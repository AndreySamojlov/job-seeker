# Isolated Jev worker

Build from the repository root: `docker build -f deploy/fit/Dockerfile -t job-machine/fit:s4 .`.
The production base is pinned to `job-machine/package:3d0b9af`, matching the board base.
The required Docker image ID is `sha256:6e63a54d7c15e5b10188ebfe7ebd95911cecfebfbe779a87188e58ea8def0d23`
(57,838,084 bytes). Before building, compare `docker image inspect job-machine/package:3d0b9af --format '{{.Id}}'`
to this exact ID and refuse a mismatch. This config ID is not a registry manifest digest.
Verify its image identity and installed dependencies before delivery. The HTTP dependency stack
is pinned to exact versions from `uv.lock`; no floating packages are installed.
Only fit and its ATS/text adapter source paths are copied. No runtime directory or secret is copied.

Run as UID/GID 65532:65532 on `greenhouse-runtime`, without published ports or `/data`.
Mount the TypeSafe key file read-only at `/run/secrets/typesafe_api_key`, readable by UID65532;
the daemon reads it in process, without placing it in an argument or environment variable.
`TYPESAFE_API_KEY_FILE` can override the mount path. Supply `DATABASE_URL` via the approved runtime
secret configuration; never bake credentials into the image. Set PostgreSQL `connect_timeout=5`
and bound statement/lock timeouts through connection options for health and shutdown responsiveness.

Required settings: memory 256MiB, CPU 0.5, PIDs64, read-only root filesystem,
`cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`, writable `/tmp` tmpfs
with `rw,noexec,nosuid,size=16m,uid=65532,gid=65532`. Allow at least 60 seconds stop grace:
SIGTERM stops polling after the current bounded operation, preserving durable leases for recovery.
Preparation can consume longer than one HTTP timeout across children; no shutdown deletes queued work.

Egress: PostgreSQL on the private runtime network, DNS, TypeSafe HTTPS
`api.typesafe.ai:443`, and the configured Greenhouse/ATS HTTPS content hosts. Apply an external
network policy to restrict egress; Dockerfile alone does not enforce endpoint filtering.
No n8n changes or existing worker restarts are needed.

Only vacancies with `ats_family='greenhouse'` are claimed by the daemon in either queue;
other ATS remain durable and unprocessed. Library callers can opt into a family filter.
One preparation job then one fit job runs per 5-second poll. Diagnostics expose only fixed
outcome codes per poll, never provider text, URLs, payloads, or exceptions. `status` and
`preparation-status` expose aggregate counts. `health` checks a heartbeat younger than90s;
it proves loop responsiveness, not successful provider requests or database availability.
The heartbeat can expire during unusually long preparation work; inspect safe status counts
and DB connectivity before treating it as an availability failure.

Every attempted Jev HTTP request reserves a durable event before HTTP under a global transaction
advisory lock, with a maximum of1000 reservations per UTC day. A crash consumes its reservation;
provider retries consume another. At exhaustion only the claimed pair is deferred until UTC midnight.
Use normal PostgreSQL READ COMMITTED connections. No historical vacancy backfill occurs.

This directory prepares an image; it does not authorize production delivery or migrations.
