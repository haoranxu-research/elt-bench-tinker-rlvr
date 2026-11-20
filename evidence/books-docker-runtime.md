# Post-restart books runtime

Executed on 2026-11-19 after the Windows restart, from implementation commit
`2c6f6aa`. The pending Windows servicing flag cleared. Docker Desktop's Linux
daemon reported Docker 29.9.3, 18 CPUs and 15.4 GiB assigned RAM. A genuine
`hello-world` container pulled and ran successfully. Its image digest was
`sha256:1e4c05b897a751332ce85c7e9449da2d93514ea2dea6dbb0e2753c9e949b2bfa`.
Docker Desktop used its own running WSL 2 distro. A separate Ubuntu download
ended with `Wsl/InstallDistro/WININET_E_CONNECTION_RESET`. The Windows Docker
CLI and Windows abctl can operate without that separate distro.

```powershell
$docker = Join-Path $env:LOCALAPPDATA 'Programs/DockerDesktop/resources/bin/docker.exe'
& $docker --context desktop-linux info --format '{{.OSType}} {{.ServerVersion}} {{.NCPU}} {{.MemTotal}}'
& $docker --context desktop-linux run --rm hello-world
```

## Executed sources

Docker Compose started the pinned source stack with
`deploy/books-compose.loopback.yml`. The override restricts published host
ports to loopback and makes the one-node MongoDB replica advertise its
Compose hostname. The original upstream config remains unmodified.

```powershell
& $docker --context desktop-linux compose -p elt-docker -f runs/books-machine/staged/elt-docker/docker-compose.yml -f deploy/books-compose.loopback.yml up -d --wait
python runs/books-machine/seed-compose.py postgres
python runs/books-machine/seed-compose.py s3
python runs/books-machine/seed-compose.py rest
$env:PYTHONPATH=(Resolve-Path runs/books-native/python).Path
python runs/books-machine/seed-compose.py mongodb
```

The Windows harness in the ignored runtime directory used the pinned Bash
Postgres seeder, pinned MongoDB seeder, and the two pinned S3 objects. It
queried the live containers and checked every count against the official
table manifest. It also verified the downloaded S3 objects byte for byte and
checked real HTTP pagination against the pinned REST app.

| Container | Verified output |
|---|---|
| `elt-postgres` | address 1,000; cust_order 7,550; customer_address 3,350; order_history 22,348; order_line 7,550 |
| `elt-mongodb` | author 9,235; book 11,127; customer 2,000 |
| `elt-localstack` | country 232; shipping_method 4 |
| `elt-api` | book_author 17,642; book_language 27; publisher 2,264 |

The published upstream declarative manifest uses the `alias` stream for its
connector check. The Flask route reads `data/address/alias.csv`, which was
missing in the books-only staging tree. That official file was fetched from
the pinned REST archive, SHA-256
`c26aba1616612309a827599b490b0ecf06061872eadd1f46b78ce76b24e11bc5`.
Its 41,701 records matched upstream expectations. The deployed REST app
returned one record for the health request with the limit set to one. This
file is a connector prerequisite. The 15 scored `books` streams are unchanged.
Fresh staging and loopback checks passed. The complete offline suite passed
`60 tests in 61.13s` using the prior offline environment and
`--basetemp .venv/books-after-reboot-tests`.

## Airbyte installation

The Windows abctl v0.30.4 release ZIP passed its published SHA-256 check.
The install used the verified Airbyte 1.5.1 chart, the documented MinIO
override, and the Windows Docker Desktop Linux context. The first install
stalled in Docker's pull of its pinned `kindest/node:v1.32.2` manifest. An
independent ranged download verified the official compressed layers and
manifest SHA-256 before a Docker load. Docker then reported the exact
`sha256:f226345927d7e348497136874b6d207e0b32cc52154ad8323129352923a3142f`
tag reference. After the stalled child pull was stopped, the original
installer continued. The Kubernetes control-plane node reached Ready on
v1.32.2. The node joined the source network and resolved all four pinned
source hostnames. A separate BusyBox Kubernetes pod reached both database
ports, the LocalStack health endpoint and the books REST endpoint. The pod
reported `POSTGRES_OK`, `MONGODB_OK`, `LOCALSTACK_OK` and `REST_OK`, then
was deleted. Airbyte began pulling its platform images after the node became
ready.

## Snowflake

The private credential scaffold still has blank account and host fields.
Snowflake connectivity, official evaluation, and a warehouse-derived reward
require authorized credentials and new approvals. No Snowflake credits or
other paid services were used. The prior Tinker pilot was not repeated.

## Pause and resume

