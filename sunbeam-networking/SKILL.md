---
name: sunbeam-networking
description: "Sunbeam/OpenStack lab networking knowledge for new joiners. Use when: explaining NICs, bonds, fabrics, VLANs, switches, routers, bridges; configuring MAAS interfaces for a new node; debugging missing Juju spaces; onboarding to the Sunbeam lab network; creating network diagrams or PPTs; understanding why a charm deployment fails due to network bindings. Covers: lab rack layout, management-fabric vs data-fabric, bondm/bondd/bond2/br-bond2 structure, VLAN IDs 3400-3409, Juju space to subnet mapping, step-by-step MAAS CLI commands."
argument-hint: "concept to explain OR node to configure (e.g. 'explain VLANs', 'configure Node 5', 'why overlay space fails')"
---

# Sunbeam Networking Skill

## Resources

| Resource | Use when |
|---|---|
| [concepts.md](./references/concepts.md) | Explaining any networking concept to a new joiner |
| [maas-ops.md](./references/maas-ops.md) | Configuring a node in MAAS (CLI commands, VLAN IDs) |
| [lab-layout.md](./references/lab-layout.md) | Node interface tables, IP allocations, Juju space map |
| [docs/networking-basics.md](../../../docs/networking-basics.md) | Full written reference (source of truth) |
| [docs/networking-basics.pptx](../../../docs/networking-basics.pptx) | Onboarding slide deck (12 slides, navy/orange theme) |

---

## Quick Procedures

### 1 — Explain a Networking Concept

Read [concepts.md](./references/concepts.md). Answer analogy-first:
1. Real-world analogy (door, pipe, lane, seat number)
2. ASCII diagram
3. Lab-specific example
4. Rule/constraint

### 2 — Configure a New Node in MAAS

Read [maas-ops.md](./references/maas-ops.md) + [lab-layout.md](./references/lab-layout.md):

1. **Discover** interfaces: `maas admin interfaces read <system_id>`
2. **Fix fabrics**: move NICs to correct fabric before bonding
3. **Create** `bondm` → link oam + admin IPs
4. **Create** `bondd` → link all data VLANs
5. **Create** `bond2` → `br-bond2` → link internal + ceph-replica
6. **Verify** all 9 Juju spaces have IPs

### 3 — Diagnose a Missing Juju Space

Read [lab-layout.md](./references/lab-layout.md) — **Juju Space → Subnet Mapping** table:

1. Identify the unbound space from the Juju error
2. Find its VLAN/subnet in the table
3. Check node: `maas admin interfaces read <system_id>`
4. If missing: create the VLAN interface and link the subnet

### 4 — Share Onboarding Deck

The deck is at `docs/networking-basics.pptx` (12 slides, navy/orange theme, speaker notes with pronunciation hints).
Upload to Google Drive → open in Google Slides → use **Slideshow → Auto-play** for voice-over.

### 5 — Verify a Node Matches Reference Layout

Run on the jump host:

```bash
/snap/bin/maas admin interfaces read <system_id> | python3 -c "
import json, sys
for i in json.load(sys.stdin):
    ip = next((l['ip_address'] for l in i.get('links', []) if l.get('ip_address')), 'no-ip')
    vlan = i.get('vlan', {})
    print(f\"{i['id']:6}  {i['name']:20}  {i['type']:12}  vid={vlan.get('vid','?'):5}  {ip}\")
"
```

Compare output against the **Expected Interface Layout** in [lab-layout.md](./references/lab-layout.md).

---

## Key Rules (Always Apply)

1. NIC must be on the correct fabric **before** bonding
2. Bond must exist **before** creating VLAN sub-interfaces
3. VLAN must exist **before** linking a subnet/IP
4. Bridge wraps the bond so VMs have an attachment point
5. Every node needs **all 9** interfaces with IPs — missing one = charm deploy fails
6. `fabric + VLAN ID = unique network identity` (same VLAN number on different fabrics = different network)
