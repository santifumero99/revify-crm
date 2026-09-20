const API='/api';
  let token=localStorage.getItem('revify_token')||'';
  let currentUser=null;
  let leads=[];
  let nextCursor=null;
  let currentLeadId=null;
  let priorityLead=null;
  let qty=1;
  let searchTimer=null;
  const PAGE_SIZE=50;
  const statusMeta={
    pending:['Pendiente','pending'],
    owner_absent:['No está el dueño','owner'],
    closed:['Local cerrado','closed'],
    follow_up:['Seguimiento','follow'],
    won:['Vendido','won'],
    lost:['No interesado','lost']
  };

  function money(n){return new Intl.NumberFormat('es-ES',{style:'currency',currency:'EUR',maximumFractionDigits:2}).format(Number(n||0))}
  function escapeHtml(v){return String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}
  function hideScreens(){document.querySelectorAll('.screen').forEach(x=>x.classList.remove('active'))}
  function setNav(name){document.querySelectorAll('.navbtn').forEach(x=>x.classList.toggle('active',x.dataset.nav===name))}
  function toast(msg){const t=document.getElementById('toast');t.textContent=msg;t.classList.add('show');clearTimeout(window.__t);window.__t=setTimeout(()=>t.classList.remove('show'),1600)}
  function showLogin(){hideScreens();document.getElementById('screen-login').classList.add('active');document.querySelector('.navbar').style.display='none'}
  function showAppNav(){document.querySelector('.navbar').style.display='grid'}
  function showHome(){hideScreens();showAppNav();document.getElementById('screen-home').classList.add('active');setNav('home');loadDashboard()}
  function showLeads(){hideScreens();showAppNav();document.getElementById('screen-leads').classList.add('active');setNav('leads');loadLeads(true)}
  function showCreate(){hideScreens();showAppNav();document.getElementById('screen-create').classList.add('active');setNav('create');setTimeout(()=>document.getElementById('newName')?.focus(),80)}
  function showMore(){hideScreens();showAppNav();document.getElementById('screen-more').classList.add('active');setNav('more')}
  function showSale(){if(!currentLeadId){toast('Abre un lead y pulsa Vender');showLeads();return}hideScreens();showAppNav();document.getElementById('screen-sale').classList.add('active');setNav('sale');hydrateSaleLead()}
  function pill(status){const m=statusMeta[status]||statusMeta.pending;return `<span class="status-pill ${m[1]}">${m[0]}</span>`}

  async function api(path,opts={}){
    const headers={'Content-Type':'application/json',...(opts.headers||{})};
    if(token) headers.Authorization='Bearer '+token;
    const res=await fetch(API+path,{...opts,headers});
    if(res.status===401){token='';localStorage.removeItem('revify_token');showLogin();throw new Error('Sesión caducada')}
    const data=await res.json().catch(()=>({}));
    if(!res.ok) throw new Error(data.detail||'Error de servidor');
    return data;
  }

  async function login(e){
    e.preventDefault();
    document.getElementById('loginError').textContent='';
    try{
      const data=await api('/login',{method:'POST',body:JSON.stringify({
        email:document.getElementById('loginEmail').value.trim(),
        password:document.getElementById('loginPassword').value
      })});
      token=data.access_token; localStorage.setItem('revify_token',token);
      currentUser=data.user;
      showHome();
    }catch(err){document.getElementById('loginError').textContent=err.message}
  }

  async function boot(){
    document.querySelector('.navbar').style.display='none';
    if(!token){showLogin();return}
    try{currentUser=await api('/me');showHome()}catch{showLogin()}
  }

  async function loadDashboard(){
    try{
      const m=await api('/metrics');
      document.getElementById('dash-visits').textContent=m.visits;
      document.getElementById('dash-demos').textContent=m.demos;
      document.getElementById('dash-sales').textContent=m.sales;
      document.getElementById('dash-revenue').textContent=money(m.revenue);
      const pct=Math.min(100,Math.round((m.sales/10)*100));
      document.getElementById('ring').style.setProperty('--val',pct);
      document.getElementById('ring-pct').textContent=pct+'%';
      document.getElementById('progress-text').textContent=m.sales+' de 10 ventas';
      priorityLead=m.priority_lead||null;
      const name=document.getElementById('priority-name');
      const address=document.getElementById('priority-address');
      const status=document.getElementById('priority-status');
      const avatar=document.getElementById('priority-avatar');
      if(priorityLead){
        name.textContent=priorityLead.name;
        address.textContent=(priorityLead.address||'Sin dirección')+(priorityLead.postal_code?' · '+priorityLead.postal_code:'');
        status.textContent=(statusMeta[priorityLead.status]||statusMeta.pending)[0];
        avatar.textContent=priorityLead.name.charAt(0).toUpperCase();
      }else{
        name.textContent='Sin tareas pendientes';
        address.textContent='Da de alta tu primer negocio';
        status.textContent='Todo al día';
        avatar.textContent='✓';
      }
    }catch(err){toast(err.message)}
  }

  function handleLeadSearch(){clearTimeout(searchTimer);searchTimer=setTimeout(()=>loadLeads(true),180)}
  async function loadLeads(reset=false){
    if(reset){leads=[];nextCursor=null}
    const q=(document.getElementById('leadSearch')?.value||'').trim();
    const params=new URLSearchParams({limit:String(PAGE_SIZE)});
    if(q) params.set('search',q);
    if(!reset && nextCursor) params.set('cursor',nextCursor);
    try{
      const data=await api('/leads?'+params.toString());
      if(reset) leads=data.items; else leads.push(...data.items);
      nextCursor=data.next_cursor||null;
      renderLeads(data.summary);
    }catch(err){toast(err.message)}
  }
  function loadMoreLeads(){if(nextCursor)loadLeads(false)}
  function renderLeads(summary={}){
    document.getElementById('sumTotal').textContent=summary.total??leads.length;
    document.getElementById('sumPending').textContent=summary.pending??0;
    document.getElementById('sumFollow').textContent=summary.follow_up??0;
    document.getElementById('sumWon').textContent=summary.won??0;
    document.getElementById('leadList').innerHTML=leads.map(x=>`<button class="lead-row" onclick="openLead(${x.id})"><span class="lead-avatar">${escapeHtml(x.name.charAt(0))}</span><span><b>${escapeHtml(x.name)}</b><small>${escapeHtml(x.business_type||'Sin categoría')}${x.business_subtype?` · ${escapeHtml(x.business_subtype)}`:''} · ${escapeHtml(x.address||'Sin dirección')}${x.postal_code?` · ${escapeHtml(x.postal_code)}`:''}</small><small>${escapeHtml(x.next_action||'')}</small></span><span class="lead-right">${pill(x.status)}<em>Ver ficha ›</em></span></button>`).join('')||'<div style="color:#c3d2e8;font-size:9px;padding:14px;text-align:center">No hay resultados.</div>';
    const more=document.getElementById('loadMoreLeads');
    more.style.display=nextCursor?'block':'none';
    if(nextCursor) more.textContent='Cargar 50 más';
  }

  async function openLead(id){
    try{
      const x=await api('/leads/'+id);
      currentLeadId=id;
      hideScreens();showAppNav();document.getElementById('screen-lead-detail').classList.add('active');setNav('leads');
      document.getElementById('leadDetail').innerHTML=`<div class="detail-card"><div class="detail-top"><span class="lead-avatar">${escapeHtml(x.name.charAt(0))}</span><div><h3>${escapeHtml(x.name)}</h3><p>${escapeHtml(x.address||'Sin dirección')}${x.postal_code?` · ${escapeHtml(x.postal_code)}`:''}</p>${pill(x.status)}</div></div><div class="detail-meta"><div><span>CATEGORÍA</span><b>${escapeHtml(x.business_type||'—')}</b></div><div><span>TIPO CONCRETO</span><b>${escapeHtml(x.business_subtype||'—')}</b></div><div><span>RESPONSABLE</span><b>${escapeHtml(x.owner_name||'—')}</b></div><div><span>TELÉFONO</span><b>${escapeHtml(x.phone||'—')}</b></div><div><span>CÓDIGO POSTAL</span><b>${escapeHtml(x.postal_code||'—')}</b></div><div><span>ESTADO</span><b>${(statusMeta[x.status]||statusMeta.pending)[0]}</b></div><div><span>PRÓXIMA ACCIÓN</span><b>${escapeHtml(x.next_action||'—')}</b></div></div><div class="detail-actions"><button onclick="cycleStatus(${x.id},'${x.status}')">Cambiar estado</button><button onclick="registerActivity(${x.id})">Registrar visita</button><button class="blue" onclick="currentLeadId=${x.id};showSale()">Vender</button></div></div>`;
    }catch(err){toast(err.message)}
  }

  async function cycleStatus(id,current){
    const order=['pending','owner_absent','closed','follow_up','won','lost'];
    const next=order[(order.indexOf(current)+1)%order.length];
    try{await api('/leads/'+id,{method:'PATCH',body:JSON.stringify({status:next})});await openLead(id);toast('Estado actualizado')}catch(err){toast(err.message)}
  }

  async function registerActivity(id){
    try{await api('/leads/'+id+'/activities',{method:'POST',body:JSON.stringify({activity_type:'visit',notes:''})});toast('Visita registrada');await loadDashboard()}catch(err){toast(err.message)}
  }

  async function saveLead(e){
    e.preventDefault();
    const payload={
      name:document.getElementById('newName').value.trim(),
      address:document.getElementById('newAddress').value.trim(),
      postal_code:document.getElementById('newPostalCode').value.replace(/\D/g,'').slice(0,5),
      business_type:document.getElementById('newBusinessType').value,
      business_subtype:document.getElementById('newBusinessSubtype').value.trim(),
      owner_name:document.getElementById('newOwner').value.trim(),
      phone:document.getElementById('newPhone').value.trim(),
      status:document.getElementById('newStatus').value
    };
    if(payload.postal_code.length!==5){toast('Código postal de 5 dígitos');return}
    try{await api('/leads',{method:'POST',body:JSON.stringify(payload)});e.target.reset();showLeads();toast('Lead guardado')}catch(err){toast(err.message)}
  }

  function sellPriorityLead(){
    if(!priorityLead){showCreate();return}
    currentLeadId=priorityLead.id;showSale();
  }

  async function hydrateSaleLead(){
    if(!currentLeadId)return;
    try{
      const x=await api('/leads/'+currentLeadId);
      document.getElementById('sale-name').textContent=x.name;
      document.getElementById('sale-address').textContent=(x.address||'Sin dirección')+(x.postal_code?' · '+x.postal_code:'');
      document.getElementById('sale-avatar').textContent=x.name.charAt(0).toUpperCase();
    }catch(err){toast(err.message)}
  }

  function calc(){
    const p=Math.max(.01,Number(document.getElementById('price').value||25));
    const total=qty*p;
    document.getElementById('qty').textContent=qty;
    document.getElementById('total').textContent=money(total);
    document.getElementById('collected').value=total.toFixed(2);
  }
  function changeQty(d){qty=Math.max(1,qty+d);calc()}
  function selectPay(el){document.querySelectorAll('[data-pay]').forEach(x=>{x.classList.remove('selected');const c=x.querySelector('.check');if(c)c.textContent=''});el.classList.add('selected');const c=el.querySelector('.check');if(c)c.textContent='✓'}
  function selectDelivery(el){el.parentElement.querySelectorAll('.seg').forEach(x=>{x.classList.remove('selected');const c=x.querySelector('.check');if(c)c.textContent=''});el.classList.add('selected');const c=el.querySelector('.check');if(c)c.textContent='✓'}
  function formatCollected(){}

  async function finishSale(){
    if(!currentLeadId){toast('Selecciona un lead');return}
    const p=Math.max(.01,Number(document.getElementById('price').value||25));
    const selected=document.querySelector('[data-pay].selected');
    const payment=selected?.dataset.pay||'cash';
    const delivered=document.querySelector('#screen-sale .seg-group:last-of-type .seg.selected')?.textContent.includes('Sí')??true;
    try{
      await api('/sales',{
        method:'POST',
        headers:{'Idempotency-Key':crypto.randomUUID()},
        body:JSON.stringify({lead_id:currentLeadId,quantity:qty,unit_price:p,payment_method:payment,delivered})
      });
      toast('Venta registrada correctamente');
      currentLeadId=null;qty=1;calc();showHome();
    }catch(err){toast(err.message)}
  }

  function confirmLogout(){
    if(confirm('¿Quieres cerrar sesión?')){
      token='';currentUser=null;localStorage.removeItem('revify_token');showLogin();
    }
  }

  calc();
  boot();