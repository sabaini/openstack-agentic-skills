#!/usr/bin/env python3
"""Generate driver-spec YAML files from extracted Cinder driver data.

Reads the JSON output of extract_opts.py, classifies each option (type,
required, secret, enum, validation, type_overrides), and writes YAML spec
files compatible with sunbeam-cinder-factory.

Usage:
    python generate_spec.py <extracted.json> [-o output_dir] [--driver VENDOR] [--verbose]

Examples:
    python generate_spec.py extracted.json -o driver-specs/
    python generate_spec.py extracted.json --driver purestorage -o driver-specs/
"""

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    import yaml
except ImportError:
    logger.error("PyYAML is required: pip install pyyaml")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# oslo.config type → YAML spec type
OSLO_TO_YAML_TYPE: dict[str, str] = {
    "StrOpt": "string",
    "IntOpt": "int",
    "BoolOpt": "boolean",
    "PortOpt": "int",
    "ListOpt": "string",
    "MultiOpt": "string",
    "FloatOpt": "string",
    "URIOpt": "string",
    "IPOpt": "string",
    "HostnameOpt": "string",
    "HostAddressOpt": "string",
    "DictOpt": "string",
}

# Options auto-injected by sunbeam-cinder-factory — never include in user specs
AUTO_INJECTED_OPTS = {
    "volume_backend_name",
    "backend_availability_zone",
}

# SAN base class opts — auto-injected if driver inherits from SanDriver
SAN_AUTO_INJECTED = set()  # san_ip is now in SAN_INCLUDE_OPTS instead

# Options to always skip (internal to cinder, not charm-configurable)
ALWAYS_SKIP = {
    "volume_driver",
    "volume_backend_name",
    "backend_availability_zone",
    "reserved_percentage",
    "max_over_subscription_ratio",
    "driver_ssl_cert_verify",
    "driver_ssl_cert_path",
    "use_chap_auth",
    "replication_device",
    "image_volume_cache_enabled",
    "image_volume_cache_max_size_gb",
    "image_volume_cache_max_count",
    # SAN base opts that are internal
    "san_is_local",
    "ssh_conn_timeout",
    "ssh_min_pool_conn",
    "ssh_max_pool_conn",
    "san_ssh_port",
    "san_private_key",
    "san_clustername",
}

# SAN opts that may need to be included as explicit config (not auto-injected)
SAN_INCLUDE_OPTS = {
    "san_ip",
    "san_login",
    "san_password",
    "san_thin_provision",
}

# Common base-class options that many drivers use and should be in the spec
# These come from volume_opts in driver.py, not from driver-specific opt lists
COMMON_DRIVER_OPTS = {
    "use_multipath_for_image_xfer": {
        "name": "use_multipath_for_image_xfer",
        "oslo_type": "BoolOpt",
        "default": True,
        "help": "Enable multipathing for image transfer operations.",
        "secret": False,
        "choices": None,
        "deprecated_for_removal": False,
        "item_type": None,
    },
}

