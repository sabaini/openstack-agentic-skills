# MAAS Operations Reference — pc8a Lab

All commands run on jump host: `ubuntu@<your-jump-host>`
MAAS CLI prefix: `/snap/bin/maas admin`

---

## Known Fabric and VLAN IDs

### management-fabric (fabric ID = 0)

| VLAN tag | MAAS VLAN ID | Subnet ID | Network | Space |
|---|---|---|---|---|
| 3400 (untagged) | 5001 | 1 | 10.21.2.0/24 | oam |
| 3402 | 5002 | 2 | 10.21.3.0/24 | admin |

### data-fabric (fabric ID = 15)

| VLAN tag | MAAS VLAN ID | Subnet ID | Network | Space |
|---|---|---|---|---|
| untagged | 5017 | — | — | (bond parent) |
| 3403 | 5026 | 4 | 10.21.7.0/24 | internal |
| 3404 | 5018 | 3 | 10.21.8.0/24 | public |
| 3405 | 5043 | 7 | 10.21.4.0/24 | ceph-access |
| 3406 | 5035 | 6 | 10.21.5.0/24 | ceph-replica |
| 3407 | 5034 | 5 | 10.21.6.0/24 | overlay |
| 3408 | 5045 | 9 | 10.21.9.0/24 | tenant-storage |
| 3409 | 5044 | 8 | 91.189.88.0/28 | provider |

---

## Step 0 — Discover Current State

```bash
# List all interfaces with IDs, names, types
/snap/bin/maas admin interfaces read <system_id> | python3 -c "
import json, sys
for i in json.load(sys.stdin):
    ip = next((l['ip_address'] for l in i.get('links', []) if l.get('ip_address')), 'no-ip')
    vlan = i.get('vlan', {})
    print(f\"{i['id']:6}  {i['name']:20}  {i['type']:12}  vid={vlan.get('vid','?'):5}  fabric={vlan.get('fabric','?'):20}  {ip}\")
"
```

---

## Step 1 — Fix NICs on Wrong Fabrics

> Do this **before** creating any bonds. All bond members must be on the same fabric.

```bash
# Move NIC <iface_id> to management-fabric (MAAS VLAN ID 5001)
/snap/bin/maas admin interface update <system_id> <iface_id> vlan=5001

# Move NIC <iface_id> to data-fabric untagged (MAAS VLAN ID 5017)
/snap/bin/maas admin interface update <system_id> <iface_id> vlan=5017
```

---

## Step 2 — Create Management Bond (bondm)

```bash
# Create bondm  (replace MAC and parent IDs with actual values)
/snap/bin/maas admin interfaces create-bond <system_id> \
  name=bondm \
  mac_address=<mac_of_ens20f0> \
  parents=<id_ens20f0> parents=<id_ens20f1> parents=<id_ens20f2> parents=<id_ens20f3> \
  bond_mode=802.3ad bond_lacp_rate=fast bond_xmit_hash_policy=layer3+4 \
  bond_miimon=100 mtu=1500 vlan=5001

# Link oam IP (note the bondm interface ID returned above)
/snap/bin/maas admin interface link-subnet <system_id> <bondm_id> \
  mode=STATIC subnet=1 ip_address=<10.21.2.x>

# Create bondm.3402 VLAN sub-interface
/snap/bin/maas admin interfaces create-vlan <system_id> \
  vlan=5002 parents=<bondm_id> mtu=1500

# Link admin IP
/snap/bin/maas admin interface link-subnet <system_id> <bondm3402_id> \
  mode=STATIC subnet=2 ip_address=<10.21.3.x>
```

---

## Step 3 — Create Data Bond (bondd)

> bondd is usually auto-created by MAAS. Check Step 0 output first.
> If it exists, skip creation and just link the VLANs.

