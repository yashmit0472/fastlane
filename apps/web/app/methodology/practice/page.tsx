import Link from 'next/link';
import {PageHeading} from '@/components/ui';
import PracticeReports from '@/components/practice-reports';
export const metadata={title:'Practice model evaluation'};
export default function PracticeMethodology(){return <div className="page-shell"><PageHeading eyebrow="FP1 / FP2 / FP3" title="Practice, tested." description="Chronological backtests and honest comparisons for each practice-stage forecast."/><Link href="/methodology">Back to methodology</Link><PracticeReports/></div>;}
