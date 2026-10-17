# Cockpit Engine a9 merged board wheel

`build.py` derives immutable wheel `0.2.0a9` from the pinned RWR `0.2.0a8` wheel. It applies the Fit S3 client-sort assets from `cockpit-engine-board-s3/` and restores the accepted stylesheet from `styles.css`. Every other wheel asset, including RWR's `table-engine.js`, is retained from a8.

The source stylesheet is pinned by SHA-256 in the builder. The builder verifies the input wheel and stylesheet, refuses to overwrite the output, regenerates `RECORD`, and checks that the RWR runtime assets are the intended versions. Build from the repository root with:

```powershell
.venv\Scripts\python.exe vendor/patches/cockpit-engine-link-style/build.py
```

Input, source assets, and output hashes are recorded in `provenance/board-s1.json`.
