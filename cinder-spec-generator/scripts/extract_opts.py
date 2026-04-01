#!/usr/bin/env python3
"""Extract oslo.config options from Cinder volume drivers using AST parsing.

Walks the Cinder drivers directory, parses all Python files with the AST module,
and extracts cfg.*Opt declarations, class hierarchies, protocol support, and
driver metadata.  Outputs structured JSON.

Usage:
    python extract_opts.py <cinder_drivers_dir> [-o output.json] [--driver NAME] [--verbose]

Examples:
    python extract_opts.py /path/to/cinder/cinder/volume/drivers -o extracted.json
    python extract_opts.py /path/to/cinder/cinder/volume/drivers --driver pure -o pure.json
"""

import argparse
import ast
import json
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Directories that contain multiple independent sub-drivers
MULTI_VENDOR_PACKAGES = {
    "dell_emc", "hpe", "ibm", "nec", "huawei", "fujitsu",
    "infortrend", "inspur", "lenovo", "toyou", "vmware",
}

# Skip these directory entries — they aren't real vendor drivers
SKIP_ENTRIES = {
    "__init__.py", "__pycache__", "san", "remotefs.py", "nfs.py",
    "rbd.py", "lvm.py",
}

# Known path → vendor mappings for correct naming
PATH_TO_VENDOR = {
    "pure.py": "purestorage",
    "solidfire.py": "solidfire",
    "infinidat.py": "infinidat",
    "lightos.py": "lightos",
    "linstordrv.py": "linstor",
    "qnap.py": "qnap",
    "quobyte.py": "quobyte",
    "rsd.py": "rsd",
    "spdk.py": "spdk",
    "storpool.py": "storpool",
    "vzstorage.py": "vzstorage",
    "veritas_cnfs.py": "veritascnfs",
    "dell_emc/sc": "dellsc",
    "dell_emc/unity": "dellunity",
    "dell_emc/powermax": "dellpowermax",
    "dell_emc/powerstore": "dellpowerstore",
    "dell_emc/powerflex": "dellpowerflex",
    "dell_emc/powervault": "dellpowervault",
    "dell_emc/vnx": "dellvnx",
    "dell_emc/xtremio.py": "dellxtremio",
    "hpe/nimble.py": "nimble",
    "hpe/xp": "hpexp",
    "netapp": "netapp",
    "hitachi": "hitachi",
    "ceph": "ceph",
}

