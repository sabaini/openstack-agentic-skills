# oslo.config → YAML Spec Type Mapping

## Primary Type Map

| oslo.config Type | YAML `type` | Notes |
|---|---|---|
| `cfg.StrOpt()` | `string` | Default |
| `cfg.StrOpt(secret=True)` | `secret` | Passwords, tokens, API keys |
| `cfg.IntOpt()` | `int` | |
| `cfg.BoolOpt()` | `boolean` | |
| `cfg.PortOpt()` | `int` | Port numbers (int with range) |
| `cfg.ListOpt()` | `string` | Comma-separated in Juju config |
| `cfg.MultiOpt()` | `string` | Rare, treated as string |
| `cfg.FloatOpt()` | `string` | Rare, no float in charmcraft |

## Special Classifications

| oslo.config Pattern | YAML Spec Treatment |
|---|---|
| `secret=True` | `type: secret` + `secret_key: <name>` |
| `choices=[...]` | Add `enum: [...]` |
| `choices=[...]` + vendor-prefixed | Add `enum_class: PascalName` for StrEnum |
| `item_type=types.IPAddress()` | Add `validation: ip_address` |
| Field name contains `cidr` (StrOpt) | Add `validation: ip_network` |
| Field name contains `cidr` (ListOpt) | Add `validation: ip_network_list` |
| `deprecated_for_removal=True` | Skip entirely |

## type_overrides Mapping

| Condition | Override Type | Pattern |
|---|---|---|
| Secret + required | `secret` | `{type: secret, secret_key: ..., required: true}` |
| Secret + optional | `secret` | `{type: secret, secret_key: ...}` |
| Required int/custom type | `required` | `{type: required, python_type: int}` |
| Protocol with literal values | `literal` | `{type: literal, values: [...], required: true}` |
| Vendor-prefixed enum field | `enum` | `{type: enum, enum_class: PascalName}` |
| Vendor-prefixed IP network | `ip_network` | `{type: ip_network}` |
| Vendor-prefixed CIDR list | `ip_network_list` | `{type: ip_network_list}` |
| Secondary/failover group | `required_group` | `{type: required_group, group: secondary}` |
| Secret in group | `secret_group` | `{type: secret_group, secret_key: ..., group: secondary}` |

## Auto-Injected Options (never include in spec)

These are added automatically by the factory via `_normalize_config_options()`:
- `volume-backend-name`
- `backend-availability-zone`
- `san-ip` (for SAN-based drivers)
- `driver-ssl-cert` (unless removed via `remove_base_config`)
