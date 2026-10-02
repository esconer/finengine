/**
 * Portfolio Statistics Component
 * Displays comprehensive portfolio analytics and performance metrics
 */

'use client';

import React from 'react';
import { 
  TrendingUp, 
  TrendingDown, 
  Activity,
  DollarSign,
  Percent,
  Target
} from 'lucide-react';
import { PortfolioPosition, Currency } from '@/types';
import { cn, formatCurrency } from '@/lib/utils';

interface PortfolioStatsProps {
  positions: PortfolioPosition[];
  currency: Currency;
}

/**
 * A monetary value that PRESERVES absence. The sibling `monetaryValue` in this
 * file and in `app/portfolio/manage/page.tsx` is typed `(…): number` with a
 * terminal `return 0`, which makes `Number.isFinite(monetaryValue(…))` always
 * true and every N/A guard written over its result unreachable — the % Return
 * cell rendered a green `+0.00%` for a holding the engine could not cost.
 *
 * The two helpers differ only in the terminal case, and which one a call site
 * needs is decided by what it does with an absent value:
 *   - a REDUCTION (`sum + …`) needs a 0: an absent leg contributes nothing to a
 *     total, and the total is stated over the legs that were measured.
 *   - anything that renders ONE holding's figure needs `null`, so the render can
 *     say N/A instead of publishing a fabricated zero.
 */
const measuredValue = (base: number | null | undefined, native: number | null | undefined): number | null => {
  if (typeof base === 'number' && Number.isFinite(base)) return base;
  if (typeof native === 'number' && Number.isFinite(native)) return native;
  return null;
};

/** The reduction form: an absent leg adds nothing rather than voiding the sum. */
const monetaryValue = (base: number | null | undefined, native: number | null | undefined): number => {
  return measuredValue(base, native) ?? 0;
};