# Known vendor → display name
VENDOR_DISPLAY_NAMES = {
    "purestorage": "Pure Storage FlashArray",
    "solidfire": "NetApp SolidFire",
    "infinidat": "INFINIDAT InfiniBox",
    "dellsc": "Dell SC Series (Storage Center)",
    "dellunity": "Dell Unity",
    "dellpowermax": "Dell PowerMax",
    "dellpowerstore": "Dell PowerStore",
    "dellpowerflex": "Dell PowerFlex",
    "dellpowervault": "Dell PowerVault",
    "dellvnx": "Dell VNX",
    "dellxtremio": "Dell XtremIO",
    "nimble": "HPE Nimble Storage",
    "hpexp": "HPE XP",
    "netapp": "NetApp ONTAP",
    "hitachi": "Hitachi Block Storage",
    "lightos": "Lightbits LightOS",
    "qnap": "QNAP Storage",
    "quobyte": "Quobyte Storage",
    "storpool": "StorPool",
}


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _get_dotted_name(node: ast.expr) -> str | None:
    """Resolve a dotted name from an AST node (e.g., cfg.StrOpt → 'cfg.StrOpt')."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _get_dotted_name(node.value)
        if parent:
            return f"{parent}.{node.attr}"
        return node.attr
    return None


def _extract_literal(node: ast.expr) -> Any:
    """Best-effort extraction of a literal value from an AST node.

    Returns the Python value for constants, lists, tuples.
    Returns a descriptive string like '<variable>' for unresolvable nodes.
    """
    if node is None:
        return None
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.List):
        return [_extract_literal(e) for e in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_extract_literal(e) for e in node.elts)
    if isinstance(node, ast.Set):
        return [_extract_literal(e) for e in node.elts]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        val = _extract_literal(node.operand)
        if isinstance(val, (int, float)):
            return -val
    if isinstance(node, ast.Name):
        # True/False/None are Constants in 3.8+, but just in case
        return f"<{node.id}>"
    if isinstance(node, ast.Attribute):
        name = _get_dotted_name(node)
        return f"<{name}>"
    if isinstance(node, ast.Call):
        name = _get_dotted_name(node.func)
        return f"<{name}()>"
    if isinstance(node, ast.JoinedStr):
        return "<f-string>"
    if isinstance(node, ast.BinOp):
        return "<expr>"
    return "<unknown>"


def _is_cfg_opt_call(node: ast.expr) -> str | None:
    """If node is a cfg.XxxOpt(...) call, return the Opt type name (e.g., 'StrOpt').
    Otherwise return None."""
    if not isinstance(node, ast.Call):
        return None
    func_name = _get_dotted_name(node.func)
    if not func_name:
        return None
    # Match cfg.StrOpt, cfg.IntOpt, etc.
    parts = func_name.split(".")
    if len(parts) == 2 and parts[0] == "cfg" and parts[1].endswith("Opt"):
        return parts[1]
    # Also handle direct imports like StrOpt(...)
    if len(parts) == 1 and parts[0].endswith("Opt"):
        return parts[0]
    return None


def _extract_opt_kwargs(call_node: ast.Call) -> dict[str, Any]:
    """Extract keyword arguments from a cfg.*Opt() call node."""
    kwargs = {}
    for kw in call_node.keywords:
        if kw.arg is None:
            continue  # **kwargs — skip
        kwargs[kw.arg] = _extract_literal(kw.value)
    return kwargs


def _extract_single_opt(call_node: ast.Call) -> dict[str, Any] | None:
    """Extract a single oslo.config option from a cfg.*Opt() AST Call node."""
    opt_type = _is_cfg_opt_call(call_node)
    if not opt_type:
        return None

    # First positional arg is the option name
    if not call_node.args:
        return None
    name_val = _extract_literal(call_node.args[0])
    if not isinstance(name_val, str):
        return None

    kwargs = _extract_opt_kwargs(call_node)

    # Normalize choices: extract first element from tuples
    choices = kwargs.get("choices")
    if isinstance(choices, list):
        normalized = []
        for c in choices:
            if isinstance(c, tuple) and len(c) >= 1:
                normalized.append(c[0])
            elif c is not None and not isinstance(c, str):
                normalized.append(str(c))
            elif c is not None:
                normalized.append(c)
        choices = normalized if normalized else None

    # Detect item_type (e.g., types.IPAddress())
    item_type_raw = kwargs.get("item_type")
    item_type = None
    if isinstance(item_type_raw, str):
        if "IPAddress" in item_type_raw:
            item_type = "IPAddress"
        elif "Hostname" in item_type_raw:
            item_type = "Hostname"

    return {
        "name": name_val,
        "oslo_type": opt_type,
        "default": kwargs.get("default"),
        "help": kwargs.get("help", ""),
        "secret": kwargs.get("secret", False) is True,
        "choices": choices,
        "deprecated_for_removal": kwargs.get("deprecated_for_removal", False) is True,
        "item_type": item_type,
        "ignore_case": kwargs.get("ignore_case", False) is True,
    }


# ---------------------------------------------------------------------------
# File-level AST visitor
# ---------------------------------------------------------------------------

class _FileVisitor(ast.NodeVisitor):
    """Visit a single Python file and extract opts, classes, and registrations."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.opt_lists: dict[str, list[dict]] = {}  # var_name → [opt, ...]
        self.classes: dict[str, dict] = {}           # class_name → info
        self.driver_opts_methods: dict[str, list[str]] = {}  # class → referenced opt names
        self.append_config_values_refs: dict[str, list[str]] = {}  # class → [var_name, ...]

    def visit_Assign(self, node: ast.Assign):
        """Detect: OPTS = [cfg.StrOpt(...), ...]"""
        if isinstance(node.value, ast.List):
            opts = []
            for elt in node.value.elts:
                if isinstance(elt, ast.Call):
                    opt = _extract_single_opt(elt)
                    if opt:
                        opts.append(opt)
            if opts:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.opt_lists[target.id] = opts
                        logger.debug(
                            "  Found opt list %s with %d opts in %s",
                            target.id, len(opts), self.filepath,
                        )
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        """Extract class info: bases, decorators, class-level assignments."""
        bases = []
        for b in node.bases:
            name = _get_dotted_name(b)
            if name:
                bases.append(name)

        # Check for @interface.volumedriver decorator
        is_volume_driver = False
        for dec in node.decorator_list:
            dec_name = _get_dotted_name(dec)
            if dec_name and "volumedriver" in dec_name:
                is_volume_driver = True

        # Class-level attributes
        attrs: dict[str, Any] = {}
        for item in node.body:
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        val = _extract_literal(item.value)
                        attrs[target.id] = val

        self.classes[node.name] = {
            "bases": bases,
            "is_volume_driver": is_volume_driver,
            "attributes": attrs,
            "file": self.filepath,
        }

        # Scan for get_driver_options() method
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if item.name == "get_driver_options":
                    self._parse_get_driver_options(node.name, item)
                elif item.name == "__init__":
                    self._parse_init_for_append(node.name, item)

        self.generic_visit(node)

    def _parse_get_driver_options(self, class_name: str, func_node: ast.FunctionDef):
        """Extract opt names referenced in get_driver_options().

        Looks for cls._get_oslo_driver_opts('name1', 'name2', ...) calls.
        """
        refs = []
        for node in ast.walk(func_node):
            if isinstance(node, ast.Call):
                func_name = _get_dotted_name(node.func)
                if func_name and "_get_oslo_driver_opts" in func_name:
                    for arg in node.args:
                        val = _extract_literal(arg)
                        if isinstance(val, str):
                            refs.append(val)
        if refs:
            self.driver_opts_methods[class_name] = refs

    def _parse_init_for_append(self, class_name: str, func_node: ast.FunctionDef):
        """Detect self.configuration.append_config_values(VAR) in __init__."""
        refs = []
        for node in ast.walk(func_node):
            if isinstance(node, ast.Call):
                func_name = _get_dotted_name(node.func)
                if func_name and "append_config_values" in func_name:
                    for arg in node.args:
                        if isinstance(arg, ast.Name):
                            refs.append(arg.id)
        if refs:
            self.append_config_values_refs[class_name] = refs


