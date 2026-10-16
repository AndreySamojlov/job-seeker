# Isolated RWR worker package

This package builds and describes only the RWR polling worker. It does not run
the general pipeline, candidate-fit evaluation, migrations, or board service.
The Compose service has no published ports and pins RWR processing off with
`RWR_ENABLED=false`; the persistent database control is independently created
disabled by migration `0041`.

## Build

Build from the repository root. The default base is the official
`python:3.12.15-slim-bookworm` multi-platform image pinned to manifest digest
`sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258`.
The Dockerfile rejects an override without a digest. Keep the resulting
immutable RWR image reference in `RWR_IMAGE`.

```powershell
docker build --file deploy/remote-readiness/Dockerfile `
  --tag <immutable-rwr-image-tag> .
```

`Dockerfile.dockerignore` is applied automatically to this Dockerfile and
restricts the context to the Dockerfile plus its explicit `COPY` inputs. It contains the
RWR package, database connection adapter, and the existing ATS adapters and
text helpers imported by RWR intake. It excludes the full pipeline, fit
package, board, runtime state, and secrets. Runtime Python versions are pinned
in `requirements.lock`; Cockpit Engine is copied from the repository's exact
`0.2.0a8` wheel.

## Runtime inputs

`compose.yaml` is a target-neutral template. Before rendering it, provide an
immutable `RWR_IMAGE`, the already approved database URL injection, an
approved read-only provider-key source, the existing database-access network,
and resource limits measured for the target. It intentionally does not choose
host secret paths, database addresses, network names, CPU/memory ceilings, or a
shutdown grace period. Do not commit a populated environment file or print the
rendered configuration because it contains runtime credentials.

The initial disabled service has no database credential, provider key, network,
published port, or writable data volume. It sets `RWR_ENABLED=false`; startup
does not connect to PostgreSQL, apply schema changes, or make ATS/Jev requests.
This makes the requested disabled deployment self-contained and unable to
reach providers. Enabling RWR requires a separately authorized, reviewed
runtime configuration with an approved database credential, read-only provider
key secret mount, and the existing database/provider network. Do not add those
inputs to this disabled-only Compose template.

The service runs as UID/GID 10001, with a read-only root filesystem, all Linux
capabilities dropped, `no-new-privileges`, bounded tmpfs, CPU, memory, process
count, and operator-supplied stop grace. Its command is
`python -m job_machine.remote_readiness daemon`.

## Checks and delivery boundary

Static checks should verify the Dockerfile COPY allowlist, Compose security
settings, absence of published ports and disabled defaults. A real image build
also requires the approved base-image digest and an available Docker daemon.
This package is not a production deployment procedure: target identity,
migration preflight/apply, secret provisioning, resource values, and rollout
evidence belong to the S5 deployment task and its runbook.
