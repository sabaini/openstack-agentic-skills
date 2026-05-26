---
name: diagnose-sunbeam
description: Use when diagnosing failed Sunbeam CI runs, analyzing sosreport tarballs, juju status files, sunbeam CLI logs, or investigating multi-node OpenStack deployment failures on Canonical K8s
---

# Diagnose Sunbeam CI Failures

## Core Principle

**Prove less, qualify more.** Symptoms are not causes. A diagnosis must separate what the artifacts show from what you infer. Name a root cause only when direct evidence supports it. When the artifacts prove only the failure surface, say so.

## Mandatory Diagnosis Algorithm

Every diagnosis MUST follow these steps in order. Do not skip steps or reorder them.

```
1. Extract archives
2. Identify deployment phase from artifacts
3. Collect observed facts with file:line references
4. Run false-negative checklist (MANDATORY before declaring real failure)
5. Identify the immediate failure surface (what directly failed)
6. Evaluate candidate mechanisms (what might have caused it)
7. Check counter-evidence for each candidate
8. Classify each claim: Confirmed / Supported / Speculative
9. Write DIAGNOSTICS.md
```

## Evidence Hierarchy

When artifacts conflict, higher-ranked evidence wins:

| Rank | Source | What it proves |
|---|---|---|
| 1 | Remote CLI completion log (`sosreport-*/logs/sunbeam-*.log` ending in `ResultType.COMPLETED`) | The remote operation succeeded, regardless of what the CI transport reports |
| 2 | Juju status + cluster list at collection time | Actual deployment state at a known timestamp |
| 3 | CI output log (`generated-sunbeam-output.log`) exit codes and stderr | What the CI runner observed â€” may not reflect remote reality |
| 4 | Juju debug logs | Agent lifecycle events â€” useful for sequencing, not for proving external causes |
| 5 | Pod logs, sosreport system logs | Supporting detail â€” confirms or weakens a hypothesis |

**Key rule:** A CI exit code 255 with "Broken pipe" is a Rank 3 observation. A remote CLI log showing `ResultType.COMPLETED` is Rank 1. Rank 1 overrides Rank 3. Always check before concluding the operation failed.

**Partial log caveat:** `ResultType.COMPLETED` on the **last step** of a CLI log confirms full completion. `ResultType.COMPLETED` on an intermediate step only confirms that step succeeded. Check which step is last before declaring the entire operation succeeded.

## Red Herrings â€” Do Not Treat These as Root Causes

| Observation | Why it's a red herring | What to do instead |
|---|---|---|
| Interactive prompt in SSH stdout (`Configure endpoint services? [y/n]`) | Often appears in the output buffer BEFORE the real work ran; does not prove the prompt caused the hang | Check remote CLI logs for what actually executed |
| Post-failure SSH host key change (`REMOTE HOST IDENTIFICATION HAS CHANGED`) | Proves the host identity changed AFTER the failure was recorded; does not prove MAAS re-provisioned DURING the operation | State: "host key changed post-failure; cause of the original failure is not established by this artifact" |
| `No route to host` after an SSH session dies | Proves the node was unreachable at cleanup time; does not prove when or why it became unreachable | Report it as a post-failure observation, not a cause |
| Downstream blocked/waiting units | A unit in `blocked` after another unit failed is a consequence, not a cause | Trace back to the first unit that left `active/idle` |
| `generated-monitor.log` showing "No new models found" on single-node | Normal for single-node â€” controller is on the remote LXD, not visible to the CI monitor | Ignore for single-node topology |

## Step 0: Extract Archives

```bash
cd /path/to/run-directory

# Extract sosreport tarballs (mknod errors are expected and harmless)
for f in generated-sunbeam-sosreport-*.tar.xz; do
  tar -xf "$f" 2>/dev/null
done

# Extract pod log tarballs
for f in generated-sunbeam-pods_*_logs.tgz; do
  tar -xzf "$f" 2>/dev/null
done
```

## Step 1: Identify Deployment Phase

Determine how far the deployment got:

| Artifacts Present | Phase |
|---|---|
| No juju status files, no sunbeam CLI logs in sosreports | Pre-bootstrap |
| Juju status files exist, only bootstrap node has CLI logs | Bootstrap (joins never started) |
| Juju status files exist, multiple nodes have CLI logs | Join phase |
| Validation logs exist (`generated-sunbeam-validation_*.log`) | Post-deploy / test |
| Plugin enable output visible in `generated-sunbeam-output.log` | Plugin enable |

