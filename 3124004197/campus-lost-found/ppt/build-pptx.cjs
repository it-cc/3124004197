const pptxgen = require('pptxgenjs');
const fs = require('node:fs');
const path = require('node:path');
const P = new pptxgen(); P.layout='LAYOUT_WIDE';
P.author='脉语团队';P.subject='软件工程团队选题与需求分析';P.title='寻回 · 校园失物找回助手';P.company='脉语团队';P.lang='zh-CN';
P.theme={headFontFace:'Microsoft YaHei',bodyFontFace:'Microsoft YaHei',lang:'zh-CN'};
const C={ink:'1A2E1F',paper:'F5F1E8',accent:'2E6B4F',muted:'5D665D',card:'EBEDE5',darkCard:'2D4333',mint:'A5CDB2',line:'C0C2B7'};
const N=JSON.parse(fs.readFileSync(path.join(__dirname,'讲稿数据.json'),'utf8'));
const SW=13.333333,SH=7.5,M=.62;
function txt(s,text,x,y,w,h,size=17,color=C.ink,bold=false,extra={}){s.addText(text,{x,y,w,h,fontFace:'Microsoft YaHei',fontSize:size,color,bold,margin:0,breakLine:false,valign:'top',paraSpaceAfterPt:4,...extra});}
function rect(s,x,y,w,h,color,r=true){s.addShape(r?P.ShapeType.roundRect:P.ShapeType.rect,{x,y,w,h,rectRadius:.08,fill:{color},line:{color,transparency:100},radius:.08});}
function base(i,dark=false){const s=P.addSlide();s.background={color:dark?C.ink:C.paper};s._dark=dark;s._fg=dark?C.paper:C.ink;s._muted=dark?C.mint:C.muted;
 txt(s,'脉语团队 / '+N[i].section,M,.25,10,.22,10.5,s._muted);txt(s,String(i+1).padStart(2,'0')+' / 10',11.4,.25,1.3,.22,10.5,s._muted,false,{align:'right'});
 txt(s,N[i].title,M,.76,12.08,.62,N[i].title.length>25?30:32,s._fg,true);
 txt(s,N[i].purpose,M,1.47,12.0,.39,15.5,s._muted);
 txt(s,'寻回 · 校园失物找回助手',M,7.04,9,.2,10.5,s._muted);txt(s,'软件工程选题与需求分析',9.5,7.04,3.2,.2,10.5,s._muted,false,{align:'right'});
 s.addNotes('建议讲述 '+Math.round(N[i].minutes*60)+' 秒\n本页目的：'+N[i].purpose+'\n\n讲述要点：\n'+N[i].talk.map((x,n)=>(n+1)+'. '+x).join('\n')+'\n\n转场：'+N[i].transition);
 return s;}
