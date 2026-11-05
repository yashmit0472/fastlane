import {api} from '@/lib/api';
import {PageHeading} from '@/components/ui';
import {PerformanceDashboard} from '@/components/performance-dashboard';
import {ConditionsReport} from '@/components/conditions-report';
import {ProspectiveBenchmarks} from '@/components/prospective-benchmarks';
export const metadata={title:'Prediction performance'};
export default async function PerformancePage(){
  const [live,validation,source,conditions]=await Promise.all([api.performance(),api.validation(),api.sourceValidation(),api.conditions()]);
  return <div className="page-shell"><PageHeading eyebrow="FORECAST ACCOUNTABILITY" title="Track the forecast." description="Compare the model with simple baselines, inspect calibration, and follow the results of predictions saved before each race."/><PerformanceDashboard live={live.data} validation={validation.data} source={source.data}/><ProspectiveBenchmarks performance={live.data}/><ConditionsReport report={conditions.data}/></div>;
}