export function PortfolioStats({ positions, currency }: PortfolioStatsProps) {
  // Calculate comprehensive statistics
  const stats = React.useMemo(() => {
    // Unreachable behind the `positions.length === 0` early return below, but the
    // values still have to match the contract the populated branch returns: an
    // empty book has NO measured concentration and NO measured average, and 0
    // would assert both.
    if (positions.length === 0) {
      return {
        bestPerformer: null,
        worstPerformer: null,
        avgGainLoss: null,
        portfolioConcentration: null,
        totalGainLoss: 0,
        totalGainLossPct: 0,
        totalCost: 0,
        totalCurrentValue: 0,
        winnersCount: 0,
        losersCount: 0
      };
    }

    const totalCost = positions.reduce(
      (sum, pos) => sum + monetaryValue(pos.total_cost_base, pos.total_cost),
      0
    );
    const totalCurrentValue = positions.reduce(
      (sum, pos) => sum + monetaryValue(pos.current_value_base, pos.current_value),
      0
    );
    const totalGainLoss = positions.reduce(
      (sum, pos) => sum + monetaryValue(
        pos.unrealized_gain_loss_base,
        pos.unrealized_gain_loss
      ),
      0
    );
    const totalGainLossPct = totalCost > 0 ? (totalGainLoss / totalCost) * 100 : 0;
    // Per-holding figures, so absence must SURVIVE to the render: routed
    // through `monetaryValue` these read 0 and the card publishes "+0.00%"
    // for a holding with no measured return. `formatPercent` below already
    // renders null as '—', so null is the value it is waiting for.
    const gainLossPct = (pos: PortfolioPosition) => measuredValue(
      pos.unrealized_gain_loss_pct_base,
      pos.unrealized_gain_loss_pct
    );
    const gainLoss = (pos: PortfolioPosition) => measuredValue(
      pos.unrealized_gain_loss_base,
      pos.unrealized_gain_loss
    );

    // Best and worst performers in the selected base currency, ranked over the
    // legs the engine actually measured a return for.
    //
    // An unmeasured leg must not be able to win either title. Routing it
    // through the 0-absorbing helper gave it an absent 0 it could beat a real
    // loser with, and comparing against a null pct coerces to 0 in exactly the
    // same way — so ranking is done over `ranked`, never over the raw list.
    const ranked = positions
      .map(pos => ({ pos, pct: gainLossPct(pos) }))
      .filter((entry): entry is { pos: PortfolioPosition; pct: number } => entry.pct !== null);
    const bestPerformer = ranked.length > 0
      ? ranked.reduce((best, entry) => (entry.pct > best.pct ? entry : best)).pos
      : null;
    const worstPerformer = ranked.length > 0
      ? ranked.reduce((worst, entry) => (entry.pct < worst.pct ? entry : worst)).pos
      : null;

    // Portfolio concentration (largest position weight).
    //
    // `Math.max(…positions.map(pos => pos.weight * 100))` had no zero-guard:
    // `undefined * 100` is NaN and `Math.max` is NaN-poisoned, so ONE holding
    // without a measured weight made the whole card print "NaN%".
    //
    // Filter to the legs the engine actually weighed. This is NOT the same as
    // dropping unmeasured legs from a claim about the book: a measured leg's
    // weight does not depend on an unmeasured sibling, so the largest MEASURED
    // weight is still a true one. With nothing measured there is no largest
    // position, so the card is withheld rather than filled with a 0.
    const measuredWeights = positions
      .map(pos => measuredValue(pos.weight, null))
      .filter((weight): weight is number => weight !== null)
      .map(weight => weight * 100);
    const portfolioConcentration = measuredWeights.length > 0
      ? Math.max(...measuredWeights)
      : null;

    // Winners vs Losers. A leg with no measured P&L is neither: `null > 0` and
    // `null < 0` are both false, so it counts in neither bucket — the same
    // outcome the old 0-absorbing read produced, without asserting a zero.
    const winnersCount = positions.filter(pos => (gainLoss(pos) ?? 0) > 0).length;
    const losersCount = positions.filter(pos => (gainLoss(pos) ?? 0) < 0).length;

    // Average return across the book. It is a mean over EVERY leg, so ONE
    // unmeasured leg makes the mean absent — the same rule the concentration
    // cumulative weight already follows. Averaging only the measured subset
    // would be the quieter fabrication: it publishes an average of a book the
    // card claims to describe while silently excluding a holding from it.
    const avgGainLoss = ranked.length > 0 && ranked.length === positions.length
      ? ranked.reduce((sum, entry) => sum + entry.pct, 0) / ranked.length
      : null;

    return {
      bestPerformer,
      worstPerformer,
      avgGainLoss,
      portfolioConcentration,
      totalGainLoss,
      totalGainLossPct,
      totalCost,
      totalCurrentValue,
      winnersCount,
      losersCount
    };
  }, [positions]);

  const money = (amount?: number | null) =>
    amount != null && Number.isFinite(amount) ? formatCurrency(amount, currency) : '—';

  const formatPercent = (value: number | null | undefined) => {
    if (value == null || !Number.isFinite(value)) return '—';
    const sign = value >= 0 ? '+' : '';
    return `${sign}${value.toFixed(2)}%`;
  };

  if (positions.length === 0) {
    return (
      <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Portfolio Statistics
        </h3>
        <p className="text-gray-500 dark:text-gray-400 text-center py-8">
          Add positions to see portfolio statistics
        </p>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-gray-900 rounded-lg shadow p-6">
      <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-6">
        Portfolio Statistics
      </h3>
      
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {/* Best Performer */}
        <div className="bg-green-50 dark:bg-green-900/20 rounded-lg p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-green-800 dark:text-green-200">
                Best Performer
              </p>
              <p className="text-lg font-semibold text-green-900 dark:text-green-100">
                {stats.bestPerformer?.ticker}
              </p>
              <p className="text-sm text-green-700 dark:text-green-300">
                {formatPercent(stats.bestPerformer ? measuredValue(stats.bestPerformer.unrealized_gain_loss_pct_base, stats.bestPerformer.unrealized_gain_loss_pct) : null)}
              </p>
            </div>
            <TrendingUp className="h-8 w-8 text-green-600" />
          </div>
        </div>

        {/* Worst Performer */}
        <div className="bg-red-50 dark:bg-red-900/20 rounded-lg p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-red-800 dark:text-red-200">
                Worst Performer
              </p>
              <p className="text-lg font-semibold text-red-900 dark:text-red-100">
                {stats.worstPerformer?.ticker}
              </p>
              <p className="text-sm text-red-700 dark:text-red-300">
                {formatPercent(stats.worstPerformer ? measuredValue(stats.worstPerformer.unrealized_gain_loss_pct_base, stats.worstPerformer.unrealized_gain_loss_pct) : null)}
              </p>
            </div>
            <TrendingDown className="h-8 w-8 text-red-600" />
          </div>
        </div>

        {/* Winners vs Losers */}
        <div className="bg-blue-50 dark:bg-blue-900/20 rounded-lg p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-blue-800 dark:text-blue-200">
                Winners / Losers
              </p>
              <p className="text-lg font-semibold text-blue-900 dark:text-blue-100">
                {stats.winnersCount} / {stats.losersCount}
              </p>
              <p className="text-sm text-blue-700 dark:text-blue-300">
                {((stats.winnersCount / positions.length) * 100).toFixed(0)}% winners
              </p>
            </div>
            <Activity className="h-8 w-8 text-blue-600" />
          </div>
        </div>

        {/* Portfolio Concentration — withheld when no leg carries a measured
            weight. `toFixed` on a NaN is the literal string "NaN", so the card
            used to publish "NaN%" beside a book that was never weighed. */}
        {stats.portfolioConcentration !== null && (
          <div className="bg-purple-50 dark:bg-purple-900/20 rounded-lg p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-purple-800 dark:text-purple-200">
                  Largest Position
                </p>
                <p className="text-lg font-semibold text-purple-900 dark:text-purple-100">
                  {stats.portfolioConcentration.toFixed(1)}%
                </p>
                <p className="text-sm text-purple-700 dark:text-purple-300">
                  Concentration Risk
                </p>
              </div>
              <Target className="h-8 w-8 text-purple-600" />
            </div>
          </div>
        )}
      </div>

      {/* Additional Metrics Row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-6 pt-6 border-t border-gray-200 dark:border-gray-700">
        {/* Total Cost */}
        <div className="text-center">
          <p className="text-sm font-medium text-gray-500 dark:text-gray-400">
            Total Investment
          </p>
          <p className="text-xl font-semibold text-gray-900 dark:text-white">
            {money(stats.totalCost)}
          </p>
        </div>

        {/* Current Value */}
        <div className="text-center">
          <p className="text-sm font-medium text-gray-500 dark:text-gray-400">
            Current Value
          </p>
          <p className="text-xl font-semibold text-gray-900 dark:text-white">
            {money(stats.totalCurrentValue)}
          </p>
        </div>

        {/* Average Gain/Loss */}
        <div className="text-center">
          <p className="text-sm font-medium text-gray-500 dark:text-gray-400">
            Average Return
          </p>
          <p className={cn(
            'text-xl font-semibold',
            // No colour on the absent state: green would read as "no change",
            // red as "a loss". `null >= 0` is true, so an unguarded ternary
            // painted the withheld '—' green.
            stats.avgGainLoss == null
              ? ''
              : stats.avgGainLoss >= 0 ? 'text-green-600' : 'text-red-600'
          )}>
            {formatPercent(stats.avgGainLoss)}
          </p>
        </div>
      </div>
    </div>
  );
}

export default PortfolioStats;