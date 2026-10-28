'use strict';
// Design prototype only. No network, clipboard API, native bridge or real data.
const KEY='clawboard-proposal-20261025-v1';
const defaults={design:'a',dark:false,narrow:false,source:false,size:false,dense:false,tab:'all',kind:'all',q:'',listening:true,projectName:'给桌面工具做一次设计升级',projectNext:'先比较三套界面，选择一套视觉基调。',projectNote:'保留小面板的效率；整理时才展开工作台。',recipeInput:'  一份好内容，值得再用一次。  \n\n  找得到，也能接着做。  ',recipeTrim:true,recipeBlank:true,recipeBullet:true};
let stored={};try{stored=JSON.parse(localStorage.getItem(KEY)||'{}')}catch(_){}
const state={...defaults,...Object.fromEntries(Object.keys(defaults).filter(k=>typeof stored[k]===typeof defaults[k]).map(k=>[k,stored[k]]))};
if(!['a','b','c'].includes(state.design))state.design='a';
const designs={
 a:{title:'清爽，而不空泛。',description:'用纸张白、墨绿色和轻分隔建立层次。可爱只留给爪印图标，内容始终是主角。',benefits:['保留熟悉的单击粘贴与底部短搜索','来源和大小默认隐藏，正文有更多空间','统一线性图标，取消混杂的表情符号'],icon:'icon-a-paw-note.svg'},
 b:{title:'可爱，但不喧闹。',description:'淡紫、奶白与小猫夹组成温柔的桌面伙伴。圆角更柔和，品牌表情只出现在图标和空状态。',benefits:['和 A 使用相同工作流，上手成本低','柔和色彩与少量个性，避免整屏装饰','保留高对比文字和减少动画选项'],icon:'icon-b-cat-clip.svg'},
 c:{title:'快取，也能深度整理。',description:'用侧边分类和完整预览组织大量内容。宽窗适合整理，收窄后回到熟悉的轻量面板。',benefits:['宽窗显示分类与预览，减少反复打开弹窗','窄窗主动收起次要分栏，保证按钮可达','工作台作为可选模式，避免默认面板膨胀'],icon:'icon-c-stacked.svg'}
};
const rows=[
 {id:1,text:'收到，我整理后在今天下午发给你。',source:'聊天示例',kind:'text',size:'54 B',favorite:false},
 {id:2,text:'https://example.com/design-notes',source:'浏览器示例',kind:'url',size:'32 B',favorite:true},
 {id:3,text:'周末计划：散步、读书，留一点时间给自己。',source:'记事本示例',kind:'text',size:'63 B',favorite:false},
 {id:4,text:'山与湖的配色灵感',source:'截图示例',kind:'image',size:'640 × 320',favorite:false},
 {id:5,text:'把常用内容整理好，下一次就能少找一会儿。',source:'笔记示例',kind:'text',size:'66 B',favorite:false},
 {id:6,text:'谢谢反馈，问题已经记下，处理后会同步结果。',source:'常用语示例',kind:'text',size:'69 B',favorite:true,phrase:true,name:'反馈回复'},
 {id:7,text:'方便的话，请告诉我具体时间，我来安排。',source:'常用语示例',kind:'text',size:'60 B',favorite:false,phrase:true,name:'时间确认'}
];
let selected=rows[0].id,removed=[],settingsSection='appearance';
const $=s=>document.querySelector(s);
const $$=s=>[...document.querySelectorAll(s)];
const icon=(name,cls='')=>`<svg class="${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function persist(){try{localStorage.setItem(KEY,JSON.stringify(state));$('#savedState').textContent='草案选项与示例工作流已保存在此浏览器'}catch(_){$('#savedState').textContent='浏览器未允许保存，设计文件仍保留在项目中'}}
function visibleRows(){return rows.filter(r=>!removed.includes(r.id)&&(state.tab==='fav'?r.favorite:state.tab==='phrase'?r.phrase:!r.phrase)&&(state.kind==='all'||state.kind===r.kind)&&(!state.q||(r.text+' '+r.source+' '+(r.name||'')).toLowerCase().includes(state.q.toLowerCase())))}
function render(){
 const design=designs[state.design];$('#designTitle').textContent=design.title;$('#designDescription').textContent=design.description;
 $('#designBenefits').innerHTML=design.benefits.map(x=>`<li>${esc(x)}</li>`).join('');
 $('#appIcon').src=design.icon;$('#stage').dataset.design=state.design;$('#stage').dataset.dark=state.dark;
 $('#appWindow').classList.toggle('narrow',state.narrow);$('#appWindow').classList.toggle('dense',state.dense);
 $('#darkToggle').checked=state.dark;$('#compactToggle').checked=state.narrow;
 $$('.design-choice').forEach(b=>{b.classList.toggle('active',b.dataset.design===state.design);b.setAttribute('aria-pressed',b.dataset.design===state.design)});
 $$('[data-tab]').forEach(b=>{b.classList.toggle('active',b.dataset.tab===state.tab);b.setAttribute('aria-pressed',b.dataset.tab===state.tab)});
 $$('[data-kind]').forEach(b=>{b.classList.toggle('active',b.dataset.kind===state.kind);b.setAttribute('aria-pressed',b.dataset.kind===state.kind)});
 $('#listenText').textContent=state.listening?'监听示意':'暂停示意';$('#listenToggle').classList.toggle('paused',!state.listening);
 $('#listCaption').textContent=state.tab==='fav'?'收藏内容':state.tab==='phrase'?'常用语 · 默认分组':'最近复制';
 const items=visibleRows();$('#count').textContent=`${items.length} 条`;
 if(!items.some(r=>r.id===selected))selected=items[0]?.id;
 $('#clipList').innerHTML=items.length?items.map(r=>`<div class="clip-row ${r.id===selected?'selected':''}" tabindex="${r.id===selected?0:-1}" role="button" data-id="${r.id}" aria-label="模拟粘贴：${esc(r.text)}" aria-pressed="${r.id===selected}"><div class="clip-type">${icon(r.kind==='url'?'link':r.kind==='image'?'image':'note')}</div><div class="clip-copy">${r.kind==='image'?'<div class="thumb" aria-label="合成风景示例"><span></span></div>':''}<div class="clip-text">${esc(r.text)}</div>${r.phrase?`<div class="clip-sub">${esc(r.name)}</div>`:state.source?`<div class="clip-sub">${esc(r.source)}</div>`:''}</div>${state.size?`<span class="clip-size">${r.size}</span>`:''}${r.favorite?'<span class="clip-star" aria-label="已收藏">★</span>':''}</div>`).join(''):'<div class="empty">这里暂时没有匹配内容。<br>试试其他分类或关键词。<br><button data-action="reset-filter">清除筛选</button></div>';
 const current=rows.find(r=>r.id===selected);$('#detailContent').textContent=current?.text||'选中一条内容，在这里查看。';
 if($('#searchInput').value!==state.q)$('#searchInput').value=state.q;
 persist();
}
function feedback(text,undo=false){$('#feedback').innerHTML='<span class="feedback-dot"></span>'+esc(text)+(undo?'<button class="toast-action" data-action="undo">撤销</button>':'')}
function activateRow(id){selected=Number(id);render();feedback('已模拟粘贴 · 真实剪贴板未改动');const el=$(`[data-id="${selected}"]`);el?.focus({preventScroll:true});el?.classList.add('flash');setTimeout(()=>el?.classList.remove('flash'),160)}
function settings(){
 const content={
 appearance:`<h3>让内容更清楚</h3><p>保持安静的默认外观，需要的信息再打开。</p>${setting('显示来源','在每条内容下显示来源程序','source')}${setting('显示条目大小','在右侧显示字节数或图片尺寸','size')}${setting('紧凑行高','同一窗口内显示更多内容','dense')}${setting('深色外观','适合较暗的环境','dark')}`,
 capture:'<h3>采集与隐私</h3><p>新版建议把相关设置集中在这里。</p><div class="setting-card"><strong>保留现有保护</strong>暂停监听、私密标记、敏感遮罩、应用忽略名单。</div><div class="setting-card"><strong>候选增强 · 尚未实现</strong>临时暂停计时、过期自动清理、按应用制定保留规则。加密方案需单独评估数据兼容性。</div>',
 keys:'<h3>快捷键</h3><p>保持熟悉的快捷方式，新增操作有清楚的提示。</p><div class="setting-card"><strong>草案内可体验</strong><kbd>↑</kbd> <kbd>↓</kbd> 选择记录<br><kbd>Enter</kbd> 模拟粘贴<br><kbd>Esc</kbd> 关闭设置</div><div class="setting-card"><strong>产品已有能力，后续保留</strong>全局唤起、纯文本粘贴、命令面板，以及 1–10 项快速粘贴。</div>',
 data:'<h3>数据与备份</h3><p>让保存、搬家和恢复形成完整闭环。</p><div class="setting-card"><strong>候选增强 · 尚未实现</strong>打包备份 JSON + 图片、导入预览、备份恢复、删除撤销。</div><div class="setting-card"><strong>本草案不操作真实数据</strong>清除浏览器数据会重置这里的选项；项目中的方案、代码和图标文件不会受影响。</div>'
 };
 $('#settingsPage').innerHTML=content[settingsSection];$$('[data-section]').forEach(b=>b.classList.toggle('active',b.dataset.section===settingsSection));
}
function setting(title,note,key){return `<label class="setting-row"><span><strong>${title}</strong><small>${note}</small></span><input type="checkbox" data-setting="${key}" ${state[key]?'checked':''} aria-label="${title}"></label>`}
function projectDemo(){
 $('#workflowTitle').textContent='项目口袋 / 续上昨天';
 $('#workflowBody').innerHTML=`<p class="workflow-intro">把相关材料和下一步放在一起。离开一会儿，回来时就知道从哪里接着做。这里请只填写示例内容。</p><label class="workflow-field">项目名称<input id="projectName" value="${esc(state.projectName)}"></label><div class="material-cards"><div>${icon('note')}<span>设计原则<small>简洁、清晰，保留紧凑操作。</small></span></div><div>${icon('link')}<span>参考链接<small>example.com / 合成来源</small></span></div><div>${icon('image')}<span>视觉草案<small>示例材料快照</small></span></div></div><label class="workflow-field">我做到哪里了？<textarea id="projectNote" rows="2">${esc(state.projectNote)}</textarea></label><label class="workflow-field">下次先做什么？<textarea id="projectNext" rows="2">${esc(state.projectNext)}</textarea></label><button class="workflow-primary" data-action="save-project">保存示例项目</button><p class="workflow-footnote">草案可关闭、重新打开或刷新。正式版仍须另外验证文件落盘、图片归属、备份恢复和新进程重载。</p>`;
 $('#workflowStatus').textContent='项目材料为合成示例；不会读取真实历史或磁盘文件。';$('#workflowDialog').showModal();
}
function recipeDemo(){
 $('#workflowTitle').textContent='小工序 / 可复用处理配方';
 $('#workflowBody').innerHTML=`<p class="workflow-intro">把常做的几步清理存成配方。先看结果，再决定怎么用；原材料保持完整。</p><div class="recipe-columns"><label class="workflow-field">原材料<textarea id="recipeInput" rows="7">${esc(state.recipeInput)}</textarea></label><label class="workflow-field">结果预览<textarea id="recipeOutput" rows="7" readonly></textarea></label></div><div class="recipe-steps">${[['recipeTrim','① 清理行首尾空格'],['recipeBlank','② 移除空行'],['recipeBullet','③ 添加列表符号']].map(([key,name])=>`<label><input type="checkbox" data-recipe="${key}" ${state[key]?'checked':''}>${name}</label>`).join('')}</div><p class="workflow-footnote">三步受控动作的交互样机，不运行用户脚本，不覆盖原材料，不调用AI或真实剪贴板。</p>`;
 updateRecipe();$('#workflowDialog').showModal();
}
function updateRecipe(){
 let lines=state.recipeInput.split('\n');if(state.recipeTrim)lines=lines.map(x=>x.trim());if(state.recipeBlank)lines=lines.filter(x=>x.trim());if(state.recipeBullet)lines=lines.map(x=>x?'• '+x:x);
 $('#recipeOutput').value=lines.join('\n');$('#workflowStatus').textContent='示例配方与原材料保存在此浏览器，可关闭后重开。';persist();
}
function action(name){
 switch(name){
  case 'project-demo':projectDemo();break;
  case 'recipe-demo':recipeDemo();break;
  case 'save-project':state.projectName=$('#projectName').value;state.projectNote=$('#projectNote').value;state.projectNext=$('#projectNext').value;persist();$('#workflowStatus').textContent='示例项目已保存到此浏览器；正式产品文件保存尚未实施。';break;
  case 'settings':settings();$('#settingsDialog').showModal();break;
  case 'delete':if(selected){removed.push(selected);render();feedback('示例已移除 · 撤销为候选功能演示',true)}break;
  case 'undo':removed.pop();render();feedback('示例已恢复');break;
  case 'add':state.tab='phrase';state.kind='all';state.q='';render();feedback('常用语入口示意 · 未写入真实资料');break;
  case 'split':feedback('拆词面板将沿用完整输入和固定底部按钮');break;
  case 'filters':$('#filters').hidden=!$('#filters').hidden;break;
  case 'more':feedback('更多操作：变换、导出、预览 · 方案示意');break;
  case 'pin':feedback('置顶操作示意 · 未修改系统窗口');break;
  case 'collapse':case 'close-demo':$('#appWindow').hidden=true;$('#restoreDemo').hidden=false;break;
  case 'reset-filter':state.q='';state.kind='all';render();break;
 }
}
document.addEventListener('click',e=>{
 const design=e.target.closest('[data-design].design-choice');if(design){state.design=design.dataset.design;render();return}
 const tab=e.target.closest('[data-tab]');if(tab){state.tab=tab.dataset.tab;state.kind='all';render();return}
 const kind=e.target.closest('[data-kind]');if(kind){state.kind=kind.dataset.kind;state.tab='all';render();return}
 const section=e.target.closest('[data-section]');if(section){settingsSection=section.dataset.section;settings();return}
 const button=e.target.closest('[data-action]');if(button){action(button.dataset.action);return}
 const row=e.target.closest('[data-id]');if(row)activateRow(row.dataset.id);
});
$('#darkToggle').addEventListener('change',e=>{state.dark=e.target.checked;render()});
$('#compactToggle').addEventListener('change',e=>{state.narrow=e.target.checked;render()});
$('#listenToggle').addEventListener('click',()=>{state.listening=!state.listening;render();feedback(state.listening?'草案监听状态：开启':'草案监听状态：暂停')});
$('#searchInput').addEventListener('input',e=>{state.q=e.target.value;render()});
$('#settingsPage').addEventListener('change',e=>{if(e.target.dataset.setting){state[e.target.dataset.setting]=e.target.checked;render();feedback('草案外观设置已保存')}});
$('#closeSettings').addEventListener('click',()=>$('#settingsDialog').close());
$('#closeWorkflow').addEventListener('click',()=>$('#workflowDialog').close());
$('#workflowBody').addEventListener('input',e=>{if(e.target.id==='recipeInput'){state.recipeInput=e.target.value;updateRecipe()}});
$('#workflowBody').addEventListener('change',e=>{if(e.target.dataset.recipe){state[e.target.dataset.recipe]=e.target.checked;updateRecipe()}});
$('#restoreDemo').addEventListener('click',()=>{$('#appWindow').hidden=false;$('#restoreDemo').hidden=true;$('#appWindow').focus()});
$('#appWindow').addEventListener('keydown',e=>{
 if(!e.target.closest('[data-id]'))return;
 if(e.key==='ArrowDown'||e.key==='ArrowUp'){
  e.preventDefault();const items=visibleRows();if(!items.length)return;
  const index=items.findIndex(r=>r.id===selected),step=e.key==='ArrowDown'?1:-1;
  selected=items[Math.max(0,Math.min(items.length-1,index+step))].id;render();$(`[data-id="${selected}"]`)?.focus();
 }else if(e.key==='Enter'||e.key===' '){e.preventDefault();activateRow(e.target.closest('[data-id]').dataset.id)}
});
render();
