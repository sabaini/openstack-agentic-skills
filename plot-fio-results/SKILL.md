---
name: plot-fio-results
description: "Generate a 4-panel matplotlib chart from rally-ci-churn fio benchmark result files. Use when you have result files in the results/ directory and want to visualize throughput scaling, IOPS, latency (avg/P99), and scaling efficiency. Triggers: plot results, chart fio, visualize benchmark, fio chart, throughput chart."
argument-hint: "Optional: path to results directory (default: results/)"
---

# Plot FIO Benchmark Results

Generates a 4-panel PNG chart from fio benchmark markdown result files produced by `CIChurn.fio_distributed`.

## When to Use

- After running one or more `fio_distributed` scenarios
- When results files exist in `results/` (or a custom directory)
- To compare throughput, IOPS, and latency across different client counts

## Output

- `<results_dir>/fio_benchmark_results.png` — 4-panel chart saved in the same directory as the input files
- Panel 1: Aggregate (sum) bandwidth per run, sorted by client count
- Panel 2: Aggregate IOPS per run
- Panel 3: Avg vs P99 latency per run (grouped bar)
- Panel 4: Actual bandwidth vs ideal linear scaling (saturation gap shaded)
- All panels: x-axis shows client count numbers only (e.g. `3`, `4`, `9`, `20`), labelled "FIO Client Count" — no filenames, no rotation

## Procedure

1. **Locate result files** — accepts an optional directory argument (default: `results/` relative to workspace root); files may be in dated subdirectories (e.g. `results/apr7/`); each file is a markdown document with a `## Summary Table` section

2. **Parse each file** — extract the summary row using this regex pattern:
   ```
   ^\| (\d+)\s+\| (\d+)\s+\| (\d+)\s+\| (\S+)\s+\| (\S+)\s+\| (\S+)\s+\| (\d+)\s+\| (\d+)\s+
   \| ([\d.]+ \S+/s)\s+\| ([\d.]+ \S+/s)\s+\| ([\d.]+ \S+/s)\s+\| ([\d.]+ \S+/s)\s+
   \| ([\d.k]+)\s+\| ([\d.k]+)\s+\| ([\d.k]+)\s+\| ([\d.k]+)\s+\| ([\d.]+)\s+\| ([\d.]+)
   ```
   Fields: `clients, vols_per_client, total_vols, profile, rw, bs, numjobs, iodepth, bw_sum, bw_avg, bw_max, bw_min, iops_sum, iops_avg, iops_max, iops_min, avg_lat_ms, p99_lat_ms`

3. **Normalise bandwidth** — convert all BW values to MiB/s:
   - `GiB/s × 1024`, `MiB/s × 1`, `KiB/s ÷ 1024`

4. **Normalise IOPS** — strip trailing `k` and multiply by 1000

5. **Sort rows** by `clients` ascending

6. **Run the plot script** — use `[./scripts/plot_fio_results.py](./scripts/plot_fio_results.py)` (already present in `scripts/`), passing the results directory as an argument:
   ```bash
   uv run --with matplotlib scripts/plot_fio_results.py <results_dir>
   ```
   e.g. `uv run --with matplotlib scripts/plot_fio_results.py results/apr7`
   > The script uses `matplotlib.use("Agg")` — no display required.

7. **Confirm output** — verify `<results_dir>/fio_benchmark_results.png` was saved in the same folder as the input files

## Key Observations to Report

After generating the chart, summarise:
- At what client count throughput/IOPS plateaued (storage saturation point)
- Latency degradation factor from lowest to highest client count
- Whether results are from a single profile or mixed (flag mixed profiles)

## Result File Format Reference

```markdown
## Summary Table

| Client Nodes | Volumes/Client | Total Volumes | Profile | RW | Block Size | NumJobs | IoDepth | BW Sum | BW Avg | BW Max | BW Min | IOPS Sum | IOPS Avg | IOPS Max | IOPS Min | Avg Latency (ms) | 99th Percentile Latency (ms) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 9 | 1 | 9 | db-workload | randrw | 4k | 1 | 64 | 260 MiB/s | 29 MiB/s | ... | ... | 66.6k | ... | ... | ... | 9.74 | 36.96 |
```

## Notes

- `bw_min`/`bw_max` are per-client values, not bounds on the sum — do not use them as error bars on the aggregate
- Multiple rows per file are supported (e.g. a sweep over iodepth levels in the same run)
- The `uv run --with matplotlib` flag adds matplotlib without modifying `pyproject.toml`
- The script reads files with suffix `""` (no extension) **or** `.md` — both formats are supported
- The `.png` output is skipped automatically because `.png` is neither `""` nor `.md`
- The PNG is always written to the same directory as the input files (the directory argument), not hardcoded to `results/`
- Result files from `scp` are typically named `<short-uuid>-summary.md` (e.g. `d72df443-summary.md`)
