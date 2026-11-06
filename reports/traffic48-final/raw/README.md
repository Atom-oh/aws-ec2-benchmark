# Complete captured experiment data

`manifest.json` lists all 189 regular source files (5,867,605,722 bytes),
including the final traffic48 run and the separate historical flex48 snapshot.
The 19 sorted `raw.tar.zst.part-NNN` files form one lossless tar.zst stream
(908,434,813 compressed bytes); each part is at most 48 MiB.
No Git LFS or external object storage is required.

From repository root (Python 3, zstd, GNU coreutils):

```bash
python3 scripts/traffic48_archive.py verify reports/traffic48-final/raw
python3 scripts/traffic48_archive.py restore reports/traffic48-final/raw /path/to/empty-restore
```

Verification checks every part, rejects unexpected archive paths, and hashes
every decompressed file against the inventory without loading the dataset into
memory. Restore refuses a nonempty destination. The archive preserves every
captured file byte; it cannot recover data never captured (e.g. lost GC rotations).
The flex48 CSVs contain 2,842 samples per type through about 47.47 hours.
Its progress summaries are stale (5.17/11.94 hours), and captured status is
RUNNING, so it is not a verified completed 48-hour result. See [the report](../README.md) for interpretation.
