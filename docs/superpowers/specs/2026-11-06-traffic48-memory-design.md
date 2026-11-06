# Traffic48 analyzer memory reduction

The user requests lowering the local analyzer's memory. The running watcher
3426201 reached 35.3 GiB resident memory and retains 10.3 GiB while idle. The
latest approximately 3.9 GiB of inputs required 2 h 35 min to analyze. The
request and the existing benchmark authorization cover this focused fix.

Preserve every report field, integer count, histogram, percentile, relative
comparison, validation threshold, source distinction, recovery calculation,
and GC coverage qualification. Preserve live EC2/Kubernetes workloads, their
configuration, image digests, JVM history and original experiment end.

Read JSONL one line at a time. Store valid histograms compactly in memory while
preserving dictionary semantics used by validation and aggregation; malformed
input must retain its original validation behavior. Avoid doing expensive GC
correlation for rows discarded by the existing stable top-20 spike selection.
Use time indexing where it preserves event ordering and exact inclusion.

Run each report in a short-lived child of the watcher, so its allocator exits
and returns memory after each report. Keep one collector and one foreground
analyzer; do not overlap mutable input snapshots or weaken error handling.
An unsuccessful analysis must leave the previous atomic report available.

Target current-data peak below 8 GiB, preferably 4 GiB. Measure actual peak RSS
and wall time, and compare the new full report with the already computed old
report on an immutable copy of the same inputs. Do not rerun the expensive old
full analyzer. Unit fixtures additionally compare old and new implementations.

Deploy only a watch-process replacement after independent code/security/content
PASS >=85 on the exact source hash. No commits, no workload restarts, no Go
changes, no new dependencies. Preserve unrelated concurrent workspace edits.
