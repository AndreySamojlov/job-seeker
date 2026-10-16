"use strict";

function serializeBoardColumnFilters(filters){
  if(!filters||typeof filters!=="object"||Array.isArray(filters))throw new Error("Invalid filters");
  const normalized={};
  for(const key of Object.keys(filters).sort()){
    const input=filters[key];if(!input||typeof input!=="object"||Array.isArray(input))throw new Error("Invalid filter");
    const state={};for(const field of Object.keys(input).sort()){
      const value=input[field];if(value==null)continue;
      if(field==="q"&&typeof value==="string"){if(value.trim())state.q=value.trim();}
      else if(["min","max"].includes(field)&&typeof value==="number"&&Number.isFinite(value))state[field]=value;
      else throw new Error("Invalid filter value");
    }
    if(Object.keys(state).length)normalized[key]=state;
  }
  return JSON.stringify(normalized);
}

function validateBoardPayload(p, {refreshEnabled=false}={}) {
  const fail = () => {throw new Error("Invalid board payload");};
  const record = v => v && typeof v === "object" && !Array.isArray(v);
  const array = Array.isArray;
  if (!record(p) || p.schema_version !== 1 || !["live","unavailable"].includes(p.state)) fail();
  if (!record(p.meta) || typeof p.meta.domain !== "string" || !record(p.meta.filters)) fail();
  try { new Intl.DateTimeFormat("ru-RU", {timeZone:p.meta.timezone || "Europe/Moscow"}); } catch (_) {fail();}
  if (!array(p.filters) || !array(p.kpis) || !record(p.charts) || !array(p.charts.specs) || !array(p.charts.chart_series)) fail();
  if (!record(p.table) || !array(p.table.columns) || !array(p.table.rows)) fail();
  const t = p.table;
  if (![t.total_rows,t.page,t.page_size].every(Number.isSafeInteger) || t.total_rows<0 || t.page<0 || t.page_size<1 || t.rows.length>t.page_size || t.rows.length>t.total_rows) fail();
  if(refreshEnabled){
    const m=p.meta;
    if(!record(m.context)||!Object.keys(m.context).length||typeof m.read_id!=="string"||!m.read_id||
       typeof m.snapshot_at!=="string"||!Number.isFinite(Date.parse(m.snapshot_at))||
       !Number.isFinite(m.snapshot_age_ms)||m.snapshot_age_ms<0||typeof t.row_key!=="string"||!t.row_key)fail();
    const c=m.context;
    if(c.domain!==m.domain||c.page!==t.page||c.page_size!==t.page_size||typeof c.sort_key!=="string"||!c.sort_key||!["asc","desc"].includes(c.sort_direction))fail();
    if(Object.values(c).some(v=>v!==null&&!["string","number","boolean"].includes(typeof v)))fail();
    const boundKeys=new Set(["domain","page","page_size","sort_key","sort_direction"]);
    if(t.filter_param!=null||t.filter_context_key!=null){
      if(typeof t.filter_param!=="string"||!/^[a-z][a-z0-9_]*$/.test(t.filter_param)||
         typeof t.filter_context_key!=="string"||boundKeys.has(t.filter_context_key)||!record(t.filters))fail();
      if(p.filters.some(f=>f.key===t.filter_param||(f.context_key||f.key)===t.filter_context_key))fail();
      for(const [key,state] of Object.entries(t.filters)){
        const col=t.columns.find(col=>col.key===key);if(!col||!["text","range"].includes(col.filter))fail();
        if(!record(state)||(col.filter==="text"?Object.keys(state).some(k=>k!=="q"):Object.keys(state).some(k=>!["min","max"].includes(k))))fail();
      }
      if(typeof c[t.filter_context_key]!=="string"||serializeBoardColumnFilters(JSON.parse(c[t.filter_context_key]))!==serializeBoardColumnFilters(t.filters))fail();
      boundKeys.add(t.filter_context_key);
    }
    for(const f of p.filters){
      const binding=f.context_key||f.key;
      if(typeof binding!=="string"||!Object.hasOwn(c,binding)||boundKeys.has(binding)||String(c[binding]??"")!==String(f.value??""))fail();
      boundKeys.add(binding);
    }
    if(Object.keys(c).some(k=>!boundKeys.has(k)))fail();
    const rowKeys=new Set();
    for(const row of t.rows){const k=row[t.row_key];if(typeof k!=="string"||!k||rowKeys.has(k))fail();rowKeys.add(k);}
  }
  const keys = new Set();
  for (const c of t.columns) {
    if (!record(c) || typeof c.key !== "string" || !c.key || keys.has(c.key) || typeof c.label !== "string" || !["text","number","link","datetime"].includes(c.kind)) fail();
    if (c.format !== undefined && (c.format !== "percent" || c.kind !== "number")) fail();
    if (c.sortable !== undefined && typeof c.sortable !== "boolean") fail();
    keys.add(c.key);
  }
  for (const row of t.rows) {
    if (!record(row)) fail();
    for (const c of t.columns) if (c.kind === "number" && row[c.key] != null && !Number.isFinite(row[c.key])) fail();
  }
  for (const k of p.kpis) if (!record(k) || typeof k.label !== "string" || typeof k.value !== "string") fail();
  const ids = new Set();
  for (const s of p.charts.specs) {
    if (!record(s) || typeof s.id !== "string" || !/^[a-zA-Z][\w-]*$/.test(s.id) || ids.has(s.id) || !["bar","hbar","line","grouped-bar","stacked-hbar","pie","date-scatter"].includes(s.encoding)) fail();
    ids.add(s.id);
  }
  for (const f of p.filters) {
    if (!record(f) || !/^[a-zA-Z][\w_]*$/.test(f.key) || ["domain","page","sort_key","sort_direction"].includes(f.key) || typeof f.label !== "string" || !["select","date"].includes(f.kind)) fail();
    if (f.kind === "select" && (!array(f.options) || !f.options.every(o=>record(o)&&typeof o.value==="string"&&typeof o.label==="string"))) fail();
  }
  return p;
}