def parse_file(filepath: Path) -> dict[str, Any]:
    """Parse a single Python file and return extracted data."""
    try:
        source = filepath.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as e:
        logger.warning("Syntax error in %s: %s", filepath, e)
        return {"opt_lists": {}, "classes": {}, "driver_opts_methods": {},
                "append_config_values_refs": {}}

    visitor = _FileVisitor(str(filepath))
    visitor.visit(tree)

    return {
        "opt_lists": visitor.opt_lists,
        "classes": visitor.classes,
        "driver_opts_methods": visitor.driver_opts_methods,
        "append_config_values_refs": visitor.append_config_values_refs,
    }


# ---------------------------------------------------------------------------
# Driver discovery
# ---------------------------------------------------------------------------

def discover_driver_units(drivers_dir: Path) -> dict[str, list[Path]]:
    """Identify driver units and their source files.

    Returns a dict mapping driver_id (string) to list of Python file paths.
    """
    units: dict[str, list[Path]] = {}

    for entry in sorted(drivers_dir.iterdir()):
        if entry.name in SKIP_ENTRIES or entry.name.startswith("__"):
            continue
        if entry.name.startswith("."):
            continue

        if entry.is_file() and entry.suffix == ".py":
            driver_id = entry.stem
            units[driver_id] = [entry]

        elif entry.is_dir():
            if entry.name in MULTI_VENDOR_PACKAGES:
                # Each subdirectory/file is a separate driver
                for sub in sorted(entry.iterdir()):
                    if sub.name.startswith("__") or sub.name.startswith("."):
                        continue
                    sub_id = f"{entry.name}/{sub.stem}" if sub.is_file() else f"{entry.name}/{sub.name}"
                    if sub.is_file() and sub.suffix == ".py":
                        units[sub_id] = [sub]
                    elif sub.is_dir():
                        py_files = sorted(sub.rglob("*.py"))
                        if py_files:
                            units[sub_id] = py_files
            else:
                # Single driver package
                py_files = sorted(entry.rglob("*.py"))
                if py_files:
                    units[entry.name] = py_files

    return units


# ---------------------------------------------------------------------------
# Driver-level aggregation
# ---------------------------------------------------------------------------

def _resolve_vendor(driver_id: str) -> str:
    """Map a driver_id (path-based) to a vendor name."""
    # Check direct mapping
    for path_key, vendor in PATH_TO_VENDOR.items():
        # Normalize: remove .py for comparison
        norm_key = path_key.replace(".py", "")
        norm_id = driver_id.replace(".py", "")
        if norm_id == norm_key:
            return vendor
    # Fallback: use last component, strip underscores
    parts = driver_id.replace("/", "_").split("_")
    return "".join(parts).lower()


