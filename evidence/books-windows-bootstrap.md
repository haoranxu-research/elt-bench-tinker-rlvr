# Windows bootstrap for the official books rollout

Executed on 2026-11-19 from implementation commit `65863df`. This follow-up
prepared the machine and prerequisites for the official Airbyte and Snowflake
run. The [prior runtime audit](books-runtime.md) records complete staged row
counts and local PostgreSQL, MongoDB, and REST execution.

## WSL installed and awaiting restart

The Windows host reported build 26200, 18 logical processors, 31.6 GiB total
memory, and about 7 GiB free during the first check. Free disk space was
55.4 GiB on C: and 555.0 GiB on S:. Firmware virtualization and SLAT were
available. The project shell was unprivileged, and the Windows Server service
was running with automatic start. No Docker engine pipe or default all-user
or per-user Docker Desktop installation was present.

```powershell
wsl.exe --status
wsl.exe --list --verbose
dism.exe /Online /Get-FeatureInfo /FeatureName:VirtualMachinePlatform /English
Start-Process -FilePath "$env:SystemRoot\System32\wsl.exe" -Verb RunAs -WindowStyle Hidden -ArgumentList '--install','--no-distribution','--web-download' -Wait -PassThru
wsl.exe --version
wsl.exe --status
wsl.exe --list --verbose
```

Initial WSL status and list exited 50 and 1. DISM exited 740 as the project
user. The elevated WSL install ran and exited 0. After installation,
`wsl.exe --version` reported WSL 3.0.5.0 and kernel 6.18.58.1-1, and
`wsl.exe --status` reported default version 2. The latter also reported the
WSL 2 VM could not start in the current boot. The distribution list was empty.

The Windows servicing `RebootPending` key was present. Setup log event 13
recorded that VirtualMachinePlatform requires a restart before it can be
turned on. No reboot was initiated. After a user-initiated restart, resume
with the first post-restart command in the [Docker and WSL runbook](../LIVE_SETUP.md#1-prepare-and-verify-the-local-sources).

Downloaded Docker Desktop 4.99.0.245822 from Docker's official x86-64
endpoint, resumed after one network timeout, and verified a `Valid`
Authenticode signature from `Docker Inc`. The installer is retained in
ignored `runs/books-machine/`.

The documented per-user command with `--backend=wsl-2` and `--quiet`
exited 0. The installed desktop binary was found in
`%LOCALAPPDATA%\Programs\DockerDesktop`. The installed client reported Docker
29.9.3 (build `5457199`) and Docker Compose v5.7.0. An explicit local engine
probe through `npipe:////./pipe/docker_engine` exited 1 because the pipe was
absent. Docker Desktop has yet to be started. Windows still reported
`RebootPending` after installation.

## Airbyte and sources prepared

- Downloaded Airbyte chart 1.5.1 from the official legacy Helm repository.
  Its chart and app versions both read 1.5.1. Its SHA-256 matches the
  published index at `5fa22b209478f4ed42d746fbf226baaecf1abc1ae6d0cb6dc7c8139675316ead`.
- Downloaded Airbyte abctl v0.30.4 for Linux x86-64. The archive lists the
  binary and its accompanying files, and its SHA-256 matches the GitHub
  release at `bcd46d55d5e515fc2ccc92cd67d493825640c2977fb2d3dd81a5c965ef545534`.
  Both archives are in ignored `runs/books-machine/`.
- Rendered the actual chart with Helm v3.17.3 and the MinIO repository
  override shown below. The render contained
  `airbyte/minio:RELEASE.2023-11-20T22-40-07Z` and
  `airbyte/bootloader:1.5.1`, `airbyte/server:1.5.1`, and `airbyte/worker:1.5.1`.
  Public Docker Hub tag metadata returned HTTP 200 with Linux amd64 entries
  for those four images and for `localstack/localstack:4.14.0`. No image was
  run.
- The pinned REST app passed the loopback HTTP check again. The observed
  counts were 17,642 `book_author`, 27 `book_language`, and 2,264 `publisher`.
  Both pinned Google Drive flat-file URLs returned HTTP 200 and bytes
  identical to the staged files. Checks ran from Windows.
- The Windows checkout had CRLF line endings in both pinned Bash seeder
  scripts. The stager now writes LF for these scripts. Fresh staging matched
  all 15 source counts, and both Bash files matched the exact upstream Git
  blobs byte for byte and passed `bash -n`.

```powershell
& ./runs/books-machine/windows-amd64/helm.exe template airbyte-abctl runs/books-machine/airbyte-1.5.1.tgz --namespace airbyte-abctl --values runs/books-machine/minio-values.yaml
$env:PYTHONPATH=(Resolve-Path src).Path
python -m elt_rl.books_setup --checkout ../upstream-elt-bench rest-check --runtime runs/books-runtime-verified
.\.venv-core\Scripts\python.exe -m elt_rl.books_setup --checkout ../upstream-elt-bench stage --assets runs/books-assets --out runs/books-machine/staged
```

```yaml
minio:
  image:
    repository: airbyte/minio
```

Airbyte, LocalStack, and the source containers await the Docker engine.
The [local sync procedure](../LIVE_SETUP.md#run-one-local-airbyte-sync-before-snowflake)
uses the official custom REST connector, a local PostgreSQL destination, an
actual 27-row transfer, and Airbyte job logs. It is ready for execution after
the restart and engine check. Connector publication and the sync remain
unexecuted.

## Snowflake trial preparation

The project preflight exited 2. No project Snowflake credential setting or
standard Snowflake CLI or SnowSQL profile was found. There was no
authorized Snowflake account configuration to probe. The preflight made no
service requests.

```powershell
.\.venv-core\Scripts\python.exe -m elt_rl.preflight official --airbyte-probe --snowflake-probe
```

An encrypted 2048-bit PKCS#8 RSA key and matching public key were created in
`%LOCALAPPDATA%\ELTBenchBooks`. The directory ACL was verified as protected
from inherited rules and restricted to the current Windows user. The
private JSON has a key-file reference and the proposed service user, role,
and warehouse names. Account and hostname are blank. Local decryption and
public-key matching passed. The private material is outside the repository,
and the key was never submitted to a service.

Use the public key to configure an authorized account, then enter its
account identifier and hostname into the private JSON. The
[Snowflake runbook](../LIVE_SETUP.md#3-configure-snowflake-after-authorization)
covers trial signup, grants, a monitored X-Small warehouse, the read-only
probe, separately authorized DDL, and cleanup.

## Verification and outstanding work

The complete offline suite, including the pinned renderer and Terraform
provider checks, returned `60 passed in 40.10s` after the seeder fix. The command used the
[previously recorded environment](books-runtime.md#correctness-and-regression-evidence)
with basetemp `.venv/books-machine-tests`. The test output and service checks
are in ignored `runs/books-machine/`.

After the restart, install and initialize Ubuntu, start the installed
Docker Desktop, and verify it with `docker run --rm hello-world`. Then bring up the
source stack and Airbyte, publish the connector, and execute and inspect the
local sync. Once an authorized Snowflake account and the warehouse and model
sampling approvals are in place, run the official rollout as documented.
Stage 1, Stage 2 and the execution-derived reward remain unverified live.
New cloud charges were USD 0.