**Quick artifact inventory:**
```bash
# Which key files exist?
ls generated-sunbeam-output.log generated-sunbeam-juju_status_*.txt \
   generated-sunbeam-validation_*.log generated-foundation.log 2>/dev/null

# Count CLI logs per node (most logs = likely bootstrap node)
for sos in sosreport-*/; do
  hostname=$(echo "$sos" | sed 's/sosreport-\(.*\)-20[0-9]*-.*/\1/')
  count=$(ls "$sos/home/ubuntu/snap/openstack/common/logs"/*.log 2>/dev/null | wc -l)
  echo "$hostname: $count CLI logs"
done
```

**Topology:** Check `config-sunbeam.yaml` or the run directory name for SKU:
- `single_node`: one node, LXD-backed controller (monitor "No new models" is normal)
- `external_juju`: pre-existing controller, `generated-foundation.log` covers MAAS layer
- Multi-node: 3-7+ bare-metal nodes

## Step 2: Collect Observed Facts

Read the primary artifacts for the identified phase. Record **only what the file directly shows**, with `file:line` references.

**For every phase â€” always check these first:**
```bash
# SSH transport failures
grep -n "client_loop: send disconnect: Broken pipe" generated-sunbeam-output.log
grep -n "Connection to .* closed by remote host" generated-sunbeam-output.log
grep -n "REMOTE HOST IDENTIFICATION HAS CHANGED" generated-sunbeam-output.log generated-github-runner-run.log
```

**Phase-specific checks:**

### Pre-bootstrap
- `generated-sunbeam-output.log` â€” check: `wipefs` errors, `CalledProcessError`, `ERROR: No external connectivity`
- `generated-foundation.log` â€” check: MAAS API errors (`ServerError: 500`, `400 Bad Request`); does the error body name a specific issue or is it generic? Also check `pg_dump` failures, Python tracebacks
- `generated-github-runner-run.log` â€” check: `ssh-keyscan` failures (timeout vs connection refused?), Testflinger provisioning errors, `Mirror sync in progress?` (if multiple nodes fail the same curtin step simultaneously, mirror issue is a candidate)
- `sosreport-*/sos_commands/block/lsblk` â€” check: does the node have the expected disks, or only an OS drive?

### Bootstrap
- `generated-sunbeam-output.log`: exit codes, stdout/stderr of bootstrap command
- Remote CLI log: `sosreport-<bootstrap>/home/ubuntu/snap/openstack/common/logs/sunbeam-*.log` â€” search for final `ResultType` entry
- `pexpect.exceptions.TIMEOUT`: juju add-machine connectivity issue

### Join
- `generated-sunbeam-output.log`: per-node join exit codes, stdout, stderr
- Remote CLI logs for each failing node: search for final `ResultType` entry
- `generated-sunbeam-juju_status_openstack-machines.txt`: unit states, scale
- `generated-sunbeam-sunbeam_cluster_list.txt`: which nodes are present

### Post-deploy / Plugin enable
- `generated-sunbeam-output.log`: which command failed, exit code, timeout messages
- `generated-sunbeam-juju_status_openstack.txt`: unit states
- `generated-sunbeam-validation_*.log`: test results, HTTP errors
- Pod logs (`generated/sunbeam/logs-openstack-*.txt`): service-level errors

## Step 3: False-Negative Check (MANDATORY)

**You MUST run this checklist before declaring any failure real.** This is not optional.

| Check | How | If true |
|---|---|---|
| CI stderr shows `client_loop: send disconnect: Broken pipe`? | Grep output.log | SSH transport died; remote may have succeeded |
| Remote CLI log ends with `ResultType.COMPLETED`? | Read last 20 lines of sosreport sunbeam-*.log for the failing node | Remote operation succeeded â€” CI failure is false negative |
| `sunbeam_cluster_list.txt` shows all expected nodes? | Compare node count to `config-nodes.yaml` | Cluster formed successfully |
| All juju units `active/idle`? | Scan both juju status files | Deployment is healthy |
| All K8s pods `Running` with 0 restarts? | Check `kubectl_get_pod.txt` | K8s layer is healthy |

**If all five checks pass: the failure is a false negative.** State this directly. Do not speculate about what "might have" gone wrong.

**If the remote CLI log is not available** (no sosreport, or sosreport from wrong node): state that the false-negative check is inconclusive, not that the operation failed.

## Step 4: Identify Immediate Failure Surface

State **what directly failed** using only the facts collected in Step 2. This is the narrowest true statement you can make.

Examples of good failure surface statements:
- "The CI recorded exit code 255 and `Broken pipe` for the SSH session running `sunbeam cluster join` on node X at timestamp T."
- "`wipefs -a /dev/disk/by-dname/disk1` on node X returned `No such file or directory`."
- "`sunbeam enable loadbalancer` exited with `wait timed out after 900s` at timestamp T."

