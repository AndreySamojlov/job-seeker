"use strict";

function formatBoardCell(column, row, timezone = "Europe/Moscow") {
  const value = row[column.key];
  let text = value == null || value === "" ? "—" : String(value);
  if (column.kind === "number" && value != null) {
    text = column.format === "percent"
      ? new Intl.NumberFormat("ru-RU", {style:"percent", minimumFractionDigits:1, maximumFractionDigits:1}).format(value).replace(/[\u00a0\u202f]%/g, "%")
      : new Intl.NumberFormat("ru-RU", {maximumSignificantDigits: 21}).format(value);
  }
  if (column.kind === "datetime" && value != null) {
    const date = new Date(value);
    text = Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat("ru-RU", {dateStyle:"short", timeStyle:"short", timeZone:timezone}).format(date) : "—";
  }
  let href = null;
  if (column.kind === "link") {
    try { const url = new URL(row[column.href_key]); if (["https:", "http:"].includes(url.protocol)) href = url.href; } catch (_) { /* plain text */ }
  }
  return {text, href};
}

// Client sort operates on the complete bounded snapshot before choosing a page.
// Null stays last in either direction; vacancy identity breaks all remaining ties.
function boardTablePage(columns, rows, options={}) {
  if (!options.clientSort) return rows;
  const column=columns.find(c=>c.key===options.sortKey) ||
    (options.sortKey==="discovered_at"?{key:"discovered_at",kind:"datetime"}:null);
  const textCompare=(a,b)=>a<b?-1:a>b?1:0;
  const compare=(a,b)=>{
    let order=0;
    if(column){
      const av=a[column.key],bv=b[column.key];
      if(av==null||bv==null){if(av==null&&bv!=null)return 1;if(bv==null&&av!=null)return -1;}
      else order=column.kind==='number'?av-bv:textCompare(String(av),String(bv));
    }
    if(order)return options.sortDirection==='desc'?-order:order;
    return textCompare(String(a[options.rowKey]??''),String(b[options.rowKey]??''));
  };
  const size=options.pageSize||100,page=options.page||0;
  return [...rows].sort(compare).slice(page*size,(page+1)*size);
}

