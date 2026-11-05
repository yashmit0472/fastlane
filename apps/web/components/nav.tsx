'use client';
import Link from 'next/link';
import {usePathname} from 'next/navigation';
import {useEffect,useRef,useState} from 'react';
import {Menu,X} from 'lucide-react';
export function Nav(){
  const [open,setOpen]=useState(false); const path=usePathname();
  const menu=useRef<HTMLButtonElement>(null);
  useEffect(()=>{
    if(!open)return;
    const dismiss=(event:KeyboardEvent)=>{if(event.key==='Escape'){setOpen(false);menu.current?.focus();}};
    document.addEventListener('keydown',dismiss);
    return ()=>document.removeEventListener('keydown',dismiss);
  },[open]);
  const links=[{href:'/',label:'Overview'},{href:'/predictions',label:'Races'},{href:'/weekend',label:'Session data'},{href:'/circuits',label:'Circuits'},{href:'/performance',label:'Performance'},{href:'/methodology',label:'The model'}];
  return <header className="nav"><Link href="/" className="wordmark" aria-label="FASTLANE home"><span className="speed-mark" aria-hidden="true"><i/><i/><i/></span>FASTLANE<span className="red">.</span></Link><nav id="main-navigation" aria-label="Main navigation" className={open?'nav-links open':'nav-links'}>{links.map(l=><Link key={l.href} href={l.href} onClick={()=>setOpen(false)} aria-current={(l.href==='/'?path==='/':path.startsWith(l.href))?'page':undefined} className={(l.href==='/'?path==='/':path.startsWith(l.href))?'active':''}>{l.label}</Link>)}</nav><span className="nav-caption">Formula 1 · Race analysis</span><button ref={menu} className="menu-button" onClick={()=>setOpen(!open)} aria-expanded={open} aria-controls="main-navigation" aria-label={open?'Close navigation':'Open navigation'}>{open?<X size={21}/>:<Menu size={21}/>}</button></header>;
}