def _resolve_display_name(vendor: str, classes: dict) -> str:
    """Derive a display name from vendor and class info."""
    if vendor in VENDOR_DISPLAY_NAMES:
        return VENDOR_DISPLAY_NAMES[vendor]
    # Try to extract from class docstrings or names
    for cls_name, info in classes.items():
        if info.get("is_volume_driver"):
            # Convert PascalCase to spaced: "PureISCSIDriver" → "Pure ISCSI"
            return cls_name.replace("Driver", "").replace("ISCSI", " iSCSI").replace("FC", " FC")
    return vendor.replace("-", " ").title()


def _detect_protocols(classes: dict) -> list[str]:
    """Detect supported protocols from class hierarchies."""
    protocols = []
    for cls_name, info in classes.items():
        if not info.get("is_volume_driver"):
            continue
        bases_str = " ".join(info.get("bases", []))
        name_lower = cls_name.lower()

        if "iscsi" in bases_str.lower() or "iscsi" in name_lower:
            if "iscsi" not in protocols:
                protocols.append("iscsi")
        if "fibrechannel" in bases_str.lower() or "fc" in name_lower:
            if "fc" not in protocols:
                protocols.append("fc")
        if "nvme" in name_lower or "nvmeof" in bases_str.lower():
            if "nvme" not in protocols:
                protocols.append("nvme")

    # If no protocols detected from class names, check for iscsi as default
    if not protocols:
        for cls_name, info in classes.items():
            bases_str = " ".join(info.get("bases", []))
            if "SanISCSIDriver" in bases_str or "ISCSIDriver" in bases_str:
                protocols.append("iscsi")
                break
            if "SanDriver" in bases_str:
                # SAN driver without specific protocol — likely iSCSI
                protocols.append("iscsi")
                break

    return protocols


def _detect_supported(classes: dict) -> bool:
    """Check if any driver class has SUPPORTED = False."""
    for info in classes.values():
        attrs = info.get("attributes", {})
        if attrs.get("SUPPORTED") is False:
            return False
    return True


def _detect_ha(classes: dict) -> bool:
    """Check for SUPPORTS_ACTIVE_ACTIVE = True."""
    for info in classes.values():
        attrs = info.get("attributes", {})
        if attrs.get("SUPPORTS_ACTIVE_ACTIVE") is True:
            return True
    return False


def _inherits_san(classes: dict, file_data: list[dict] | None = None) -> bool:
    """Check if any class inherits from a SAN driver or uses san_opts."""
    san_markers = {"SanDriver", "SanISCSIDriver", "san.SanDriver", "san.SanISCSIDriver"}
    for info in classes.values():
        for base in info.get("bases", []):
            if base in san_markers or "San" in base:
                return True
    # Also check if any class appends san_opts
    if file_data:
        for fd in file_data:
            for refs in fd.get("append_config_values_refs", {}).values():
                if "san_opts" in refs:
                    return True
    return False


def _collect_base_opts_referenced(file_data: list[dict]) -> list[str]:
    """Collect opts referenced via get_driver_options() or _get_oslo_driver_opts()."""
    refs = []
    for fd in file_data:
        for cls_refs in fd.get("driver_opts_methods", {}).values():
            refs.extend(cls_refs)
    return sorted(set(refs))


def _uses_san_opts(file_data: list[dict]) -> bool:
    """Check if any class in the driver appends san_opts."""
    for fd in file_data:
        for refs in fd.get("append_config_values_refs", {}).values():
            if "san_opts" in refs:
                return True
    return False


