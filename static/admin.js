const API='/api';
let token=localStorage.getItem('revify_token')||'';
let analytics={postal_codes:[],postal_directory:[],categories:[],reps:[],statuses:[],daily:[],attention:[],recent:[],summary:{}};
let reps=[];
let adminLeadCursor=null;
let adminLeadTimer=null;
let visibleBusinesses=[];

function money(n){return new Intl.NumberFormat('es-ES',{style:'currency',currency:'EUR'}).format(Number(n||0))}
function num(n){return new Intl.NumberFormat('es-ES').format(Number(n||0))}
function pct(n){return Number(n||0).toFixed(1).replace('.0','')+'%'}
function esc(v){return String(v==null?'':v).replace(/[&<>'"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]})}
function dateText(v){if(!v)return '—';try{return new Date(v).toLocaleString('es-ES',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})}catch(e){return v}}
function statusLabel(s){return ({pending:'Pendiente',owner_absent:'No está el dueño',closed:'Local cerrado',follow_up:'Seguimiento',won:'Vendido',lost:'No interesado'})[s]||s}
function postalInfo(cp){
  const code=String(cp||'').trim();
  return (analytics.postal_directory||[]).find(function(x){return x.postal_code===code})||{postal_code:code,zone_label:'Fuera del directorio Barcelona',zone_short:'Fuera de Barcelona / sin zona'};
}
function updatePostalHint(){
  const input=document.getElementById('fPostal');const hint=document.getElementById('fPostalHint');
  if(!input||!hint)return;
  const cp=input.value.trim();
  if(!cp){hint.textContent='Escribe un CP para ver su barrio/zona.';hint.className='';return}
  const info=postalInfo(cp);
  hint.textContent=cp.length===5?info.zone_label:'Completa los 5 dígitos del CP';
  hint.className=cp.length===5?'resolved':'';
}
function eventLabel(s){return ({lead_created:'Lead creado',lead_updated:'Lead actualizado',activity_created:'Actividad registrada',sale_created:'Venta registrada',commercial_created:'Comercial creado',commercial_password_reset:'Contraseña restablecida',commercial_access_changed:'Acceso de comercial modificado',password_changed:'Contraseña cambiada'})[s]||s.replaceAll('_',' ')}

async function req(path,opts){
  opts=opts||{};
  const headers=Object.assign({'Content-Type':'application/json'},opts.headers||{});
  if(token)headers.Authorization='Bearer '+token;
  const r=await fetch(API+path,Object.assign({},opts,{headers:headers}));
  const data=await r.json().catch(function(){return {}});
  if(r.status===401){localStorage.removeItem('revify_token');token='';showLogin();throw new Error(data.detail||'Sesión no válida')}
  if(!r.ok)throw new Error(data.detail||'Error de servidor');
  return data;
}

function showLogin(){document.getElementById('loginView').classList.remove('hidden');document.getElementById('adminView').classList.add('hidden')}
function showAdmin(){document.getElementById('loginView').classList.add('hidden');document.getElementById('adminView').classList.remove('hidden')}
function adminLogout(){localStorage.removeItem('revify_token');token='';showLogin()}

async function adminLogin(e){
  e.preventDefault();
  const err=document.getElementById('loginError');err.textContent='';
  try{
    const login=await fetch(API+'/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:document.getElementById('adminEmail').value.trim(),password:document.getElementById('adminPassword').value})});
    const data=await login.json().catch(function(){return {}});
    if(!login.ok)throw new Error(data.detail||'Email o contraseña incorrectos');
    token=data.access_token;localStorage.setItem('revify_token',token);
    const me=await req('/admin/me');document.getElementById('adminIdentity').textContent=me.email;
    showAdmin();await loadEverything();
  }catch(ex){err.textContent=ex.message;localStorage.removeItem('revify_token');token=''}
}
async function boot(){
  if(!token){showLogin();return}
  try{const me=await req('/admin/me');document.getElementById('adminIdentity').textContent=me.email;showAdmin();await loadEverything()}
  catch(ex){showLogin()}
}

function showTab(name){
  document.querySelectorAll('.tab').forEach(function(x){x.classList.add('hidden')});
  document.getElementById('tab-'+name).classList.remove('hidden');
  document.querySelectorAll('.nav').forEach(function(x){x.classList.toggle('active',x.dataset.tab===name)});
  const titles={
    dashboard:['Dashboard','Visión global de Revify'],
    postal:['Zonas y códigos postales','Rendimiento geográfico de la cartera'],
    categories:['Categorías','Rendimiento por tipo de comercio'],
    team:['Comerciales','Actividad, resultado y accesos'],
    leads:['Negocios','Detalle negocio a negocio'],
    activity:['Actividad','Últimos movimientos registrados'],
    security:['Seguridad','Tu acceso de administrador']
  };
  document.getElementById('pageTitle').textContent=titles[name][0];
  document.getElementById('pageSubtitle').textContent=titles[name][1];
  if(name==='leads')loadAdminLeads(true);
}

async function loadEverything(){await loadAnalytics();await loadAdminLeads(true)}

async function loadAnalytics(){
  const days=document.getElementById('periodSelect').value||'30';
  const postal=document.getElementById('postalSegment').value||'';
  const rep=document.getElementById('globalRep')?.value||'';
  const params=new URLSearchParams({days:days});
  if(postal)params.set('postal_code',postal);
  if(rep)params.set('assigned_user_id',rep);
  analytics=await req('/admin/analytics?'+params.toString());
  reps=analytics.reps||[];
  renderGlobalRep();
  renderPostalSegment();
  updatePostalHint();
  renderDashboard();renderCategoryKpis();renderPostalTable();renderCategoryTable();renderTeam();renderActivity();renderRepFilters();renderTerritory();
  if(document.getElementById('tab-leads')&&!document.getElementById('tab-leads').classList.contains('hidden'))loadAdminLeads(true);
}

function renderGlobalRep(){
  const sel=document.getElementById('globalRep');if(!sel)return;
  const current=String((analytics.segment&&analytics.segment.assigned_user_id)||sel.value||'');
  sel.innerHTML='<option value="">Todo el equipo</option>'+(reps||[]).filter(function(r){return r.role!=='admin'}).map(function(r){return '<option value="'+r.id+'">'+esc(r.email)+'</option>'}).join('');
  sel.value=current;
}
function renderPostalSegment(){
  const sel=document.getElementById('postalSegment');
  const current=(analytics.segment&&analytics.segment.postal_code)||sel.value||'';
  const options=(analytics.available_postal_codes||[]).map(function(cp){const z=postalInfo(cp);return '<option value="'+esc(cp)+'">'+esc(cp)+' · '+esc(z.zone_short)+'</option>'}).join('');
  sel.innerHTML='<option value="">Todos los CP / zonas</option>'+options;
  sel.value=current;
}
function renderCategoryKpis(){
  const s=analytics.summary||{};
  document.getElementById('catKLeads').textContent=num(s.leads_total);
  document.getElementById('catKWon').textContent=num(s.won_total);
  document.getElementById('catKVisits').textContent=num(s.visits);
  document.getElementById('catKUnits').textContent=num(s.units);
  document.getElementById('catKConv').textContent=pct(s.portfolio_conversion_pct);
  document.getElementById('catKRevenue').textContent=money(s.revenue);
}
function deltaText(key){
  const d=analytics.comparison&&analytics.comparison.delta_pct?analytics.comparison.delta_pct[key]:null;
  if(d===null||d===undefined)return '';
  const sign=d>0?'+':'';
  return ' · '+sign+d.toFixed(1).replace('.0','')+'% vs anterior';
}
function renderDashboard(){
  const s=analytics.summary||{};
  document.getElementById('kLeads').textContent=num(s.leads_total);
  document.getElementById('kNewLeads').textContent=num(s.new_leads)+' nuevos'+deltaText('new_leads');
  document.getElementById('kRevenue').textContent=money(s.revenue);
  document.getElementById('kUnits').textContent=num(s.units)+' NFC vendidos'+(deltaText('revenue')||'');
  document.getElementById('kSales').textContent=num(s.sales);
  document.getElementById('kAvgTicket').textContent='Ticket '+money(s.avg_ticket)+(deltaText('sales')||'');
  document.getElementById('kPortfolioConversion').textContent=pct(s.portfolio_conversion_pct);
  document.getElementById('kVisits').textContent=num(s.visits);
  document.getElementById('kSalePerVisit').textContent=pct(s.sale_per_visit_pct)+' venta / visita'+(deltaText('visits')||'');
  document.getElementById('kDemos').textContent=num(s.demos);
  document.getElementById('kFollowups').textContent=num(s.followups)+' seguimientos';
  document.getElementById('kRevenuePerVisit').textContent=money(s.revenue_per_visit);
  document.getElementById('kUsers').textContent=num(s.active_users);
  document.getElementById('kOpenDeals').textContent=num(s.open_deals);
  document.getElementById('kFollowupsToday').textContent=num(s.followups_today);
  document.getElementById('kOverdue').textContent=num(s.overdue_followups);
  document.getElementById('kStale').textContent=num(s.stale_active_leads);
  document.getElementById('avgOpenAge').textContent=(s.avg_open_age_days||0)+' días';
  document.getElementById('qWinRate').textContent=pct(s.decision_win_rate_pct);
  document.getElementById('qDaysToSale').textContent=Number(s.avg_days_to_sale||0).toFixed(1).replace('.0','');
  document.getElementById('qFollowScheduled').textContent=pct(s.followup_scheduled_pct);
  document.getElementById('qFollowOverdue').textContent=pct(s.followup_overdue_pct);
  document.getElementById('qCoverage').textContent=pct(s.territory_coverage_pct);
  document.getElementById('qCoverageCount').textContent=num(s.covered_postal_codes)+' / '+num(s.territory_total_postal_codes)+' CP';
  document.getElementById('qRevenueVisit').textContent=money(s.revenue_per_visit);
  renderAttention();
  renderInsights();
  renderPipelineAging();

  const total=Math.max(1,s.leads_total||0);
  document.getElementById('statusFunnel').innerHTML=(analytics.statuses||[]).map(function(x){
    const w=Math.max(4,(x.count/total)*100);
    return '<div class="funnel-row"><div><b>'+esc(x.label)+'</b><span>'+num(x.count)+' · '+pct(x.pct)+'</span></div><div class="funnel-bar"><i style="width:'+w+'%"></i></div></div>';
  }).join('')||'<p class="empty">Aún no hay negocios.</p>';

  const days=(analytics.daily||[]).slice(-14);
  const maxRevenue=Math.max.apply(null,[1].concat(days.map(function(x){return x.revenue||0})));
  document.getElementById('dailyTrend').innerHTML=days.map(function(x){
    return '<div class="trend-row"><span>'+x.date.slice(5)+'</span><div class="trend-bar"><i style="width:'+Math.max(2,(x.revenue/maxRevenue)*100)+'%"></i></div><small>L '+x.leads+' · V '+x.visits+' · ✓ '+x.sales+'</small><b>'+money(x.revenue)+'</b></div>';
  }).join('')||'<p class="empty">Sin actividad todavía.</p>';

  const globalRep=document.getElementById('globalRep')?.value||'';
  const repRows=(analytics.reps||[]).filter(function(r){return r.role!=='admin'&&(!globalRep||String(r.id)===String(globalRep))});
  document.getElementById('repPerformance').innerHTML=repRows.map(repRow).join('')||'<tr><td colspan="15">Sin datos para este segmento.</td></tr>';
  renderPostalRanking();
  renderMiniRanking('categoryTop',analytics.categories||[],'category');
}
function renderPostalRanking(){
  const rows=(analytics.postal_codes||[]).slice(0,6);
  const max=Math.max.apply(null,[1].concat(rows.map(function(x){return x.revenue||0})));
  document.getElementById('postalTop').innerHTML=rows.map(function(x){
    return '<div class="rank-row"><div><b>'+esc(x.postal_code)+' · '+esc(x.zone_short||postalInfo(x.postal_code).zone_short)+'</b><small>'+num(x.leads)+' negocios · '+num(x.sales)+' ventas</small></div><div class="rank-meter"><i style="width:'+Math.max(4,(x.revenue/max)*100)+'%"></i></div><strong>'+money(x.revenue)+'</strong></div>';
  }).join('')||'<p class="empty">Aún no hay datos.</p>';
}
function renderAttention(){
  const box=document.getElementById('attentionList');if(!box)return;
  const rows=analytics.attention||[];
  box.innerHTML=rows.map(function(x){
    const when=x.reason==='Seguimiento vencido'?(x.follow_up_at?'Programado '+dateText(x.follow_up_at):'Seguimiento pendiente'):'Último movimiento '+dateText(x.updated_at);
    return '<button class="attention-row" data-name="'+esc(x.name)+'" onclick="focusAttentionLead(this.dataset.name)"><span class="attention-flag '+(x.reason==='Seguimiento vencido'?'overdue':'stale')+'"></span><span><b>'+esc(x.name)+'</b><small>'+esc(x.postal_code)+' · '+esc(x.zone_short)+' · '+esc(x.rep_email)+'</small></span><span><b>'+esc(x.reason)+'</b><small>'+esc(when)+'</small></span><em>›</em></button>';
  }).join('')||'<div class="attention-empty">No hay oportunidades pendientes de atención especial.</div>';
}
function focusAttentionLead(name){
  showTab('leads');
  const search=document.getElementById('fSearch');
  if(search){search.value=name;loadAdminLeads(true)}
}
function renderInsights(){
  const box=document.getElementById('smartInsights');if(!box)return;
  const rows=analytics.insights||[];
  box.innerHTML=rows.map(function(x){
    return '<article class="insight-card '+esc(x.level||'info')+'"><span class="insight-dot"></span><div><b>'+esc(x.title)+'</b><p>'+esc(x.body)+'</p></div></article>';
  }).join('')||'<div class="attention-empty">Todavía no hay suficiente actividad para generar lecturas útiles.</div>';
}
function renderPipelineAging(){
  const box=document.getElementById('pipelineAging');if(!box)return;
  const a=analytics.pipeline_aging||{};
  const rows=[['0–2 días',a['0_2']||0],['3–7 días',a['3_7']||0],['8–14 días',a['8_14']||0],['15+ días',a['15_plus']||0]];
  const max=Math.max.apply(null,[1].concat(rows.map(function(x){return x[1]})));
  box.innerHTML=rows.map(function(x,i){
    const cls=i>=3?'old':i===2?'warm':'';
    return '<div class="aging-row '+cls+'"><div><b>'+x[0]+'</b><span>'+num(x[1])+' deals</span></div><div class="aging-meter"><i style="width:'+Math.max(3,(x[1]/max)*100)+'%"></i></div></div>';
  }).join('');
}
function renderTerritory(){
  const s=analytics.summary||{};
  const pctv=Math.max(0,Math.min(100,Number(s.territory_coverage_pct||0)));
  const p=document.getElementById('postalCoveragePct');if(p)p.textContent=pct(pctv);
  const b=document.getElementById('postalCoverageBar');if(b)b.style.width=pctv+'%';
  const t=document.getElementById('postalCoverageText');if(t)t.textContent=num(s.covered_postal_codes)+' de '+num(s.territory_total_postal_codes)+' códigos postales con deals.';
  const box=document.getElementById('whitespaceList');
  if(box)box.innerHTML=(analytics.whitespace||[]).slice(0,12).map(function(x){return '<button type="button"><b>'+esc(x.postal_code)+'</b><span>'+esc(x.zone_short)+'</span></button>'}).join('')||'<div class="attention-empty">Toda la cobertura postal del directorio ya tiene actividad.</div>';
}
function renderMiniRanking(id,rows,key){
  const top=rows.slice(0,6);
  const max=Math.max.apply(null,[1].concat(top.map(function(x){return x.revenue||0})));
  document.getElementById(id).innerHTML=top.map(function(x){
    return '<div class="rank-row"><div><b>'+esc(x[key])+'</b><small>'+num(x.leads)+' negocios · '+num(x.sales)+' ventas</small></div><div class="rank-meter"><i style="width:'+Math.max(4,(x.revenue/max)*100)+'%"></i></div><strong>'+money(x.revenue)+'</strong></div>';
  }).join('')||'<p class="empty">Aún no hay datos.</p>';
}

function metricCells(x){
  return '<td>'+num(x.leads)+'</td><td>'+num(x.won)+'</td><td>'+num(x.visits)+'</td><td>'+num(x.demos)+'</td><td>'+num(x.followups)+'</td><td>'+num(x.sales)+'</td><td>'+num(x.units)+'</td><td>'+pct(x.conversion_pct)+'</td><td>'+pct(x.sale_per_visit_pct)+'</td><td>'+money(x.avg_ticket)+'</td><td>'+money(x.revenue_per_lead)+'</td><td><b>'+money(x.revenue)+'</b></td>';
}
function renderPostalTable(){
  const q=(document.getElementById('postalSearch')?document.getElementById('postalSearch').value:'').trim().toLowerCase();
  const rows=(analytics.postal_codes||[]).filter(function(x){return !q||String(x.postal_code).toLowerCase().includes(q)||String(x.zone_label||'').toLowerCase().includes(q)});
  document.getElementById('postalTable').innerHTML=rows.map(function(x){return '<tr><td><b>'+esc(x.postal_code)+'</b></td><td><b>'+esc(x.zone_short||postalInfo(x.postal_code).zone_short)+'</b><small class="subline zone-full">'+esc(x.zone_label||postalInfo(x.postal_code).zone_label)+'</small></td>'+metricCells(x)+'</tr>'}).join('')||'<tr><td colspan="14">Sin datos.</td></tr>';
}
function renderCategoryTable(){
  const q=(document.getElementById('categorySearch')?document.getElementById('categorySearch').value:'').trim().toLowerCase();
  const rows=(analytics.categories||[]).filter(function(x){return !q||String(x.category).toLowerCase().includes(q)});
  document.getElementById('categoryTable').innerHTML=rows.map(function(x){
    return '<tr>'+
      '<td><b>'+esc(x.category)+'</b></td>'+
      '<td><span class="metric-chip m-blue">'+num(x.leads)+'</span></td>'+
      '<td><span class="metric-chip m-green">'+num(x.won)+'</span></td>'+
      '<td><span class="metric-chip m-purple">'+num(x.visits)+'</span></td>'+
      '<td><span class="metric-chip m-amber">'+num(x.units)+'</span></td>'+
      '<td><span class="metric-chip m-cyan">'+pct(x.conversion_pct)+'</span></td>'+
      '<td><span class="metric-chip m-slate">'+money(x.avg_ticket)+'</span></td>'+
      '<td><span class="metric-chip m-rose">'+money(x.revenue_per_lead)+'</span></td>'+
      '<td><span class="metric-chip m-navy">'+money(x.revenue)+'</span></td>'+
    '</tr>';
  }).join('')||'<tr><td colspan="9">Sin datos.</td></tr>';
}
function repRow(r){
  return '<tr><td><b>'+esc(r.email)+'</b><small class="subline">'+esc(r.role)+'</small></td><td>'+num(r.leads)+'</td><td>'+num(r.open_leads)+'</td><td>'+num(r.won)+'</td><td>'+num(r.visits)+'</td><td>'+num(r.demos)+'</td><td>'+num(r.followups)+'</td><td><span class="'+(r.overdue_followups?'risk-num':'')+'">'+num(r.overdue_followups)+'</span></td><td>'+num(r.sales)+'</td><td>'+num(r.units)+'</td><td>'+pct(r.conversion_pct)+'</td><td>'+pct(r.sale_per_visit_pct)+'</td><td>'+money(r.avg_ticket)+'</td><td><b>'+money(r.revenue)+'</b></td><td>'+dateText(r.last_activity_at)+'</td></tr>';
}
function renderTeam(){
  document.getElementById('teamTable').innerHTML=(analytics.reps||[]).map(function(r){
    let buttons='';
    if(r.role!=='admin'){
      buttons='<button data-email="'+esc(r.email)+'" onclick="resetRepPassword('+r.id+',this.dataset.email)">Contraseña</button><button class="'+(r.is_active?'danger':'')+'" onclick="toggleRep('+r.id+','+(!r.is_active)+')">'+(r.is_active?'Pausar':'Activar')+'</button>';
    }
    return '<tr><td><b>'+esc(r.email)+'</b></td><td>'+esc(r.role)+'</td><td><span class="status '+(r.is_active?'on':'off')+'">'+(r.is_active?'Activo':'Pausado')+'</span></td><td>'+num(r.leads)+'</td><td>'+num(r.open_leads)+'</td><td>'+num(r.won)+'</td><td>'+num(r.visits)+'</td><td>'+num(r.demos)+'</td><td>'+num(r.followups)+'</td><td><span class="'+(r.overdue_followups?'risk-num':'')+'">'+num(r.overdue_followups)+'</span></td><td>'+num(r.sales)+'</td><td>'+num(r.units)+'</td><td>'+pct(r.conversion_pct)+'</td><td>'+money(r.avg_ticket)+'</td><td><b>'+money(r.revenue)+'</b></td><td>'+dateText(r.last_activity_at)+'</td><td><div class="actions">'+buttons+'</div></td></tr>';
  }).join('');
}
function renderActivity(){
  document.getElementById('activityFeed').innerHTML=(analytics.recent||[]).map(function(x){
    return '<div class="activity-item"><div class="activity-dot"></div><div><b>'+esc(eventLabel(x.event_type))+'</b><p>'+esc(x.lead_name||'Sistema')+' · '+esc(x.user_email)+'</p></div><time>'+dateText(x.created_at)+'</time></div>';
  }).join('')||'<p class="empty">Aún no hay actividad.</p>';
}
function renderRepFilters(){
  const sel=document.getElementById('fRep');const global=document.getElementById('globalRep')?.value||'';const current=global||sel.value;
  sel.innerHTML='<option value="">Todos los comerciales</option>'+reps.filter(function(r){return r.role!=='admin'}).map(function(r){return '<option value="'+r.id+'">'+esc(r.email)+'</option>'}).join('');
  sel.value=current;
}

function debouncedAdminLeads(){clearTimeout(adminLeadTimer);adminLeadTimer=setTimeout(function(){loadAdminLeads(true)},180)}
async function loadAdminLeads(reset){
  if(reset)adminLeadCursor=null;
  const p=new URLSearchParams({limit:'50'});
  const search=document.getElementById('fSearch').value.trim();
  const postal=document.getElementById('fPostal').value.trim()||document.getElementById('postalSegment').value||'';
  const rep=document.getElementById('fRep').value;
  const status=document.getElementById('fStatus').value;
  const cat=document.getElementById('fCategory').value;
  if(search)p.set('search',search);if(postal)p.set('postal_code',postal);if(rep)p.set('assigned_user_id',rep);if(status)p.set('status',status);if(cat)p.set('business_type',cat);if(!reset&&adminLeadCursor)p.set('cursor',adminLeadCursor);
  const data=await req('/admin/leads?'+p.toString());adminLeadCursor=data.next_cursor||null;
  if(reset)visibleBusinesses=data.items.slice();else visibleBusinesses=visibleBusinesses.concat(data.items);
  document.getElementById('leadCountLabel').textContent=num(data.total_filtered)+' negocios con los filtros actuales.';
  const html=data.items.map(function(x){
    const next=x.follow_up_at?'Seguimiento '+dateText(x.follow_up_at):(x.next_action||'—');
    return '<tr><td><b>'+esc(x.name)+'</b><small class="subline">'+esc(x.address||'Sin dirección')+'</small></td><td><b>'+esc(x.postal_code)+'</b></td><td><b>'+esc(x.zone_short||postalInfo(x.postal_code).zone_short)+'</b><small class="subline zone-full">'+esc(x.zone_label||postalInfo(x.postal_code).zone_label)+'</small></td><td>'+esc(x.business_type)+'<small class="subline">'+esc(x.business_subtype||'—')+'</small></td><td>'+esc(x.rep_email||'Sin asignar')+'</td><td><span class="badge">'+esc(statusLabel(x.status))+'</span></td><td>'+num(x.visits)+'</td><td>'+num(x.demos)+'</td><td>'+num(x.sales)+'</td><td>'+num(x.units)+'</td><td>'+money(x.avg_ticket)+'</td><td><b>'+money(x.revenue)+'</b></td><td>'+esc(x.owner_name||'—')+'<small class="subline">'+esc(x.phone||'')+'</small></td><td>'+esc(next)+'</td><td>'+dateText(x.updated_at)+'</td></tr>';
  }).join('');
  const body=document.getElementById('businessTable');
  if(reset)body.innerHTML=html||'<tr><td colspan="15">No hay negocios con estos filtros.</td></tr>';else body.insertAdjacentHTML('beforeend',html);
  document.getElementById('adminLoadMore').classList.toggle('hidden',!adminLeadCursor);
}
function clearLeadFilters(){
  document.getElementById('fSearch').value='';
  document.getElementById('fPostal').value='';
  document.getElementById('fStatus').value='';
  document.getElementById('fCategory').value='';
  document.getElementById('fRep').value=document.getElementById('globalRep')?.value||'';
  updatePostalHint();
  loadAdminLeads(true);
}
function csvCell(v){
  const s=String(v==null?'':v).replaceAll('"','""');
  return '"'+s+'"';
}
function exportVisibleBusinesses(){
  if(!visibleBusinesses.length){alert('No hay negocios visibles para exportar.');return}
  const head=['Negocio','Dirección','CP','Barrio / zona','Categoría','Tipo','Comercial','Estado','Visitas','Demos','Ventas','Unidades','Ticket','Facturación','Contacto','Teléfono','Próxima acción','Actualizado'];
  const rows=visibleBusinesses.map(function(x){
    const next=x.follow_up_at?'Seguimiento '+dateText(x.follow_up_at):(x.next_action||'');
    return [x.name,x.address,x.postal_code,x.zone_label||x.zone_short,x.business_type,x.business_subtype,x.rep_email,statusLabel(x.status),x.visits,x.demos,x.sales,x.units,x.avg_ticket,x.revenue,x.owner_name,x.phone,next,dateText(x.updated_at)];
  });
  const csv='\uFEFF'+[head].concat(rows).map(function(r){return r.map(csvCell).join(';')}).join('\n');
  const blob=new Blob([csv],{type:'text/csv;charset=utf-8;'});
  const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='revify-negocios-'+new Date().toISOString().slice(0,10)+'.csv';document.body.appendChild(a);a.click();a.remove();setTimeout(function(){URL.revokeObjectURL(a.href)},500);
}

function openCreateCommercial(){
  document.getElementById('commercialModal').classList.remove('hidden');document.getElementById('createCommercialMsg').textContent='';document.getElementById('commercialEmail').value='';generateCommercialPassword();setTimeout(function(){document.getElementById('commercialEmail').focus()},50)
}
function closeCreateCommercial(){document.getElementById('commercialModal').classList.add('hidden')}
function generateCommercialPassword(){
  const chars='ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@$%';const arr=new Uint32Array(18);crypto.getRandomValues(arr);document.getElementById('commercialPassword').value=Array.from(arr,function(x){return chars[x%chars.length]}).join('')
}
async function createCommercial(e){
  e.preventDefault();
  const email=document.getElementById('commercialEmail').value.trim();const password=document.getElementById('commercialPassword').value;const msg=document.getElementById('createCommercialMsg');msg.textContent='';
  try{
    await req('/admin/users',{method:'POST',body:JSON.stringify({email:email,temporary_password:password})});closeCreateCommercial();
    const box=document.getElementById('credentialBox');box.innerHTML='<b>Acceso creado correctamente</b>Comparte estas credenciales con el comercial.<code>Email: '+esc(email)+'<br>Contraseña temporal: '+esc(password)+'<br>CRM: https://revify-web-production.up.railway.app</code>';box.classList.remove('hidden');showTab('team');await loadAnalytics();
  }catch(ex){msg.textContent=ex.message}
}
async function toggleRep(id,isActive){
  try{await req('/admin/users/'+id+'/active',{method:'PATCH',body:JSON.stringify({is_active:isActive})});await loadAnalytics()}catch(ex){alert(ex.message)}
}
async function resetRepPassword(id,email){
  const p=prompt('Nueva contraseña temporal para '+email+' (mínimo 10 caracteres):');if(!p)return;if(p.length<10){alert('Debe tener al menos 10 caracteres.');return}
  try{await req('/admin/users/'+id+'/reset-password',{method:'POST',body:JSON.stringify({new_password:p})});const box=document.getElementById('credentialBox');box.innerHTML='<b>Contraseña restablecida</b><code>Email: '+esc(email)+'<br>Nueva contraseña temporal: '+esc(p)+'</code>';box.classList.remove('hidden')}catch(ex){alert(ex.message)}
}
async function changeMyPassword(e){
  e.preventDefault();const current=document.getElementById('currentPass').value;const next=document.getElementById('newPass').value;const next2=document.getElementById('newPass2').value;const msg=document.getElementById('passwordMsg');
  if(next!==next2){msg.textContent='Las contraseñas nuevas no coinciden.';return}
  try{await req('/account/password',{method:'POST',body:JSON.stringify({current_password:current,new_password:next})});msg.style.color='#0b7d51';msg.textContent='Contraseña cambiada correctamente.';e.target.reset()}
  catch(ex){msg.style.color='#d64555';msg.textContent=ex.message}
}
boot();