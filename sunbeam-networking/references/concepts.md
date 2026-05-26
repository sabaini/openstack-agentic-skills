# Networking Concepts Reference

Beginner-friendly explanations using analogies, then the technical reality.

---

## 1. Physical NIC — the door

**Analogy:** Your server is a house. Each NIC is a door connecting the house to the street (network cable).

```
Server
 ├── ens20f0   (1G door → management street)
 ├── ens1f0np0 (100G door → data street)
 └── ens2f0np0 (100G door → VM traffic street)
```

- Has a unique **MAC address** (hardware fingerprint, never changes)
- MAAS discovers NICs automatically at enlistment
- Speed: 1 Gbps (management) or 100 Gbps (data)

---

## 2. Switch vs Router

| | Switch | Router |
|---|---|---|
| Analogy | Office intercom | Post-office sorting centre |
| Connects | Devices on the **same** network | **Different** networks |
| Identifies by | MAC address | IP address |
| Scope | This building only | The whole world |

```
Switch (same network):
  n1 ──┐
  n2 ──┤── switch ── all talk directly
  n4 ──┘

Router (between networks):
  public  ──┐
  overlay ──┤── router ── internet
  admin   ──┘
```

**In this lab:**
- `management-fabric` and `data-fabric` = switches
- VLAN 3409 (provider) = the exit door to the router → internet

---

## 3. Fabric — which switch?

**Analogy:** A fabric is a label stuck on a cable that says "this goes into switch X".

- MAAS groups all ports on the same physical switch into one fabric
- `management-fabric` = the 1G management switch in the rack
- `data-fabric` = the 200G data switch in the rack

**Why it matters:**
- `fabric + VLAN ID = unique network` — VLAN 3402 on management-fabric ≠ VLAN 3402 on data-fabric
- You **cannot bond** ports from different fabrics
- MAAS auto-discovers fabrics; you only intervene when a NIC lands on the wrong one (e.g. `fabric-122`)

---

## 4. Bond — super-door

**Analogy:** Two doors knocked into one wide doorway. More throughput, and if one is blocked, the other still works.

```
ens1f0np0 ─┐
            ├──→  bondd  (200 Gbps logical port)
ens1f1np1 ─┘
```

**Why bond?**
- **Speed**: 100 + 100 = 200 Gbps
- **Redundancy**: cable failure → traffic auto-shifts to surviving member
- Mode used: `802.3ad` (LACP) — the switch and server actively negotiate

**Lab bonds:**

| Bond | Members | Speed | Fabric | Purpose |
|---|---|---|---|---|
| `bondm` | ens20f0/f1/f2/f3 | 1 Gbps | management | OAM + admin |
| `bondd` | ens1f0np0/f1np1 | 200 Gbps | data | Data plane |
| `bond2` | ens2f0np0/f1np1 | 200 Gbps | data | VM / OVS bridge |

---

## 5. VLAN — a numbered lane

**Analogy:** The bond cable is a motorway. Each VLAN is a numbered lane. Every packet carries a tag saying which lane it belongs to.

```
bondd (one cable)
  ├── tag 3404 → public          10.21.8.0/24
  ├── tag 3405 → ceph-access     10.21.4.0/24
  ├── tag 3407 → overlay         10.21.6.0/24
  ├── tag 3408 → tenant-storage  10.21.9.0/24
  └── tag 3409 → provider        91.189.88.0/28
```

Each VLAN becomes a virtual interface: `bondd.3404`, `bondd.3407`, etc.

**Why the same VLAN ID on every node?**
VLAN 3404 = public network. Every node tags its traffic `3404`. The switch collects all traffic tagged `3404` and puts it on the same network. It's a shared membership tag, not a per-server unique ID.

```
n1/bondd.3404 ──┐
n2/bondd.3404 ──┤──→ switch ──→ public network (10.21.8.0/24)
n4/bondd.3404 ──┘
```

---

## 6. Subnet / IP — your seat number

**Analogy:** The subnet is the row. The IP address is your seat number in that row.

**IP modes in MAAS:**
- `STATIC` — operator manually specifies the exact IP
- `MAAS-provided` (AUTO) — MAAS permanently assigns a fixed IP from its pool
- `LINK_UP` — no IP, just keeps the link alive (used for provider VLAN 3409)

---

## 7. Bridge — VM handover

**Analogy:** A bridge is a traffic marshal standing between the physical road and a car park. VMs park in the car park; the marshal directs traffic in and out.

```
ens2f0np0 ─┐
            ├→ bond2 → br-bond2 (bridge)
ens2f1np1 ─┘              ├── br-bond2.3403  internal     10.21.7.0/24
                           └── br-bond2.3406  ceph-replica 10.21.5.0/24
```

- OpenStack attaches VMs to `br-bond2`, not directly to `bond2`
- OVS (Open vSwitch) manages the bridge in production

---

## The Rule Chain

```
NIC on correct fabric  →  bond  →  VLAN sub-interface  →  IP  →  (bridge if VMs)
```

Skipping any step causes MAAS or OpenStack to fail. This is the most common setup mistake.