def extract_driver(
    driver_id: str,
    source_files: list[Path],
    drivers_dir: Path,
) -> dict[str, Any]:
    """Extract complete information for a single driver unit."""
    logger.info("Extracting driver: %s (%d files)", driver_id, len(source_files))

    all_file_data = []
    all_opts: list[dict] = []
    all_classes: dict[str, dict] = {}
    opt_list_names: list[str] = []

    for fpath in source_files:
        if fpath.name == "__init__.py":
            continue
        rel = fpath.relative_to(drivers_dir)
        logger.debug("  Parsing %s", rel)

        fd = parse_file(fpath)
        all_file_data.append(fd)

        for list_name, opts in fd["opt_lists"].items():
            opt_list_names.append(list_name)
            for opt in opts:
                opt["source_file"] = str(rel)
                opt["opt_list_name"] = list_name
                all_opts.append(opt)

        for cls_name, cls_info in fd["classes"].items():
            cls_info["file"] = str(rel)
            all_classes[cls_name] = cls_info

    # Filter deprecated options
    active_opts = [o for o in all_opts if not o.get("deprecated_for_removal")]
    deprecated_opts = [o for o in all_opts if o.get("deprecated_for_removal")]
    if deprecated_opts:
        logger.info(
            "  Skipping %d deprecated options: %s",
            len(deprecated_opts),
            ", ".join(o["name"] for o in deprecated_opts),
        )

    vendor = _resolve_vendor(driver_id)
    protocols = _detect_protocols(all_classes)
    inherits_san = _inherits_san(all_classes, all_file_data)
    explicitly_uses_san_opts = _uses_san_opts(all_file_data)
    uses_san = inherits_san or explicitly_uses_san_opts

    return {
        "driver_id": driver_id,
        "vendor": vendor,
        "display_name": _resolve_display_name(vendor, all_classes),
        "source_files": [str(f.relative_to(drivers_dir)) for f in source_files if f.name != "__init__.py"],
        "protocols": protocols,
        "supported": _detect_supported(all_classes),
        "ha_enabled": _detect_ha(all_classes),
        "inherits_san": uses_san,
        "uses_san_login": explicitly_uses_san_opts,
        "opts": active_opts,
        "opt_list_names": opt_list_names,
        "base_opts_referenced": _collect_base_opts_referenced(all_file_data),
        "classes": {
            name: {
                "bases": info["bases"],
                "is_volume_driver": info.get("is_volume_driver", False),
                "attributes": {
                    k: v for k, v in info.get("attributes", {}).items()
                    if k in ("SUPPORTED", "SUPPORTS_ACTIVE_ACTIVE", "VERSION",
                             "CI_WIKI_NAME", "backend_type", "display_name",
                             "service_name")
                },
                "file": info.get("file", ""),
            }
            for name, info in all_classes.items()
        },
    }


# ---------------------------------------------------------------------------
# SAN base opts extraction
# ---------------------------------------------------------------------------

def extract_san_opts(drivers_dir: Path) -> list[dict]:
    """Extract san_opts from san/san.py for reference."""
    san_file = drivers_dir / "san" / "san.py"
    if not san_file.exists():
        logger.warning("san/san.py not found")
        return []
    fd = parse_file(san_file)
    return fd["opt_lists"].get("san_opts", [])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Extract oslo.config options from Cinder volume drivers."
    )
    parser.add_argument(
        "drivers_dir",
        type=Path,
        help="Path to cinder/volume/drivers/ directory",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Output JSON file (default: stdout)",
    )
    parser.add_argument(
        "--driver",
        type=str,
        default=None,
        help="Extract only this driver (by driver_id or partial match)",
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

    if not args.drivers_dir.is_dir():
        logger.error("Not a directory: %s", args.drivers_dir)
        sys.exit(1)

    # Discover driver units
    units = discover_driver_units(args.drivers_dir)
    logger.info("Discovered %d driver units", len(units))

    # Filter if requested
    if args.driver:
        filtered = {
            k: v for k, v in units.items()
            if args.driver.lower() in k.lower()
        }
        if not filtered:
            logger.error("No driver matching '%s'. Available: %s", args.driver, ", ".join(sorted(units)))
            sys.exit(1)
        units = filtered
        logger.info("Filtered to %d driver(s): %s", len(units), ", ".join(sorted(units)))

    # Extract san_opts for reference
    san_opts = extract_san_opts(args.drivers_dir)

    # Extract each driver
    drivers = []
    for driver_id, files in sorted(units.items()):
        try:
            info = extract_driver(driver_id, files, args.drivers_dir)
            drivers.append(info)
        except Exception as e:
            logger.error("Failed to extract %s: %s", driver_id, e)

    result = {
        "cinder_drivers_dir": str(args.drivers_dir),
        "san_opts": san_opts,
        "drivers": drivers,
    }

    output_text = json.dumps(result, indent=2, default=str)
    if args.output:
        args.output.write_text(output_text, encoding="utf-8")
        logger.info("Wrote extraction to %s", args.output)
    else:
        print(output_text)


if __name__ == "__main__":
    main()
