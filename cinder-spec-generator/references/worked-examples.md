# Worked Examples

## Example 1: Pure Storage (pure.py → pure.yaml)

### Source (oslo.config in pure.py)
```python
PURE_OPTS = [
    cfg.StrOpt("pure_api_token",
               help="REST API authorization token."),
    cfg.BoolOpt("pure_automatic_max_oversubscription_ratio",
                default=True, ...),
    cfg.StrOpt("pure_host_personality",
               default=None,
               choices=['aix', 'esxi', 'hitachi-vsp', ...]),
    cfg.IntOpt("pure_replica_interval_default", default=3600, ...),
    cfg.StrOpt("pure_iscsi_cidr", default="0.0.0.0/0", ...),
    cfg.ListOpt("pure_iscsi_cidr_list", default=None, ...),
    cfg.StrOpt("pure_nvme_transport", default="roce",
               choices=['roce', 'tcp'], ...),
    cfg.BoolOpt("pure_eradicate_on_delete", default=False, ...),
]
```

### Classification decisions
- `pure_api_token`: No `secret=True` in oslo, but the YAML spec uses `type: secret` because it's an auth token. The name pattern `_token` triggers secret detection.
- `pure_host_personality`: Vendor-prefixed + choices → `enum_class: Personality`
- `pure_iscsi_cidr`: Name contains "cidr" + StrOpt → `validation: ip_network`
- `pure_iscsi_cidr_list`: Name contains "cidr" + ListOpt → `validation: ip_network_list`
- `pure_nvme_transport`: Vendor-prefixed + choices → `enum_class: NvmeTransport`
- Protocol: `[iscsi, fc, nvme]` from class hierarchy (`PureISCSIDriver`, `PureFCDriver`, `PureNVMEDriver`)

### Generated YAML spec (pure.yaml)
```yaml
vendor: purestorage
display_name: Pure Storage FlashArray
description: |
  Pure Storage FlashArray integration for OpenStack Cinder.
ha_enabled: true
charm:
  name: cinder-volume-purestorage
  summary: OpenStack volume service - Pure Storage backend

type_overrides:
  - name: pure-api-token
    type: secret
    secret_key: token
    required: true
  - name: pure-host-personality
    type: enum
    enum_class: Personality
  - name: pure-nvme-transport
    type: enum
    enum_class: NvmeTransport
  - name: pure-iscsi-cidr
    type: ip_network
  - name: pure-iscsi-cidr-list
    type: ip_network_list
  - name: pure-nvme-cidr
    type: ip_network
  - name: pure-nvme-cidr-list
    type: ip_network_list

config_options:
  - name: protocol
    default: iscsi
    description: Pure Storage protocol selector.
    cli_prompt: true
    enum: [iscsi, fc, nvme]
  - name: pure-api-token
    type: secret
    description: REST API authorization token from the FlashArray.
    required: true
    cli_prompt: true
    secret_key: token
  - name: pure-host-personality
    description: Host personality for protocol tuning.
    enum: [aix, esxi, hitachi-vsp, hpux, oracle-vm-server, solaris, vms]
    enum_class: Personality
  # ... (remaining options)
```

## Example 2: Dell SC (dell_emc/sc/ → dellsc.yaml)

### Source (oslo.config in storagecenter_common.py)
```python
common_opts = [
    cfg.IntOpt('dell_sc_ssn', default=64702, help='Storage Center System Serial Number'),
    cfg.PortOpt('dell_sc_api_port', default=3033, ...),
    cfg.StrOpt('dell_sc_server_folder', default='openstack', ...),
    cfg.BoolOpt('dell_sc_verify_cert', default=False, ...),
    cfg.StrOpt('secondary_san_ip', default='', ...),
    cfg.StrOpt('secondary_san_login', default='Admin', ...),
    cfg.StrOpt('secondary_san_password', default='', secret=True, ...),
    cfg.PortOpt('secondary_sc_api_port', default=3033, ...),
]
```

### Classification decisions
- `SUPPORTED = False` on SCISCSIDriver/SCFCDriver → `unsupported_driver: true`
- `san_login`, `san_password` from san_opts → included because driver uses them
- `dell_sc_ssn`: Integer, help says "Serial Number" → `required: true`, `type_override: required`
- `secondary_san_*`: Group pattern → `required_group`/`secret_group` with group: `secondary`
- Driver doesn't reference `driver_ssl_cert_path` → `remove_base_config: [driver-ssl-cert]`

### Generated YAML spec (key sections)
```yaml
unsupported_driver: true
remove_base_config:
  - driver-ssl-cert

type_overrides:
  - name: san-login
    type: secret
    secret_key: san-login
    required: true
  - name: san-password
    type: secret
    secret_key: san-password
    required: true
  - name: dell-sc-ssn
    type: required
    python_type: int
  - name: protocol
    type: literal
    values: [fc, iscsi]
    required: true
  - name: secondary-san-ip
    type: required_group
    group: secondary
  - name: secondary-san-login
    type: secret_group
    secret_key: secondary-san-login
    group: secondary
  - name: secondary-san-password
    type: secret_group
    secret_key: secondary-san-password
    group: secondary
```
