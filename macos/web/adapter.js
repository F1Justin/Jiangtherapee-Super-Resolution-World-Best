'use strict';
const $ = s => document.querySelector(s);
let macDropHandler=null;
const Vault = Object.freeze({
 request:async(route,payload={})=>{
  try{return await window.webkit.messageHandlers.vault.postMessage({route,payload});}
  catch(error){throw Error(error.message||String(error));}
 },
 onDrop:handler=>{macDropHandler=handler;}
});
const api=Vault.request;
window.macHandleDrop=paths=>macDropHandler?.(paths);
window.addEventListener('error',e=>{const node=$('#mac-error');node.hidden=false;node.textContent=e.message;});
