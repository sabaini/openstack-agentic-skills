# openstack-agentic-skills

A collection of GitHub Copilot agent skills for OpenStack / Sunbeam development workflows.

## Skills

| Skill | Description |
|---|---|
| [cinder-spec-generator](cinder-spec-generator/SKILL.md) | Extracts oslo.config options from Cinder volume driver source and generates driver-spec YAML files for sunbeam-cinder-factory |

---

## cinder-spec-generator

### Configuration

1. **Copy the skill into your project's agent skills directory:**

   ```bash
   cp -r cinder-spec-generator /path/to/your/project/.agents/skills/
   ```

2. **Register the skill** by referencing it in your VS Code Copilot configuration (`.github/copilot-instructions.md` or workspace `.vscode/settings.json`), or place the skill directory under `.agents/skills/` in the target repository so Copilot picks it up automatically.

3. **Install the Python dependency:**

   ```bash
   pip install pyyaml
   ```

4. **Ensure a Cinder source tree is accessible** (default expected location: `../cinder` relative to your working repo).

### Usage

Invoke the skill via Copilot chat by describing what you want, e.g.:

> *"Generate a driver spec for the Pure Storage Cinder driver"*

See [cinder-spec-generator/SKILL.md](cinder-spec-generator/SKILL.md) for the full workflow, all options, and reference material.
