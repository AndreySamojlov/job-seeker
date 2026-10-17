# S3 production board image

`Dockerfile.s3` builds the S3-capable board from the production board image that was verified during the 16 October 2026 board rollout. It copies the repository's S3 board source and installs the immutable local `cockpit-engine==0.2.0a7` wheel. The app and engine versions are checked during the build.

## Pinned inputs

| Input | Identity |
|---|---|
| Production base tag | `job-machine/board:linkstyle-a7-20261016-r1` |
| Production base image ID | `sha256:d885700bfbc85ed4e989ab4cd550b3cd2fef2b566b69630584dc3ce8223ef56e` |
| Cockpit Engine wheel | `vendor/cockpit_engine-0.2.0a7-py3-none-any.whl` |
| Wheel SHA-256 | `cc83cf230e1c4390085e0abd1b3234f981c07fc43ac943d7958823442fa1a0f0` |
| S3 source | `src/job_machine/board/` from this checkout; source files are versioned in Git |

The Dockerfile records base tag and immutable ID as OCI labels. For reproducibility, the builder must have the pinned base image locally; the build does not pull packages or contact external services. Build context is the repository root:

```powershell
docker build --pull=false --network=none --file deploy/board/Dockerfile.s3 --tag job-machine/board:jev-s3-20261016-r1 .
```

Record the resulting image ID and verify its labels before considering the image for deployment:

```powershell
docker image inspect job-machine/board:jev-s3-20261016-r1 --format '{{.Id}} {{json .Config.Labels}}'
```

The exact prior production image for rollback is `job-machine/board:linkstyle-a7-20261016-r1` with image ID `sha256:d885700bfbc85ed4e989ab4cd550b3cd2fef2b566b69630584dc3ce8223ef56e`. This base preserves the accepted link styling. Rollback should target that image explicitly. Production rollout, role grant, migrations and Compose changes belong to later S4 tasks.

## Runtime contract

- The image listens on container port `8080`; the built-in health check requests `/healthz`.
- The image runs as UID/GID `65532:65532` and sets `PYTHONDONTWRITEBYTECODE=1`; application files are not writable by that user.
- The server uses the existing `job_board_reader` PostgreSQL role and `/run/secrets/board.pgpass`, with `default_transaction_read_only=on`.
- The production runtime must retain its existing loopback-only host binding, read-only root filesystem, dropped capabilities, no-new-privileges, resource limits and read-only secret mount.
- The board joins only completed `fit_job` rows for the selected candidate. Score `0` remains numeric and missing/incomplete results remain `NULL`. The full response budget rejects overflow instead of returning a partial report.

## Local checks

Run the board suite and synthetic HTTP fixture without a database:

```powershell
.venv\Scripts\python.exe -m pytest tests/board -m "not db" -q -p no:cacheprovider --basetemp=.runtime/pytest-board-s3
.venv\Scripts\python.exe -m uvicorn tests.board.fixture_app:create_app --factory --host 127.0.0.1 --port 18769 --workers 1
```

For the container smoke, run the same fixture command with the built image's entrypoint overridden to `python -m uvicorn tests.board.fixture_app:create_app --factory --host 0.0.0.0 --port 8080 --workers 1 --no-access-log`, after mounting the checkout read-only at `/app`. Confirm `/healthz` and the report endpoint return HTTP 200, then stop only that synthetic container. Do not pass production credentials or connect the fixture to a database.
