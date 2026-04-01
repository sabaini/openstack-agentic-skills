---
name: cinder-spec-generator
description: Extracts oslo.config options from OpenStack Cinder volume driver Python source code and generates driver-spec YAML files for sunbeam-cinder-factory. Use when adding new storage vendor support, updating existing driver specs from upstream Cinder, or batch-generating specs for all Cinder drivers. Handles AST parsing, type classification, secret detection, protocol detection, enum mapping, and type_override generation.
---

# Cinder Driver Spec Generator

Automates the pipeline: **Cinder driver source → YAML driver spec → Sunbeam charm**.

## Prerequisites

- Python 3.12+
- Access to a Cinder source tree (default: `../cinder` relative to this repo)
- PyYAML installed (`pip install pyyaml` or available in the project venv)
- sunbeam-cinder-factory repo (this repo) with `charm_generator` available

## Quick Start (All Drivers)

```bash
# Step 1: Extract config options from all Cinder drivers
python .agents/skills/cinder-spec-generator/scripts/extract_opts.py \
    /path/to/cinder/cinder/volume/drivers \
    -o /tmp/cinder_drivers_extracted.json

# Step 2: Generate YAML specs from extracted data
python .agents/skills/cinder-spec-generator/scripts/generate_spec.py \
    /tmp/cinder_drivers_extracted.json \
    -o driver-specs/

# Step 3: Generate charms from specs (one at a time or batch)
for spec in driver-specs/*.yaml; do
    python -m charm_generator generate "$spec" || echo "FAILED: $spec"
done

# Step 4: Validate generated charms
for spec in driver-specs/*.yaml; do
    vendor=$(python -c "import yaml; print(yaml.safe_load(open('$spec'))['charm']['name'])")
    python -m charm_generator validate "$vendor" --spec "$spec" || echo "INVALID: $spec"
done
```

## Detailed Workflow

### Step 1: Extract Driver Configuration

Run [extract_opts.py](scripts/extract_opts.py) against the Cinder drivers directory.

```bash
python .agents/skills/cinder-spec-generator/scripts/extract_opts.py \
    /path/to/cinder/cinder/volume/drivers \
    -o extracted.json \
    --verbose
```

The script uses Python AST parsing (not regex) for accuracy. It extracts:
- All `cfg.*Opt` declarations with name, type, default, help, secret flag, choices
- Class hierarchies and base class inheritance
- Protocol support by detecting `@interface.volumedriver` decorated classes
- `SUPPORTED` flag (for unsupported drivers)
- `SUPPORTS_ACTIVE_ACTIVE` flag (for HA)
- Base opts referenced via `get_driver_options()` and `append_config_values()`

**Single driver extraction:**
```bash
python .agents/skills/cinder-spec-generator/scripts/extract_opts.py \
    /path/to/cinder/cinder/volume/drivers \
    --driver pure \
    -o pure_extracted.json
```

### Step 2: Generate YAML Specs

Run [generate_spec.py](scripts/generate_spec.py) to classify options and produce YAML:

```bash
python .agents/skills/cinder-spec-generator/scripts/generate_spec.py \
    extracted.json \
    -o driver-specs/ \
    --verbose
```

The script applies these classification rules automatically:

**Type mapping**: See [references/type-mapping.md](references/type-mapping.md)

**Secret detection**:
- `secret=True` in oslo.config → `type: secret` in YAML
- Backup: field names matching `*_password`, `*_token`, `*_key` (auth keys only)

**Required detection** (conservative — only high-confidence fields):
- Secret fields without defaults → required
- Fields explicitly without defaults that are connection-critical
- `san_ip` is auto-injected as required by the factory

**Enum detection**:
- `choices=[...]` in oslo.config → `enum: [...]` in YAML
- Vendor-prefixed enum fields get `enum_class` for StrEnum generation

**Validation detection**:
- `item_type=types.IPAddress()` → `validation: ip_address`
- Field names containing `cidr` + StrOpt → `validation: ip_network`
- Field names containing `cidr` + ListOpt → `validation: ip_network_list`

**type_overrides generation**:
- Secret + required → `{type: secret, secret_key: ..., required: true}`
- Vendor-prefixed enum → `{type: enum, enum_class: ...}`
- Vendor-prefixed IP/CIDR → `{type: ip_network}` or `{type: ip_network_list}`
- Required non-string types → `{type: required, python_type: ...}`
- Protocol with literal choices + required → `{type: literal, values: [...]}`

**Unsupported driver**: `SUPPORTED = False` → `unsupported_driver: true`

**Base config removal**: If driver doesn't reference `driver_ssl_cert` options → `remove_base_config: [driver-ssl-cert]`

### Step 3: Review Generated Specs

Before running the charm generator, review the YAML specs for:

1. **Vendor name and display_name** — Verify they match expected conventions
2. **Required fields** — The script is conservative; you may need to mark additional fields as required
3. **cli_prompt fields** — Should include required fields + protocol selector
4. **type_overrides** — Verify secret_key values, enum_class names, group assignments
5. **Grouping** — Secondary/failover fields may need `required_group`/`secret_group` type_overrides with a shared group name

### Step 4: Run the Charm Generator

```bash
python -m charm_generator generate driver-specs/newvendor.yaml
```

### Step 5: Validate

```bash
python -m charm_generator validate cinder-volume-newvendor --spec driver-specs/newvendor.yaml
```

Fix any validation errors and re-generate if needed.

## Reference Files

- [Type Mapping Table](references/type-mapping.md) — Complete oslo.config → YAML type mapping
- [Worked Examples](references/worked-examples.md) — Pure Storage and Dell SC end-to-end examples

## Known Limitations

1. **Complex default values**: Expressions, variable references, and computed defaults are represented as `null` in the YAML spec. Review help text for intended defaults.
2. **Grouping heuristics**: Fields with `secondary_` prefix are auto-grouped, but other grouping patterns need manual review.
3. **Display names**: Derived from docstrings and class names — verify for accuracy.
4. **Deprecated options**: Options with `deprecated_for_removal=True` are excluded by default.
5. **Imported opts from other packages**: The script resolves opts within the driver's own files and the `san.py` base module. Opts imported from third-party packages are not extracted.
