import React, {useEffect, useMemo, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Search, Bell, LayoutDashboard, ArrowRightLeft, AlertTriangle, Bot, ClipboardCheck, ShieldCheck, ChevronRight, RefreshCw, X, Sparkles, Activity, CircleDollarSign, FileSearch, Clock3, LoaderCircle} from 'lucide-react';
import './styles.css';

const API = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';
const money = n => `₹${Math.abs(Number(n || 0)).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2})}`;
const signedMoney = n => `${Number(n || 0) < 0 ? '−' : ''}${money(n)}`;
const compactMoney = n => {
  const v = Number(n || 0);
  if (Math.abs(v) >= 10000000) return `₹${(v/10000000).toFixed(2)}Cr`;
  if (Math.abs(v) >= 100000) return `₹${(v/100000).toFixed(2)}L`;
  if (Math.abs(v) >= 1000) return `₹${(v/1000).toFixed(1)}K`;
  return money(v);
};

async function api(path) {
  const res = await fetch(`${API}${path}`);
  const body = await res.json();
  if (!res.ok) throw new Error(body.error || `API request failed (${res.status})`);
  return body;
}

function App(){
  const [page,setPage] = useState('Overview');
  const [selected,setSelected] = useState(null);
  const [query,setQuery] = useState('');
  const [data,setData] = useState(null);
  const [transactions,setTransactions] = useState([]);
  const [evaluation,setEvaluation] = useState(null);
  const [audit,setAudit] = useState([]);
  const [loading,setLoading] = useState(true);
  const [error,setError] = useState('');
  const [lastSync,setLastSync] = useState(null);
  const [notificationsOpen,setNotificationsOpen] = useState(false);
  const [searchFocused,setSearchFocused] = useState(false);

  const load = async () => {
    setLoading(true); setError('');
    try {
      const [overview, tx, ev, au] = await Promise.all([
        api('/api/overview'), api('/api/transactions?limit=100'), api('/api/evaluation'), api('/api/audit')
      ]);
      setData(overview);
      setTransactions(tx.items || []);
      setEvaluation(ev);
      setAudit(au.items || []);
      setLastSync(new Date());
    } catch (e) {
      setError(`Could not reach CashTrace API. Start it with: python src/cashtrace_api.py (${e.message})`);
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const exceptions = useMemo(() => transactions.filter(x => x.status !== 'matched'), [transactions]);
  const searched = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return transactions;
    return transactions.filter(x => `${x.txn_id} ${x.payout_id || ''} ${x.description || ''} ${x.channel || ''} ${x.date || ''} ${x.status || ''} ${x.verdict || ''}`.toLowerCase().includes(q));
  }, [transactions, query]);
  const searchedExceptions = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return exceptions;
    return exceptions.filter(x => `${x.txn_id} ${x.payout_id || ''} ${x.description || ''} ${x.channel || ''} ${x.date || ''} ${x.status || ''} ${x.verdict || ''}`.toLowerCase().includes(q));
  }, [exceptions, query]);
  const searchedAudit = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return audit;
    return audit.filter(x => `${x.title || ''} ${x.detail || ''} ${x.time || ''} ${x.txn_id || ''}`.toLowerCase().includes(q));
  }, [audit, query]);
  const searchMatches = useMemo(() => searched.slice(0, 6), [searched]);
  const submitSearch = () => {
    const first = searched[0];
    if (first) { setSearchFocused(false); openTransaction(first); }
  };

  const batchDates = useMemo(() => {
    const dates = transactions.map(x=>x.date).filter(Boolean).sort();
    return dates.length ? `${dates[0]} – ${dates[dates.length-1]}` : 'Current batch';
  }, [transactions]);

  const nav=[['Overview',LayoutDashboard],['Transactions',ArrowRightLeft],['Exceptions',AlertTriangle],['Investigations',Bot],['Evaluation',ClipboardCheck],['Audit Trail',ShieldCheck]];
  const openTransaction = async (item) => {
    if (!item?.txn_id) { setSelected(item); return; }
    try { setSelected(await api(`/api/transactions/${item.txn_id}`)); }
    catch { setSelected(item); }
  };

  return <div className="app">
    <aside className="sidebar">
      <div className="brand"><div className="brandmark">C</div><div><div className="brandname">CashTrace</div><div className="brandsub">Financial Control Tower</div></div></div>
      <div className="navlabel">WORKSPACE</div>
      <nav>{nav.map(([n,I])=><button key={n} className={page===n?'navitem active':'navitem'} onClick={()=>setPage(n)}><I size={18}/><span>{n}</span>{n==='Exceptions'&&exceptions.length>0&&<span className="navbadge">{exceptions.length}</span>}</button>)}</nav>
      <div className="sidebarBottom"><div className="system"><span className="dot"></span><div><b>{error?'API offline':'Systems operational'}</b><small>{lastSync ? `Last sync · ${lastSync.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}` : 'Connecting…'}</small></div></div><div className="user"><div className="avatar">A</div><div><b>Finance workspace</b><small>Administrator</small></div></div></div>
    </aside>
    <main className="main">
      <header className="topbar"><div className="crumb"><span>Workspace</span><ChevronRight size={14}/><b>{page}</b></div><div className="topactions"><div className={`search ${searchFocused?'focused':''}`}><Search size={16}/><input value={query} onFocus={()=>setSearchFocused(true)} onChange={e=>setQuery(e.target.value)} onKeyDown={e=>{if(e.key==='Enter')submitSearch();if(e.key==='Escape')setSearchFocused(false)}} placeholder="Search transactions, IDs…"/>{query.trim()&&searchFocused&&<div className="searchresults">{searchMatches.length ? searchMatches.map(x=><button key={x.txn_id} className="searchresult" onMouseDown={e=>e.preventDefault()} onClick={()=>{setSearchFocused(false);openTransaction(x)}}><span className="searchresultmain"><b>{x.txn_id}</b><small>{x.payout_id || 'Settlement'} · {x.channel || 'Unknown channel'}</small></span><span className="searchresultamt">{signedMoney(x.variance)}</span><ChevronRight size={14}/></button>) : <div className="searchempty">No matching transactions</div>}{searched.length>6&&<div className="searchhint">Press Enter to open the first match</div>}</div>}</div><div className="notifwrap">
        <button className={`iconbtn ${notificationsOpen?'active':''}`} title="Notifications" onClick={()=>setNotificationsOpen(v=>!v)} aria-expanded={notificationsOpen}><Bell size={18}/>{exceptions.length>0&&<span className="notif"></span>}</button>
        {notificationsOpen&&<div className="notifpanel">
          <div className="notifhead"><div><b>Notifications</b><small>{exceptions.length ? `${exceptions.length} items need attention` : 'All clear'}</small></div><button onClick={()=>setNotificationsOpen(false)} aria-label="Close notifications"><X size={15}/></button></div>
          {exceptions.length ? exceptions.slice(0,5).map(e=><button key={e.txn_id} className="notifitem" onClick={()=>{setNotificationsOpen(false);openTransaction(e)}}><span className={`severity ${(e.severity||'Low').toLowerCase()}`}></span><span><b>{e.txn_id}</b><small>{e.payout_id || 'Settlement'} · {signedMoney(e.variance)} variance</small></span><ChevronRight size={15}/></button>) : <div className="notifempty">No new exceptions in this batch.</div>}
          {exceptions.length>5&&<button className="notifall" onClick={()=>{setNotificationsOpen(false);setPage('Exceptions')}}>View all exceptions <ChevronRight size={14}/></button>}
        </div>}
      </div><button className="sync" onClick={load} disabled={loading}>{loading?<LoaderCircle size={15} className="spin"/>:<RefreshCw size={15}/>} {loading?'Syncing':'Sync'}</button></div></header>
      {error&&<div className="apierror">{error}</div>}
      <div className="content">
        {page==='Overview'&&<Overview data={data} exceptions={searchedExceptions} dates={batchDates} onOpen={openTransaction} onPage={setPage}/>} 
        {page==='Exceptions'&&<Exceptions data={searchedExceptions} onOpen={openTransaction} query={query}/>} 
        {page==='Transactions'&&<Transactions data={searched} onOpen={openTransaction}/>} 
        {page==='Investigations'&&<Investigations data={searchedExceptions} onOpen={openTransaction}/>} 
        {page==='Evaluation'&&<Evaluation data={evaluation} onOpen={openTransaction}/>} 
        {page==='Audit Trail'&&<Audit items={audit} onOpen={openTransaction}/>} 
      </div>
    </main>
    {selected&&<Drawer item={selected} close={()=>setSelected(null)}/>} 
  </div>
}