```bash
# Only if bondd doesn't exist yet:
/snap/bin/maas admin interfaces create-bond <system_id> \
  name=bondd \
  mac_address=<mac_of_ens1f0np0> \
  parents=<id_ens1f0np0> parents=<id_ens1f1np1> \
  bond_mode=802.3ad bond_lacp_rate=fast bond_xmit_hash_policy=layer3+4 \
  bond_miimon=100 mtu=9000 vlan=5017

# Link all data VLANs  (replace bondd VLAN sub-interface IDs after reading them)
/snap/bin/maas admin interface link-subnet <system_id> <bondd3404_id> \
  mode=STATIC subnet=3 ip_address=<10.21.8.x>

/snap/bin/maas admin interface link-subnet <system_id> <bondd3405_id> \
  mode=STATIC subnet=7 ip_address=<10.21.4.x>

/snap/bin/maas admin interface link-subnet <system_id> <bondd3407_id> \
  mode=STATIC subnet=5 ip_address=<10.21.6.x>

/snap/bin/maas admin interface link-subnet <system_id> <bondd3408_id> \
  mode=STATIC subnet=9 ip_address=<10.21.9.x>

/snap/bin/maas admin interface link-subnet <system_id> <bondd3409_id> \
  mode=LINK_UP subnet=8
```

---

## Step 4 — Create VM Bond + Bridge (bond2 → br-bond2)

```bash
# Create bond2
/snap/bin/maas admin interfaces create-bond <system_id> \
  name=bond2 \
  mac_address=<mac_of_ens2f0np0> \
  parents=<id_ens2f0np0> parents=<id_ens2f1np1> \
  bond_mode=802.3ad bond_lacp_rate=fast bond_xmit_hash_policy=layer3+4 \
  bond_miimon=100 mtu=9000 vlan=5017

# Create br-bond2 bridge on top of bond2
/snap/bin/maas admin interfaces create-bridge <system_id> \
  name=br-bond2 \
  mac_address=<mac_of_ens2f0np0> \
  parents=<bond2_id> bridge_type=standard mtu=9000 vlan=5017

# Create VLAN sub-interfaces on br-bond2 and link IPs
/snap/bin/maas admin interfaces create-vlan <system_id> \
  vlan=5026 parents=<br_bond2_id> mtu=9000

/snap/bin/maas admin interface link-subnet <system_id> <br_bond2_3403_id> \
  mode=STATIC subnet=4 ip_address=<10.21.7.x>

/snap/bin/maas admin interfaces create-vlan <system_id> \
  vlan=5035 parents=<br_bond2_id> mtu=9000

/snap/bin/maas admin interface link-subnet <system_id> <br_bond2_3406_id> \
  mode=STATIC subnet=6 ip_address=<10.21.5.x>
```

---

## Common Errors and Fixes

| Error | Cause | Fix |
|---|---|---|
| `Cannot create bond: members on different fabrics` | NIC still on wrong fabric | Run Step 1 first |
| `IP address already in use` | Chosen IP taken by another node | Pick the next available IP in the subnet |
| `Duplicate link created (alias :1)` | `link-subnet` run twice | `maas admin interface unlink-subnet <sys_id> <iface_id> id=<link_id>` |
| `mac_address required` | Bond creation missing MAC | Always pass `mac_address=` explicitly |
| `No VLANs available` | Bond not on any fabric | Fix fabric first, then retry VLAN creation |
| Juju space unbound | VLAN interface or IP missing | Add the missing VLAN + IP, redeploy charm |

---

## Useful One-Liners

```bash
# Find system_id by hostname
/snap/bin/maas admin machines read | python3 -c "
import json,sys
for m in json.load(sys.stdin):
    print(m['system_id'], m['hostname'])
" | grep <hostname>

# List all subnets with IDs
/snap/bin/maas admin subnets read | python3 -c "
import json,sys
for s in json.load(sys.stdin):
    print(s['id'], s['cidr'], s['name'])
"

# List all VLANs on data-fabric
/snap/bin/maas admin vlans read 15 | python3 -c "
import json,sys
for v in json.load(sys.stdin):
    print(v['id'], v['vid'], v['name'])
"

# Unlink a subnet from an interface (to fix duplicate links)
/snap/bin/maas admin interface unlink-subnet <system_id> <iface_id> id=<link_id>
```
