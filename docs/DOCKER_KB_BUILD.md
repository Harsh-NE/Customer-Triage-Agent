# Building the Docker knowledge base (Tier 1)

How the vector + BM25 store under `data/processed/docker/store/` is produced, how to verify it, and how it was
built on a one-shot AWS EC2 batch job. Everything here was run for real unless marked **untested**.

## 1. What the build produces

| Artifact | Path (under `data/processed/docker/`) | Notes |
|---|---|---|
| Filter manifest | `filter_manifest.jsonl` | one record per Markdown file, with the reason it was kept or dropped |
| Cleaned docs | `cleaned_docs.jsonl` | 961 documents |
| Chunks | `chunks.jsonl`, `chunks_metadata.jsonl` | 10,031 chunks; the second adds `product_area`, `component`, `doc_kind`, `tags`, `error_signals`, `source_url`, `license` |
| Taxonomy | `taxonomy.json` | frequency-counted `product_area` / `component` / `tags` |
| Vector store | `store/vector/` | Chroma, collection `kb_chunks__baai-bge-base-en-v1-5`, 768-dim |
| BM25 index | `store/bm25/` | `bm25_index.pkl` + `chunk_ids.json` |
| Run manifest | `store/store_manifest.json` | model, dimension, counts, status |

`data/` is git-ignored: the store is regenerable, so only the scripts and manifests are version-controlled.

## 2. Build locally

```bash
git clone --depth 1 https://github.com/docker/docs.git data/raw/docker-docs
python scripts/02_filter.py
python scripts/03_clean.py
python scripts/04_chunk.py
python scripts/05_metadata.py
python scripts/06_store.py          # downloads BAAI/bge-base-en-v1.5 once (~440 MB), then embeds every chunk
```

