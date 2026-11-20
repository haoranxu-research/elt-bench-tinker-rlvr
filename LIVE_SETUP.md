# Live acceptance setup

## Tinker pilot

Production read-only checks accepted the saved credential, reported
`Qwen/Qwen3.5-4B` as sampleable and trainable with 65,536 context tokens, and
permitted reading billing usage. The project ID is unset, so `ServiceClient`
will use the organization’s Default project. A read-only Default project can
still reject session creation. Confirm the organization has spendable credit
before the authorized run. The usage API response verifies access to usage
metadata. [Tinker project and organization permissions](https://tinker-docs.thinkingmachines.ai/tinker/data-model/)

The pilot uses rank 16, three rollouts, one `forward_backward`, one
`optim_step` and one post-update verification forward pass. If all rewards
are equal or no usable actions remain, it exits before optimizing. The
reference token estimate is USD 0.4904. The run manifest records the rates
used for the final estimate. Checkpoint storage and finalized billing are separate.
[Published rates](https://tinker-docs.thinkingmachines.ai/tinker/models/models_and_pricing/)

The [authorized pilot](evidence/tinker-pilot.md) ran this command once from
the project root on Windows. The launcher uses the existing base Python CPU
PyTorch. Repeating the command for a new pilot requires separate approval.

```powershell
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys,runpy; sys.path.append(str(Path(sys.base_prefix) / ""Lib"" / ""site-packages"")); runpy.run_module(""elt_rl.run"", run_name=""__main__"")' train-one --allow-paid --budget-usd 0.60 --group-size 3 --out runs/tinker-001
```

The manifest captures sampling token counts, actual rewards, aligned action
count and target fingerprint, forward/backward input token count, optimizer
status, post-update probe, checkpoint path and metadata readback. Preserve the private manifest
and pipeline artifacts. After usage appears in billing, use the recorded
session to reconcile its usage and gross cost in the console. The SDK billing
API exposes hourly session-attributed usage, typically with a delay. Its cost
estimates and the local token estimate are separate from invoice totals or
remaining credit. Do not infer an update from a submitted request or rerun
automatically on a timeout.

## Official Snowflake books

Use the pinned ELT-Bench checkout and public source files. The Windows checkout
already has all 15 source inputs and three reference CSVs in ignored
`runs/books-assets/`. The host passed a real loopback HTTP test for the three
REST streams. Airbyte has completed a real local PostgreSQL sync. The scored
Snowflake rollout awaits authorized account access. [Runtime evidence](evidence/books-docker-runtime.md)

### 1. Prepare and verify the local sources

Use an existing Linux lab host with Docker Engine and Compose 2.24.4 or later, or enable WSL2
and Docker Desktop with administrator approval. Use a host isolated from
untrusted peers because the pinned Compose stack publishes development service
ports. Plan for at least 4 logical processors and 8 GiB available to Airbyte,
plus resources for the other services. Install `abctl`, Helm, `kubectl`, `psql`, Terraform,
and Python 3.11 or later. Use a dedicated Docker context or machine for the
fixed `elt-*` container names and the `books` seed databases.
[Airbyte requirements](https://docs.airbyte.com/platform/using-airbyte/getting-started/oss-quickstart)

On this Windows machine, enable WSL as an administrator first. Install the
Ubuntu distro under the project user's account so Docker Desktop can integrate
with it. The Docker Desktop per-user install uses the WSL 2 backend.
[Microsoft WSL install](https://learn.microsoft.com/en-us/windows/wsl/install)
[Docker Desktop install](https://docs.docker.com/desktop/setup/install/windows-install/)

On the audited machine, WSL and Docker Desktop are installed and the completed
Windows restart activated Virtual Machine Platform. Docker Desktop's own
WSL 2 distro can run Linux containers from the Windows Docker CLI. A separate
Ubuntu distro is useful for the Bash examples. [Bootstrap evidence](evidence/books-windows-bootstrap.md)

```powershell
# Administrator PowerShell. Save work and restart when installation requests it.
wsl.exe --install --no-distribution --web-download
# After the restart, in the project user's PowerShell.
wsl.exe --version
wsl.exe --set-default-version 2
wsl.exe --install --web-download -d Ubuntu
wsl.exe --list --verbose
```

Launch Ubuntu once to create its Linux user. If Docker Desktop is missing,
use the official installer in per-user mode. Launch Docker Desktop, review its
first-run agreement, and enable Ubuntu under **Settings → Resources → WSL
Integration**. Verify the engine and Compose from Ubuntu with a real container.
The WSL package must be 2.1.5 or newer and Ubuntu must be registered as version 2.
[Docker Desktop WSL backend](https://docs.docker.com/desktop/features/wsl/)

```powershell
Set-Location S:\STARTER\elt-tinker-phase1
# Only needed if Docker Desktop has yet to be installed.
$installer = (Resolve-Path 'runs/books-machine/Docker Desktop Installer.exe').Path
$signature = Get-AuthenticodeSignature -FilePath $installer
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Docker') {
    throw 'Docker installer signature could not be verified'
}
Start-Process -FilePath $installer -Wait -ArgumentList 'install','--user','--backend=wsl-2'
# From PowerShell after opening Docker Desktop and enabling Ubuntu integration.
wsl.exe -d Ubuntu -- docker info --format '{{.OSType}} {{.ServerVersion}}'
wsl.exe -d Ubuntu -- docker compose version
wsl.exe -d Ubuntu -- docker run --rm hello-world
```

Use the download linked in the Docker install guide if the staged installer
is missing or incomplete. Resume from the first check that has yet to pass.
If a partial download remains in the ignored directory, resume it before the
signature check.

```powershell
curl.exe -fsSL -C - 'https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe' `
  -o 'runs/books-machine/Docker Desktop Installer.exe'
```

Continue the Linux commands from the repository root inside Ubuntu. On the
audited machine, try `cd /mnt/s/STARTER/elt-tinker-phase1`. If the S: volume
isn't mounted, mount it as DrvFS or copy the project, pinned upstream checkout
and ignored staged assets to the Linux filesystem. Create a Linux virtual
environment there before installing the Python dependencies. The existing
Windows virtual environments are Windows-only.

Transfer the ignored staged files to the corresponding paths on the target
host. To fetch replacements, extract the `data/books` paths from the official
`data_api.zip` and `data_db.zip` into `runs/books-assets/data-api/` and
`runs/books-assets/data-db/`, respectively. Also extract
`data/address/alias.csv` from `data_api.zip` into `runs/books-assets/data-api/`.
The pinned shared connector uses that stream for its connection check. It is
outside the 15 `books` streams used for the reward. Download the two flat files from
the URLs in the pinned `books/config.yaml` to `runs/books-assets/flat-files/`
as `address_status.jsonl` and `order_status.csv`. The connector uses the original
URLs during a live run. Verify both URLs from the Airbyte workload network.
Fetch the three reference CSVs from the pinned revision
and verify the recorded hashes. [Upstream archive IDs](https://github.com/uiuc-kang-lab/ELT-Bench/blob/3b068d5f15f64541d05fbc33a817e4b08c6bf173/setup/elt_setup.sh)
[Reference hashes](evidence/live-readiness.md#official-snowflake-books)

From the project root in an activated project venv:

```bash
umask 077
python -m pip install -e '.[official]' awscli pymongo flask
export ELT_BENCH_ROOT="$(cd ../upstream-elt-bench && pwd)"
runtime="$PWD/runs/books-runtime-wsl"
private="$PWD/runs/books-private"
mkdir -p "$private"
python -m elt_rl.books_setup --checkout "$ELT_BENCH_ROOT" stage \
  --assets runs/books-assets --out "$runtime"
python -m elt_rl.books_setup --checkout "$ELT_BENCH_ROOT" rest-check --runtime "$runtime"

docker compose -p elt-docker -f "$runtime/elt-docker/docker-compose.yml" \
  -f "$PWD/deploy/books-compose.loopback.yml" config --quiet
docker compose -p elt-docker -f "$runtime/elt-docker/docker-compose.yml" \
  -f "$PWD/deploy/books-compose.loopback.yml" up -d --wait
pg_isready -h 127.0.0.1 -p 5433
curl -fsS http://127.0.0.1:4566/_localstack/health >/dev/null
docker exec elt-mongodb mongosh --quiet --eval 'if (!db.hello().isWritablePrimary) quit(1)'
(cd "$runtime/setup/sources/books" && bash ./data.sh "$runtime/setup")
(cd "$runtime/setup" && python mongo.py --path "$runtime/setup")
```

Run the seed commands only on the disposable source stack. The pinned seeders
recreate the local PostgreSQL and MongoDB `books` databases. Check each seeded
table or collection against the count printed by `stage` and check the two
objects in the local `books-bucket`. The PostgreSQL helper can continue past
an individual SQL error, so a successful script exit alone is insufficient.

LocalStack Community may lose its S3 objects after a restart. Before launching
the agent, seed or refresh the two staged inputs and check the keys using the
container's `awslocal` endpoint.

```bash
docker exec elt-localstack awslocal --region us-west-2 s3api head-bucket --bucket books-bucket ||
  docker exec elt-localstack awslocal --region us-west-2 s3 mb s3://books-bucket
for file in country.csv shipping_method.csv; do
  docker cp "$runtime/setup/data/books/$file" "elt-localstack:/tmp/$file"
  docker exec elt-localstack awslocal --region us-west-2 s3 cp "/tmp/$file" "s3://books-bucket/$file"
done
docker exec elt-localstack awslocal --region us-west-2 s3 ls s3://books-bucket/
```

### 2. Start and bind Airbyte

The official custom connector declares CDK 4.3.0 for Airbyte 1.5.1. The
legacy chart index lists chart 1.5.1 for that platform version. Use a private,
disposable cluster and keep Connector Builder enabled. The local deployment
below uses the documented image repository override for historical MinIO tags.
The verified chart archive staged in `runs/books-machine/airbyte-1.5.1.tgz`
can be unpacked into `$runtime` in place of the `helm pull` command.
On Linux x86-64, the staged abctl v0.30.4 archive can be unpacked into
`$runtime` and its binary directory added to the current shell PATH.

```bash
tar -xf runs/books-machine/abctl-v0.30.4-linux-amd64.tar.gz -C "$runtime"
export PATH="$runtime/abctl-v0.30.4-linux-amd64:$PATH"
abctl version
```

```bash
helm pull airbyte --repo https://airbytehq.github.io/helm-charts/ \
  --version 1.5.1 --untar --untardir "$runtime"
cat > "$runtime/minio-values.yaml" <<'YAML'
minio:
  image:
    repository: airbyte/minio
YAML
abctl local install --chart "$runtime/airbyte" --values "$runtime/minio-values.yaml" \
  --host localhost --insecure-cookies --no-browser
abctl local status
docker network connect elt-docker_elt_network airbyte-abctl-control-plane
```

On Windows, the same chart can be installed with the staged Windows abctl
binary. The Docker Desktop Linux context must be active. The artifacts below
are under the project's ignored runtime directory.

```powershell
$dockerBin = Join-Path $env:LOCALAPPDATA 'Programs/DockerDesktop/resources/bin'
$env:Path = "$dockerBin;$env:Path"
$env:DOCKER_CONTEXT = 'desktop-linux'
$env:DO_NOT_TRACK = '1'
$abctl = './runs/books-machine/abctl-v0.30.4-windows-amd64/abctl.exe'
& $abctl local install --chart (Resolve-Path runs/books-machine/chart/airbyte).Path `
  --values (Resolve-Path runs/books-machine/minio-values.yaml).Path `
  --host localhost --insecure-cookies --no-browser
& $abctl local status
```

If `abctl` stalls contacting Docker Hub after its images are cached, the
verified Airbyte 1.5.1 chart can also run directly in the existing kind cluster.
Import cached images into the node before deploying. The Docker Desktop cache
and the kind node's containerd cache are separate. The role of port `18000`
below is to reach the Airbyte server through a loopback-only port-forward.
Keep the port-forward open during setup, preflight and the rollout.

```powershell
$kubeconfig = Join-Path $env:USERPROFILE '.airbyte/abctl/abctl.kubeconfig'
$kubectl = Join-Path $dockerBin 'kubectl.exe'
& ./runs/books-machine/windows-amd64/helm.exe --kubeconfig $kubeconfig upgrade --install `
  airbyte-abctl runs/books-machine/chart/airbyte --namespace airbyte-abctl --create-namespace `
  --values deploy/books-airbyte-values.yaml --wait --timeout 20m
& $kubectl --kubeconfig $kubeconfig -n airbyte-abctl port-forward --address 127.0.0.1 `
  svc/airbyte-abctl-airbyte-server-svc 18000:8001
```

On a fresh local instance, complete the setup screen using the webapp service.
Forward `svc/airbyte-abctl-airbyte-webapp-svc` from `18001:80` in a separate
terminal and open `http://127.0.0.1:18001`. Use the server URL
`http://127.0.0.1:18000` for connector setup and append `/api/public/v1` for
`ELT_AIRBYTE_URL` on this route. [Local deployment evidence](evidence/books-docker-runtime.md)

From an Airbyte workload pod, verify that `elt-postgres:5432`,
`elt-mongodb:27017`, `elt-localstack:4566`, and `elt-api:5005` resolve and
accept connections, and that the public flat-file URLs are reachable. The
Docker network attachment is the upstream procedure. Actual pod reachability
depends on the host's network and DNS configuration.
[Upstream setup](https://github.com/uiuc-kang-lab/ELT-Bench/blob/3b068d5f15f64541d05fbc33a817e4b08c6bf173/setup/elt_setup.sh)
[Airbyte chart installation](https://docs.airbyte.com/platform/deploying-airbyte/abctl)

```bash
kubectl --kubeconfig "$HOME/.airbyte/abctl/abctl.kubeconfig" -n airbyte-abctl \
  run books-source-probe --image=busybox:1.36 --restart=Never --rm -i -- \
  sh -ec 'nc -w 5 elt-postgres 5432 </dev/null; nc -w 5 elt-mongodb 27017 </dev/null;
          wget -qO /dev/null http://elt-localstack:4566/_localstack/health;
          wget -qO /dev/null "http://elt-api:5005/books/book_language?limit=1&offset=0"'
```

Use the namespace where sync workloads run if the deployment differs from the
default. Test the flat files with the connector's own connection check or job.

Initialize a workspace in the local UI. The upstream helper can read local
abctl credentials through Docker. If that discovery lacks permissions, create
`$private/airbyte.json` with the workspace's `username` and `password` in a
private editor. The helper updates that file with the workspace and published
connector definition IDs. It creates an Airbyte Source without starting a sync.

```bash
python "$runtime/setup/setup_airbyte.py" --url http://localhost:8000 \
  --credentials "$private/airbyte.json"
python -m elt_rl.books_setup --checkout "$ELT_BENCH_ROOT" bind-airbyte \
  --credentials "$private/airbyte.json" --out "$private/books"
export ELT_BOOKS_INPUT_DIR="$private/books"
export ELT_AIRBYTE_URL=http://localhost:8000/api/public/v1
export ELT_GT_SNOWFLAKE="$PWD/runs/books-assets/gt_snowflake"
python -m elt_rl.preflight official --airbyte-probe
```

The binder generates the adapter's private `books/config.yaml` using the
pinned public config and the four Airbyte binding fields. The staged
`books-template` contains public specifications only. The adapter reads
Snowflake credentials separately and takes source routing and connector IDs
for built-in sources from the pinned checkout.

### Run one local Airbyte sync before Snowflake

This uses the published upstream REST connector and a disposable database on
the existing local source-stack PostgreSQL server. It requires the local
Compose stack and Airbyte. Use it to check discovery, the workload network,
actual row transfer, and job logs without cloud services.

```bash
docker exec elt-postgres psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -c 'CREATE DATABASE books_airbyte_smoke;'
```

1. In the self-hosted workspace, create a Postgres destination named
   `books-airbyte-smoke` with host `elt-postgres`, port `5432`, database
   `books_airbyte_smoke`, and default schema `airbyte_smoke`. Use the pinned
   development Postgres login from the public `books/config.yaml`. For this
   local stack use SSL disabled and no SSH tunnel. Run the destination check.
2. Create a manual connection from the published `Elt Snowflake` Source to
   `books-airbyte-smoke`. Choose the destination-defined namespace, enable only
   `book_language` and select **Full Refresh | Append**. Save and start one
   sync. Use a new empty destination database for a fresh count check.
3. Open the connection's **Job History**, inspect the attempt logs, and save
   them under an ignored run directory. Record the job ID, state, stream,
   records read and written, and connector versions. Confirm the destination
   contains 27 rows and record the SQL result. An Airbyte success label alone
   is insufficient.
4. After the job is terminal and the logs are saved, remove that test
   connection and destination in Airbyte. Leave the official source published
   for the rollout. Remove only the disposable database.

```bash
docker exec elt-postgres psql -U postgres -d books_airbyte_smoke -v ON_ERROR_STOP=1 \
  -Atc 'SELECT count(*) FROM airbyte_smoke.book_language;'
docker exec elt-postgres psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -c 'DROP DATABASE books_airbyte_smoke;'
```

Check the job's configured namespace and table mapping if the count query
cannot find the table. The smoke sync exercises one official REST stream.
Snowflake transfer for all 15 streams and the official evaluators require the
credentialed rollout. [Postgres destination](https://docs.airbyte.com/integrations/destinations/postgres)
[Airbyte job logs](https://docs.airbyte.com/platform/operator-guides/browsing-output-logs)

### 3. Configure Snowflake after authorization

Use an existing authorized lab account if available. To create a trial:

1. Open the Snowflake trial page and select **Start Here** under **The AI Data Cloud**.
2. Submit a valid email address and complete the signup and email verification steps.
   Choose **Standard** and a cloud and region permitted by the lab when prompted.
   Use the Snowflake trial offer and leave payment details unset.
3. Sign in to Snowsight as the trial administrator. Verify that the account is
   on trial terms and that the free usage balance is positive. Copy the account
   identifier and account URL from the account details. Use the identifier as
   `account` and the hostname portion of the URL as `host` in the private JSON.
4. Once setup and trial credit use are authorized, run the administrator SQL
   below with the prepared public key. Confirm the approved warehouse credit
   quota and the separate Tinker sampling budget before starting the rollout.

[Trial signup](https://www.snowflake.com/en/snowflake-trial/)
[Trial terms](https://docs.snowflake.com/en/user-guide/admin-trial-account)
[Account identifiers](https://docs.snowflake.com/en/user-guide/admin-account-identifier)

On the host where the
rollout runs, create an encrypted RSA PKCS#8 key in the private directory.
Send only the public key body to the Snowflake administrator.

On the audited Windows host, the encrypted key, public key and incomplete
credential JSON are already in `%LOCALAPPDATA%\ELTBenchBooks`. Reuse these files
for this account setup. Fill in `account` and `host` only after account access
is authorized. Select the path using `ELT_SNOWFLAKE_CREDENTIAL_JSON` when the
service account and grants are ready.

```powershell
$booksPrivate = Join-Path $env:LOCALAPPDATA 'ELTBenchBooks'
((Get-Content -LiteralPath (Join-Path $booksPrivate 'snowflake.pub')) |
    Where-Object { $_ -notlike '-----*' }) -join ''
# Once the account and role have been configured and login is authorized:
$env:ELT_SNOWFLAKE_CREDENTIAL_JSON = Join-Path $booksPrivate 'snowflake.json'
.\.venv-core\Scripts\python.exe -m elt_rl.preflight official --snowflake-probe
```

For a different host or a new key, use the following commands.

```bash
openssl genrsa 2048 | openssl pkcs8 -topk8 -v2 aes-256-cbc -out "$private/snowflake.p8"
openssl pkey -in "$private/snowflake.p8" -pubout -out "$private/snowflake.pub"
```

An authorized administrator can use the following example for a dedicated
role, service user, and single-cluster X-Small Gen1 warehouse. Choose the
monitor quota for the approved account and run, and replace the public key
placeholder with the base64 public key without the PEM header and footer.
The quota below is an example credit threshold. Resource monitors can have
enforcement latency and cover warehouse compute.
[Key pair authentication](https://docs.snowflake.com/en/user-guide/key-pair-auth)
[Airbyte destination grants](https://docs.airbyte.com/integrations/destinations/snowflake)
[Resource monitors](https://docs.snowflake.com/en/user-guide/resource-monitors)

```sql
USE ROLE ACCOUNTADMIN;
CREATE ROLE ELT_BOOKS_ROLE;
GRANT ROLE ELT_BOOKS_ROLE TO ROLE SYSADMIN;
CREATE RESOURCE MONITOR ELT_BOOKS_MONITOR WITH CREDIT_QUOTA = 1
    FREQUENCY = NEVER START_TIMESTAMP = IMMEDIATELY
    TRIGGERS ON 100 PERCENT DO SUSPEND_IMMEDIATE;
CREATE WAREHOUSE ELT_BOOKS_WH WITH WAREHOUSE_TYPE = STANDARD
    WAREHOUSE_SIZE = XSMALL GENERATION = '1'
    AUTO_SUSPEND = 60 AUTO_RESUME = TRUE INITIALLY_SUSPENDED = TRUE
    RESOURCE_MONITOR = ELT_BOOKS_MONITOR;
CREATE USER ELT_BOOKS_SERVICE TYPE = SERVICE
    RSA_PUBLIC_KEY = '<PUBLIC_KEY_BODY>'
    DEFAULT_ROLE = ELT_BOOKS_ROLE DEFAULT_WAREHOUSE = ELT_BOOKS_WH;
GRANT ROLE ELT_BOOKS_ROLE TO USER ELT_BOOKS_SERVICE;
GRANT USAGE ON WAREHOUSE ELT_BOOKS_WH TO ROLE ELT_BOOKS_ROLE;
GRANT CREATE DATABASE ON ACCOUNT TO ROLE ELT_BOOKS_ROLE;
```

Before a live run, confirm as `ACCOUNTADMIN` that the warehouse's
`resource_monitor` column names the dedicated monitor and that the monitor's
`credit_quota` and `remaining_credits` match the approved run. Inspect the
raw `SHOW` results so a `SELECT` projection cannot auto-resume the warehouse.

```sql
SHOW WAREHOUSES LIKE 'ELT_BOOKS_WH';
SHOW RESOURCE MONITORS LIKE 'ELT_BOOKS_MONITOR';
```

The role owns each transient database it creates and the `BOOKS` schema. That
ownership supplies the database and schema rights for Airbyte's internal
schema, stages and tables, Snowflake CTAS transformations, grading and
cleanup. Allow outbound TLS to Snowflake from both the driver and Airbyte
workers under the account's network policy. In a private editor, save
`$private/snowflake.json` with the following fields filled in, then point
`ELT_SNOWFLAKE_CREDENTIAL_JSON` at it. The account identifier and host are
separate fields. An encrypted key needs its passphrase for both connectors.

```json
{
  "account": "<organization-account>",
  "host": "<organization-account>.snowflakecomputing.com",
  "user": "ELT_BOOKS_SERVICE",
  "role": "ELT_BOOKS_ROLE",
  "warehouse": "ELT_BOOKS_WH",
  "private_key_file": "snowflake.p8",
  "private_key_file_pwd": "<passphrase>"
}
```

```bash
export ELT_SNOWFLAKE_CREDENTIAL_JSON="$private/snowflake.json"
python -m elt_rl.preflight official --airbyte-probe --snowflake-probe
```

With authorized credentials, the Snowflake probe can verify authentication
and warehouse visibility via `SHOW WAREHOUSES`. Add `--namespace-probe` only
after DDL is authorized. It creates and drops a fresh transient database and
`BOOKS` schema. Airbyte transfer and transform permissions need a live run.

### 4. Execute and clean up one official rollout

With separate authorization for Snowflake usage and Tinker model sampling,
set the project Tinker settings and run one rollout. The token budget below
is an example and does not constrain Snowflake costs. The runner performs its
token estimate before sampling.

```bash
python -m elt_rl.run official-rollout --allow-paid --allow-warehouse --budget-usd 1 --out runs/books-001
```

Keep the manifest, trajectory and artifacts, Airbyte job metadata, Stage 1
log, Stage 2 results when the gate passes, and grade private. The replay uses
its own database, and the adapter destroys its own Airbyte resources and
drops the database. If `cleanup-required.txt` appears, inspect just that
run's Airbyte job IDs and configuration. Confirm that its syncs are terminal
and remove its Airbyte connections, sources and destination before dropping
the exact database named in the notice. A Snowflake administrator can use
`DROP DATABASE IF EXISTS <exact_run_database>;` after confirming ownership.
Keep any `private-recovery/` directory private because it can hold Terraform
state with credentials.

The run writes sampled tokens to `sampled-actions.jsonl`, tool calls and
observations to `pipelines/*.tools.jsonl`, and per-attempt Airbyte jobs and
grader files to `official/<run-database>/`.

Warm the exact connector versions reported by the local Airbyte catalog in
the kind node before starting the rollout. The adapter allows 600 seconds
per Airbyte sync, Terraform operation and evaluator process. This accounts
for the queue delay observed in the verified local sync. The rollout uses a
60-minute Cookbook timeout to allow for the six-connection load and the
submission replay. In-flight service operations retain their own timeouts.

Run the local source preflight immediately before requesting execution. It
compares the published custom connector manifest to the pinned checkout,
provisions all six Airbyte connections with their original source settings and
sync modes, and verifies the complete inventory and all 15 counts against
`evaluation/table.json` in a disposable local PostgreSQL database. Its JSON
includes the job IDs, expected and observed row counts, and cleanup status.
The command requires loopback Airbyte and the `elt-postgres` Docker container.
It does not contact Tinker or Snowflake with the flags shown below. Reseed
LocalStack after a restart and rerun the probe after changing source inputs
or network configuration.

On the Windows host with the local Airbyte API forwarded to port `18000`, use
the same Python runtime as the verified model pilot. Run preflight first. The
rollout command requires explicit approval for both services and a new output
directory. The example uses USD 1 as its Tinker estimate limit.

```powershell
$booksPrivate = Join-Path $env:LOCALAPPDATA 'ELTBenchBooks'
$env:ELT_BOOKS_INPUT_DIR = Join-Path $booksPrivate 'books'
$env:ELT_AIRBYTE_URL = 'http://127.0.0.1:18000/api/public/v1'
$env:ELT_SNOWFLAKE_CREDENTIAL_JSON = Join-Path $booksPrivate 'snowflake.json'
$env:TF_CLI_CONFIG_FILE = (Resolve-Path .venv-core/tf-tools/terraform.rc).Path
$env:CHECKPOINT_DISABLE = '1'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$docker = Join-Path $env:LOCALAPPDATA 'Programs/DockerDesktop/resources/bin/docker.exe'
.\.venv-core\Scripts\python.exe -m elt_rl.preflight official --airbyte-probe --source-probe --docker $docker --docker-context desktop-linux
# After the local probe passes and both services have been authorized:
.\.venv-core\Scripts\python.exe -m elt_rl.preflight official --snowflake-probe
# Run only after the approved service checks pass.
.\.venv\Scripts\python.exe -c 'from pathlib import Path; import sys,runpy; sys.path.append(str(Path(sys.base_prefix) / ""Lib"" / ""site-packages"")); runpy.run_module(""elt_rl.run"", run_name=""__main__"")' official-rollout --allow-paid --allow-warehouse --budget-usd 1 --out runs/books-001
```

Record the rollout's UTC start and end times and preserve the run manifest's
actual sampling token counts and published-rate cost estimate. Reconcile
against the Tinker billing entry when available. For Snowflake, an authorized
administrator can record `CREDITS_USED_COMPUTE` and `CREDITS_USED_CLOUD_SERVICES`
from `SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY` for `ELT_BOOKS_WH` and
the matching hourly windows. Keep delayed metering pending until it appears.
The warehouse view reports usage credits, and cloud-services credits can
differ from billed credits. [Warehouse metering](https://docs.snowflake.com/en/sql-reference/account-usage/warehouse_metering_history)

The second November 20 credentialed attempt loaded all 15 streams into
Snowflake. Validation of the sampled transformations blocked submission.
The Airbyte worker override in `deploy/books-airbyte-values.yaml` limits
each sync job to one attempt.
[Second credentialed attempt evidence](evidence/books-snowflake-second.md)

After inspecting results, stop the disposable local services. Admins can
suspend the dedicated warehouse, revoke `CREATE DATABASE` from the dedicated
role, and drop the dedicated service user, warehouse, monitor and role if
they were reserved for one run and all run-owned databases are gone.

```bash
docker compose -p elt-docker -f "$runtime/elt-docker/docker-compose.yml" \
  -f "$PWD/deploy/books-compose.loopback.yml" down
abctl local uninstall
```


## Warehouse cost

Snowflake advertises an eligible trial with USD 400 in usage credits. The
trial lasts up to 30 days or until the credit balance is exhausted, and
does not require a payment method. Leave the account on trial terms if using
trial credits. The locally hosted Airbyte and source containers incur no
cloud service subscription if run on a machine already available to the
project. [Trial offer](https://www.snowflake.com/en/snowflake-trial/) · [Trial terms](https://docs.snowflake.com/en/user-guide/admin-trial-account)

For context, AWS US East Standard on-demand is USD 2 per platform credit,
and an X-Small Gen1 warehouse uses one credit per hour. Fifteen to sixty
billed compute minutes would therefore be USD 0.50 to USD 2.00 for compute
alone. That is a cost illustration. No run time or actual Snowflake charge
was measured. Resumes have a 60-second minimum, and storage, transfer and
other charges can add to the total. Use short auto-suspend and a monitored
dedicated warehouse. [Credit prices](https://www.snowflake.com/legal/creditconsumptiontable/) ·
[Warehouse rates](https://docs.snowflake.com/en/user-guide/performance-query-warehouse-size) ·
[Compute billing](https://docs.snowflake.com/en/user-guide/cost-understanding-compute)
