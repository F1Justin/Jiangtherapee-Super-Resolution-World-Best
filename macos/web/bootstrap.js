'use strict';
$('#author-close').onclick=()=>$('#author-support').close();
window.macSelfTest=async(runJob=false)=>{
 await window.JsrReady;
 const wait=async(fn)=>{for(let i=0;i<6000;i++){if(fn())return;await new Promise(r=>setTimeout(r,100));}throw Error('UI等待超时：'+$('#jsr-error').textContent);};
 const modes=[];
 for(const engine of ['fastk14','v98k14','stormer7']){
  await window.JsrAssistantBridge.execute('set_mode',{engine},window.JsrAssistantBridge.token());
  $('#jsr-select').click();
  await wait(()=>!$('#jsr-select').disabled&&!!window.JsrAssistantBridge.snapshot().width);
  if(engine==='fastk14'){
   const paths=JSON.parse(window.JsrAssistantBridge.token()).paths;
   $('#jsr-clear').click();await wait(()=>window.JsrAssistantBridge.snapshot().frame_count===0&&!$('#jsr-select').disabled);
   await window.macHandleDrop(paths.slice(0,2));
   if(window.JsrAssistantBridge.snapshot().frame_count!==2||window.JsrAssistantBridge.snapshot().width)throw Error('未满组提前解析');
   await window.macHandleDrop(paths.slice(2));
   if(window.JsrAssistantBridge.snapshot().frame_count!==14||!window.JsrAssistantBridge.snapshot().width)throw Error('增量选片未完成');
  }
  for(const id of ['jsr-calibration-dialog','jsr-exposure-dialog']){if($('#'+id).open)$('#'+id).close();}
  let darkRequired=false;
  if(engine==='v98k14'){
   darkRequired=$('#jsr-start').disabled;
   $('#jsr-dark-pick').click();await wait(()=>$('#jsr-dark-name').textContent!=='尚未选择黑场');
  }else{
   $('#jsr-manual').checked=true;$('#jsr-manual').dispatchEvent(new Event('change'));
   for(const [id,value] of [['read_noise',0],['black',1008],['fullwell',20000]]){$('#jsr-'+id).value=value;$('#jsr-'+id).dispatchEvent(new Event('input'));}
  }
  $('#jsr-output').value='/tmp';$('#jsr-output').dispatchEvent(new Event('change'));
  await wait(()=>!$('#jsr-start').disabled);
  modes.push({engine,count:$('#jsr-count').textContent,ready:!$('#jsr-start').disabled,darkRequired});
 }
 let job=null;
 if(runJob){
  $('#jsr-memory').value='6';$('#jsr-memory').dispatchEvent(new Event('input'));
  $('#jsr-tiff').checked=true;$('#jsr-deghost').checked=true;$('#jsr-deghost').dispatchEvent(new Event('change'));$('#jsr-start').click();
  await wait(()=>!$('#jsr-cancel').hidden);await wait(()=>$('#jsr-cancel').hidden);
  job=await api('jsr/status');if(job.state!=='complete')throw Error(job.log);
 }
 return {host:'WKWebView',modes,job,author:!!$('#author-support img'),errors:$('#jsr-error').textContent};
};
