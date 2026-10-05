'use strict';
const $ = s => document.querySelector(s);
const ui = {items:[], selected:new Set()};
const Vault = Object.freeze({request:async(route,payload={}) => {
  try {return await window.webkit.messageHandlers.vault.postMessage({route,payload});}
  catch(error){throw Error(error.message||String(error));}
}});
const api = Vault.request;
window.addEventListener('error', e => {$('#mac-error').textContent=e.message;});
