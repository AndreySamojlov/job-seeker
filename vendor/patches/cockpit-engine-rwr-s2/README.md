# Cockpit Engine RWR S2 consumer wheel

This builder derives immutable consumer wheel `0.2.0a8` from pinned consumer wheel `0.2.0a7` (SHA-256 `ebec7bd70d91f805311bdcd444b240fd4f2603fd66c1624a850f17c734ee3044`). It replaces only the generic `board-runtime.js`, `board-table.js`, and `table-engine.js` assets with the S2 Engine implementation, while carrying forward every other a7 file including Job Seeker's existing client-sort and link-style adaptations. It also updates wheel metadata and `RECORD`.

`build.py` validates the exact input wheel, fixes timestamps and permissions, sorts archive members, and regenerates `RECORD` for deterministic output. The three `*.patch` files show each asset diff from a7; the patch hashes, source asset hashes, and resulting wheel hash are recorded in `provenance/board-s1.json`.

Run from the Job Seeker repository root with the project Python environment:

```powershell
.venv\Scripts\python.exe vendor/patches/cockpit-engine-rwr-s2/build.py
```
