"""Execute the actual wheel assets in Node, without a browser or database."""
from pathlib import Path
import subprocess
import zipfile
import pytest

ROOT = Path(__file__).resolve().parents[2]

@pytest.mark.parametrize('installed', [False, True])
def test_client_table_full_set_order_and_server_default(tmp_path, installed):
    if installed:
        import cockpit_engine
        base = Path(cockpit_engine.__file__).parent / 'web' / 'static'
        table = (base / 'board-table.js').read_text(encoding='utf-8')
        runtime = (base / 'board-runtime.js').read_text(encoding='utf-8')
    else:
        wheel = sorted((ROOT / 'vendor').glob('cockpit_engine-*.whl'))[-1]
        with zipfile.ZipFile(wheel) as z:
            table = z.read('cockpit_engine/web/static/board-table.js').decode()
            runtime = z.read('cockpit_engine/web/static/board-runtime.js').decode()
    script = tmp_path / 'check.cjs'
    script.write_text(table + '\n' + runtime + r"""
const assert = require('node:assert/strict');
assert.equal(typeof boardTablePage, 'function');
const cols=[{key:'score',kind:'number'},{key:'title',kind:'text'}];
const rows=Array.from({length:201},(_,i)=>({vacancy_id:String(i).padStart(3,'0'),score:200-i,title:String(200-i)}));
let opts={clientSort:true,sortKey:'score',sortDirection:'asc',rowKey:'vacancy_id',page:0,pageSize:100};
assert.equal(boardTablePage(cols,rows,opts)[0].score,0);
assert.equal(boardTablePage(cols,rows,{...opts,page:1})[0].score,100);
assert.equal(boardTablePage(cols,rows,{...opts,page:2}).length,1);
assert.equal(boardTablePage(cols,rows,{}).length,201);
assert.deepEqual(boardTablePage(cols,[{vacancy_id:'a',discovered_at:'2026-10-01'},{vacancy_id:'b',discovered_at:'2026-10-16'}],{...opts,sortKey:'discovered_at',sortDirection:'desc'}).map(r=>r.vacancy_id),['b','a']);
const mixed=[{vacancy_id:'b',score:10,title:'B'},{vacancy_id:'c',score:null,title:null},{vacancy_id:'a',score:10,title:'A'},{vacancy_id:'z',score:0,title:'Z'}];
assert.deepEqual(boardTablePage(cols,mixed,opts).map(r=>r.vacancy_id),['z','a','b','c']);
assert.deepEqual(boardTablePage(cols,mixed,{...opts,sortDirection:'desc'}).map(r=>r.vacancy_id),['a','b','z','c']);
assert.deepEqual(boardTablePage(cols,mixed,{...opts,sortKey:'title'}).map(r=>r.vacancy_id),['a','b','z','c']);
const rwrCols=[{key:'remote_work_readiness',kind:'number',format:'percent'}];
const readiness=[{vacancy_id:'mid',remote_work_readiness:0.5},{vacancy_id:'none',remote_work_readiness:null},
  {vacancy_id:'low',remote_work_readiness:0.1},{vacancy_id:'high',remote_work_readiness:0.9}];
assert.deepEqual(boardTablePage(rwrCols,readiness,{...opts,sortKey:'remote_work_readiness'}).map(r=>r.vacancy_id),['low','mid','high','none']);
assert.deepEqual(boardTablePage(rwrCols,readiness,{...opts,sortKey:'remote_work_readiness',sortDirection:'desc'}).map(r=>r.vacancy_id),['high','mid','low','none']);
const p={schema_version:1,state:'live',meta:{domain:'x',filters:{}},filters:[],kpis:[],charts:{specs:[],chart_series:[]},table:{columns:[],rows,total_rows:201,page:0,page_size:100}};
assert.throws(()=>validateBoardPayload(p));
assert.equal(validateBoardPayload({...p,table:{...p.table,client_sort:true}}).table.rows.length,201);
assert.throws(()=>validateBoardPayload({...p,table:{...p.table,client_sort:true,total_rows:202}}));
// Exercise the actual table renderer: visible, selected and exported rows agree.
let exported, selected, headCallbacks;
class Element {
 constructor(tag,attrs={},children=[]) {this.tag=tag;this.children=[];this.attrs=attrs;this.dataset={};this.classList={add(){},remove(){},toggle(){}};this.listeners={};this.append(...(Array.isArray(children)?children:[children]));}
 append(...items){for(const item of items.flat()){if(item==null)continue;this.children.push(item);if(typeof item==='object')item.parentElement=this;}}
 replaceChildren(...items){this.children=[];this.append(...items);}
 addEventListener(key,fn){this.listeners[key]=fn;}
 removeEventListener(){}
 setAttribute(){}
 removeAttribute(){}
 querySelector(selector){if(selector==='.tblexport')return {textContent:'',title:''};return null;}
 querySelectorAll(){return [];}
}
global.el=(tag,attrs,children)=>new Element(tag,attrs,children);
global.tblColState=()=>({hidden:new Set(),sortKey:null,sortDir:'asc'});
global.tblDispose=()=>{};
global.tblHeadCell=(col,state,callbacks)=>{headCallbacks=callbacks;return el('th',{},col.key);};
global.tblColgroup=()=>el('colgroup');
global.tblWrap=(state,rerender,data)=>{exported=data.rows;return el('div');};
global.tblEnableSelection=(wrap,state,data)=>{selected=data.rows;};
global.tblObserveInteractions=()=>{};
const host=el('div');
renderBoardTable(host,cols,rows,{...opts,page:1,totalRows:201});
assert.equal(exported.length,100);assert.equal(exported[0].score,100);
assert.equal(selected,exported);
let serverSort;
renderBoardTable(host,cols,rows.slice(0,3),{onSort:(...args)=>serverSort=args});
headCallbacks.rerender('sort');assert.ok(serverSort);
assert.equal(exported.length,3);

// Drive mountBoard refresh callbacks: client sort/page makes no server request,
// and a new complete snapshot retains the current sort and page.
global.document={title:'',activeElement:null,hidden:false,addEventListener(){},removeEventListener(){}};
global.window={addEventListener(){},removeEventListener(){}};
let control,requestCount=0,viewOptions,viewRows;const activeInteractions=new Set();
global.createBoardRefreshController=config=>{
  control={...config,setContext(){requestCount++;},getState(){return {readId:control.readId};},setInteraction(token,active){if(active)activeInteractions.add(token);else activeInteractions.delete(token);},setVisible(){},destroy(){}};
 return control;
};
global.renderKpiCards=()=>{};
global.mountStage=()=>({update(){},destroy(){}});
mountBoardTable=(container,columns,data,options)=>{
 viewOptions=options;viewRows=data;
  return {captureViewState(){return {};},restoreViewState(){},destroy(){},update(c,r,o){const old=viewOptions;if(old?.onInteraction)queueMicrotask(()=>old.onInteraction({token:'selection',active:false}));viewOptions=o;viewRows=r;}};
};
mountBoard(el('div'),{title:'Test',domains:[{key:'x',label:'X'}],refresh:{}});
const payload={...p,meta:{...p.meta,read_id:'first',context:{sort_key:'score',sort_direction:'desc'}},table:{...p.table,columns:cols,client_sort:true,row_key:'vacancy_id'}};
control.readId='first';control.onView({invalidated:0,payload,readId:'first',phase:'live'});
assert.equal(viewOptions.sortDirection,'desc');
const before=requestCount;
viewOptions.onInteraction({token:'selection',active:true});
assert.ok(activeInteractions.has('table:selection'));
viewOptions.onSort('score','desc');viewOptions.onPage(1);
assert.equal(requestCount,before);
assert.equal(viewOptions.page,1);assert.equal(viewOptions.sortDirection,'desc');
assert.equal(boardTablePage(cols,viewRows,viewOptions)[0].score,100);
queueMicrotask(()=>assert.equal(activeInteractions.has('table:selection'),false));
control.readId='second';control.onView({invalidated:0,payload:{...payload,meta:{...payload.meta,read_id:'second'}},readId:'second',phase:'live'});
assert.equal(viewOptions.page,1);assert.equal(viewOptions.sortKey,'score');assert.equal(viewOptions.sortDirection,'desc');

""", encoding='utf-8')
    result = subprocess.run(['node', str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
