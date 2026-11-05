'use client';
import {useEffect} from 'react';
import {useRouter} from 'next/navigation';
export function AutoRefresh(){
  const router=useRouter();
  useEffect(()=>{
    const refresh=()=>{if(document.visibilityState==='visible'&&navigator.onLine)router.refresh();};
    const timer=window.setInterval(refresh,60000);
    document.addEventListener('visibilitychange',refresh);
    window.addEventListener('online',refresh);
    return ()=>{window.clearInterval(timer);document.removeEventListener('visibilitychange',refresh);window.removeEventListener('online',refresh);};
  },[router]);
  return null;
}
