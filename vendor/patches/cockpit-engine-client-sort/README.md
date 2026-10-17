# cockpit-engine client sort adaptation

The original `vendor/cockpit_engine-0.2.0a5-py3-none-any.whl` is retained unchanged.
The two JavaScript files here are the authoritative adapted sources. `client-sort.patch`
is the readable unified change against upstream (normalized LF line endings).

Rebuild from the repository root with:

```powershell
.runtime/venv-312/Scripts/python.exe vendor/patches/cockpit-engine-client-sort/build.py
uv sync --frozen --all-groups --python 3.12
```

The builder verifies the input hash, replaces only the two assets and package version,
recomputes wheel RECORD hashes, and uses fixed timestamps and sorted ZIP members.
The immutable output version is 0.2.0a6; other table consumers retain server pagination.
