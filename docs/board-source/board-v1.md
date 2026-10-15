# Portable board v1

This opt-in UI requires no database/core migrations or legacy Registration. Consumer owns the FastAPI app, GET data endpoint, calculations and one consistent read snapshot. The engine owns rendering. MP Cockpit deployment is not updated automatically.

## Python

`BoardDomain(key, label)` and immutable `BoardSpec(key,title,page_path,data_url,domains)` live in `cockpit_engine.web.board_contract`. `register_board_routes(app, *, board)` from `board_routes` installs HTML and allowlisted `/cockpit-assets` resources only. Paths must be plain same-origin absolute paths. Conflicts are rejected; never register legacy routes as part of this opt-in path. One board per app; any explicitly configured domains. No mutable registration shared across applications.

## Data GET

Return JSON `schema_version:1`, `state:live|unavailable`, `meta:{domain,filters,timezone,fetched_at}`, `filters:[]`, `kpis:[]`, `charts:{specs:[],chart_series:[]}`, `table:{columns:[],rows:[],total_rows,page,page_size}`. Errors use HTTP503; invalid input uses 422. A successful empty selection is a live response with zero totals, not an outage. Do not send raw exception details, DSNs or credentials.

Filters: `{key,label,kind:select|date,value,options?}`; select options have `{value,label}`. Reserved query keys domain/page/sort_key/sort_direction are controlled by runtime. Filter changes reset page=0. Consumer validates every field and candidate authorization; frontend validation is not a security boundary.

KPI cards use existing `renderKpiCards` contract: label/value strings, optional sub/element. A legitimate zero is "0", unknown metric is "Нет данных". Elements support existing line/bars/ring primitives and consume precomputed values.

Charts use existing engine spec/series shapes, `chart_series[].id` matches spec.id. New `pie`: x labels, one series with nonnegative y values. New `date-scatter`: series.data points `{x:epoch_milliseconds,y:number,label?}`, optional color from engine palette, yMin/yMax, xLabel/yLabel. Uses linear date-formatted X without a time adapter or quadrant; original scatter is unchanged. Moscow is default timezone; set meta.timezone explicitly. Date-scatter accepts fit=0; null/non-numeric points are not zero. Consumer separately counts excluded points. No data is synthesized by renderer.

For TOML compilation explicitly request `load_chart_types(portable=True)` and pass its result to `build_domain(raw, types)`. The default `load_chart_types()` and `build_engine()` keep the eight legacy types unchanged. Portable definitions live in separate package data `portable_chart_types.toml`; no consumer gets them merely by updating the package.

Table columns `{key,label,kind:text|number|link|datetime,href_key?}`; values are text, never HTML. Links accept only http/https. Numeric zero is visible, null becomes "—". Datetimes use meta.timezone. Consumer returns up to page_size rows and total_rows of the complete filtered set, not the current page. Sorting/paging triggers a fresh whole report; aggregate/chart selection is unaffected by page. Stable sort and snapshot are consumer responsibilities. JSON carries no callbacks; runtime supplies event handlers.

The loader aborts superseded requests and also rejects late responses by generation, clears stale displays after a current failure, and validates schema. mount returns destroy for cleanup. Existing shared CSS, KPI and chart stage are reused; new layout CSS is scoped to .ce-board. New assets never load legacy app.js/shared.js or issue legacy product requests.

## Independent example

From the source checkout: `uv run --with uvicorn uvicorn examples.portable_board.app:create_app --factory --host 127.0.0.1 --port 18767` (verify the port is free). The example uses synthetic Alpha/Beta data, empty/failure modes and 101 entities to exercise pagination; no external calls or mutations. Install a built wheel in a clean environment and copy only this example there to verify package completeness. Runtime consumer needs FastAPI/Uvicorn installed separately; they are not newly forced on non-web engine consumers.