Paused at the operator's request during Airbyte platform image downloads.
Docker Hub CDN read timeouts interrupted some large image transfers. The
Airbyte installer, supplementary image downloads and health/sync watcher
were stopped. The four verified source containers and the Kubernetes
control-plane container were left running. Completed images remain in
Docker's local cache. No connector was published and no Airbyte sync ran.

Resume with the Windows abctl command in the live setup guide. The existing
kind cluster and completed images can be reused. Logs are under the ignored
`runs/books-machine/` directory.

## Resumed deployment and successful local sync

On November 20, Docker Desktop and all four source containers restarted.
The Kubernetes control plane returned `Ready`. All 14 platform images were
verified in Docker Desktop's cache. The resumed `abctl` installer still
attempted registry pulls, which hit Docker Hub TLS handshake timeouts.
The same pinned Airbyte 1.5.1 Helm chart was deployed directly in the
existing kind cluster with `deploy/books-airbyte-values.yaml`. Images were
imported individually into the node's containerd cache after the grouped
import timed out. The initial Helm wait also timed out during image pulls.
The bootloader completed and all ten long-running Airbyte pods subsequently
reported `1/1 Running`.

The server's loopback port-forward on `127.0.0.1:18000` returned
`{"available":true}` from `/api/v1/health`. The upstream setup script
published `Elt Snowflake` from the pinned manifest. The project binder
generated the private books config, and `elt_rl.preflight official
--airbyte-probe` passed the Airbyte, generated-input, and asset checks.
Preflight exited 2 overall because Snowflake credentials remain unset.

An actual Airbyte job copied the official `book_language` stream into the
disposable PostgreSQL warehouse. Airbyte used `source-declarative-manifest`
4.3.0 and `destination-postgres` 2.4.3. Job `1`, attempt `0`, succeeded on
November 20 from 02:11:22 to 02:17:01 UTC. The job reported 27 emitted and
27 committed records. A SQL count in `airbyte_smoke.book_language` returned
27. The script cleaned up the temporary Airbyte resources and database. A
separate PostgreSQL check found zero remaining smoke databases. Sanitized
logs and row count evidence remain under `runs/books-machine/`. Full job
detail is in the project's private configuration directory.

This sync exercised the official source connector against local PostgreSQL.
The separate scored Snowflake rollout remains unexecuted. No paid operation
was performed.

## Credentialed rollout handoff

Starting from `ff5e2a9`, the Airbyte health endpoint returned
`{"available":true}` again, and all ten long-running Airbyte pods reported
`1/1 Running`. The saved job `1` and its recorded SQL count were checked
again. The successful attempt recorded 27 emitted and 27 committed rows,
and SQL observed 27 rows.

With `ELT_BOOKS_INPUT_DIR` set to the private books configuration and
`ELT_AIRBYTE_URL` set to the loopback Airbyte public API, the following
preflight passed the local asset, input, dependency and Airbyte checks:

```powershell
.\.venv-core\Scripts\python.exe -m elt_rl.preflight official --airbyte-probe
```

The command exited 2 because Snowflake credentials are missing. The private
Snowflake JSON has blank account and host fields. No Snowflake credential
file is selected by the project and no default Snowflake CLI profile was
found. The prepared PKCS#8 RSA key decrypted locally with its configured
passphrase and matched the public key. Its size is 2048 bits.

The [trial and provisioning steps](../LIVE_SETUP.md#3-configure-snowflake-after-authorization)
cover account setup without payment details, registration of the existing
public key, a dedicated service role, and a monitored X-Small Gen1 warehouse.
Account setup and execution authorization are outstanding. Snowflake and
Tinker were not called during this handoff, so warehouse transfer, official
evaluation and the execution-derived reward remain unobserved.

## Authorized Snowflake preflight

The operator authorized one rollout with a 1-credit Snowflake warehouse
monitor and a USD 1 Tinker sampling estimate limit. The Standard trial showed
a positive balance. The dedicated X-Small warehouse was created initially
suspended using `GENERATION = '1'` and 60-second auto-suspend. Snowflake rejected
the first DDL using `RESOURCE_CONSTRAINT = STANDARD_GEN_1`. The corrected
script registered the prepared public key and granted the service role
warehouse usage and ownership of its own transient databases.

The Snowflake and Airbyte preflight passed with RSA authentication. The
namespace probe created and dropped a transient database and its `BOOKS`
schema. A Kubernetes pod verified TCP access to the Snowflake endpoint and
Google Drive. The exact five built-in connector images reported by Airbyte
were warmed in kind. Local Terraform created and removed all six source
configurations without a warehouse destination. The full offline test suite
passed 60 tests with the updated service timeout.
