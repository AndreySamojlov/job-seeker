# Fit S3 table behavior on the RWR board runtime

These two assets start from the RWR S2 consumer runtime and table. They add Fit S3 complete-snapshot sorting and local paging while preserving the RWR display-only column and the existing Cockpit table engine, selection, export, and refresh behavior.

`boardTablePage` sorts the bounded full result before slicing one page, keeps missing values last in either direction, and uses the stable vacancy identifier for ties. The runtime validates that `client_sort=true` responses contain the complete result, retains sort/page state between refreshes, and handles local table interactions without issuing a new API request. The source hashes and resulting a9 wheel are recorded in `provenance/board-s1.json`.
