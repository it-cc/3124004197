const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../public/app.js'),'utf8');
function harness(fetch){let state;const context={console,fetch,URLSearchParams,FormData,AbortController,Date,setTimeout:()=>0,setInterval:()=>0,document:{visibilityState:'visible'},Vue:{ref:value=>({value}),reactive:value=>value,computed:fn=>({get value(){return fn();}}),nextTick:async()=>{},onMounted(){},createApp:app=>({mount(){state=app.setup();}})}};vm.runInNewContext(source,context);return state;}
const response=(data,status=200)=>({ok:status<400,status,json:async()=>data});

test('late private claims are not exposed after switching accounts',async()=>{
 let release;const state=harness(()=>new Promise(resolve=>release=resolve));state.user.value={id:1};
 const pending=state.loadClaims();state.user.value={id:2};release(response({claims:[{id:1,contact:'private-to-user-1'}]}));await pending;
 assert.equal(state.claims.value.length,0);assert.equal(state.user.value.id,2);
});

test('old unauthorized response does not log out a newly logged-in account',async()=>{
 let release;const state=harness(()=>new Promise(resolve=>release=resolve));state.user.value={id:1};
 const pending=state.loadClaims();state.user.value={id:2};release(response({detail:'old login expired'},401));await pending;
 assert.equal(state.user.value.id,2);
});

test('late own-items response does not enter another account',async()=>{
 let release;const state=harness(()=>new Promise(resolve=>release=resolve));state.user.value={id:1};
 const pending=state.setView('mine');state.user.value={id:2};release(response({items:[{id:1,owner_id:1}]}));await pending;
 assert.equal(state.ownItems.value.length,0);
});

test('stale search response does not replace the latest filter results',async()=>{
 const requests=[];const state=harness(()=>new Promise(resolve=>requests.push(resolve)));
 state.filters.q='first';const first=state.loadBoard();state.filters.q='second';const second=state.loadBoard();
 requests[1](response({items:[{id:2}],total:1}));await second;requests[0](response({items:[{id:1}],total:1}));await first;
 assert.equal(state.items.value[0].id,2);assert.equal(state.loading.value,false);
});

test('empty optional dates are omitted from search requests',async()=>{
 let url;const state=harness(async value=>{url=value;return response({items:[],total:0});});await state.loadBoard();
 assert(!url.includes('date_from=')&&!url.includes('date_to='));assert(url.includes('include_demo=true'));
});

test('same-account login also invalidates responses from its previous session',async()=>{
 let release;
 let first=true;
 const user={id:1,username:'same_user',nickname:'same',contact:'private'};
 const state=harness(async url=>{
  if(url==='/api/me/claims' && first){first=false;return await new Promise(resolve=>release=resolve);}
  if(url==='/api/auth/login')return response(user);
  if(url==='/api/meta')return response({categories:[],counts:{lost:0,found:0,returned:0}});
  if(url.startsWith('/api/items?'))return response({items:[],total:0});
  if(url==='/api/me/items')return response({items:[]});
  return response({claims:[]});
 });
 state.user.value=user;state.authDialog.value={close(){}};state.detailDialog.value={open:false};
 const pending=state.loadClaims();await new Promise(resolve=>setImmediate(resolve));
 state.authMode.value='login';state.auth.username='same_user';state.auth.password='password123';
 await state.submitAuth();release(response({detail:'expired old token'},401));await pending;
 assert.equal(state.user.value.id,1);
});