# Vendor → known PascalCase name
VENDOR_PASCAL: dict[str, str] = {
    "purestorage": "PureStorage",
    "netapp": "NetApp",
    "hitachi": "Hitachi",
    "dellsc": "DellSC",
    "dellunity": "DellUnity",
    "dellpowermax": "DellPowerMax",
    "dellpowerstore": "DellPowerStore",
    "dellpowerflex": "DellPowerFlex",
    "dellpowervault": "DellPowerVault",
    "dellvnx": "DellVNX",
    "dellxtremio": "DellXtremIO",
    "solidfire": "SolidFire",
    "infinidat": "Infinidat",
    "nimble": "Nimble",
    "hpexp": "HpeXP",
    "lightos": "LightOS",
    "qnap": "QNAP",
    "quobyte": "Quobyte",
    "storpool": "StorPool",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_hyphen(name: str) -> str:
    """Convert snake_case oslo name to hyphenated YAML name."""
    return name.replace("_", "-")


def _to_pascal(s: str) -> str:
    """Convert a string to PascalCase."""
    return "".join(w.capitalize() for w in re.split(r"[-_]", s))


def _opt_prefix(opts: list[dict]) -> str:
    """Detect the common vendor prefix from option names.

    E.g., for pure_api_token, pure_iscsi_cidr → 'pure'.
    """
    prefixes: dict[str, int] = {}
    for opt in opts:
        parts = opt["name"].split("_")
        if len(parts) >= 2:
            # Skip common non-vendor prefixes
            if parts[0] not in ("san", "use", "driver", "volume", "backend",
                                "image", "ssh", "target", "num", "reserved"):
                prefixes[parts[0]] = prefixes.get(parts[0], 0) + 1
    if prefixes:
        return max(prefixes, key=prefixes.get)
    return ""


def _is_vendor_prefixed(opt_name: str, vendor_prefix: str) -> bool:
    """Check if an option name starts with the vendor prefix."""
    if not vendor_prefix:
        return False
    return opt_name.startswith(vendor_prefix + "_")


def _derive_enum_class(opt_name: str, vendor_prefix: str) -> str:
    """Derive a PascalCase StrEnum class name from an option name.

    Strips the full vendor prefix (including sub-prefixes like 'pure_' from
    'pure_host_personality') to get just the meaningful suffix.
    For multi-word suffixes where the first word is a common qualifier
    (host, storage, server, etc.), uses only the final word(s).

    E.g., pure_host_personality → Personality
          pure_nvme_transport → NvmeTransport
          dell_server_os → ServerOs
    """
    name = opt_name
    if vendor_prefix and name.startswith(vendor_prefix + "_"):
        name = name[len(vendor_prefix) + 1:]
    parts = name.split("_")
    # If first part is a common qualifier and there are 2+ parts, drop it
    common_qualifiers = {"host", "storage", "server", "default", "backend"}
    if len(parts) >= 2 and parts[0] in common_qualifiers:
        parts = parts[1:]
    return _to_pascal("_".join(parts))


def _clean_help(help_text: Any) -> str:
    """Clean up help text for use as description."""
    if not help_text or not isinstance(help_text, str):
        return ""
    # Collapse whitespace
    text = " ".join(help_text.split())
    # Remove trailing period if present
    return text.strip()


def _clean_default(default: Any, yaml_type: str) -> Any:
    """Clean up default values for YAML output."""
    if default is None:
        return None
    if isinstance(default, str) and default.startswith("<"):
        return None  # Unresolvable expression
    if yaml_type == "secret":
        return None  # Secrets should not have defaults in charm specs
    if yaml_type == "boolean":
        if isinstance(default, bool):
            return default
        return None
    if yaml_type == "int":
        if isinstance(default, (int, float)):
            return int(default)
        return None
    if isinstance(default, str) and default == "":
        return None  # Empty string default → treat as no default
    if isinstance(default, list) and len(default) == 0:
        return None  # Empty list default → treat as no default
    return default


# ---------------------------------------------------------------------------
# Option classification
# ---------------------------------------------------------------------------

def classify_option(
    opt: dict,
    driver: dict,
    vendor_prefix: str,
) -> dict[str, Any] | None:
    """Classify a single extracted option into YAML spec format.

    Returns None if the option should be skipped.
    """
    name = opt["name"]

    # Skip internal/auto-injected options
    if name in ALWAYS_SKIP or name in AUTO_INJECTED_OPTS:
        return None

    # Skip SAN auto-injected if the driver inherits SAN
    if name in SAN_AUTO_INJECTED and driver.get("inherits_san"):
        return None

    # SAN_INCLUDE_OPTS are handled by build_spec() injection logic;
    # no filtering needed here.

    yaml_type = OSLO_TO_YAML_TYPE.get(opt["oslo_type"], "string")

    # Secret detection
    is_secret = opt.get("secret", False)
    if not is_secret:
        # Backup heuristic: name patterns
        if any(pat in name for pat in ("_password", "_token")):
            # Only if it looks like an auth credential
            if "api" in name or "san" in name or "auth" in name or "login" not in name:
                is_secret = "_password" in name or "_token" in name
        # Login/username fields associated with SAN are also secrets (Juju credentials)
        if name.endswith("san_login") or name.endswith("_login") and "san" in name:
            is_secret = True

    if is_secret:
        yaml_type = "secret"

    # Default handling
    default = _clean_default(opt.get("default"), yaml_type)

    # Required detection (conservative)
    # Secondary/failover fields are managed by groups, not individually required
    is_grouped = any(name.startswith(p + "_") for p in ("secondary", "failover"))
    is_required = False
    if not is_grouped:
        if is_secret and default is None:
            is_required = True
        # SAN credentials are always required (even if they have defaults like 'admin')
        if name in ("san_login", "san_password"):
            is_required = True
    # SSN/array-id type fields (often have placeholder defaults)
    if yaml_type == "int" and opt.get("help"):
        help_lower = (opt["help"] or "").lower()
        if any(k in help_lower for k in ("serial number", "array id", "system id")):
            is_required = True
    # san_ip is always required for SAN drivers
    if name == "san_ip":
        is_required = True
    # Protocol with choices is always required (user must select transport)
    if name == "protocol" and opt.get("choices"):
        is_required = True

    # CLI prompt: required fields + protocol selector
    is_cli_prompt = is_required
    if name == "protocol" or (opt.get("choices") and "protocol" in name):
        is_cli_prompt = True

    # Enum detection
    choices = opt.get("choices")
    enum_list = None
    enum_class = None
    if choices and isinstance(choices, list) and len(choices) > 0:
        enum_list = [c for c in choices if c is not None]
        if enum_list:
            # Protocol always gets enum_class "Protocol"
            if name == "protocol":
                enum_class = "Protocol"
            # Vendor-prefixed enum fields get an enum_class
            if _is_vendor_prefixed(name, vendor_prefix):
                enum_class = _derive_enum_class(name, vendor_prefix)

    # Validation detection
    validation = None
    item_type = opt.get("item_type")
    if item_type == "IPAddress":
        validation = "ip_address"
    elif name == "san_ip" or name.endswith("_san_ip"):
        validation = "ip_address"
    elif "cidr" in name.lower():
        if opt["oslo_type"] == "ListOpt":
            validation = "ip_network_list"
        else:
            validation = "ip_network"

    # Build the YAML option dict
    result: dict[str, Any] = {
        "name": _to_hyphen(name),
    }

    if yaml_type != "string":
        result["type"] = yaml_type
    if default is not None and not (is_required and not enum_list):
        result["default"] = default
    if _clean_help(opt.get("help")):
        result["description"] = _clean_help(opt["help"])
    if is_required:
        result["required"] = True
    if is_cli_prompt:
        result["cli_prompt"] = True
    if is_secret:
        result["secret_key"] = _to_hyphen(name)
    if enum_list:
        result["enum"] = enum_list
        if enum_class:
            result["enum_class"] = enum_class
    if validation:
        result["validation"] = validation

    return result


# ---------------------------------------------------------------------------
# Type overrides detection
# ---------------------------------------------------------------------------

def detect_type_overrides(
    classified_opts: list[dict],
    driver: dict,
    vendor_prefix: str,
) -> list[dict]:
    """Determine which type_overrides entries are needed for charm.py."""
    overrides = []

    # Detect grouping patterns (secondary-*, failover-*)
    group_prefixes = {"secondary": "secondary"}
    # Find opts that form groups
    grouped_opts: dict[str, str] = {}  # opt_name → group_name
    for opt in classified_opts:
        oslo_name = opt["name"].replace("-", "_")
        for prefix, group in group_prefixes.items():
            if oslo_name.startswith(prefix + "_"):
                grouped_opts[opt["name"]] = group

    for opt in classified_opts:
        name = opt["name"]
        oslo_name = name.replace("-", "_")
        group = grouped_opts.get(name)

        # Secret fields in a group → secret_group override
        if opt.get("type") == "secret" and group:
            overrides.append({
                "name": name,
                "type": "secret_group",
                "secret_key": opt.get("secret_key", name),
                "group": group,
            })
            continue

        # Secret fields → secret override
        if opt.get("type") == "secret":
            entry: dict[str, Any] = {
                "name": name,
                "type": "secret",
                "secret_key": opt.get("secret_key", name),
            }
            if opt.get("required"):
                entry["required"] = True
            overrides.append(entry)
            continue

        # Non-secret fields in a group → required_group override
        if group:
            overrides.append({
                "name": name,
                "type": "required_group",
                "group": group,
            })
            continue

        # Required non-string types → required override
        if opt.get("required") and opt.get("type") in ("int",):
            overrides.append({
                "name": name,
                "type": "required",
                "python_type": opt["type"],
            })
            continue

        # Protocol with literal values
        if "protocol" in name and opt.get("enum"):
            entry = {
                "name": name,
                "type": "literal",
                "values": opt["enum"],
                "required": True,
            }
            overrides.append(entry)
            continue

        # Vendor-prefixed enum fields → enum override
        if opt.get("enum_class") and _is_vendor_prefixed(oslo_name, vendor_prefix):
            overrides.append({
                "name": name,
                "type": "enum",
                "enum_class": opt["enum_class"],
            })
            continue

        # Vendor-prefixed IP/CIDR → ip_network or ip_network_list override
        if opt.get("validation") in ("ip_network", "ip_network_list"):
            if _is_vendor_prefixed(oslo_name, vendor_prefix):
                overrides.append({
                    "name": name,
                    "type": opt["validation"],
                })
                continue

    return overrides


# ---------------------------------------------------------------------------
# Full spec generation
# ---------------------------------------------------------------------------

def build_spec(driver: dict, san_opts: list[dict]) -> dict[str, Any]:
    """Build a complete YAML spec dict for a driver."""
    vendor = driver["vendor"]
    display_name = driver["display_name"]
    protocols = driver.get("protocols", [])
    vendor_prefix = _opt_prefix(driver.get("opts", []))

    # Collect all opts to classify
    raw_opts = list(driver.get("opts", []))

    # Add SAN opts that the driver explicitly uses
    own_opt_names = {o["name"] for o in raw_opts}
    # Check if driver uses its own auth mechanism (api_token, etc.)
    # or doesn't explicitly use san_opts (append_config_values)
    has_own_auth = any(
        "api_token" in n or "api_key" in n or "auth_token" in n
        for n in own_opt_names
    )
    uses_san_login = driver.get("uses_san_login", False)
    if driver.get("inherits_san"):
        for san_opt in san_opts:
            if san_opt["name"] not in own_opt_names and san_opt["name"] not in ALWAYS_SKIP:
                if san_opt["name"] in SAN_INCLUDE_OPTS:
                    # Only include san_login/san_password/san_thin_provision
                    # if driver explicitly uses san_opts or doesn't have its own auth
                    if san_opt["name"] in ("san_login", "san_password", "san_thin_provision"):
                        if not uses_san_login and has_own_auth:
                            continue
                    raw_opts.append(san_opt)

    # Add common driver opts (use_multipath_for_image_xfer) if referenced
    base_refs = set(driver.get("base_opts_referenced", []))
    for opt_name, opt_data in COMMON_DRIVER_OPTS.items():
        if opt_name not in own_opt_names:
            # Include use_multipath if driver references it or is SAN-based
            if opt_name in base_refs or (opt_name == "use_multipath_for_image_xfer" and driver.get("inherits_san")):
                raw_opts.append(opt_data)

    # Synthesize a protocol option if driver supports multiple protocols
    if len(protocols) > 1 and "protocol" not in own_opt_names:
        raw_opts.insert(0, {
            "name": "protocol",
            "oslo_type": "StrOpt",
            "default": protocols[0],
            "help": f"Protocol selector: {', '.join(protocols)}.",
            "secret": False,
            "choices": protocols,
            "deprecated_for_removal": False,
            "item_type": None,
        })

    # Classify options
    classified = []
    for opt in raw_opts:
        result = classify_option(opt, driver, vendor_prefix)
        if result:
            classified.append(result)

    # Detect type overrides
    type_overrides = detect_type_overrides(classified, driver, vendor_prefix)

    # Detect unsupported driver
    unsupported = not driver.get("supported", True)

    # Detect remove_base_config
    remove_base = []
    base_refs = set(driver.get("base_opts_referenced", []))
    all_opt_names = {o["name"] for o in raw_opts}
    # Remove driver-ssl-cert if driver doesn't use it:
    # - Not in base_opts_referenced (no get_driver_options() referencing it)
    # - Not in driver's own opt names
    # - Has its own verify_cert opt (handles SSL independently)
    has_own_ssl = any("verify_cert" in o["name"] or "ssl_cert" in o["name"] for o in raw_opts)
    uses_base_ssl = "driver_ssl_cert_path" in base_refs or "driver_ssl_cert_verify" in base_refs
    if not uses_base_ssl and (has_own_ssl or "driver_ssl_cert" not in all_opt_names):
        remove_base.append("driver-ssl-cert")

    # Build the spec
    charm_name = f"cinder-volume-{vendor}"
    spec: dict[str, Any] = {
        "vendor": vendor,
        "display_name": display_name,
        "description": f"{display_name} integration for OpenStack Cinder.\n",
        "ha_enabled": driver.get("ha_enabled", False),
        "charm": {
            "name": charm_name,
            "summary": f"OpenStack volume service - {display_name} backend",
        },
    }

    if unsupported:
        spec["unsupported_driver"] = True

    if remove_base:
        spec["remove_base_config"] = remove_base

    if type_overrides:
        spec["type_overrides"] = type_overrides
    else:
        spec["type_overrides"] = []

    spec["config_options"] = classified

    return spec


# ---------------------------------------------------------------------------
# YAML writing
# ---------------------------------------------------------------------------

class _YamlDumper(yaml.SafeDumper):
    """Custom YAML dumper for clean output."""
    pass


def _str_representer(dumper, data):
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


def _none_representer(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:null", "null")


def _bool_representer(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:bool", "true" if data else "false")


_YamlDumper.add_representer(str, _str_representer)
_YamlDumper.add_representer(type(None), _none_representer)
_YamlDumper.add_representer(bool, _bool_representer)


def write_spec(spec: dict, output_path: Path) -> None:
    """Write a YAML spec to file."""
    content = yaml.dump(
        spec,
        Dumper=_YamlDumper,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        width=100,
    )
    output_path.write_text(content, encoding="utf-8")
    logger.info("Wrote spec: %s", output_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate driver-spec YAML files from extracted Cinder driver data."
    )
    parser.add_argument(
        "extracted_json",
        type=Path,
        help="Path to extracted JSON from extract_opts.py",
    )
    parser.add_argument(
        "-o", "--output-dir",
        type=Path,
        default=Path("driver-specs"),
        help="Output directory for YAML specs (default: driver-specs/)",
    )
    parser.add_argument(
        "--driver",
        type=str,
        default=None,
        help="Generate only for this vendor name",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    if not args.extracted_json.exists():
        logger.error("File not found: %s", args.extracted_json)
        sys.exit(1)

    data = json.loads(args.extracted_json.read_text(encoding="utf-8"))
    san_opts = data.get("san_opts", [])
    drivers = data.get("drivers", [])

    if args.driver:
        drivers = [d for d in drivers if args.driver.lower() in d["vendor"].lower()]
        if not drivers:
            logger.error("No driver matching '%s'", args.driver)
            sys.exit(1)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    generated = []
    skipped = []

    for driver in drivers:
        vendor = driver["vendor"]

        # Skip drivers with no config options
        if not driver.get("opts"):
            logger.info("Skipping %s (no config options)", vendor)
            skipped.append(vendor)
            continue

        # Skip drivers with no detected protocols
        if not driver.get("protocols"):
            logger.info("Skipping %s (no protocols detected)", vendor)
            skipped.append(vendor)
            continue

        try:
            spec = build_spec(driver, san_opts)
            output_file = args.output_dir / f"{vendor}.yaml"
            write_spec(spec, output_file)
            generated.append(vendor)
        except Exception as e:
            logger.error("Failed to generate spec for %s: %s", vendor, e)
            skipped.append(vendor)

    logger.info(
        "Generated %d specs, skipped %d drivers",
        len(generated), len(skipped),
    )
    if generated:
        logger.info("Generated: %s", ", ".join(generated))
    if skipped:
        logger.info("Skipped: %s", ", ".join(skipped))


if __name__ == "__main__":
    main()