Examples of over-claiming (avoid these):
- "MAAS re-provisioned the node" (unless you have direct MAAS logs proving it)
- "The node ran out of memory" (unless you have OOM killer logs)
- "Network connectivity was lost" (unless you have both endpoints' logs showing the drop)

## Step 5: Evaluate Candidate Mechanisms

For each plausible explanation, apply this template:

```
Candidate: [mechanism name]
Suggests it: [what symptom points here]
Would confirm it: [what artifact would prove this]
Would contradict it: [what artifact would disprove this]
Artifact check result: [what you actually found]
Status: Confirmed / Supported / Speculative
```

**Status definitions:**
- **Confirmed**: Direct artifact evidence proves the mechanism (e.g., remote CLI log shows `ResultType.COMPLETED` proving the operation succeeded; `lsblk` shows no `disk1` proving the disk is missing)
- **Supported**: Artifacts are consistent with the mechanism but do not prove it exclusively (e.g., SSH exit 255 + empty stdout is consistent with PTY failure, but could also be a network drop)
- **Speculative**: No direct evidence; mechanism is plausible based on general knowledge but artifacts do not distinguish it from alternatives (e.g., "likely OOM" when no OOM killer log exists)

**Counter-evidence requirement:** For every candidate you evaluate, you MUST check for at least one artifact that would weaken the claim. If you skip this, the diagnosis is incomplete.

**Missing remote evidence rule:** If no sosreport exists for the failing node (node was down at collection time, or sosreport is from a different host like a Juju controller LXD), then no claim about what happened on that node can be Confirmed. You may list candidates as Supported or Speculative, but the diagnosis MUST state: "Remote-side evidence unavailable for node X; mechanism not established."

## Diagnostic Heuristics

These are patterns observed in prior CI failures. Use them as **hypotheses to test**, not conclusions to assume. Each requires the evidence listed under "Confirms it" before you can claim it.

### SSH Transport Failures

**Broken Pipe (false negative candidate)**
- Suggests it: exit 255, `client_loop: send disconnect: Broken pipe` in stderr
- Confirms it: remote CLI log ends with `ResultType.COMPLETED`
- Contradicts it: remote CLI log shows `ERROR`/`Exception`, or no remote CLI log exists
- If unconfirmed: "CI SSH session died (exit 255, Broken pipe); remote outcome not established"

**PTY Allocation Failure (false negative candidate)**
- Suggests it: `Pseudo-terminal will not be allocated` in stderr, empty stdout, exit 255
- Confirms it: remote CLI log shows the command ran and completed
- Contradicts it: remote CLI log absent or shows no execution
- If unconfirmed: "SSH PTY allocation failed; whether the remote command executed is not established"

### Infrastructure Failures

**Missing disk**
- Suggests it: `wipefs: error: /dev/disk/by-dname/disk1: No such file or directory`
- Confirms it: `lsblk` in sosreport shows no secondary disk on that node
- Contradicts it: `lsblk` shows the disk exists (maybe a symlink issue instead)

**MAAS API failure**
- Suggests it: `ServerError: 500` or `400 Bad Request` in `generated-foundation.log`
- Confirms it: specific MAAS error message in the response body (e.g., `maasserver_routable_pairs does not exist`)
- Contradicts it: error is a client-side timeout, not a server error
- Caution: do not claim "MAAS DB corruption" from a 500 alone; 500 could be transient

**VM boot timeout**
- Suggests it: `ssh-keyscan` retries exhausted in `generated-github-runner-run.log`
- Confirms it: timing shows VM boot took longer than retry window
- Contradicts it: keyscan failed for a different reason (connection refused vs timeout)

### Juju / Charm Failures

**Agent loss after model migration**
- Suggests it: unit in `unknown/lost` state
- Confirms it: juju debug log shows `QUIESCE` + `agent.conf left unchanged` or `invalid entity name or password` for that specific unit
- Contradicts it: unit went lost at a time with no migration events in the log
- If unconfirmed: "unit X is in unknown/lost state; cause not established"

**Terraform state lock contention**
- Suggests it: `Error acquiring the state lock` in CLI logs
- Confirms it: lock error followed by successful retry (60s later) â€” confirms contention, not failure
- Note: lock contention alone rarely causes deployment failure; check whether it contributed to a timeout

**Timeout near-miss**
- Suggests it: `wait timed out after N` in output.log
- Confirms it: pod logs or juju debug log show the unit going active within minutes after the timeout timestamp
- Contradicts it: unit never reached active state

### Post-Deploy Failures

**Traefik hook backlog after TLS**
- Suggests it: traefik unit stuck in `maintenance` after `sunbeam enable tls`
- Confirms it: juju debug log shows continuous `ingress-relation-changed` hook executions on that unit spanning the timeout window
- Contradicts it: traefik unit was idle; a different unit caused the timeout

**MySQL connection exhaustion**
- Suggests it: `MySQL Error (1040)` in any pod log
- Confirms it: error 1040 appears across multiple mysql-router pod logs simultaneously
- Contradicts it: error appears in only one pod log (might be a single-service issue, not exhaustion)

**Validation test failures**
- Suggests it: non-zero failure count in `validation_*.log`
- Confirms it: specific HTTP error codes and messages in the test log
- Note: if pre-TLS tests passed but post-TLS tests failed, the TLS enablement window is a candidate â€” but confirm the specific failing test endpoints use the TLS-affected ingress path. If failing tests are unrelated to TLS (e.g., Swift/RGW auth, metadata service), timing correlation alone does not establish TLS as the cause

### Node Unavailability

**Node became unreachable mid-run**
- Suggests it: `Connection to ... closed by remote host` followed by `No route to host`
- Confirms it: sosreport `uptime` shows reboot during the run, OR sosreport shows fresh image (snap list = only snapd+core, missing juju dir)
- Contradicts it: sosreport uptime is consistent with continuous operation; node was available at collection time
- **Caution:** "closed by remote host" + post-failure host key change does NOT prove MAAS re-provisioned the node during the operation. It proves: (1) the remote SSH daemon terminated the session, and (2) the host key was different when checked later. The mechanism is not established. Use: "Node became unreachable at T; host key had changed by T+N. Cause not established by available artifacts."

## Log File Reference

| File | Contents | Priority |
|---|---|---|
| `generated-sunbeam-output.log` | CI execution log (SSH commands, exit codes, stdout/stderr per node) | 1 |
| `sosreport-*/home/ubuntu/snap/openstack/common/logs/sunbeam-*.log` | Sunbeam CLI logs per node (remote-side execution â€” outranks CI transport) | 1 |
| `generated-sunbeam-juju_status_openstack.txt` | K8s model: OpenStack service unit states | 2 |
| `generated-sunbeam-juju_status_openstack-machines.txt` | Machine model: bare-metal unit states | 2 |
| `generated-sunbeam-sunbeam_cluster_list.txt` | Cluster membership | 2 |
| `generated-foundation.log` | MAAS/Terraform infra provisioning | 2 (pre-bootstrap) |
| `generated-sunbeam-validation_*.log` | Validation test results | 2 (post-deploy) |
| `generated-sunbeam-juju_debug_log_openstack-machines.txt` | Machine model agent logs | 3 |
| `generated-sunbeam-juju_debug_log_openstack.txt` | K8s model agent logs | 3 |
| `generated/sunbeam/logs-openstack-*.txt` | Extracted pod logs per service | 3 (post-deploy) |
| `generated-github-runner-run.log` | CI orchestrator, Python tracebacks | 4 |
| `generated-sunbeam-show_units_openstack.txt` | Unit relation data | 4 |
| `generated-sunbeam-juju_debug_log_controller.txt` | Controller agent logs | 4 |
| `generated-monitor.log` | Deployment monitor (normal="No new models" on single-node) | 5 |
| `generated-sunbeam-manifest.yaml` | Manifest (database topology, channel) | 5 |
| `generated-sunbeam-kubectl_get_pod.txt` | K8s pod status | 5 |
| `config-sunbeam.yaml` | Deployment config (osd_devices, roles) | 5 |
| `generated-lastlines.txt` | Last CI output lines + tracebacks | 5 |
| `sosreport-*/sos_commands/block/lsblk` | Block devices per node | On-demand |
| `sosreport-*/sos_commands/snap/snap_list.txt` | Installed snaps (detect fresh image) | On-demand |

## Output Format

Produce a `DIAGNOSTICS.md` in the CI run directory:

```markdown
# Diagnostics: <run-id>

## Verdict
**FALSE NEGATIVE / REAL FAILURE / INCONCLUSIVE** â€” one sentence stating what is proven.

## Failure Phase
Which phase: pre-bootstrap / bootstrap / join / plugin-enable / validation

## Immediate Failure Surface
What directly failed, stated narrowly with file:line references. No mechanism claims here.

## Observed Facts
Bullet list of what the artifacts show, each with a file:line reference.
Include facts that support AND facts that weaken any candidate explanation.

## Candidate Causes

### 1. [Name] â€” Status: CONFIRMED / SUPPORTED / SPECULATIVE
What suggests it, what confirms it, what was checked as counter-evidence.

**Evidence for:**
- `file:line` â€” what it shows

**Evidence against / not found:**
- What was checked and what it showed (or "not available")

### 2. ...

## What Is Not Established
Explicitly list plausible-sounding claims that the artifacts do NOT prove.
Example: "The artifacts do not establish whether the node was re-provisioned by MAAS
or crashed for another reason."

## Juju Status Summary
Units in error/blocked/lost, or "All healthy", or "N/A".

## Key Log Files Examined
Table of files checked with one-line findings.
```

## Parallelization

When diagnosing multiple CI runs, dispatch one subagent per run directory. Each agent follows the full algorithm independently.