function renderBoardTable(container, columns, rows, options) {
  const o = options || {};
  rows = boardTablePage(columns, rows, o);
  const cs = o.columnState || tblColState();
  cs.sortKey = o.sortKey || cs.sortKey;
  cs.sortDir = o.sortDirection || cs.sortDir;
  const allCols = columns.map((c, i) => ({...c, fixed: c.fixed === true || i === 0, r: c.kind === "number"}));
  const valueOf = (row, key) => row[key];
  let disposed = false;
  let liveWrap = null;
  function rerender(reason) {
    if (disposed) return;
    if(reason==="filter"){
      if(o.onFilters)o.onFilters(cs.filters||{});
      return;
    }
    if (reason === "sort") {
      if (o.onSort) o.onSort(cs.sortKey, cs.sortDir);
      return;
    }
    draw();
  }
  function draw() {
    if (liveWrap) tblDispose(liveWrap, cs);
    const cols = allCols.filter(c => !cs.hidden.has(c.key));
    const head = el("thead", {}, el("tr", {}, cols.map(c => tblHeadCell(c, cs, {
      root:container, rerender, cls:c.r ? "r" : "", getValue:valueOf
    }))));
    const body = el("tbody", {}, rows.map(row => el("tr", o.rowKey ? {"data-row-key":String(row[o.rowKey])} : {}, cols.map(c => {
      const cell = formatBoardCell(c, row, o.timezone);
      const attrs = {class:c.r ? "r" : ""};
      if (c.kind === "text" || c.kind === "link") { attrs.class += " clip"; attrs.title = cell.text; }
      return el("td", attrs, cell.href
        ? el("a", {href:cell.href, target:"_blank", rel:"noopener noreferrer"}, cell.text)
        : cell.text);
    }))));
    const table = el("table", {}, [tblColgroup(cols, cs), head, body]);
    const wrap = tblWrap(cs, rerender, {cols, rows, filename:"board-page.csv", getValue:valueOf,canRead:o.canRead});
    liveWrap = wrap;
    wrap.append(table);
    tblEnableSelection(wrap, cs, {cols, rows, getValue:valueOf,canRead:o.canRead});
    const total = o.totalRows || 0, size = o.pageSize || 100, page = o.page || 0;
    if (total > rows.length) {
      const download = wrap.querySelector(".tblexport");
      download.textContent = "⭳ Скачать страницу";
      download.title = "Скачать " + rows.length + " строк текущей страницы; всего в выборке " + total;
    }
    const pager = el("div", {class:"pager ce-board-pager"});
    const prev = el("button", {class:"pg",type:"button"}, "Назад");
    const next = el("button", {class:"pg",type:"button"}, "Далее");
    prev.disabled = page <= 0; next.disabled = (page + 1) * size >= total;
    prev.addEventListener("click", () => o.onPage && o.onPage(page - 1));
    next.addEventListener("click", () => o.onPage && o.onPage(page + 1));
    const first = rows.length ? page * size + 1 : 0;
    pager.append(prev, el("span", {class:"pgi"}, `${first}–${Math.min(page * size + rows.length,total)} / ${total}`), next);
    container.replaceChildren(wrap, pager);
    if(o.onInteraction)tblObserveInteractions(wrap,o.onInteraction);
    if (!rows.length) container.append(el("p", {class:"empty"}, "Нет данных"));
  }
  draw();
  return () => {disposed = true; if (liveWrap) tblDispose(liveWrap, cs); liveWrap = null; container.replaceChildren();};
}

function mountBoardTable(container, columns, rows, options={}) {
  let disposed=false,release=null,currentColumns=columns,currentRows=rows,currentOptions=options;
  function validate(cols,data,o){
    if(!o.rowKey)return;
    const keys=new Set();for(const row of data){const key=row[o.rowKey];if(typeof key!=="string"||!key||keys.has(key))throw new Error("Invalid row identity");keys.add(key);}
  }
  function captureViewState(){
    const wrap=container.querySelector(".tblwrap");if(!wrap)return {};
    const list=[...container.querySelectorAll("tbody tr")];
    const top=wrap.getBoundingClientRect().top;
    const anchor=list.find(row=>row.getBoundingClientRect().bottom>top)||list[0];
    return {left:wrap.scrollLeft,top:wrap.scrollTop,anchor:anchor?.dataset.rowKey,
      index:list.indexOf(anchor),offset:anchor?anchor.getBoundingClientRect().top-top:0};
  }
  function restoreViewState(state){
    const wrap=container.querySelector(".tblwrap");if(!wrap)return;
    wrap.scrollLeft=state.left||0;wrap.scrollTop=state.top||0;
    const list=[...container.querySelectorAll("tbody tr")];
    const row=list.find(row=>row.dataset.rowKey===state.anchor)||list[Math.max(0,Math.min(state.index||0,list.length-1))];
    if(row)wrap.scrollTop+=row.getBoundingClientRect().top-wrap.getBoundingClientRect().top-(state.offset||0);
  }
  function update(cols,data,o=currentOptions){
    if(disposed)return;validate(cols,data,o);const state=captureViewState();
    if(release)release();currentColumns=cols;currentRows=data;currentOptions=o;
    release=renderBoardTable(container,cols,data,o);restoreViewState(state);
  }
  function invalidate(){if(release)release();release=null;currentRows=[];}
  update(columns,rows,options);
  return {update,captureViewState,restoreViewState,invalidate,destroy(){disposed=true;invalidate();}};
}
if (typeof module !== "undefined") module.exports = {formatBoardCell, renderBoardTable,mountBoardTable,boardTablePage};
