import type {Metadata} from 'next';
import {Nav} from '@/components/nav';
import {Footer} from '@/components/ui';
import './globals.css';
import './polish.css';
import {AutoRefresh} from '@/components/auto-refresh';
import {Suspense} from 'react';
import {OperationsBanner} from '@/components/operations-banner';
import {MotionSystem} from '@/components/motion-system';
export const metadata: Metadata = {title:{default:'FASTLANE | Race forecasts & session analysis',template:'%s | FASTLANE'},description:'Formula 1 winner, podium and top-10 probabilities, with practice pace, qualifying and historical race analysis.'};
export default function RootLayout({children}:{children:React.ReactNode}) {return <html lang="en" data-scroll-behavior="smooth"><body><a className="skip-link" href="#main">Skip to content</a><Nav/><AutoRefresh/><MotionSystem/><Suspense fallback={null}><OperationsBanner/></Suspense><main id="main">{children}</main><Footer/></body></html>;}