function createBoardLoader(dataUrl, onData, onError, fetcher) {
  fetcher = fetcher || fetch;
  let generation = 0, controller = null, destroyed = false;
  return {
    async load(params) {
      if (destroyed) return;
      const id = ++generation;
      if (controller) controller.abort();
      controller = new AbortController();
      try {
        const query = new URLSearchParams(params);
        const response = await fetcher(dataUrl + "?" + query.toString(), {signal:controller.signal, credentials:"same-origin", cache:"no-store"});
        if (!response.ok) throw new Error("Source unavailable");
        const payload = validateBoardPayload(await response.json());
        if (!destroyed && id === generation) onData(payload);
      } catch (error) {
        if (!destroyed && id === generation && error.name !== "AbortError") onError(new Error("Данные недоступны"));
      }
    },
    destroy() {destroyed = true; generation++; if (controller) controller.abort();}
  };
}

function mountBoard(root, config, runtime={}) {
  let controller=null,tableView=null,committedRead=null,lastInvalidation=-1,epoch=0,destroyed=false;
  let chartViewState=null,tableViewState=null;
  let chartStage = null, disposeTable = null, tableState = tblColState();
  let params = {domain:config.domains[0].key, page:"0"};
  root.classList.add("page-shell");
  const content = el("main", {class:"sheet",id:"sheet"});
  const accent = el("div", {class:"accent-top"});
  const scroll = el("div", {class:"sheet-scroll",id:"sheet-scroll",role:"region","aria-label":"Область отчёта",tabindex:"0"});
  const title = el("h1", {class:"report-title"}, config.domains[0].label);
  const subtitle = el("p", {class:"report-sub"}, "");
  const pad = el("div", {class:"pad",id:"pad"});
  const section = (id, label, node) => el("section", {class:"block",id}, [el("h2", {class:"h-sec"},label),node]);
  const kpis = el("div", {class:"kpi"});
  const charts = el("div", {id:"charts-host"});
  const table = el("div", {class:"ce-board-table-host"});
  pad.append(section("board-kpi","Главные показатели",kpis),section("board-charts","Динамика и распределения",charts),section("board-table","Таблица",table));
  scroll.append(el("div",{class:"app-bar"},el("div",{class:"brand"},[el("span",{class:"mk"}),config.title])),
    el("header",{class:"report-head"},[title,subtitle]),pad);
  content.append(accent,scroll);
  const navigation = el("aside", {class:"rail",id:"rail",tabindex:"-1","aria-label":"Навигация и фильтры"});
  const domains = el("nav", {class:"rail-domains","aria-label":"Источники"});
  const filters = el("form", {class:"rail-filters"});
  const toc = el("ol", {class:"rail-toc"});
  [["board-kpi","Показатели"],["board-charts","Диаграммы"],["board-table","Таблица"]].forEach(([id,label],i)=>{
    const link=el("a",{href:"#"+id},[el("span",{class:"rail-toc-n"},String(i+1)),el("span",{class:"rail-toc-t"},label)]);
    link.addEventListener("click",event=>{event.preventDefault();pad.querySelector("#"+id).scrollIntoView({behavior:"smooth",block:"start"});});
    toc.append(el("li",{},link));
  });
  const status = el("span", {role:"status"});
  const statusDot=el("span",{class:"rail-status-dot"});
  function railSection(label,node,cls) {return el("div",{class:"rail-sec "+cls},[el("div",{class:"rail-h"},label),node]);}
  navigation.append(railSection("Источники",domains,"rail-domains-zone"),railSection("Данные",filters,"rail-data-zone"),
    railSection("Разделы",toc,"rail-toc-zone"),el("div",{class:"rail-status-zone"},railSection("Статус",el("div",{class:"rail-status"},
      el("div",{class:"rail-status-row"},[statusDot,status])),"")),el("a",{class:"skip-link",href:"#sheet-scroll"},"К отчёту"));
  root.replaceChildren(content,navigation);
  document.title=config.title;
  const clear=()=>{
    epoch++;committedRead=null;
    if(tableView){tableViewState=tableView.captureViewState();tableView.destroy();}tableView=null;
    if(chartStage?.captureViewState)chartViewState=chartStage.captureViewState();
    if(typeof closeChartModal==="function") closeChartModal();
    if(chartStage) chartStage.destroy(); chartStage=null;
    if(disposeTable) disposeTable(); disposeTable=null;
    kpis.replaceChildren();charts.replaceChildren();table.replaceChildren();
  };
  const failed=()=>{clear();status.textContent="Данные недоступны";statusDot.className="rail-status-dot c-red";
    accent.classList.remove("is-loading");pad.classList.remove("is-loading");content.removeAttribute("aria-busy");};
  const refresh=()=>{if(controller){controller.setContext(params);return;}status.textContent="Загрузка…";accent.classList.add("is-loading");pad.classList.add("is-loading");
    content.setAttribute("aria-busy","true");return loader.load(params);};
  const renderPayload=payload=>{
    try {
      if(payload.meta.domain!==params.domain || payload.state!=="live") throw new Error("Unavailable");
      if(!controller)clear();
      title.textContent=config.domains.find(d=>d.key===params.domain).label;
      subtitle.textContent=payload.meta.selection_required ? "Выберите кандидата в панели справа" : "";
      status.textContent=payload.meta.fetched_at ? new Intl.DateTimeFormat("ru-RU",{dateStyle:"short",timeStyle:"short",timeZone:payload.meta.timezone||"Europe/Moscow"}).format(new Date(payload.meta.fetched_at)) : "";
      statusDot.className="rail-status-dot c-green";
      const desired=new Set(payload.filters.map(f=>f.key));
      for(const field of [...filters.children])if(!desired.has(field.dataset.key))field.remove();
      payload.filters.forEach(f=>{
        let field=[...filters.children].find(node=>node.dataset.key===f.key);
        if(!field){
          const input=f.kind==="date" ? el("input",{type:"date",name:f.key,"aria-label":f.label}) : el("select",{name:f.key,"aria-label":f.label});
          field=el("label",{class:"rail-field"+(f.kind==="date"?" ce-board-date":""),"data-key":f.key},[
            el("span",{class:"rail-field-lbl"},f.label),
            ...(f.kind==="select"?[el("span",{class:"rail-field-val"}),el("span",{class:"rail-field-arr","aria-hidden":"true"},"⌄")]:[]),input]);
          input.addEventListener("change",()=>{params[f.key]=input.value;params.page="0";refresh();});
          filters.append(field);
        }
        const input=field.querySelector("input,select");
        if(document.activeElement!==input){
          if(f.kind==="select")input.replaceChildren(...f.options.map(o=>el("option",{value:o.value},o.label)));
          input.value=String(f.value??"");
        }
        if(params[f.key]==null&&input.value!=="")params[f.key]=input.value;
        const label=field.querySelector(".rail-field-val");if(label)label.textContent=f.options.find(o=>o.value===input.value)?.label||"—";
      });
      domains.querySelectorAll("button").forEach(b=>{b.classList.toggle("on",b.dataset.domain===params.domain);b.setAttribute("aria-pressed",String(b.dataset.domain===params.domain));});
      renderKpiCards(kpis,payload.kpis);
      const chartPayload={meta:payload.meta,chart_series:payload.charts.chart_series};
      if(chartStage?.update)chartStage.update(payload.charts.specs,chartPayload);
      else {if(chartStage)chartStage.destroy();chartStage=mountStage(charts,payload.charts.specs,chartPayload);if(chartViewState&&chartStage?.restoreViewState)chartStage.restoreViewState(chartViewState);}
      const t=payload.table;
      if(t.filter_param){params[t.filter_param]=payload.meta.context[t.filter_context_key];tableState.filters=JSON.parse(JSON.stringify(t.filters));}
      const scope=++epoch;
      const options={onFilters:t.filter_param ? state=>{params[t.filter_param]=serializeBoardColumnFilters(state);params.page="0";refresh();}:undefined,
        rowKey:t.row_key,canRead:()=>!controller||controller.getState().readId===payload.meta.read_id,
        onInteraction:({token,active})=>{if(scope===epoch&&controller)controller.setInteraction("table:"+token,active);},columnState:tableState,totalRows:t.total_rows,page:t.page,pageSize:t.page_size,timezone:payload.meta.timezone,
        sortKey:params.sort_key,sortDirection:params.sort_direction,
        onPage:page=>{params.page=String(page);refresh();},
        onSort:(key,direction)=>{if(key){params.sort_key=key;params.sort_direction=direction;}else{delete params.sort_key;delete params.sort_direction;}params.page="0";refresh();}};
      if(controller){if(tableView)tableView.update(t.columns,t.rows,options);else {tableView=mountBoardTable(table,t.columns,t.rows,options);if(tableViewState)tableView.restoreViewState(tableViewState);}}
      else disposeTable=renderBoardTable(table,t.columns,t.rows,options);
      committedRead=payload.meta.read_id;
      accent.classList.remove("is-loading");pad.classList.remove("is-loading");content.removeAttribute("aria-busy");
    } catch(error){if(controller)throw error;failed();}
  };
  const apply=el("button",{type:"button",class:"board-apply-update"},"Применить обновление (сбросить выделение)");
  apply.hidden=true;apply.addEventListener("click",()=>controller?.applyPending());
  status.parentElement.append(apply);
  const loader=config.refresh ? null : createBoardLoader(config.data_url,renderPayload,failed);
  if(config.refresh){
    controller=createBoardRefreshController({...runtime,policy:config.refresh,validate:validateBoardPayload,
      fetcher:(query,options)=>fetch(config.data_url+"?"+new URLSearchParams(query),{...options,credentials:"same-origin",cache:"no-store"}),
      onView:view=>{
        if(destroyed)return;
        if(view.invalidated!==lastInvalidation){lastInvalidation=view.invalidated;clear();}
        if(view.payload&&view.readId!==committedRead){try{renderPayload(view.payload);}catch(_){controller.invalidate();return;}}
        if(!view.payload)clear();
        status.textContent=view.phase==="loading"?"Загрузка…":view.phase==="unavailable"?"Данные недоступны":
          (view.phase==="stale"?"Данные устарели · ":"")+(view.payload?.meta.snapshot_at?new Intl.DateTimeFormat("ru-RU",{dateStyle:"short",timeStyle:"short",timeZone:view.payload.meta.timezone||"Europe/Moscow"}).format(new Date(view.payload.meta.snapshot_at)):"")+
          (view.pending?" · Есть новые данные":view.refreshing?" · Обновление…":"");
        statusDot.className="rail-status-dot "+(view.phase==="live"?"c-green":"c-red");
        apply.hidden=!view.pending;
        accent.classList.toggle("is-loading",view.refreshing);content.setAttribute("aria-busy",String(view.refreshing));
      }});
  }
  const focusIn=()=>controller?.setInteraction("filter-edit",true);
  const focusOut=()=>queueMicrotask(()=>{if(!filters.contains(document.activeElement))controller?.setInteraction("filter-edit",false);});
  filters.addEventListener("focusin",focusIn);filters.addEventListener("focusout",focusOut);
  const modalUnsubscribe=typeof subscribeChartModalLifecycle==="function"?subscribeChartModalLifecycle(({token,active})=>controller?.setInteraction(token,active)):()=>{};
  const visibility=()=>controller?.setVisible(!document.hidden);
  const pageHide=()=>controller?.setVisible(false);
  const pageShow=event=>controller?.setVisible(!document.hidden,{uncertain:!!event.persisted});
  if(controller){document.addEventListener("visibilitychange",visibility);window.addEventListener("pagehide",pageHide);window.addEventListener("pageshow",pageShow);}
  config.domains.forEach(d=>{
    const button=el("button",{class:"dtab"+(d.key===params.domain ? " on" : ""),type:"button","data-domain":d.key,"aria-pressed":String(d.key===params.domain)},d.label);
    button.addEventListener("click",()=>{params={domain:d.key,page:"0"};tableState=tblColState();refresh();});
    domains.append(button);
  });
  filters.addEventListener("submit",event=>event.preventDefault());
  refresh();
  return {destroy(){destroyed=true;if(loader)loader.destroy();if(controller)controller.destroy();modalUnsubscribe();
    document.removeEventListener("visibilitychange",visibility);window.removeEventListener("pagehide",pageHide);window.removeEventListener("pageshow",pageShow);
    filters.removeEventListener("focusin",focusIn);filters.removeEventListener("focusout",focusOut);clear();root.replaceChildren();}};
}

if (typeof module !== "undefined") module.exports={validateBoardPayload,createBoardLoader,mountBoard,serializeBoardColumnFilters};
if (typeof window !== "undefined") window.CockpitBoard={mount:mountBoard};
