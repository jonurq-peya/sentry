import {useTransactionSamplesWebVitalsScoresQuery} from 'sentry/views/insights/browser/webVitals/queries/storedScoreQueries/useTransactionSamplesWebVitalsScoresQuery';
import type {
  TransactionSampleRowWithScore,
  WebVitals,
} from 'sentry/views/insights/browser/webVitals/types';
import type {BrowserType} from 'sentry/views/insights/browser/webVitals/utils/queryParameterDecoders/browserType';
import {
  PERFORMANCE_SCORE_MEDIANS,
  PERFORMANCE_SCORE_P90S,
} from 'sentry/views/insights/browser/webVitals/utils/scoreThresholds';

type Props = {
  browserType: BrowserType;
  enabled: boolean;
  transaction: string;
  webVital: WebVitals | null;
};

export function useTransactionsCategorizedSamplesQuery({
  transaction,
  webVital,
  enabled,
  browserType,
}: Props) {
  const {data: goodData, isLoading: isGoodTransactionWebVitalsQueryLoading} =
    useTransactionSamplesWebVitalsScoresQuery({
      limit: 3,
      transaction: transaction ?? '',
      query: webVital
        ? `measurements.${webVital}:<${PERFORMANCE_SCORE_P90S[webVital]}`
        : undefined,
      enabled,
      withProfiles: true,
      sortName: 'webVitalSort',
      webVital: webVital ?? undefined,
      browserType,
    });

  const {data: mehData, isLoading: isMehTransactionWebVitalsQueryLoading} =
    useTransactionSamplesWebVitalsScoresQuery({
      limit: 3,
      transaction: transaction ?? '',
      query: webVital
        ? `measurements.${webVital}:<${PERFORMANCE_SCORE_MEDIANS[webVital]} measurements.${webVital}:>=${PERFORMANCE_SCORE_P90S[webVital]}`
        : undefined,
      enabled,
      withProfiles: true,
      sortName: 'webVitalSort',
      webVital: webVital ?? undefined,
      browserType,
    });

  const {data: poorData, isLoading: isPoorTransactionWebVitalsQueryLoading} =
    useTransactionSamplesWebVitalsScoresQuery({
      limit: 3,
      transaction: transaction ?? '',
      query: webVital
        ? `measurements.${webVital}:>=${PERFORMANCE_SCORE_MEDIANS[webVital]}`
        : undefined,
      enabled,
      withProfiles: true,
      sortName: 'webVitalSort',
      webVital: webVital ?? undefined,
      browserType,
    });

  const data = [...goodData, ...mehData, ...poorData];

  const isTransactionWebVitalsQueryLoading =
    isGoodTransactionWebVitalsQueryLoading ||
    isMehTransactionWebVitalsQueryLoading ||
    isPoorTransactionWebVitalsQueryLoading;

  const transactionsTableData: TransactionSampleRowWithScore[] = data.sort(
    (a, b) => a[`${webVital}Score`] - b[`${webVital}Score`]
  );

  return {
    data: transactionsTableData,
    isLoading: isTransactionWebVitalsQueryLoading,
  };
}
