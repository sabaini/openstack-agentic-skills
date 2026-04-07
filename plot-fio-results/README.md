# plot-fio-results

Generates a 4-panel matplotlib chart (throughput, IOPS, latency, scaling efficiency) from rally-ci-churn fio benchmark result files.

## Configuration

1. **Copy the skill into your project's agent skills directory:**

   ```bash
   cp -r plot-fio-results /path/to/your/project/.agents/skills/
   ```

2. **Register the skill** in your VS Code Copilot configuration or place the skill directory under `.agents/skills/` in the target repository.

3. **No additional dependencies required** — the skill uses `uv run --with matplotlib` to add matplotlib at runtime without modifying `pyproject.toml`.

4. **Ensure result files are present** in `results/` (or a custom subdirectory) as markdown files produced by `CIChurn.fio_distributed`.

## Usage

Invoke the skill via Copilot chat, e.g.:

> *"Plot the fio results in results/apr7"*

The skill will parse each result file's `## Summary Table`, generate a 4-panel PNG chart (`fio_benchmark_results.png` saved alongside the input files), and summarise saturation point, latency degradation, and profile consistency.

See [SKILL.md](SKILL.md) for the full workflow, regex format, and panel descriptions.
