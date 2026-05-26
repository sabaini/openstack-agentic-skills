# Lab Layout Reference — Sunbeam Rack

---

## Jump Host

```
ubuntu@<your-jump-host>
MAAS CLI: /snap/bin/maas admin
```

---

## Nodes

| Hostname | system_id | OAM IP | Arch | Role |
|---|---|---|---|---|
| n1 | (check MAAS) | 10.21.2.x | x86_64 | control/compute |
| n2 | (check MAAS) | 10.21.2.x | x86_64 | control/compute ← **reference node** |
| n3 | (check MAAS) | 10.21.2.x | x86_64 | control/compute |
| n4 | (check MAAS) | 10.21.2.x | x86_64 | compute |
| n4-dpu | (check MAAS) | 10.21.2.x | arm64 | network (DPU) |

---

## Expected Interface Layout (per x86 node)

Every x86 compute/control node must have all of these:

| Interface | Type | VLAN | Fabric | Juju Space | IP |
|---|---|---|---|---|---|
| `bondm` | bond | 3400 (untagged on mgmt-fabric) | management-fabric | oam | 10.21.2.x |
| `bondm.3402` | vlan | 3402 | management-fabric | admin | 10.21.3.x |
| `bondd` | bond | untagged | data-fabric | — | no IP |
| `bondd.3404` | vlan | 3404 | data-fabric | public | 10.21.8.x |
| `bondd.3405` | vlan | 3405 | data-fabric | ceph-access | 10.21.4.x |
| `bondd.3407` | vlan | 3407 | data-fabric | overlay | 10.21.6.x |
| `bondd.3408` | vlan | 3408 | data-fabric | tenant-storage | 10.21.9.x |
| `bondd.3409` | vlan | 3409 | data-fabric | provider | LINK_UP |
| `bond2` | bond | untagged | data-fabric | — | no IP |
| `br-bond2` | bridge | untagged | data-fabric | — | no IP |
| `br-bond2.3403` | vlan | 3403 | data-fabric | internal | 10.21.7.x |
| `br-bond2.3406` | vlan | 3406 | data-fabric | ceph-replica | 10.21.5.x |

---

## Juju Space → Subnet Mapping

| Juju Space | VLAN | Subnet | If missing on a node... |
|---|---|---|---|
| oam | 3400 | 10.21.2.0/24 | Can't reach the node at all |
| admin | 3402 | 10.21.3.0/24 | Charm API unreachable |
| public | 3404 | 10.21.8.0/24 | No public-facing API endpoint |
| ceph-access | 3405 | 10.21.4.0/24 | VMs can't read/write Ceph |
| overlay | 3407 | 10.21.6.0/24 | OVN tunnels fail, VM traffic breaks |
| internal | 3403 | 10.21.7.0/24 | OpenStack services can't communicate |
| ceph-replica | 3406 | 10.21.5.0/24 | Ceph replication stops |
| tenant-storage | 3408 | 10.21.9.0/24 | Tenant storage unavailable |
| provider | 3409 | 91.189.88.0/28 | No internet egress for VMs |

---

## n2 vs n4 IP Reference (example — your IPs will differ)

| Interface | Space | n2 IP (example) | n4 IP (example) |
|---|---|---|---|
| `bondm` | oam | 10.21.2.x | 10.21.2.x |
| `bondm.3402` | admin | 10.21.3.x | 10.21.3.x |
| `bondd.3404` | public | 10.21.8.x | 10.21.8.x |
| `bondd.3405` | ceph-access | 10.21.4.x | 10.21.4.x |
| `bondd.3407` | overlay | 10.21.6.x | 10.21.6.x |
| `bondd.3408` | tenant-storage | 10.21.9.x | 10.21.9.x |
| `bondd.3409` | provider | LINK_UP | LINK_UP |
| `br-bond2.3403` | internal | 10.21.7.x | 10.21.7.x |
| `br-bond2.3406` | ceph-replica | 10.21.5.x | 10.21.5.x |

---

## Node MAAS Interface IDs (example — read yours with Step 0)

MAAS VLAN IDs below are lab-specific. Discover yours with:
```bash
/snap/bin/maas admin vlans read <fabric-id>
```

| Interface | MAAS VLAN ID (example) | Notes |
|---|---|---|
| bondm | — | management-fabric untagged |
| bondm.3402 | — | management-fabric VLAN 3402 |
| bondd | — | data-fabric untagged |
| bondd.3404 | — | data-fabric VLAN 3404 |
| bondd.3405 | — | data-fabric VLAN 3405 |
| bondd.3407 | — | data-fabric VLAN 3407 |
| bondd.3408 | — | data-fabric VLAN 3408 |
| bondd.3409 | — | data-fabric VLAN 3409 |
| bond2 | — | data-fabric untagged |
| br-bond2 | — | data-fabric untagged |
| br-bond2.3403 | — | data-fabric VLAN 3403 |
| br-bond2.3406 | — | data-fabric VLAN 3406 |

---

## DPU Interface State (arm64 DPU node)

Typical state after MAAS enlistment:

| Interface | Type | Fabric | IP |
|---|---|---|---|
| eth0 | Physical | management-fabric VLAN 3400 | 10.21.2.x (MAAS-provided) |
| p0 | Physical (bonded) | data-fabric | — |
| p1 | Physical (bonded) | data-fabric | — |
| bondd | OVS bond | data-fabric untagged | — |
| br-data | OVS bridge | data-fabric untagged | — |

Interfaces still needed for network role:

| Interface | VLAN | Subnet | Parent | Purpose |
|---|---|---|---|---|
| `eth0.3402` | 3402 | 10.21.3.0/24 | eth0 | admin |
| `bondd.3407` | 3407 | 10.21.6.0/24 | bondd | overlay |
| `bondd.3403` | 3403 | 10.21.7.0/24 | bondd | internal |

---

## Terragrunt Profile vs Reality

The `profiles.hcl` is stale — use n2 MAAS UI as ground truth.

| What | Profile says | Reality |
|---|---|---|
| Data NICs | `ens1f0np0` standalone | bonded into `bondd` |
| VLAN parents | `ens1f0np0.3404` | `bondd.3404` |
| Second data NIC | `ens2f0np0` standalone | bonded into `bond2` |
| Bridge parent | `br-bond2` on `ens2f0np0` | `br-bond2` on `bond2` |
| VLAN 3408 link | missing | linked to 10.21.9.0/24 |
