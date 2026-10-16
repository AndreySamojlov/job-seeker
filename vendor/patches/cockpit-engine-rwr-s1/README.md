# Cockpit Engine RWR S1 consumer wheel

This builder derives immutable consumer wheel `0.2.0a7` from the Cockpit Engine source wheel `0.2.0a6` with SHA-256 `f23305d541535c7043aab30441685552b474b462078cd30bfd9519624f84616c`. It changes only distribution metadata/RECORD and the two preserved Job Seeker board assets. `build.py` checks the exact input hash, fixes timestamps and permissions, sorts archive members, and regenerates RECORD.

The original client-sort builder and its history remain unchanged. The two `*.patch` files record the exact asset diffs against the pinned a6 wheel. Build from the repository root with the project Python 3.12 environment:

```powershell
.venv\Scripts\python.exe vendor/patches/cockpit-engine-rwr-s1/build.py
```