The defaults in scripts 02–06 already point at `data/raw/docker-docs` and `data/processed/docker/`, so no flags are
needed. Embedding is the only slow step: on CPU it took roughly **55 minutes** for 10,031 chunks (a `t3.xlarge`,
using about two of its four vCPUs; derived from the instance's boot time and the store manifest timestamp). Everything before it takes seconds to a couple of minutes.

**Do not point Docker output at an older store directory.** `06_store.py` would `get_or_create_collection` by *model*
name, silently adding Docker chunks into any existing collection built with the same model. Docker uses its own
directory (`data/processed/docker/store/`) for that reason.

### Refresh metadata without re-embedding

Metadata-only fixes (a corrected `product_area`, a new field) do not need new embeddings:

```bash
python scripts/05_metadata.py
python scripts/06_store.py --metadata-only      # rewrites Chroma metadata in place; BM25 untouched (it indexes text only)
```

## 3. Verify

```bash
python -m pytest -m real_store -s      # 12 tests on the real store, incl. a taxonomy regression check
python -m triage.cli replay --all      # one line per labeled scenario against the real store
```

A quick sanity check is `store_manifest.json` (`status: success`, `chunk_count == chunks_embedded`, `errors: []`) and the
`product_area` distribution: it must contain `engine`, `desktop`, `docker-hub` and must **not** contain `content` or any
name ending in `.md` (that was a real bug; see ARCHITECTURE.md §3.3).

## 4. Building on EC2 (one-shot batch job)

Use this when you do not want to tie up a laptop for the embedding step. It is a **batch job, not a server**: nothing
is left running afterwards.

### 4.1 Design

* **S3** holds the adapted scripts in and the finished store out: `s3://<bucket>/pipeline/scripts/` and
  `s3://<bucket>/docker-kb/processed/`. S3 at this scale costs cents.
* **One CPU instance** (`t3.xlarge`, Amazon Linux 2023) with an **IAM instance profile** (S3 read/write) — no keys on the box.
  **No GPU, so no GPU quota request is needed.**
* **A user-data script** runs the whole pipeline at first boot with no SSH session, writes `_DONE` to S3, uploads its log,
  and shuts the instance down. With `--instance-initiated-shutdown-behavior terminate` that shutdown **terminates** it.
* Closing your terminal or laptop does not affect the job: it runs on the instance, started by `cloud-init`.

### 4.2 The user-data script

```bash
#!/bin/bash
set -ex
exec > >(tee /var/log/user-data.log) 2>&1

BUCKET="<your-bucket>"
cd /opt && mkdir -p pipeline && cd pipeline

dnf install -y python3.11 python3.11-pip git
python3.11 -m pip install --upgrade pip
# CPU-only torch FIRST. Plain `pip install sentence-transformers` pulls the full CUDA stack (several GB)
python3.11 -m pip install torch --index-url https://download.pytorch.org/whl/cpu
python3.11 -m pip install PyYAML rank-bm25 chromadb sentence-transformers

aws s3 sync "s3://$BUCKET/pipeline/scripts/" ./scripts/       # the ADAPTED scripts (see §4.4)
git clone --depth 1 https://github.com/docker/docs.git data/raw/docker-docs

python3.11 scripts/02_filter.py
python3.11 scripts/03_clean.py
python3.11 scripts/04_chunk.py
python3.11 scripts/05_metadata.py
python3.11 scripts/06_store.py

aws s3 sync data/processed/docker/ "s3://$BUCKET/docker-kb/processed/"
echo "DONE $(date -u)" | aws s3 cp - "s3://$BUCKET/docker-kb/_DONE"
aws s3 cp /var/log/user-data.log "s3://$BUCKET/docker-kb/user-data.log"
shutdown -h now
```

**Known weakness:** `set -e` stops the script at the first failure, so the final `shutdown` is never reached and the
instance keeps running (and billing) until you terminate it, and the log never reaches S3. A `trap '...' ERR` that uploads
the log and shuts down would fix both. **That hardening is untested.**

### 4.3 Launch and watch

```bash
aws ec2 run-instances \
  --image-id <al2023-ami> --instance-type t3.xlarge \
  --iam-instance-profile Name=<instance-profile> \
  --instance-initiated-shutdown-behavior terminate \
  --user-data file://userdata.sh \
  --associate-public-ip-address \
  --block-device-mappings file://block-device.json \
  --key-name <keypair> --region <region>
# block-device.json: [{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":30,"VolumeType":"gp3"}}]

aws s3 ls "s3://<bucket>/docker-kb/_DONE"        # appears only after the whole pipeline AND the S3 sync succeed
aws s3 sync "s3://<bucket>/docker-kb/processed/" data/processed/docker/
```

Expect about **an hour** end to end (the one observed run: ~57 minutes from boot to the manifest). Check the instance state afterwards: it should be `terminated`.

### 4.4 The scripts must be the adapted ones

The adapted scripts (02–06) are **not committed** as of 2026-10-05, so a plain `git clone` of this repo on the instance
would fetch the old versions. Either commit and push first and clone the repo in the user-data script, or
`aws s3 sync scripts/ s3://<bucket>/pipeline/scripts/` as above. Do **not** copy your local `.env` onto the instance — the
scripts' defaults already point at the Docker paths, and `.env` holds an API key.

### 4.5 Pitfalls we actually hit

| Symptom | Cause | Fix |
|---|---|---|
| "Root user access keys are not recommended" | `aws configure` with root keys | Create an IAM user (S3, EC2, IAM, SSM policies as needed) and use *its* keys |
| `<<'EOF'`, `$RANDOM`, `/d/...` fail | Bash syntax pasted into PowerShell | Use PowerShell here-strings and `Get-Random`; or use Git Bash consistently |
| `Invalid JSON: [{DeviceName:...}]` (quotes gone) | PowerShell strips `"` when passing inline JSON to `aws.exe` | Put the JSON in a file and pass `file://x.json` |
| `#!/bin/bash` broken / odd first line | PowerShell `-Encoding utf8` writes a BOM | Write script files with `-Encoding ascii` |
| `--image-id: expected one argument` | `$AMI_ID` empty (SSM lookup denied, or `$REGION` not set in this session) | Attach SSM read access to the **user**; re-set `$REGION` |
| Instance `running` for ages, no `_DONE`, empty console output | **`No space left on device`**: the default ~8 GB root volume vs the CUDA PyTorch wheels | CPU-only torch + 30 GB volume (§4.2, §4.3) |
| `get-console-output` is empty | It is a periodic serial-console snapshot, not a live log — emptiness is *not* evidence of failure | Use SSH (`tail -f /var/log/user-data.log`), or poll `_DONE` |
| `TargetNotConnected` on SSM | Role permission added after boot; the agent had not retried | Wait, or use SSH instead |
| `ssh: Connection timed out` | Security group allows port 22 only from the IP at rule-creation time; it changed | Re-authorise your current IP (`/32`) |
| `Identity file ... not accessible` | Relative key path from a different directory | `cd` to the key's folder or use an absolute path |
| Typed `aws ...` commands in the SSH session | Those run on the *instance*, not your machine | `exit` back to your local shell first |
| Variables vanished (`$BUCKET`, `$REGION`) | PowerShell variables are per-session | Re-set them in each new window |

A key pair can only be attached **at launch**; adding SSH access to a running instance means relaunching.

### 4.6 Security and cost

* The `.pem` private key must never be committed: `*.pem` and `*.key` are in `.gitignore` (the key had been sitting
  untracked in the repo root). Prefer keeping it outside the repo.
* Scope port 22 to your own `/32`, never `0.0.0.0/0`.
* `.env` is git-ignored; it holds a live LLM API key. Treat any key printed into a terminal or transcript as exposed and rotate it.
* Cost: a `t3.xlarge` for about an hour plus S3 storage is small next to the free credit; the only way to run up a bill is an
  instance left running after a failed script — always confirm it is `terminated`, or terminate it by hand.
* Once the store is downloaded you can delete the bucket (`aws s3 rm ... --recursive` then `aws s3 rb ...`). The IAM role,
  instance profile and key pair cost nothing and are reusable.
