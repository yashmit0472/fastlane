'use client';

import {useEffect} from 'react';
import {usePathname} from 'next/navigation';

/** Progressive enhancement: content remains visible without JavaScript or motion. */
export function MotionSystem() {
  const pathname=usePathname();
  useEffect(()=>{
    if(window.matchMedia('(prefers-reduced-motion: reduce)').matches||!('IntersectionObserver' in window))return;
    const observer=new IntersectionObserver(entries=>{
      for(const entry of entries)if(entry.isIntersecting){entry.target.classList.add('motion-arrived');observer.unobserve(entry.target);}
    },{threshold:.06,rootMargin:'0px 0px -15px 0px'});
    const elements=document.querySelectorAll<HTMLElement>('.weekend-spotlight,.dashboard-heading,.dashboard-columns>.panel,.dashboard-aside>.panel,.weekend-panel,.page-heading,.content-section,.race-list-card,.report-card,.context-card');
    for(const element of elements){
      if(element.getBoundingClientRect().top<window.innerHeight){element.classList.add('motion-arrived');continue;}
      element.classList.add('motion-ready');observer.observe(element);
    }
    return ()=>{observer.disconnect();for(const element of elements)element.classList.remove('motion-ready');};
  },[pathname]);
  return null;
}