function PageTitle({eyebrow,title,desc,children}){return <div className="pagetitle"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{desc}</p></div>{children}</div>}
function Overview({data,exceptions,dates,onOpen,onPage}){
  const s=data?.summary || {};
  return <>
    <PageTitle eyebrow="CONTROL TOWER" title="Good evening. Here’s the money trail." desc="CashTrace continuously verifies the lifecycle of incoming funds and surfaces what needs a human decision."><button className="datebtn">{dates} <ChevronRight size={15}/></button></PageTitle>
    <div className="metricgrid"><Metric label="Processed amount" value={compactMoney(s.processed_amount)} detail={`${s.deposits_examined||0} settlements`} icon={CircleDollarSign}/><Metric label="Verified / auto-resolved" value={`${s.verification_rate??0}%`} detail={`${s.by_status?.matched||0} of ${s.deposits_examined||0} settlements`} icon={ShieldCheck}/><Metric label="Amount at risk" value={money(s.amount_at_risk)} detail={`${exceptions.length} active exceptions`} icon={AlertTriangle} tone="warning"/><Metric label="Open investigations" value={exceptions.length} detail={`${exceptions.filter(x=>x.severity==='High').length} high materiality`} icon={FileSearch} tone="danger"/></div>
    <section className="section"><div className="sectionhead"><div><h2>Money lifecycle</h2><p>From source event to bank settlement.</p></div><span className="verifiedpill"><span className="dot"></span> Verification engine active</span></div>
      <div className="flow"><FlowCard n="01" label="Payout value" value={compactMoney(s.gross_payout_value)} detail={`${s.deposits_examined||0} matched lifecycle records`}/><div className="flowarrow"><ChevronRight size={20}/></div><FlowCard n="02" label="Expected net" value={compactMoney(s.expected_amount)} detail={`Fees ${compactMoney(s.fees_total)} · refunds ${compactMoney(s.refunds_total)}`}/><div className="flowarrow"><ChevronRight size={20}/></div><FlowCard n="03" label="Bank settlements" value={compactMoney(s.processed_amount)} detail={`${s.deposits_examined||0} deposits verified`}/></div>
    </section>
    <div className="twocol"><section className="panel"><div className="sectionhead"><div><h2>Exceptions requiring attention</h2><p>Prioritized by amount, uncertainty and business impact.</p></div><button className="textbtn" onClick={()=>onPage('Exceptions')}>View all <ChevronRight size={14}/></button></div><div className="table">{exceptions.slice(0,5).map(e=><ExceptionRow key={e.txn_id} e={e} onClick={()=>onOpen(e)}/>)}</div>{!exceptions.length&&<Empty text="No exceptions in the current batch."/>}</section><section className="panel"><div className="sectionhead"><div><h2>Recent activity</h2><p>What CashTrace has been doing.</p></div></div><div className="activity">{(data?.recent||[]).map((r,i)=><div className="activityrow" key={i}><div className={`activitydot ${r.type||'info'}`}></div><div><b>{r.event}</b><span>{r.detail}</span></div><time>Current batch</time></div>)}</div></section></div>
  </>
}
function FlowCard({n,label,value,detail}){return <div className="flowcard"><div className="flowicon">{n}</div><div><span>{label}</span><strong>{value}</strong><small>{detail}</small></div></div>}
function Metric({label,value,detail,icon:I,tone=''}){return <div className={`metric ${tone}`}><div className="metricicon"><I size={18}/></div><div><span>{label}</span><strong>{value}</strong><small>{detail}</small></div></div>}
function ExceptionRow({e,onClick}){return <button className="exceptionrow" onClick={onClick}><div className={`severity ${(e.severity||'Low').toLowerCase()}`}></div><div className="exceptionmain"><div><b>{e.txn_id}</b><span>{e.payout_id || 'No payout match'}</span></div><small>{e.channel || 'Unknown'} · {e.description || 'Settlement variance'}</small></div><div className="exceptionamt"><b>−{money(e.variance)}</b><span>{e.variance_pct}% variance</span></div><div className={`verdict ${(e.verdict||'UNRESOLVED').toLowerCase()}`}>{e.verdict}</div><ChevronRight size={17}/></button>}
function Exceptions({data,onOpen,query}){return <><PageTitle eyebrow="EXCEPTION CENTER" title="Exceptions" desc="Every unresolved or explainable variance, ranked by materiality."><button className="filterbtn">{data.length ? `${data.length} active` : 'No active exceptions'} <ChevronRight size={14}/></button></PageTitle><div className="metricgrid compact"><Metric label="Total exceptions" value={data.length} detail="Across the current batch" icon={AlertTriangle}/><Metric label="High materiality" value={data.filter(x=>x.severity==='High').length} detail={money(data.filter(x=>x.severity==='High').reduce((a,x)=>a+Math.abs(x.variance||0),0))+' at risk'} icon={Activity} tone="danger"/><Metric label="Probable" value={data.filter(x=>x.verdict==='PROBABLE').length} detail="Needs supporting evidence" icon={ShieldCheck}/><Metric label="Unresolved" value={data.filter(x=>x.verdict==='UNRESOLVED').length} detail="Human decision needed" icon={Clock3} tone="warning"/></div><section className="panel full"><div className="tablehead"><span>Exception</span><span>Amount</span><span>Verdict</span><span></span></div>{data.map(e=><ExceptionRow key={e.txn_id} e={e} onClick={()=>onOpen(e)}/>)}{!data.length&&<Empty text={query?.trim()?`No exceptions match “${query.trim()}”.`:'No active exceptions in the current batch.'}/>}</section></>}
function Transactions({data,onOpen}){return <><PageTitle eyebrow="TRANSACTION EXPLORER" title="Trace the money" desc="Follow a transaction from its originating event through settlement and verification."><button className="filterbtn">{data.length} records <ChevronRight size={14}/></button></PageTitle><section className="panel full"><div className="tablehead tx"><span>Transaction</span><span>Channel</span><span>Expected</span><span>Actual</span><span>Verdict</span></div>{data.map(r=><button className="txrow" key={r.txn_id} onClick={()=>onOpen(r)}><span><b>{r.txn_id}</b><small>{r.payout_id || 'Unmatched'} · {r.date || ''}</small></span><span>{r.channel}</span><span>{money(r.expected_net)}</span><span>{money(r.actual_deposit)}</span><span className={`verdict ${(r.verdict||'UNRESOLVED').toLowerCase()}`}>{r.verdict}</span></button>)}{!data.length&&<Empty text="No transactions match your search."/>}</section></>}
function Investigations({data,onOpen}){const [running,setRunning]=useState(false);const [result,setResult]=useState(null);const [error,setError]=useState('');const top=[...data].sort((a,b)=>Math.abs(b.variance||0)-Math.abs(a.variance||0))[0];const run=async()=>{if(!top)return;setRunning(true);setError('');try{const r=await api(`/api/investigations/${top.txn_id}`);setResult(r)}catch(e){setError(e.message||'Investigation failed')}finally{setRunning(false)}};return <><PageTitle eyebrow="AI INVESTIGATOR" title="Ask why the money changed" desc="The investigator explains evidence-backed causes. Deterministic controls remain authoritative."></PageTitle><section className="investigate"><div className="heroquery"><Sparkles size={20}/><h2>Why is this settlement lower than expected?</h2><p>CashTrace selects the highest-materiality exception, sends its verified facts to the investigator, and keeps the financial verdict under deterministic control.</p><button onClick={run} disabled={running||!top}>{running?<><LoaderCircle size={15} className="spin"/> Investigating…</>:<>Run investigation <ChevronRight size={15}/></>}</button>{!top&&<small className="heroempty">No exceptions are waiting for investigation.</small>}{error&&<small className="heroerror">{error}</small>}</div>{result?<div className="answer"><div className="answerhead"><span className="aiavatar"><Bot size={18}/></span><div><b>Investigation result · {result.facts?.transaction}</b><small>{result.mode==='llm'?'LLM explanation over deterministic evidence':'Deterministic fallback · no model key configured'}</small></div></div><div className="answergrid"><div><span>Verdict</span><strong className={`verdict ${(result.facts?.deterministic_verdict||'UNRESOLVED').toLowerCase()}`}>{result.facts?.deterministic_verdict}</strong></div><div><span>Variance</span><strong>{signedMoney(result.facts?.variance)}</strong></div><div><span>Confidence</span><strong>{data.find(x=>x.txn_id===result.facts?.transaction)?.confidence ?? 0}%</strong></div></div><div className="finding"><div className="findingtitle"><Sparkles size={15}/> AI finding</div><p>{result.summary}</p></div><div className="investigationblocks"><div><b>Likely causes</b>{(result.likely_causes||[]).map((c,i)=><div className="cause" key={i}><span>{c.status}</span><div><strong>{c.cause}</strong><small>{c.reason}</small></div></div>)}</div><div><b>Recommended next steps</b>{(result.next_steps||[]).map((x,i)=><div className="step" key={i}><span>{i+1}</span><p>{x}</p></div>)}</div></div><div className="guardrail">✓ {result.guardrail}</div><button className="textbtn" onClick={()=>onOpen(data.find(x=>x.txn_id===result.facts?.transaction)||top)}>Open full evidence <ChevronRight size={14}/></button></div>:<div className="answer"><div className="answerhead"><span className="aiavatar"><Bot size={18}/></span><div><b>Investigation preview</b><small>Nothing is auto-claimed before evidence is available</small></div></div><div className="finding"><b>Ready to investigate</b><p>{data.length} exception(s) are available. Run the investigation to inspect the strongest variance with an evidence-bounded explanation.</p></div></div>}</section></>}
function Evaluation({data,onOpen}){if(!data)return <Empty text="Evaluation data is loading…"/>;return <><PageTitle eyebrow="EVALUATION" title="Measure what the agent actually gets right" desc="No cherry-picking. Every settlement in the batch is counted."></PageTitle><div className="evalgrid"><div className="evalhero"><span>Settlement verification</span><strong>{data.verification_rate}%</strong><p>{data.correct_deterministic_matches} of {data.settlements_evaluated} deposits were deterministically matched to expected net settlement.</p><div className="bar"><i style={{width:`${data.verification_rate}%`}}></i></div></div><div className="evalcards"><div><span>Batch size</span><b>{data.batch_size}</b></div><div><span>Settlements evaluated</span><b>{data.settlements_evaluated}</b></div><div><span>Correct matches</span><b>{data.correct_deterministic_matches}</b></div><div><span>Exceptions detected</span><b>{data.exceptions_detected}</b></div></div></div><section className="panel full"><div className="sectionhead"><div><h2>Honest exception list</h2><p>These are not hidden behind the headline metric.</p></div></div>{data.exceptions.map(e=><ExceptionRow key={e.txn_id} e={e} onClick={()=>onOpen(e)}/>)}</section></>}
function Audit({items,onOpen}){
  return <><PageTitle eyebrow="AUDIT TRAIL" title="Evidence, not just answers" desc="A traceable record of what CashTrace observed, calculated and concluded."><span className="verifiedpill"><span className="dot"></span>{items.length} audit events</span></PageTitle><section className="panel audit">{items.map((x,i)=><AuditItem key={i} item={x} onOpen={onOpen}/>)}</section></>
}
function AuditItem({item,onOpen}){
  const I=item.type==='exception'?AlertTriangle:item.type==='source'?Activity:item.type==='verified'?ShieldCheck:FileSearch;
  const clickable=Boolean(item.txn_id && onOpen);
  return clickable ? <button className="audititem auditclick" onClick={()=>onOpen({txn_id:item.txn_id})}><div className="auditicon"><I size={17}/></div><div><div className="audititemtop"><b>{item.title}</b><ChevronRight size={14}/></div><small>{item.time}</small><p>{item.detail}</p></div></button> : <div className="audititem"><div className="auditicon"><I size={17}/></div><div><b>{item.title}</b><small>{item.time}</small><p>{item.detail}</p></div></div>
}
function Empty({text}){return <div className="empty">{text}</div>}
function Drawer({item,close}){const variance=Number(item.variance||0);const expected=Number(item.expected_net||0);const [running,setRunning]=useState(false);const [investigation,setInvestigation]=useState(null);const [error,setError]=useState('');const runInvestigation=async()=>{setRunning(true);setError('');try{setInvestigation(await api(`/api/investigations/${item.txn_id}`))}catch(e){setError(e.message||'Investigation failed')}finally{setRunning(false)}};return <div className="drawerwrap" onClick={close}><aside className="drawer" onClick={e=>e.stopPropagation()}><div className="drawerhead"><div><span className="eyebrow">INVESTIGATION</span><h2>{item.txn_id || item.id}</h2><small>{item.payout_id || 'No payout match'} · {item.channel || 'Unknown channel'}</small></div><button className="close" onClick={close}><X size={19}/></button></div><div className="drawerstatus"><div><span>Verdict</span><strong className={`verdict ${(item.verdict||'UNRESOLVED').toLowerCase()}`}>{item.verdict || 'UNRESOLVED'}</strong></div><div><span>Confidence</span><strong>{item.confidence ?? 0}%</strong></div></div><div className="trail"><h3>Money trail</h3><TrailRow label="Gross" value={item.gross!=null?money(item.gross):'—'}/><TrailRow label="Fees" value={item.fees!=null?signedMoney(-Math.abs(item.fees)):'—'}/><TrailRow label="Refunds / adjustments" value={item.refunds!=null?signedMoney(-Math.abs(item.refunds)):'—'}/><TrailRow label="Expected settlement" value={money(expected)}/><TrailRow label="Actual settlement" value={money(item.actual_deposit)} final/></div><div className="variance"><span>Variance</span><strong>{signedMoney(variance)}</strong><small>{item.variance_pct}% below expected · {item.severity} materiality</small></div><div className="finding"><div className="findingtitle"><Sparkles size={15}/> AI investigation</div><h3>{investigation?.summary ? 'Evidence-bounded finding' : (item.explanation||'Investigation not run').split('.')[0]}</h3><p>{investigation?.summary || item.explanation || 'Run the investigator to generate a bounded explanation from the evidence above.'}</p></div>{investigation&&<><div className="investigationblocks"><div><b>Likely causes</b>{(investigation.likely_causes||[]).map((c,i)=><div className="cause" key={i}><span>{c.status}</span><div><strong>{c.cause}</strong><small>{c.reason}</small></div></div>)}</div><div><b>Next steps</b>{(investigation.next_steps||[]).map((x,i)=><div className="step" key={i}><span>{i+1}</span><p>{x}</p></div>)}</div></div><div className="guardrail">✓ {investigation.guardrail}</div></>}{error&&<div className="drawererror">{error}</div>}<div className="evidence"><h3>Evidence used</h3>{(item.evidence||[]).map((x,i)=><div key={i}>✓ {x}</div>)}</div><div className="draweractions"><button className="secondary" onClick={close}>Close</button><button className="primary" onClick={runInvestigation} disabled={running}>{running?<><LoaderCircle size={15} className="spin"/> Investigating…</>:<><Sparkles size={15}/> {investigation?'Run again':'Run AI investigation'}</>}</button></div></aside></div>}
function TrailRow({label,value,final=false}){return <div className={final?'trailrow final':'trailrow'}><span>{label}</span><b>{value}</b></div>}

createRoot(document.getElementById('root')).render(<App/>);