function card(s,title,body,x,y,w,h,size=16.5){rect(s,x,y,w,h,s._dark?C.darkCard:C.card);txt(s,title,x+.18,y+.15,w-.36,.38,20,s._fg,true);txt(s,body,x+.18,y+.65,w-.36,h-.8,size,s._fg);}
function note(s,text,y=6.15,h=.52){rect(s,M,y,12.08,h,s._dark?C.darkCard:C.card);txt(s,text,M+.18,y+.1,11.72,h-.16,14.5,s._fg);}
function fitPNG(file,x,y,w,h){const data=fs.readFileSync(file);const iw=data.readUInt32BE(16),ih=data.readUInt32BE(20);const scale=Math.min(w/iw,h/ih);const width=iw*scale,height=ih*scale;return{x:x+(w-width)/2,y:y+(h-height)/2,w:width,h:height};}
function image(s,name,x,y,w,h,caption){rect(s,x,y,w,h,C.paper);const img=path.join(__dirname,'images',name);s.addImage({path:img,...fitPNG(img,x+.08,y+.08,w-.16,h-.16)});if(caption)txt(s,caption,x,y+h+.1,w,.35,10.5,s._muted);}
function flow(s,steps,y=2.03,h=1.04){const gap=.16,w=(12.08-gap*4)/5;steps.forEach(([title,body],i)=>{const x=M+i*(w+gap);rect(s,x,y,w,h,s._dark?C.darkCard:C.card);txt(s,title,x+.13,y+.12,w-.26,.32,17,s._fg,true);txt(s,body,x+.13,y+.5,w-.26,h-.6,12.5,s._fg);});}
function table(s,headers,rows,x,y,widths,rowH=.73,size=15){let xx=x;headers.forEach((v,i)=>{rect(s,xx,y,widths[i],.47,s._dark?C.darkCard:'DDE5D8',false);txt(s,v,xx+.13,y+.1,widths[i]-.26,.28,size,s._fg,true);xx+=widths[i];});rows.forEach((row,n)=>{let xxx=x;row.forEach((v,i)=>{rect(s,xxx,y+.47+n*rowH,widths[i],rowH,s._dark?C.darkCard:C.card,false);txt(s,v,xxx+.13,y+.56+n*rowH,widths[i]-.26,rowH-.15,size,s._fg);xxx+=widths[i];});});}
let s;
// 1 Team and product, with actual assignment roles.
s=base(0,true);txt(s,'集中发布线索，用 AI 找候选，由双方核验归还。',M,2.10,11.9,.8,27,C.paper,true);
card(s,'蔡志冲 · 3124004197','后端、AI 接入、数据库与部署\n负责权限、匹配接口和运行环境。',M,3.28,5.85,1.6,17);
card(s,'林华杰 · 3124004213','前端、需求整理与测试\n负责发布、核验和咨询交互。',6.85,3.28,5.85,1.6,17);
note(s,'团队愿景：让校园里的失物线索得到回应，让同学的善意更容易转化为实际帮助。',5.3,.72);
txt(s,'Web 软件 / DeepSeek API / V0.3 / 2026.11.09',M,6.32,11.8,.3,12.5,C.mint);
// 2 Problem and product response.
s=base(1);card(s,'丢失者：线索分散','要翻不同群聊和公告；消息被覆盖后，难以持续检索。',M,2.07,5.85,1.68);
card(s,'拾物者：描述不统一','失主写“保温杯”，拾物者可能只写“蓝色水杯、白色盖子”。',6.85,2.07,5.85,1.68);
card(s,'双方：仅靠公开描述不够','同款物品可能相似，需要时间、地点和未公开特征进一步核对。',M,4.03,5.85,1.68);
card(s,'产品回应','集中发布与筛选 → 候选和理由 → 核验说明 → 人工确认归还。',6.85,4.03,5.85,1.68);
note(s,'以上是待验证的校园场景假设，不是已完成问卷或访谈的统计结论。',6.02,.58);
// 3 Users and requirement sources.
s=base(2);table(s,['用户','需要完成的任务','优先需求'],[['丢失者','登记物品，寻找拾物线索','发布、检索、AI 匹配、提交说明'],['拾物者','发布拾物，回应与核验认领','收到请求、核验、登记归还'],['浏览者','帮同学寻找或补充线索','公开浏览、筛选、提交线索']],M,2.04,[2.0,4.83,5.25],.67,16);
card(s,'调研现状','尚未提供真实访谈／问卷证据；代码测试和演示账号不能作为用户调研。',M,4.76,5.85,1.55,16);
card(s,'下一步验证','访谈有丢失／拾物经历的同学，了解渠道、最费时步骤、公开意愿与核验方式。',6.85,4.76,5.85,1.55,16);
// 4 Complete product backed by real screenshot.
s=base(3,true);[['账号与发布','登录、文字／照片与私密特征；本人记录可编辑和关闭。'],['检索与匹配','关键词、类别、日期和状态筛选；AI 比较公开线索。'],['认领与核验','提交、撤回、补充、审批；通过后向对方显示联系。'],['咨询与管理','持续问答，资料／密码修改，对话重置与数据保存。']].forEach(([t,b],i)=>card(s,t,b,M,2.02+i*1.13,3.65,1.03,14.5));
image(s,'04-board-focus.png',4.56,2.04,8.14,4.5,'真实程序界面；图中记录是演示数据，不是实际找回案例。');
// 5 Matching pipeline and genuine model output.
s=base(4);flow(s,[['检索池','≤150 条最新有效记录'],['规则预筛','特征、地点、日期；最多12条'],['DeepSeek','比较公开描述，生成理由'],['结果校验','ID 必须来自候选列表'],['输出线索','最多8条＋得分＋核对建议']],1.99,1.05);
card(s,'演示输入','寻物：蓝色保温杯\n拾物：图书馆拾得蓝色水杯\n\n共同特征：蓝色杯身、白色杯盖、小猫贴纸；结合地点与日期比较。',M,3.30,3.95,2.67,16.5);
image(s,'05-ai-matches.png',4.9,3.30,7.8,3.0,'实际 DeepSeek 输出：候选、理由与核对问题。');
note(s,'得分表示相关度，不是物主概率。真实与演示记录分开匹配。',6.50,.43);
// 6 Claim state and permission.
s=base(5);flow(s,[['发布信息','保留未公开特征'],['提交申请','说明只对双方可见'],['人工核验','仅发布者通过／拒绝'],['更新状态','可撤回、补充和重申'],['确认归还','通过后向对方显示联系']],1.99,1.04);
card(s,'避免旧证据误审批','申请说明修改后，核验页提交的旧版本会被拒绝；需刷新再检查。',M,3.32,4.45,1.38,16);
card(s,'信息按用途分层','公开描述用于寻找；私密特征用于人工核验；联系信息在通过后共享。',M,5.00,4.45,1.38,16);
image(s,'06-review-pending.png',5.37,3.31,7.33,1.29,'核验前：说明与发布者操作。');
image(s,'06-review-approved.png',5.37,5.10,7.33,1.29,'核验后：归还状态与双方联系；均为演示数据。');
// 7 Multi-turn consultation.
s=base(6,true);[['带着当前物品上下文','可询问搜索渠道、下一步和认领时应核对什么。'],['能连续追问','近期20轮问答；按用户＋物品在 SQLite 中隔离保存。'],['有失败与重置机制','失败不写入成功历史，问题可重试；只重置本人该物品问答。']].forEach(([t,b],i)=>card(s,t,b,M,2.05+i*1.35,3.90,1.21,15.2));
image(s,'07-chat-turns.png',4.87,2.06,7.83,4.3,'真实程序中的两轮问答，使用演示账号与演示记录。');
txt(s,'服务端不自动拼入联系／私密核验字段；用户主动咨询的文字会发送给模型。',M,6.5,12.0,.35,12.4,C.mint);
// 8 Testable requirements.
s=base(7);table(s,['核心需求','验收条件','验证'],[['发布与管理','非发布者不能编辑、删除或关闭记录','权限与输入'],['线索匹配','候选存在且当前有效；AI 失败明确回退规则','白名单、状态、降级'],['认领与联系','只有发布者审批，通过后向对方共享联系','双账号核验闭环'],['持续咨询','隔离用户／物品，失败不加入成功历史','问答、切换、重置'],['数据与图片','重启恢复数据；图文修改不半完成','容器、照片、备份']],M,2.04,[2.12,6.5,3.46],.70,15.4);
note(s,'学校 SSO、图片识别、短信、地图与自动归还，不列入首版验收承诺。',6.24,.56);
// 9 Editable architecture and data flow.
s=base(8,true);card(s,'Vue 前端','公告板、发布、核验、咨询；显示加载、空结果和错误。',M,2.08,5.95,1.05,16);
txt(s,'↓',3.3,3.16,.4,.25,18,C.mint,false,{align:'center'});
card(s,'FastAPI','会话认证、资源授权、字段校验、图片重编码、状态事务与 AI 接口。',M,3.54,5.95,1.22,16);
card(s,'SQLite ＋文件','用户、物品、请求、会话、问答与照片保存。',M,5.03,2.84,1.36,15);
card(s,'DeepSeek API','公开候选比较与近期对话；不负责批准或归还。',3.74,5.03,2.83,1.36,15);
[['职责分工','身份、权限和状态由程序校验；模型输出不能越过用户权限。'],['数据发送边界','匹配发送公开文字、地点和日期；咨询附近期问答。照片供人比对。'],['运行与恢复','一键启动，Docker 持久卷，一致备份；密钥在服务端。']].forEach(([t,b],i)=>card(s,t,b,6.91,2.08+i*1.43,5.79,1.25,16));
// 10 Measured outcomes and clear plan.
s=base(9);card(s,'已完成并验证','发布、筛选、AI 匹配、认领核验和咨询。\n资料／密码、照片编辑、撤回与补充申请。\n22 项后端＋6 项前端状态测试通过。\n真实 API、双账号流程、容器重启与备份。',M,2.12,5.85,3.32,17);
card(s,'还需要完成','真实访谈／问卷，确认需求与使用价值。\n团队合照和成员个人风采。\n服务器、域名、HTTPS 与外部访问验收。\n根据实际用户反馈调整检索与核验。',6.85,2.12,5.85,3.32,17);
note(s,'团队目标：让校园线索得到回应，让物品更容易回到主人身边。',5.91,.63);
txt(s,'测试证明软件流程，不代表真实找回率。本地／容器可运行，不等于公网已上线。',M,6.67,12.0,.22,11.4,C.muted);
const output=path.join(__dirname,'寻回_团队选题与需求分析.pptx');P.writeFile({fileName:output}).then(()=>console.log(output));
