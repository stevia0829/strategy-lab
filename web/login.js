'use strict';
const form=document.getElementById('login-form');
const password=document.getElementById('password');
const message=document.getElementById('message');
const button=form.querySelector('button');
form.addEventListener('submit',async event=>{
  event.preventDefault();
  button.disabled=true;message.textContent='正在登录…';
  try{
    const response=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:password.value})});
    const body=await response.json();
    if(!response.ok)throw new Error(body.error||'登录失败');
    password.value='';
    window.location.replace('/');
  }catch(error){message.textContent=error.message;password.select();button.disabled=false;}
});
