'use strict';
$('#author-close').onclick=()=>$('#author-support').close();
$('#jsr-close').textContent='返回模式选择 ×';
$('#jsr-close').addEventListener('click',()=>$('#jsr-launch').click());
$('#jsr-launch').click();
window.macSelfTest=async(runJob=false)=>{
  const wait=async(fn)=>{for(let i=0;i<6000;i++){if(fn())return;await new Promise(r=>setTimeout(r,100));}throw Error('UI等待超时：'+$('#jsr-error').textContent);};
  const modes=[];
  for(const engine of ['fastk14','v98k14','stormer7']){
    if(!$('#jsr-mode-dialog').open)$('#jsr-launch').click();
    $(`[data-engine="${engine}"]`).click();
    await wait(()=>!$('#jsr-mode-dialog').open&&$('#jsr-dialog').open&&$('#jsr-select').disabled===false);
    $('#jsr-select').click();
    await wait(()=>$('#jsr-select').disabled===false&&$('#jsr-image').src.startsWith('data:image/jpeg'));
    for(const id of ['jsr-calibration-dialog','jsr-exposure-dialog']){if($('#'+id).open)$('#'+id).close();}
    if(engine!=='v98k14'){
      $('#jsr-manual').checked=true;$('#jsr-manual').dispatchEvent(new Event('change'));
      for(const [id,value] of [['read_noise',0],['black',1008],['fullwell',20000]]){$('#jsr-'+id).value=value;$('#jsr-'+id).dispatchEvent(new Event('input'));}
    }
    $('#jsr-output').value='/tmp';$('#jsr-output').dispatchEvent(new Event('input'));
    await wait(()=>!$('#jsr-start').disabled);
    if(engine==='stormer7'){$('#jsr-roi').click();$('[data-size="512"]').click();await wait(()=>!$('#jsr-start').disabled);}
    modes.push({engine,count:$('#jsr-count').textContent,ready:!$('#jsr-start').disabled,preview:$('#jsr-image').src.startsWith('data:image/jpeg'),roi:engine==='stormer7'?['x','y','w','h'].map(k=>Number($('#jsr-'+k).value)):null});
  }
  let job=null;
  if(runJob){
    $('#jsr-memory').value='4';$('#jsr-memory').dispatchEvent(new Event('input'));
    $('#jsr-tiff').checked=true;$('#jsr-start').click();
    await wait(()=>!$('#jsr-cancel').hidden);
    await wait(()=>$('#jsr-cancel').hidden);
    job=await api('jsr/status');
    if(job.state!=='complete')throw Error(job.log);
  }
  return {host:'WKWebView',modes,job,author:!!$('#author-support img'),errors:$('#jsr-error').textContent};
};
window.macBatchSelfTest=async()=>{
  const wait=async(fn)=>{for(let i=0;i<600;i++){if(fn())return;await new Promise(r=>setTimeout(r,100));}throw Error('批量UI等待超时：'+$('#jsr-error').textContent);};
  $('[data-engine="fastk14"]').click();
  await wait(()=>$('#jsr-dialog').open&&!$('#jsr-select').disabled);
  $('#jsr-camera-preset').value='z8';$('#jsr-camera-preset').dispatchEvent(new Event('change'));
  await wait(()=>!$('#jsr-batch-launch').hidden);
  $('#jsr-batch-launch').click();$('#jsr-batch-scan').click();
  await wait(()=>document.querySelectorAll('.jsr-batch-card').length===2&&!$('#jsr-batch-scan').disabled);
  $('#jsr-output').value='/tmp';$('#jsr-output').dispatchEvent(new Event('input'));
  await wait(()=>!$('#jsr-start').disabled);$('#jsr-start').click();
  await wait(()=>$('#jsr-start').textContent==='开始批量合成 →'&&!$('#jsr-start').disabled);
  const groups=[...document.querySelectorAll('.jsr-batch-card-status')].map(e=>e.textContent);
  if(groups.some(text=>!text.includes('准备完成')))throw Error(JSON.stringify(groups));
  return {host:'WKWebView',groups,ready:true,errors:$('#jsr-error').textContent};
};
