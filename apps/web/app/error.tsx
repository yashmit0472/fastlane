'use client';
export default function ErrorPage({reset}:{reset:()=>void}) {return <div className="page-shell empty-state"><div><h1>This view could not load.</h1><p>Try again in a moment.</p><button className="button" onClick={reset}>Try again</button></div></div>;}
