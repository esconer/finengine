# Risk Management Libraries Integration Guide

## Executive Summary

This guide provides a comprehensive implementation plan for integrating three advanced risk management libraries (riskfolio-lib, QuantLib, PyPortfolioOpt) into the Daisy Risk Engine project. The libraries are already included in the project dependencies but are currently underutilized, representing a significant opportunity to enhance the platform's analytical capabilities.

## Table of Contents

1. [Library Overview and Capabilities](#1-library-overview-and-capabilities)
2. [Current Architecture Analysis](#2-current-architecture-analysis)
3. [Step-by-Step Integration Plan](#3-step-by-step-integration-plan)
4. [Implementation Examples](#4-implementation-examples)
5. [Code Integration Examples](#5-code-integration-examples)
6. [Performance Considerations](#6-performance-considerations)
7. [Testing Strategy](#7-testing-strategy)
8. [Migration Path and Timeline](#8-migration-path-and-timeline)

---

## 1. Library Overview and Capabilities

### 1.1 PyPortfolioOpt (v1.5.6) - Portfolio Optimization Foundation

**Core Capabilities:**
- **Efficient Frontier Optimization**: Modern portfolio theory implementation with multiple optimization objectives (minimum variance, maximum Sharpe ratio, risk parity)
- **Black-Litterman Model**: Bayesian approach to portfolio optimization combining market equilibrium with investor views
- **Risk Factor Models**: Multi-factor risk models for enhanced portfolio construction
- **Robust Optimization**: Optimization under uncertainty and parameter estimation error

**Integration Opportunity:**
Replace current simplified weight calculations with sophisticated optimization algorithms.

**Key Classes to Integrate:**
```python
from pypfopt import EfficientFrontier
from pypfopt.black_litterman import BlackLittermanModel
from pypfopt import risk_models
from pypfopt import expected_returns
```

### 1.2 riskfolio-lib (v7.0.1) - Advanced Risk Analytics

**Core Capabilities:**
- **Advanced Portfolio Optimization**: Mean-CVaR, risk parity, hierarchical risk parity
- **Risk Metrics and Performance Attribution**: Comprehensive risk decomposition and factor analysis
- **Stress Testing and Scenario Analysis**: Advanced scenario modeling and stress testing
- **Risk Optimization with Constraints**: Complex optimization with transaction costs, turnover limits

**Integration Opportunity:**
Enhance current risk calculations with institutional-grade risk metrics and optimization.

**Key Classes to Integrate:**
```python
import riskfolio as rp
from riskfolio import RiskCalculations
from riskfolio import PortfolioOptimization
from riskfolio import Reports
```

### 1.3 QuantLib (v1.40) - Quantitative Finance Framework

**Core Capabilities:**
- **Derivatives Pricing**: Options, futures, swaps pricing models
- **Interest Rate Models**: Term structure modeling and bond analytics
- **Risk Management**: VaR, CVaR, credit risk models
- **Monte Carlo Simulation**: Path-dependent derivatives and risk simulations

**Integration Opportunity:**
Add options pricing, credit risk analysis, and advanced risk simulation capabilities.

**Key Classes to Integrate:**
```python
import QuantLib as ql
from QuantLib import *
from QuantLib import MarketModel
```

---

## 2. Current Architecture Analysis

### 2.1 Current Implementation Status

The current `AnalyticsEngine` (1,116 lines) implements basic financial analytics using:
- `quantstats`: Basic performance metrics
- `arch`: GARCH volatility models
- `statsmodels`: Simple regression models

**Current Strengths:**
- Solid async architecture with proper error handling
- Comprehensive API endpoints
- Real-time data integration
- Well-structured data flow

**Current Limitations:**
- Simplified portfolio optimization (equal weights)
- Basic risk metrics (VaR, CVaR only)
- No options pricing capabilities
- Limited factor models
- No Black-Litterman implementation

### 2.2 Integration Points with Current Portfolio Management

**Existing Data Flow:**
```
Portfolio Positions → Price Data → Returns → Analytics Engine → Risk Metrics
     ↓                      ↓           ↓              ↓               ↓
   weights → Portfolio Returns → VaR/CVaR → Risk Score → API Response
```

**Enhanced Data Flow (Proposed):**
```
Portfolio Positions → Price Data → Returns → Advanced Analytics Engine → Enhanced Risk Metrics
     ↓                      ↓           ↓              ↓                           ↓
   weights → Factor Models → Optimizations → Risk Decomposition → Comprehensive Reports
```

### 2.3 Current API Integration Points

The existing API endpoints can be enhanced:

- `/analytics/realized-risk` → Enhanced with factor models and performance attribution
- `/analytics/forecast-risk` → Advanced volatility forecasting with QuantLib models
- `/analytics/factor-exposure` → Multi-factor risk decomposition with riskfolio-lib
- `/analytics/stress-test` → Scenario analysis with Monte Carlo simulation
- `/analytics/volatility-sizing` → Portfolio optimization with PyPortfolioOpt

---

## 3. Step-by-Step Integration Plan

### Phase 1: PyPortfolioOpt Integration (Weeks 1-2)

**Objectives:**
- Replace current portfolio optimization logic
- Implement efficient frontier calculations
- Add Black-Litterman model support

**Tasks:**
1. **Update dependencies** in `analytics_engine.py`
2. **Create new optimization module** at `backend/app/services/portfolio_optimization.py`
3. **Enhance API endpoints** with optimization capabilities
4. **Add testing** for optimization functions

**Success Criteria:**
- Efficient frontier generation for portfolios
- Black-Litterman model implementation
- Performance improvements in portfolio construction

### Phase 2: riskfolio-lib Integration (Weeks 3-4)

**Objectives:**
- Enhance risk metrics and analysis
- Implement advanced risk models
- Add performance attribution

**Tasks:**
1. **Create risk analysis module** at `backend/app/services/risk_analytics.py`
2. **Update factor exposure analysis** with multi-factor models
3. **Enhance stress testing** with advanced scenario analysis
4. **Add risk decomposition** capabilities

**Success Criteria:**
- Comprehensive risk factor analysis
- Enhanced stress testing scenarios
- Performance attribution reporting

### Phase 3: QuantLib Integration (Weeks 5-6)

**Objectives:**
- Add options pricing capabilities
- Implement advanced risk simulations
- Enhance credit risk analysis

**Tasks:**
1. **Create derivatives module** at `backend/app/services/derivatives.py`
2. **Update risk models** with QuantLib implementations
3. **Add Monte Carlo simulation** capabilities
4. **Implement credit risk models**

**Success Criteria:**
- Options pricing functionality
- Advanced risk simulations
- Enhanced credit risk metrics

---

## 4. Implementation Examples

### 4.1 Replace Current Portfolio Optimization with PyPortfolioOpt

**Current Implementation (simplified):**
```python
# Current approach in analytics_engine.py line 67-73
if weights is None:
    weights = {col: 1.0/len(cols) for col in cols} if (cols := returns.columns) else {}
else:
    # Normalize weights to sum to 1
    weight_sum = sum(weights.values())
    if weight_sum > 0:
        weights = {k: v/weight_sum for k, v in weights.items()}
```

**Enhanced Implementation with PyPortfolioOpt:**
```python
from pypfopt import EfficientFrontier, expected_returns, risk_models
from pypfopt.black_litterman import BlackLittermanModel
import numpy as np

class PortfolioOptimization:
    """Enhanced portfolio optimization using PyPortfolioOpt"""
    
    def __init__(self, risk_free_rate=0.02):
        self.risk_free_rate = risk_free_rate
    
    def optimize_portfolio(
        self, 
        returns: pd.DataFrame, 
        method: str = "max_sharpe",
        constraints: Dict = None
    ) -> Dict[str, Any]:
        """
        Optimize portfolio using PyPortfolioOpt
        
        Args:
            returns: DataFrame of asset returns
            method: Optimization objective ("max_sharpe", "min_volatility", "risk_parity")
            constraints: Dictionary of optimization constraints
            
        Returns:
            Dictionary with optimization results
        """
        try:
            # Calculate expected returns and covariance matrix
            mu = expected_returns.mean_historical_return(returns)
            S = risk_models.sample_cov(returns)
            
            # Initialize optimizer
            ef = EfficientFrontier(mu, S)
            
            # Apply constraints if provided
            if constraints:
                self._apply_constraints(ef, constraints)
            
            # Perform optimization based on method
            if method == "max_sharpe":
                weights = ef.max_sharpe(risk_free_rate=self.risk_free_rate)
            elif method == "min_volatility":
                weights = ef.min_volatility()
            elif method == "risk_parity":
                weights = ef.risk_parity()
            else:
                weights = ef.max_sharpe(risk_free_rate=self.risk_free_rate)
            
            # Clean and format results
            weights_clean = ef.clean_weights()
            
            # Calculate performance metrics
            performance = ef.portfolio_performance(
                risk_free_rate=self.risk_free_rate
            )
            
            # Get efficient frontier points for plotting
            ef_points = self._get_efficient_frontier(ef)
            
            return {
                "weights": weights_clean,
                "expected_return": performance[0],
                "expected_volatility": performance[1],
                "sharpe_ratio": performance[2],
                "efficient_frontier": ef_points,
                "method": method,
                "num_assets": len(returns.columns),
                "optimization_success": True
            }
            
        except Exception as e:
            logger.error(f"Portfolio optimization error: {e}")
            return self._fallback_optimization(returns)
    
    def black_litterman_optimization(
        self, 
        returns: pd.DataFrame, 
        market_caps: Dict[str, float],
        views: Dict[str, float],
        tau: float = 0.025
    ) -> Dict[str, Any]:
        """
        Black-Litterman model implementation
        
        Args:
            returns: Historical returns
            market_caps: Market capitalizations for assets
            views: Investor views on asset returns
            tau: Uncertainty scalar
            
        Returns:
            Dictionary with Black-Litterman optimization results
        """
        try:
            # Calculate expected returns and covariance
            mu = expected_returns.mean_historical_return(returns)
            S = risk_models.sample_cov(returns)
            
            # Prepare market capitalizations
            market_caps_array = np.array([market_caps.get(asset, 1e9) 
                                        for asset in returns.columns])
            
            # Setup Black-Litterman model
            bl = BlackLittermanModel(
                cov_matrix=S,
                pi=mu,  # Prior returns
                absolute_views=views,
                market_caps=market_caps_array,
                risk_aversion=3.0,
                tau=tau
            )
            
            # Calculate posterior returns and covariance
            posterior_returns = bl.bl_returns()
            posterior_cov = bl.bl_cov()
            
            # Optimize with posterior estimates
            ef = EfficientFrontier(posterior_returns, posterior_cov)
            weights = ef.max_sharpe(risk_free_rate=self.risk_free_rate)
            
            performance = ef.portfolio_performance(
                risk_free_rate=self.risk_free_rate
            )
            
            return {
                "weights": ef.clean_weights(),
                "expected_return": performance[0],
                "expected_volatility": performance[1],
                "sharpe_ratio": performance[2],
                "prior_returns": mu.to_dict(),
                "posterior_returns": posterior_returns.to_dict(),
                "views_used": views,
                "method": "black_litterman",
                "optimization_success": True
            }
            
        except Exception as e:
            logger.error(f"Black-Litterman optimization error: {e}")
            return self._fallback_optimization(returns)
    
    def _apply_constraints(self, ef: EfficientFrontier, constraints: Dict):
        """Apply optimization constraints"""
        try:
            if "max_weight" in constraints:
                ef.efficient_risk(
                    target_risk=constraints["max_weight"],
                    market_neutral=False
                )
            if "min_weight" in constraints:
                # Set minimum weight constraints
                for asset, min_w in constraints["min_weight"].items():
                    ef.add_constraint(lambda w: w[asset] >= min_w)
        except Exception as e:
            logger.warning(f"Constraint application warning: {e}")
    
    def _get_efficient_frontier(self, ef: EfficientFrontier) -> List[Dict]:
        """Generate efficient frontier points"""
        try:
            # Get efficient frontier points
            ef_points = []
            target_vols = np.linspace(0.1, 0.5, 50)
            
            for vol in target_vols:
                try:
                    weights = ef.efficient_risk(target_vol=vol)
                    performance = ef.portfolio_performance(
                        risk_free_rate=self.risk_free_rate
                    )
                    ef_points.append({
                        "expected_return": performance[0],
                        "expected_volatility": performance[1],
                        "sharpe_ratio": performance[2],
                        "weights": ef.clean_weights()
                    })
                except:
                    continue
            
            return ef_points
            
        except Exception as e:
            logger.error(f"Efficient frontier generation error: {e}")
            return []
    
    def _fallback_optimization(self, returns: pd.DataFrame) -> Dict[str, Any]:
        """Fallback to equal weights"""
        num_assets = len(returns.columns)
        equal_weight = 1.0 / num_assets
        weights = {asset: equal_weight for asset in returns.columns}
        
        return {
            "weights": weights,
            "expected_return": 0.0,
            "expected_volatility": 0.20,
            "sharpe_ratio": 0.0,
            "method": "equal_weight_fallback",
            "optimization_success": False
        }
```

### 4.2 Enhanced Risk Metrics with riskfolio-lib

**Current Implementation (simplified):**
```python
# Current VaR calculation in analytics_engine.py line 672-676
var_95 = np.percentile(returns, 5)
cvar_95 = returns[returns <= var_95].mean() if len(returns[returns <= var_95]) > 0 else var_95
```

**Enhanced Implementation with riskfolio-lib:**
```python
import riskfolio as rp
from riskfolio import RiskCalculations

class AdvancedRiskAnalytics:
    """Advanced risk analytics using riskfolio-lib"""
    
    def __init__(self, returns: pd.DataFrame, weights: Dict[str, float]):
        self.returns = returns
        self.weights = weights
        self.risk_calc = RiskCalculations(returns)
    
    def calculate_comprehensive_risk_metrics(self) -> Dict[str, Any]:
        """Calculate comprehensive risk metrics using riskfolio-lib"""
        try:
            # Convert weights to numpy array
            w = np.array([self.weights.get(asset, 0) for asset in self.returns.columns])
            
            # Calculate VaR and CVaR with multiple confidence levels
            var_levels = [0.95, 0.99, 0.995]
            var_metrics = {}
            
            for level in var_levels:
                var = rp.VaR_CVaR(self.returns, alpha=level, kind='Historical')
                cvar = rp.CVaR(self.returns, alpha=level, kind='Historical')
                
                var_metrics[f"var_{int(level*100)}"] = var
                var_metrics[f"cvar_{int(level*100)}"] = cvar
            
            # Calculate drawdown metrics
            drawdown = rp.Drawdowns(self.returns)
            max_drawdown = drawdown.max_drawdown()
            avg_drawdown = drawdown.mean_drawdown()
            drawdown_duration = drawdown.max_drawdown_duration()
            
            # Calculate correlation metrics
            corr_matrix = self.returns.corr()
            diversification_ratio = rp.Diversification_ratio(w, self.returns)
            
            # Calculate risk decomposition
            risk_decomposition = self._calculate_risk_decomposition(w)
            
            # Calculate factor risk metrics
            factor_risks = self._calculate_factor_risks()
            
            # Calculate expected shortfall
            expected_shortfall = rp.CVaR(self.returns, alpha=0.95, kind='Normal')
            
            # Calculate tail risk metrics
            tail_ratio = rp.Tail_Ratio(self.returns)
           Sortino = rp.Sortino_Ratio(self.returns)
            
            return {
                "var_metrics": var_metrics,
                "drawdown_metrics": {
                    "max_drawdown": max_drawdown,
                    "average_drawdown": avg_drawdown,
                    "drawdown_duration": drawdown_duration
                },
                "correlation_metrics": {
                    "correlation_matrix": corr_matrix.to_dict(),
                    "diversification_ratio": diversification_ratio
                },
                "risk_decomposition": risk_decomposition,
                "factor_risks": factor_risks,
                "tail_risk_metrics": {
                    "expected_shortfall": expected_shortfall,
                    "tail_ratio": tail_ratio,
                    "sortino_ratio": Sortino
                },
                "risk_level": self._assess_risk_level(var_metrics.get("var_95", 0))
            }
            
        except Exception as e:
            logger.error(f"Advanced risk calculation error: {e}")
            return self._fallback_risk_metrics()
    
    def calculate_stress_scenarios(self, scenarios: List[str]) -> Dict[str, Any]:
        """Advanced stress testing with historical scenarios"""
        try:
            stress_results = {}
            
            for scenario in scenarios:
                # Get historical data for stress scenario
                scenario_data = self._get_scenario_data(scenario)
                
                if scenario_data is not None:
                    # Calculate scenario portfolio returns
                    scenario_returns = (scenario_data * 
                                      np.array([self.weights.get(asset, 0) 
                                               for asset in self.returns.columns])).sum(axis=1)
                    
                    # Calculate stress metrics
                    scenario_var = rp.VaR_CVaR(scenario_returns, alpha=0.95)
                    scenario_max_dd = rp.Drawdowns(scenario_returns).max_drawdown()
                    
                    stress_results[scenario] = {
                        "portfolio_var_95": scenario_var,
                        "max_drawdown": scenario_max_dd,
                        "scenario_returns": scenario_returns.to_dict(),
                        "volatility": scenario_returns.std() * np.sqrt(252)
                    }
                else:
                    stress_results[scenario] = self._get_default_stress_scenario(scenario)
            
            return {
                "scenarios": stress_results,
                "methodology": "Historical scenario analysis with riskfolio-lib",
                "confidence_level": 0.95
            }
            
        except Exception as e:
            logger.error(f"Stress scenario calculation error: {e}")
            return {"scenarios": {}, "error": str(e)}
    
    def _calculate_risk_decomposition(self, w: np.ndarray) -> Dict[str, Any]:
        """Calculate risk decomposition using riskfolio-lib"""
        try:
            # Calculate marginal risk contributions
            marginal_contrib = rp.MCR_CVaR(self.returns, w, alpha=0.95)
            
            # Calculate component risk contributions
            component_contrib = rp.CVaR_decomposition(self.returns, w, alpha=0.95)
            
            # Calculate percentage contributions
            total_cvar = rp.CVaR(self.returns, alpha=0.95, w=w)
            pct_contrib = {asset: contrib/total_cvar for asset, contrib in component_contrib.items()}
            
            return {
                "marginal_contributions": marginal_contrib,
                "component_contributions": component_contrib,
                "percentage_contributions": pct_contrib,
                "total_cvar": total_cvar
            }
            
        except Exception as e:
            logger.error(f"Risk decomposition error: {e}")
            return {}
    
    def _calculate_factor_risks(self) -> Dict[str, float]:
        """Calculate factor-based risk metrics"""
        try:
            # Define factor returns (simplified - would need real factor data)
            factors = {
                'market': self.returns.mean(axis=1),  # Proxy for market factor
                'size': self.returns.rolling(252).std(),  # Proxy for size factor
                'value': self.returns.rolling(60).mean(),  # Proxy for value factor
            }
            
            factor_exposures = {}
            for factor_name, factor_data in factors.items():
                # Calculate correlation with portfolio
                portfolio_returns = (self.returns * 
                                   np.array([self.weights.get(asset, 0) 
                                            for asset in self.returns.columns])).sum(axis=1)
                
                correlation = portfolio_returns.corr(factor_data.dropna())
                factor_exposures[factor_name] = correlation
            
            return factor_exposures
            
        except Exception as e:
            logger.error(f"Factor risk calculation error: {e}")
            return {}
    
    def _get_scenario_data(self, scenario: str) -> pd.DataFrame:
        """Get historical data for stress scenario"""
        # Historical stress periods
        scenarios_data = {
            "2008_crisis": ("2007-10-01", "2009-03-01"),
            "covid_crash": ("2020-02-19", "2020-03-23"),
            "inflation_spike": ("2022-01-03", "2022-10-12"),
            "china_slowdown": ("2015-08-17", "2016-02-11")
        }
        
        if scenario in scenarios_data:
            start_date, end_date = scenarios_data[scenario]
            # Filter returns data for scenario period
            return self.returns.loc[start_date:end_date]
        
        return None
    
    def _get_default_stress_scenario(self, scenario: str) -> Dict[str, float]:
        """Get default stress scenario results"""
        return {
            "portfolio_var_95": -0.15,
            "max_drawdown": -0.25,
            "volatility": 0.30,
            "note": "Default stress scenario (insufficient historical data)"
        }
    
    def _fallback_risk_metrics(self) -> Dict[str, Any]:
        """Fallback risk metrics"""
        return {
            "var_95": -0.05,
            "cvar_95": -0.08,
            "max_drawdown": -0.20,
            "diversification_ratio": 1.0,
            "methodology": "Fallback metrics"
        }
    
    def _assess_risk_level(self, var_95: float) -> str:
        """Assess overall risk level"""
        if var_95 > -0.02:
            return "LOW"
        elif var_95 > -0.05:
            return "MEDIUM"
        else:
            return "HIGH"
```

### 4.3 Options Pricing with QuantLib

**New Implementation for Derivatives:**
```python
from QuantLib import *
import QuantLib as ql

class DerivativesAnalytics:
    """Options and derivatives analytics using QuantLib"""
    
    def __init__(self):
        # Initialize QuantLib calendar and evaluation date
        self.calendar = UnitedStates()
        self.evaluation_date = Date.todaysDate()
        self.day_count = Actual365Fixed()
        
        # Setup market data handlers
        self.spot_prices = {}
        self.volatility_surfaces = {}
        self.rate_curves = {}
    
    def price_option(
        self,
        option_type: str,
        spot_price: float,
        strike_price: float,
        time_to_expiry: float,
        risk_free_rate: float,
        volatility: float,
        dividend_yield: float = 0.0
    ) -> Dict[str, Any]:
        """
        Price European option using Black-Scholes
        
        Args:
            option_type: "call" or "put"
            spot_price: Current stock price
            strike_price: Option strike price
            time_to_expiry: Time to expiry in years
            risk_free_rate: Risk-free rate
            volatility: Volatility
            dividend_yield: Dividend yield
            
        Returns:
            Dictionary with option pricing results
        """
        try:
            # Setup QuantLib instruments
            payoff = PlainVanillaPayoff(
                Option.Call if option_type.lower() == 'call' else Option.Put,
                strike_price
            )
            
            exercise = EuropeanExercise(
                self.evaluation_date + Period(int(time_to_expiry * 365), Days)
            )
            
            vanilla_option = VanillaOption(payoff, exercise)
            
            # Black-Scholes model
            black_scholes_process = BlackScholesProcess(
                QuoteHandle(SimpleQuote(spot_price)),
                YieldTermStructureHandle(
                    FlatForward(self.evaluation_date, dividend_yield, self.day_count)
                ),
                YieldTermStructureHandle(
                    FlatForward(self.evaluation_date, risk_free_rate, self.day_count)
                ),
                BlackVolTermStructureHandle(
                    BlackConstantVol(self.evaluation_date, self.calendar, volatility, self.day_count)
                )
            )
            
            # Calculate price and Greeks
            engine = AnalyticEuropeanEngine(black_scholes_process)
            vanilla_option.setPricingEngine(engine)
            
            price = vanilla_option.NPV()
            delta = vanilla_option.delta()
            gamma = vanilla_option.gamma()
            vega = vanilla_option.vega()
            theta = vanilla_option.theta()
            rho = vanilla_option.rho()
            
            # Calculate theoretical value vs intrinsic value
            intrinsic_value = max(0, (spot_price - strike_price) if option_type.lower() == 'call' 
                                else (strike_price - spot_price))
            time_value = price - intrinsic_value
            
            # Implied volatility calculation
            try:
                vol_engine = ImpliedVolatilityHelper(black_scholes_process)
                # This would require市场价格 for proper calculation
                implied_vol = volatility  # Placeholder
            except:
                implied_vol = volatility
            
            return {
                "option_price": price,
                "intrinsic_value": intrinsic_value,
                "time_value": time_value,
                "greeks": {
                    "delta": delta,
                    "gamma": gamma,
                    "vega": vega,
                    "theta": theta,
                    "rho": rho
                },
                "implied_volatility": implied_vol,
                " moneyness": self._calculate_moneyness(spot_price, strike_price, time_to_expiry, risk_free_rate),
                "break_even": self._calculate_break_even(spot_price, strike_price, price, option_type),
                "put_call_parity": self._verify_put_call_parity(spot_price, strike_price, 
                                                               time_to_expiry, risk_free_rate, volatility),
                "methodology": "Black-Scholes with QuantLib analytical engine"
            }
            
        except Exception as e:
            logger.error(f"Option pricing error: {e}")
            return self._fallback_option_pricing(option_type, spot_price, strike_price, volatility)
    
    def portfolio_options_valuation(
        self,
        options_data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Portfolio-level options valuation
        
        Args:
            options_data: List of option contracts with specifications
            
        Returns:
            Portfolio valuation results
        """
        try:
            portfolio_results = {
                "total_portfolio_value": 0.0,
                "options": [],
                "greeks_portfolio": {
                    "delta": 0.0,
                    "gamma": 0.0,
                    "vega": 0.0,
                    "theta": 0.0,
                    "rho": 0.0
                },
                "risk_metrics": {}
            }
            
            for option_spec in options_data:
                # Price individual option
                option_result = self.price_option(**option_spec)
                
                # Add position size (assuming quantity)
                quantity = option_spec.get("quantity", 1)
                position_value = option_result["option_price"] * quantity
                portfolio_results["total_portfolio_value"] += position_value
                
                # Update portfolio Greeks
                for greek in portfolio_results["greeks_portfolio"]:
                    portfolio_results["greeks_portfolio"][greek] += (
                        option_result["greeks"][greek] * quantity
                    )
                
                portfolio_results["options"].append({
                    **option_spec,
                    "valuation": option_result,
                    "position_value": position_value
                })
            
            # Calculate portfolio risk metrics
            portfolio_results["risk_metrics"] = self._calculate_portfolio_risk_metrics(portfolio_results)
            
            return portfolio_results
            
        except Exception as e:
            logger.error(f"Portfolio options valuation error: {e}")
            return {"options": [], "error": str(e)}
    
    def monte_carlo_var(
        self,
        returns: pd.Series,
        confidence_level: float = 0.95,
        simulation_days: int = 252,
        num_simulations: int = 10000
    ) -> Dict[str, Any]:
        """
        Monte Carlo VaR calculation using QuantLib
        
        Args:
            returns: Historical returns
            confidence_level: VaR confidence level
            simulation_days: Days to simulate
            num_simulations: Number of Monte Carlo paths
            
        Returns:
            Monte Carlo VaR results
        """
        try:
            # Calculate historical parameters
            mean_return = returns.mean()
            volatility = returns.std()
            
            # Setup Monte Carlo simulation
            time_steps = simulation_days
            dt = 1.0 / 252  # Daily time step
            
            # Generate random paths
            np.random.seed(42)  # For reproducibility
            
            # Geometric Brownian Motion simulation
            drift = (mean_return - 0.5 * volatility**2) * dt
            diffusion = volatility * np.sqrt(dt)
            
            # Generate random price paths
            random_shocks = np.random.normal(0, 1, (num_simulations, time_steps))
            log_returns = drift + diffusion * random_shocks
            
            # Calculate final portfolio values
            initial_value = 1.0  # Normalized to 1
            final_values = initial_value * np.exp(np.cumsum(log_returns, axis=1))
            
            # Calculate VaR
            losses = initial_value - final_values[:, -1]
            var_value = np.percentile(losses, (1 - confidence_level) * 100)
            
            # Calculate expected shortfall (conditional VaR)
            tail_losses = losses[losses >= var_value]
            expected_shortfall = np.mean(tail_losses) if len(tail_losses) > 0 else var_value
            
            # Portfolio metrics
            final_value_mean = np.mean(final_values[:, -1])
            final_value_std = np.std(final_values[:, -1])
            
            # Calculate probability of loss
            prob_loss = np.mean(losses > 0)
            
            return {
                "var": var_value,
                "expected_shortfall": expected_shortfall,
                "confidence_level": confidence_level,
                "simulation_days": simulation_days,
                "num_simulations": num_simulations,
                "portfolio_metrics": {
                    "expected_final_value": final_value_mean,
                    "volatility": final_value_std,
                    "probability_of_loss": prob_loss
                },
                "methodology": "Monte Carlo simulation with Geometric Brownian Motion"
            }
            
        except Exception as e:
            logger.error(f"Monte Carlo VaR error: {e}")
            return {"error": str(e)}
    
    def _calculate_moneyness(
        self, 
        spot_price: float, 
        strike_price: float, 
        time_to_expiry: float, 
        risk_free_rate: float
    ) -> float:
        """Calculate option moneyness"""
        forward_price = spot_price * np.exp(risk_free_rate * time_to_expiry)
        return spot_price / strike_price, forward_price / strike_price
    
    def _calculate_break_even(
        self, 
        spot_price: float, 
        strike_price: float, 
        option_price: float, 
        option_type: str
    ) -> float:
        """Calculate break-even price"""
        if option_type.lower() == 'call':
            return strike_price + option_price
        else:  # put
            return strike_price - option_price
    
    def _verify_put_call_parity(
        self, 
        spot_price: float, 
        strike_price: float, 
        time_to_expiry: float, 
        risk_free_rate: float, 
        volatility: float
    ) -> Dict[str, Any]:
        """Verify put-call parity"""
        try:
            call_price = self.price_option("call", spot_price, strike_price, 
                                         time_to_expiry, risk_free_rate, volatility)
            put_price = self.price_option("put", spot_price, strike_price, 
                                        time_to_expiry, risk_free_rate, volatility)
            
            # Put-call parity: C - P = S - K*e^(-r*T)
            parity_value = call_price["option_price"] - put_price["option_price"]
            theoretical_parity = spot_price - strike_price * np.exp(-risk_free_rate * time_to_expiry)
            
            parity_error = abs(parity_value - theoretical_parity)
            
            return {
                "call_price": call_price["option_price"],
                "put_price": put_price["option_price"],
                "parity_value": parity_value,
                "theoretical_parity": theoretical_parity,
                "parity_error": parity_error,
                "is_valid": parity_error < 0.01
            }
            
        except Exception as e:
            return {"error": str(e)}
    
    def _fallback_option_pricing(
        self, 
        option_type: str, 
        spot_price: float, 
        strike_price: float, 
        volatility: float
    ) -> Dict[str, Any]:
        """Fallback option pricing using Black-Scholes"""
        try:
            # Simple Black-Scholes approximation
            d1 = (np.log(spot_price/strike_price) + 0.5 * volatility**2) / volatility
            d2 = d1 - volatility
            
            if option_type.lower() == 'call':
                price = spot_price * self._normal_cdf(d1) - strike_price * self._normal_cdf(d2)
                delta = self._normal_cdf(d1)
            else:
                price = strike_price * self._normal_cdf(-d2) - spot_price * self._normal_cdf(-d1)
                delta = self._normal_cdf(d1) - 1
            
            gamma = self._normal_pdf(d1) / (spot_price * volatility)
            vega = spot_price * self._normal_pdf(d1) * np.sqrt(1/252)  # Daily vega
            
            return {
                "option_price": price,
                "greeks": {
                    "delta": delta,
                    "gamma": gamma,
                    "vega": vega,
                    "theta": 0.0,
                    "rho": 0.0
                },
                "methodology": "Simplified Black-Scholes fallback"
            }
            
        except Exception as e:
            return {"error": str(e)}
    
    def _calculate_portfolio_risk_metrics(self, portfolio_results: Dict) -> Dict[str, Any]:
        """Calculate portfolio-level risk metrics"""
        try:
            greeks = portfolio_results["greeks_portfolio"]
            
            # Delta risk (price sensitivity)
            delta_risk = abs(greeks["delta"])
            
            # Gamma risk (convexity)
            gamma_risk = abs(greeks["gamma"])
            
            # Vega risk (volatility sensitivity)
            vega_risk = abs(greeks["vega"])
            
            # Overall portfolio risk level
            total_risk = np.sqrt(delta_risk**2 + gamma_risk**2 + vega_risk**2)
            
            return {
                "delta_risk": delta_risk,
                "gamma_risk": gamma_risk,
                "vega_risk": vega_risk,
                "overall_risk_score": total_risk,
                "risk_level": "HIGH" if total_risk > 1.0 else "MEDIUM" if total_risk > 0.5 else "LOW"
            }
            
        except Exception as e:
            return {"error": str(e)}
    
    # Normal distribution helper functions
    def _normal_cdf(self, x: float) -> float:
        """Cumulative normal distribution approximation"""
        return 0.5 * (1 + np.sign(x) * np.sqrt(1 - np.exp(-2 * x**2 / np.pi)))
    
    def _normal_pdf(self, x: float) -> float:
        """Normal probability density function"""
        return np.exp(-0.5 * x**2) / np.sqrt(2 * np.pi)
```

---

## 5. Code Integration Examples

### 5.1 Update Analytics Engine with Advanced Libraries

**Enhanced Analytics Engine Implementation:**

```python
# New imports to add to analytics_engine.py
from app.services.portfolio_optimization import PortfolioOptimization
from app.services.risk_analytics import AdvancedRiskAnalytics  
from app.services.derivatives import DerivativesAnalytics

class EnhancedAnalyticsEngine(AnalyticsEngine):
    """Enhanced analytics engine with PyPortfolioOpt, riskfolio-lib, and QuantLib"""
    
    def __init__(self):
        super().__init__()
        self.portfolio_optimizer = PortfolioOptimization()
        self.risk_analytics = None  # Initialize when data is available
        self.derivatives = DerivativesAnalytics()
        
        # Library version tracking
        self.library_versions = {
            "pypfopt": self._get_package_version("pypfopt"),
            "riskfolio": self._get_package_version("riskfolio"),
            "quantlib": self._get_package_version("QuantLib")
        }
    
    def _get_package_version(self, package_name: str) -> str:
        """Get installed package version"""
        try:
            import importlib.metadata as metadata
            return metadata.version(package_name)
        except:
            return "unknown"
    
    async def enhanced_portfolio_optimization(
        self,
        price_data: pd.DataFrame,
        method: str = "max_sharpe",
        black_litterman_views: Optional[Dict[str, float]] = None,
        constraints: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Enhanced portfolio optimization using PyPortfolioOpt
        
        Args:
            price_data: Price data DataFrame
            method: Optimization method ("max_sharpe", "min_volatility", "risk_parity")
            black_litterman_views: Black-Litterman views dict
            constraints: Optimization constraints
            
        Returns:
            Dictionary with optimization results and efficient frontier
        """
        try:
            returns = price_data.pct_change().dropna()
            
            if black_litterman_views:
                # Use Black-Litterman model
                market_caps = self._estimate_market_caps(price_data)
                optimization_result = self.portfolio_optimizer.black_litterman_optimization(
                    returns, market_caps, black_litterman_views
                )
            else:
                # Standard optimization
                optimization_result = self.portfolio_optimizer.optimize_portfolio(
                    returns, method, constraints
                )
            
            # Calculate additional metrics
            weights = optimization_result["weights"]
            portfolio_returns = (returns * np.array([weights.get(asset, 0) 
                                                   for asset in returns.columns])).sum(axis=1)
            
            # Advanced risk metrics
            if not self.risk_analytics:
                self.risk_analytics = AdvancedRiskAnalytics(returns, weights)
            
            risk_metrics = self.risk_analytics.calculate_comprehensive_risk_metrics()
            
            return {
                **optimization_result,
                "advanced_risk_metrics": risk_metrics,
                "methodology": f"{method.title()} optimization with advanced risk analytics",
                "libraries_used": self.library_versions
            }
            
        except Exception as e:
            logger.error(f"Enhanced portfolio optimization error: {e}")
            return self._fallback_optimization(price_data)
    
    async def enhanced_stress_testing(
        self,
        price_data: pd.DataFrame,
        weights: Dict[str, float],
        scenarios: List[str],
        use_quantlib_monte_carlo: bool = True
    ) -> Dict[str, Any]:
        """
        Enhanced stress testing with QuantLib Monte Carlo and riskfolio-lib scenarios
        
        Args:
            price_data: Historical price data
            weights: Portfolio weights
            scenarios: List of stress scenarios
            use_quantlib_monte_carlo: Whether to use QuantLib Monte Carlo
            
        Returns:
            Dictionary with comprehensive stress test results
        """
        try:
            returns = price_data.pct_change().dropna()
            
            # Riskfolio-lib stress testing
            if not self.risk_analytics:
                self.risk_analytics = AdvancedRiskAnalytics(returns, weights)
            
            stress_results = self.risk_analytics.calculate_stress_scenarios(scenarios)
            
            # QuantLib Monte Carlo VaR if requested
            portfolio_returns = (returns * np.array([weights.get(asset, 0) 
                                                   for asset in returns.columns])).sum(axis=1)
            
            if use_quantlib_monte_carlo:
                monte_carlo_var = self.derivatives.monte_carlo_var(portfolio_returns)
                stress_results["monte_carlo_var"] = monte_carlo_var
            
            # Historical scenario analysis
            historical_scenarios = await self._analyze_historical_scenarios(returns, weights)
            
            # Combine results
            comprehensive_results = {
                **stress_results,
                "historical_scenarios": historical_scenarios,
                "methodology": "Multi-library stress testing with historical and Monte Carlo analysis",
                "confidence_levels": [0.95, 0.99],
                "libraries_used": self.library_versions
            }
            
            return comprehensive_results
            
        except Exception as e:
            logger.error(f"Enhanced stress testing error: {e}")
            return self._fallback_stress_test(price_data, weights)
    
    async def options_portfolio_analysis(
        self,
        options_positions: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Analyze options portfolio using QuantLib
        
        Args:
            options_positions: List of options position specifications
            
        Returns:
            Dictionary with options portfolio analysis
        """
        try:
            # Portfolio valuation
            portfolio_valuation = self.derivatives.portfolio_options_valuation(options_positions)
            
            # Risk analysis
            greeks_portfolio = portfolio_valuation["greeks_portfolio"]
            
            # Calculate Greeks-based risk metrics
            risk_metrics = self._calculate_options_risk_metrics(greeks_portfolio)
            
            # Stress test options positions
            stress_scenarios = self._stress_test_options_positions(options_positions)
            
            # Calculate portfolio Greeks breakdown by expiration and strike
            greeks_breakdown = self._analyze_greeks_breakdown(options_positions)
            
            return {
                "portfolio_valuation": portfolio_valuation,
                "risk_metrics": risk_metrics,
                "stress_scenarios": stress_scenarios,
                "greeks_breakdown": greeks_breakdown,
                "methodology": "QuantLib-based options portfolio analysis",
                "libraries_used": {"QuantLib": self.library_versions["quantlib"]}
            }
            
        except Exception as e:
            logger.error(f"Options portfolio analysis error: {e}")
            return {"error": str(e)}
    
    def _estimate_market_caps(self, price_data: pd.DataFrame) -> Dict[str, float]:
        """Estimate market capitalizations for assets"""
        # Simplified market cap estimation
        # In practice, you'd fetch actual market cap data
        market_caps = {}
        for ticker in price_data.columns:
            # Approximate market cap (in billions)
            base_caps = {"AAPL": 3000, "MSFT": 2800, "GOOGL": 1800, "AMZN": 1600}
            market_caps[ticker] = base_caps.get(ticker, 100) * 1e9
        
        return market_caps
    
    async def _analyze_historical_scenarios(
        self, 
        returns: pd.DataFrame, 
        weights: Dict[str, float]
    ) -> Dict[str, Any]:
        """Analyze performance during historical market stress periods"""
        try:
            portfolio_returns = (returns * np.array([weights.get(asset, 0) 
                                                   for asset in returns.columns])).sum(axis=1)
            
            historical_periods = {
                "financial_crisis_2008": ("2007-10-01", "2009-03-01"),
                "covid_crash_2020": ("2020-02-19", "2020-03-23"),
                "inflation_spike_2022": ("2022-01-03", "2022-10-12"),
                "china_slowdown_2015": ("2015-08-17", "2016-02-11")
            }
            
            scenario_analysis = {}
            
            for period_name, (start_date, end_date) in historical_periods.items():
                try:
                    period_returns = portfolio_returns.loc[start_date:end_date]
                    
                    if not period_returns.empty:
                        scenario_analysis[period_name] = {
                            "period_return": period_returns.sum(),
                            "max_drawdown": self._calculate_max_drawdown(period_returns.cumsum()),
                            "volatility": period_returns.std() * np.sqrt(252),
                            "worst_day": period_returns.min(),
                            "best_day": period_returns.max(),
                            "days_duration": len(period_returns),
                            "negative_days": (period_returns < 0).sum(),
                            "negative_days_pct": (period_returns < 0).mean()
                        }
                    else:
                        scenario_analysis[period_name] = {"error": "Insufficient data"}
                        
                except Exception as e:
                    scenario_analysis[period_name] = {"error": str(e)}
            
            return scenario_analysis
            
        except Exception as e:
            logger.error(f"Historical scenario analysis error: {e}")
            return {}
    
    def _calculate_options_risk_metrics(self, greeks_portfolio: Dict[str, float]) -> Dict[str, Any]:
        """Calculate risk metrics specific to options portfolio"""
        try:
            delta = abs(greeks_portfolio["delta"])
            gamma = abs(greeks_portfolio["gamma"])
            vega = abs(greeks_portfolio["vega"])
            theta = abs(greeks_portfolio["theta"])
            
            # Calculate risk scores (normalized)
            risk_scores = {
                "delta_risk": min(100, delta * 100),
                "gamma_risk": min(100, gamma * 10000),  # Gamma typically much smaller
                "vega_risk": min(100, vega * 100),
                "theta_risk": min(100, theta * 100),
                "overall_options_risk": np.sqrt(delta**2 + gamma**2 + vega**2 + theta**2) * 100
            }
            
            # Risk level assessment
            overall_risk = risk_scores["overall_options_risk"]
            if overall_risk > 50:
                risk_level = "HIGH"
            elif overall_risk > 25:
                risk_level = "MEDIUM"
            else:
                risk_level = "LOW"
            
            return {
                **risk_scores,
                "risk_level": risk_level,
                "delta_neutral": delta < 0.1,
                "gamma_exposure": "POSITIVE" if gamma > 0 else "NEGATIVE",
                "vega_exposure": "POSITIVE" if vega > 0 else "NEGATIVE",
                "theta_decay_per_day": theta
            }
            
        except Exception as e:
            logger.error(f"Options risk metrics calculation error: {e}")
            return {}
    
    def _stress_test_options_positions(self, options_positions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Stress test options positions under market shocks"""
        try:
            stress_scenarios = {
                "market_crash_20pct": {"price_change": -0.20, "vol_change": 0.50},
                "market_rally_20pct": {"price_change": 0.20, "vol_change": -0.20},
                "volatility_spike": {"price_change": 0.0, "vol_change": 1.00},
                "crash_with_vol_spike": {"price_change": -0.15, "vol_change": 0.75}
            }
            
            stress_results = {}
            
            for scenario_name, shock_params in stress_scenarios.items():
                scenario_pnl = 0
                affected_positions = 0
                
                for position in options_positions:
                    try:
                        # Simplified P&L calculation under stress
                        position_pnl = self._calculate_stress_pnl(position, shock_params)
                        scenario_pnl += position_pnl
                        affected_positions += 1
                    except:
                        continue
                
                stress_results[scenario_name] = {
                    "scenario_pnl": scenario_pnl,
                    "positions_affected": affected_positions,
                    "average_pnl_per_position": scenario_pnl / max(1, affected_positions),
                    "shock_parameters": shock_params
                }
            
            return stress_results
            
        except Exception as e:
            logger.error(f"Options stress testing error: {e}")
            return {}
    
    def _calculate_stress_pnl(self, position: Dict[str, Any], shock_params: Dict[str, float]) -> float:
        """Calculate P&L for option position under stress scenario"""
        try:
            option_type = position.get("option_type", "call")
            quantity = position.get("quantity", 1)
            current_price = position.get("current_price", 100)
            
            price_change = shock_params["price_change"]
            vol_change = shock_params["vol_change"]
            
            # Simplified stress P&L calculation
            # In practice, would re-price option under stress
            delta_impact = price_change * (1 if option_type.lower() == 'call' else -1)
            vega_impact = vol_change * 0.1  # Simplified vega impact
            
            total_impact = delta_impact + vega_impact
            pnl = total_impact * quantity * current_price
            
            return pnl
            
        except:
            return 0.0
    
    def _analyze_greeks_breakdown(self, options_positions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze Greeks breakdown by expiration and strike"""
        try:
            breakdown = {
                "by_expiration": {},
                "by_strike": {},
                "net_exposure": {"delta": 0, "gamma": 0, "vega": 0, "theta": 0}
            }
            
            for position in options_positions:
                expiry = position.get("expiry", "unknown")
                strike = position.get("strike", "unknown")
                quantity = position.get("quantity", 1)
                option_type = position.get("option_type", "call")
                
                # Simplified Greeks calculation
                delta = 0.5 if option_type.lower() == 'call' else -0.5
                gamma = 0.1
                vega = 0.2
                theta = -0.01
                
                # Weight by quantity
                delta *= quantity
                gamma *= quantity
                vega *= quantity
                theta *= quantity
                
                # Accumulate by expiration
                if expiry not in breakdown["by_expiration"]:
                    breakdown["by_expiration"][expiry] = {"delta": 0, "gamma": 0, "vega": 0, "theta": 0}
                
                breakdown["by_expiration"][expiry]["delta"] += delta
                breakdown["by_expiration"][expiry]["gamma"] += gamma
                breakdown["by_expiration"][expiry]["vega"] += vega
                breakdown["by_expiration"][expiry]["theta"] += theta
                
                # Accumulate by strike
                if strike not in breakdown["by_strike"]:
                    breakdown["by_strike"][strike] = {"delta": 0, "gamma": 0, "vega": 0, "theta": 0}
                
                breakdown["by_strike"][strike]["delta"] += delta
                breakdown["by_strike"][strike]["gamma"] += gamma
                breakdown["by_strike"][strike]["vega"] += vega
                breakdown["by_strike"][strike]["theta"] += theta
                
                # Net exposure
                breakdown["net_exposure"]["delta"] += delta
                breakdown["net_exposure"]["gamma"] += gamma
                breakdown["net_exposure"]["vega"] += vega
                breakdown["net_exposure"]["theta"] += theta
            
            return breakdown
            
        except Exception as e:
            logger.error(f"Greeks breakdown analysis error: {e}")
            return {}
    
    def _fallback_optimization(self, price_data: pd.DataFrame) -> Dict[str, Any]:
        """Fallback optimization when advanced libraries fail"""
        try:
            returns = price_data.pct_change().dropna()
            weights = {col: 1.0/len(returns.columns) for col in returns.columns}
            
            return {
                "weights": weights,
                "expected_return": returns.mean().mean() * 252,
                "expected_volatility": returns.std().mean() * np.sqrt(252),
                "sharpe_ratio": 0.0,
                "method": "equal_weight_fallback",
                "libraries_used": self.library_versions,
                "fallback_reason": "Advanced optimization failed"
            }
            
        except Exception as e:
            logger.error(f"Fallback optimization error: {e}")
            return {"error": str(e)}
    
    def _fallback_stress_test(
        self, 
        price_data: pd.DataFrame, 
        weights: Dict[str, float]
    ) -> Dict[str, Any]:
        """Fallback stress test when advanced libraries fail"""
        try:
            returns = price_data.pct_change().dropna()
            portfolio_returns = (returns * np.array([weights.get(asset, 0) 
                                                   for asset in returns.columns])).sum(axis=1)
            
            max_drawdown = self._calculate_max_drawdown(portfolio_returns.cumsum())
            
            return {
                "scenarios": {
                    "default_stress": {
                        "max_drawdown": max_drawdown,
                        "portfolio_var_95": np.percentile(portfolio_returns, 5),
                        "note": "Fallback stress test due to advanced library failure"
                    }
                },
                "methodology": "Fallback stress testing",
                "libraries_used": self.library_versions
            }
            
        except Exception as e:
            logger.error(f"Fallback stress test error: {e}")
            return {"error": str(e)}
```

### 5.2 Enhanced API Endpoints

**New API Endpoints to Add:**

```python
# Add to backend/app/api/analytics.py

@router.post("/portfolio-optimization")
async def optimize_portfolio(
    request: PortfolioOptimizationRequest,
    data_service: DataService = Depends(get_data_service),
    analytics_engine: AnalyticsEngine = Depends(get_analytics_engine)
) -> Dict:
    """
    Advanced portfolio optimization using PyPortfolioOpt
    """
    try:
        # Fetch price data
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=252)).strftime('%Y-%m-%d')
        
        price_data_dict = {}
        for ticker in request.tickers:
            df = await data_service.fetch_historical_data(ticker, start, end)
            if df is not None and not df.empty:
                price_data_dict[ticker] = df['adj_close'] if 'adj_close' in df.columns else df['close']
        
        if not price_data_dict:
            return {
                "error": "Insufficient price data for optimization",
                "available_tickers": list(price_data_dict.keys())
            }
        
        price_data = pd.DataFrame(price_data_dict)
        
        # Perform optimization
        optimization_result = await analytics_engine.enhanced_portfolio_optimization(
            price_data, 
            method=request.method,
            black_litterman_views=request.black_litterman_views,
            constraints=request.constraints
        )
        
        return {
            **optimization_result,
            "request": {
                "tickers": request.tickers,
                "method": request.method,
                "constraints": request.constraints
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Portfolio optimization error: {e}")
        raise HTTPException(status_code=500, detail=f"Optimization failed: {str(e)}")

@router.post("/advanced-stress-test")
async def advanced_stress_test(
    request: AdvancedStressTestRequest,
    data_service: DataService = Depends(get_data_service),
    analytics_engine: AnalyticsEngine = Depends(get_analytics_engine)
) -> Dict:
    """
    Advanced stress testing with QuantLib and riskfolio-lib
    """
    try:
        # Fetch price data
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=756)).strftime('%Y-%m-%d')
        
        price_data_dict = {}
        for ticker in request.tickers:
            df = await data_service.fetch_historical_data(ticker, start, end)
            if df is not None and not df.empty:
                price_data_dict[ticker] = df['adj_close'] if 'adj_close' in df.columns else df['close']
        
        if not price_data_dict:
            return {"error": "Insufficient price data for stress testing"}
        
        price_data = pd.DataFrame(price_data_dict)
        
        # Perform advanced stress testing
        stress_result = await analytics_engine.enhanced_stress_testing(
            price_data, 
            request.weights, 
            request.scenarios,
            use_quantlib_monte_carlo=request.use_quantlib_monte_carlo
        )
        
        return {
            **stress_result,
            "request": {
                "tickers": request.tickers,
                "weights": request.weights,
                "scenarios": request.scenarios,
                "monte_carlo_enabled": request.use_quantlib_monte_carlo
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Advanced stress test error: {e}")
        raise HTTPException(status_code=500, detail=f"Stress testing failed: {str(e)}")

@router.post("/options-analysis")
async def analyze_options_portfolio(
    request: OptionsPortfolioRequest,
    analytics_engine: AnalyticsEngine = Depends(get_analytics_engine)
) -> Dict:
    """
    Options portfolio analysis using QuantLib
    """
    try:
        # Analyze options portfolio
        analysis_result = await analytics_engine.options_portfolio_analysis(
            request.options_positions
        )
        
        return {
            **analysis_result,
            "request": {
                "num_positions": len(request.options_positions),
                "portfolio_summary": request.options_positions[:5]  # Show first 5 for reference
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Options analysis error: {e}")
        raise HTTPException(status_code=500, detail=f"Options analysis failed: {str(e)}")

@router.get("/efficient-frontier")
async def get_efficient_frontier(
    tickers: str = Query(..., description="Comma-separated tickers"),
    method: str = Query(default="max_sharpe", description="Optimization method"),
    points: int = Query(default=50, ge=10, le=200, description="Number of frontier points"),
    data_service: DataService = Depends(get_data_service),
    analytics_engine: AnalyticsEngine = Depends(get_analytics_engine)
) -> Dict:
    """
    Generate efficient frontier for portfolio optimization
    """
    try:
        # Parse tickers
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
        
        # Fetch price data
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=252)).strftime('%Y-%m-%d')
        
        price_data_dict = {}
        for ticker in ticker_list:
            df = await data_service.fetch_historical_data(ticker, start, end)
            if df is not None and not df.empty:
                price_data_dict[ticker] = df['adj_close'] if 'adj_close' in df.columns else df['close']
        
        if not price_data_dict:
            return {"error": "Insufficient price data for efficient frontier"}
        
        price_data = pd.DataFrame(price_data_dict)
        
        # Generate efficient frontier points
        efficient_frontier = analytics_engine.portfolio_optimizer.get_efficient_frontier_points(
            price_data.pct_change().dropna(), 
            points
        )
        
        # Get optimal portfolio
        optimal_portfolio = await analytics_engine.enhanced_portfolio_optimization(
            price_data, method
        )
        
        return {
            "efficient_frontier": efficient_frontier,
            "optimal_portfolio": optimal_portfolio,
            "methodology": f"Efficient frontier with {points} points using {method} optimization",
            "tickers": ticker_list,
            "data_range": {"start": start, "end": end},
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Efficient frontier error: {e}")
        raise HTTPException(status_code=500, detail=f"Efficient frontier generation failed: {str(e)}")
```

### 5.3 New Pydantic Schemas

**Enhanced Request/Response Schemas:**

```python
# Add to backend/app/models/schemas.py

class PortfolioOptimizationRequest(BaseModel):
    """Schema for portfolio optimization request"""
    tickers: List[str] = Field(..., min_items=2, max_items=50, description="List of asset tickers")
    method: str = Field(default="max_sharpe", description="Optimization method")
    constraints: Optional[Dict[str, Any]] = Field(None, description="Optimization constraints")
    black_litterman_views: Optional[Dict[str, float]] = Field(None, description="Black-Litterman views")
    target_return: Optional[float] = Field(None, gt=0, description="Target return")
    risk_aversion: float = Field(default=3.0, gt=0, description="Risk aversion parameter")
    
    @validator('method')
    def validate_method(cls, v):
        valid_methods = ["max_sharpe", "min_volatility", "risk_parity", "max_return", "black_litterman"]
        if v not in valid_methods:
            raise ValueError(f'Invalid method. Must be one of: {valid_methods}')
        return v

class AdvancedStressTestRequest(BaseModel):
    """Schema for advanced stress testing request"""
    tickers: List[str] = Field(..., min_items=1, description="Portfolio tickers")
    weights: Dict[str, float] = Field(..., description="Portfolio weights")
    scenarios: List[str] = Field(default=["2018_q4", "2020_covid", "2022_inflation"], 
                                description="Stress scenarios to test")
    use_quantlib_monte_carlo: bool = Field(default=True, description="Use QuantLib Monte Carlo")
    confidence_levels: List[float] = Field(default=[0.95, 0.99], 
                                          description="VaR confidence levels")
    
    @validator('scenarios')
    def validate_scenarios(cls, v):
        valid_scenarios = ["2018_q4", "2020_covid", "2022_inflation", "china_slowdown", 
                          "market_crash_20pct", "volatility_spike", "credit_crisis"]
        for scenario in v:
            if scenario not in valid_scenarios:
                logger.warning(f"Unknown scenario: {scenario}")
        return v

class OptionsPosition(BaseModel):
    """Schema for individual options position"""
    ticker: str = Field(..., description="Underlying asset ticker")
    option_type: str = Field(..., description="Option type: 'call' or 'put'")
    strike: float = Field(..., gt=0, description="Option strike price")
    expiry: str = Field(..., description="Option expiry date (YYYY-MM-DD)")
    quantity: int = Field(..., description="Number of contracts (positive=long, negative=short)")
    current_price: float = Field(..., gt=0, description="Current option price")
    implied_volatility: float = Field(..., gt=0, lt=1, description="Current implied volatility")
    risk_free_rate: float = Field(default=0.02, description="Risk-free rate")
    dividend_yield: float = Field(default=0.0, ge=0, lt=0.1, description="Dividend yield")
    
    @validator('option_type')
    def validate_option_type(cls, v):
        if v.lower() not in ['call', 'put']:
            raise ValueError('Option type must be "call" or "put"')
        return v.lower()

class OptionsPortfolioRequest(BaseModel):
    """Schema for options portfolio analysis request"""
    options_positions: List[OptionsPosition] = Field(..., min_items=1, description="List of options positions")
    portfolio_value: Optional[float] = Field(None, gt=0, description="Total portfolio value")
    currency: str = Field(default="USD", description="Portfolio currency")
    use_quantlib: bool = Field(default=True, description="Use QuantLib for analysis")

class EfficientFrontierRequest(BaseModel):
    """Schema for efficient frontier request"""
    tickers: List[str] = Field(..., min_items=2, max_items=20, description="Portfolio tickers")
    method: str = Field(default="max_sharpe", description="Optimization method")
    num_points: int = Field(default=50, ge=10, le=200, description="Number of frontier points")
    constraints: Optional[Dict[str, Any]] = Field(None, description="Portfolio constraints")

# Response schemas for advanced analytics
class OptimizationResponse(BaseModel):
    """Schema for portfolio optimization response"""
    weights: Dict[str, float]
    expected_return: float
    expected_volatility: float
    sharpe_ratio: float
    efficient_frontier: Optional[List[Dict[str, float]]] = None
    method: str
    library_version: str
    optimization_success: bool

class StressTestResponse(BaseModel):
    """Schema for enhanced stress test response"""
    scenarios: Dict[str, Dict[str, float]]
    monte_carlo_var: Optional[Dict[str, Any]] = None
    historical_scenarios: Dict[str, Dict[str, Any]]
    methodology: str
    confidence_levels: List[float]

class OptionsAnalysisResponse(BaseModel):
    """Schema for options portfolio analysis response"""
    portfolio_valuation: Dict[str, Any]
    risk_metrics: Dict[str, Any]
    stress_scenarios: Dict[str, Any]
    greeks_breakdown: Dict[str, Any]
    methodology: str

class EfficientFrontierResponse(BaseModel):
    """Schema for efficient frontier response"""
    efficient_frontier: List[Dict[str, float]]
    optimal_portfolio: Dict[str, Any]
    methodology: str
    ticker_count: int
    data_range: Dict[str, str]
```

---

## 6. Performance Considerations

### 6.1 Caching Strategies

**Implement Redis/Memory Caching for Expensive Calculations:**

```python
from app.services.cache_service import CacheService
import json
from datetime import timedelta

class CachedAnalyticsEngine(EnhancedAnalyticsEngine):
    """Analytics engine with caching for performance optimization"""
    
    def __init__(self, cache_service: CacheService):
        super().__init__()
        self.cache_service = cache_service
        self.cache_ttl = {
            "portfolio_optimization": 3600,  # 1 hour
            "risk_metrics": 1800,            # 30 minutes
            "stress_testing": 7200,          # 2 hours
            "options_valuation": 900,        # 15 minutes
            "efficient_frontier": 3600       # 1 hour
        }
    
    async def get_cached_optimization(
        self,
        tickers: List[str],
        method: str,
        cache_key_prefix: str = "portfolio_opt"
    ) -> Optional[Dict[str, Any]]:
        """Get cached portfolio optimization result"""
        try:
            cache_key = f"{cache_key_prefix}:{method}:{'-'.join(sorted(tickers))}"
            cached_result = await self.cache_service.get(cache_key)
            
            if cached_result:
                logger.info(f"Cache hit for optimization: {cache_key}")
                return json.loads(cached_result)
            
            return None
            
        except Exception as e:
            logger.warning(f"Cache retrieval error: {e}")
            return None
    
    async def cache_optimization_result(
        self,
        tickers: List[str],
        method: str,
        result: Dict[str, Any],
        cache_key_prefix: str = "portfolio_opt"
    ) -> bool:
        """Cache portfolio optimization result"""
        try:
            cache_key = f"{cache_key_prefix}:{method}:{'-'.join(sorted(tickers))}"
            ttl = self.cache_ttl.get("portfolio_optimization", 3600)
            
            success = await self.cache_service.set(
                cache_key, 
                json.dumps(result), 
                ttl
            )
            
            if success:
                logger.info(f"Cached optimization result: {cache_key}")
            
            return success
            
        except Exception as e:
            logger.warning(f"Cache storage error: {e}")
            return False
    
    async def enhanced_portfolio_optimization_with_cache(
        self,
        price_data: pd.DataFrame,
        method: str = "max_sharpe",
        force_refresh: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """Portfolio optimization with caching"""
        tickers = list(price_data.columns)
        
        # Try cache first (unless force refresh)
        if not force_refresh:
            cached_result = await self.get_cached_optimization(tickers, method)
            if cached_result:
                cached_result["from_cache"] = True
                cached_result["timestamp"] = datetime.utcnow().isoformat()
                return cached_result
        
        # Perform optimization
        optimization_result = await self.enhanced_portfolio_optimization(
            price_data, method, **kwargs
        )
        
        # Cache result
        await self.cache_optimization_result(tickers, method, optimization_result)
        optimization_result["from_cache"] = False
        optimization_result["timestamp"] = datetime.utcnow().isoformat()
        
        return optimization_result
```

### 6.2 Async Processing for Optimization Tasks

**Implement Background Task Processing:**

```python
from fastapi import BackgroundTasks
import asyncio
from typing import Callable

class AsyncOptimizationService:
    """Background task processing for heavy optimization computations"""
    
    def __init__(self):
        self.task_queue = asyncio.Queue()
        self.results_cache = {}
        self.max_concurrent_tasks = 3
    
    async def submit_optimization_task(
        self,
        task_id: str,
        ticker_data: Dict[str, Any],
        optimization_params: Dict[str, Any],
        callback: Optional[Callable] = None
    ) -> str:
        """Submit optimization task for background processing"""
        try:
            task = {
                "task_id": task_id,
                "ticker_data": ticker_data,
                "optimization_params": optimization_params,
                "callback": callback,
                "status": "queued",
                "created_at": datetime.utcnow()
            }
            
            await self.task_queue.put(task)
            
            # Start processing if not already running
            if not hasattr(self, '_processing_active'):
                self._processing_active = True
                asyncio.create_task(self._process_queue())
            
            return task_id
            
        except Exception as e:
            logger.error(f"Task submission error: {e}")
            raise
    
    async def _process_queue(self):
        """Process optimization tasks from queue"""
        try:
            while not self.task_queue.empty():
                task = await self.task_queue.get()
                task_id = task["task_id"]
                
                try:
                    task["status"] = "running"
                    
                    # Perform optimization in background
                    result = await self._perform_background_optimization(
                        task["ticker_data"], 
                        task["optimization_params"]
                    )
                    
                    task["status"] = "completed"
                    task["result"] = result
                    task["completed_at"] = datetime.utcnow()
                    
                    # Cache result
                    self.results_cache[task_id] = task
                    
                    # Call callback if provided
                    if task["callback"]:
                        try:
                            await task["callback"](task_id, result)
                        except Exception as e:
                            logger.warning(f"Callback error: {e}")
                    
                    logger.info(f"Optimization task completed: {task_id}")
                    
                except Exception as e:
                    task["status"] = "failed"
                    task["error"] = str(e)
                    task["failed_at"] = datetime.utcnow()
                    self.results_cache[task_id] = task
                    
                    logger.error(f"Optimization task failed: {task_id} - {e}")
                
                finally:
                    self.task_queue.task_done()
                    
        except Exception as e:
            logger.error(f"Queue processing error: {e}")
        finally:
            self._processing_active = False
    
    async def _perform_background_optimization(
        self,
        ticker_data: Dict[str, Any],
        optimization_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Perform optimization in background thread"""
        try:
            # Convert to DataFrame and perform optimization
            price_data = pd.DataFrame(ticker_data)
            engine = EnhancedAnalyticsEngine()
            
            result = await engine.enhanced_portfolio_optimization(
                price_data,
                **optimization_params
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Background optimization error: {e}")
            return {"error": str(e)}
    
    async def get_task_result(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get result of background optimization task"""
        if task_id in self.results_cache:
            return self.results_cache[task_id]
        return None
    
    async def cancel_task(self, task_id: str) -> bool:
        """Cancel pending optimization task"""
        # Implementation for canceling queued tasks
        # This would require maintaining task queue state
        logger.info(f"Task cancellation requested: {task_id}")
        return True
```

### 6.3 Database Schema Updates

**Required Database Schema Updates:**

```sql
-- Analytics results cache table
CREATE TABLE IF NOT EXISTS analytics_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cache_key VARCHAR(255) UNIQUE NOT NULL,
    result_data TEXT NOT NULL,
    cache_type VARCHAR(50) NOT NULL, -- 'optimization', 'stress_test', 'risk_metrics'
    tickers TEXT NOT NULL, -- JSON array of tickers
    parameters TEXT NOT NULL, -- JSON object of parameters
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    INDEX idx_cache_key (cache_key),
    INDEX idx_expires_at (expires_at),
    INDEX idx_cache_type (cache_type)
);

-- Portfolio optimization results table
CREATE TABLE IF NOT EXISTS portfolio_optimizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id VARCHAR(255) UNIQUE NOT NULL,
    tickers TEXT NOT NULL, -- JSON array
    weights TEXT NOT NULL, -- JSON object
    expected_return REAL NOT NULL,
    expected_volatility REAL NOT NULL,
    sharpe_ratio REAL NOT NULL,
    method VARCHAR(50) NOT NULL,
    constraints TEXT, -- JSON object
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(20) DEFAULT 'pending', -- 'pending', 'completed', 'failed'
    computation_time_ms INTEGER,
    INDEX idx_task_id (task_id),
    INDEX idx_method (method),
    INDEX idx_created_at (created_at)
);

-- Stress testing results table
CREATE TABLE IF NOT EXISTS stress_test_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_id VARCHAR(255) UNIQUE NOT NULL,
    tickers TEXT NOT NULL,
    weights TEXT NOT NULL, -- JSON object
    scenarios TEXT NOT NULL, -- JSON array
    results TEXT NOT NULL, -- JSON object with scenario results
    monte_carlo_enabled BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_test_id (test_id),
    INDEX idx_created_at (created_at)
);

-- Options positions table for portfolio analysis
CREATE TABLE IF NOT EXISTS options_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id VARCHAR(255) UNIQUE NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    option_type VARCHAR(10) NOT NULL, -- 'call' or 'put'
    strike_price REAL NOT NULL,
    expiry_date DATE NOT NULL,
    quantity INTEGER NOT NULL,
    current_price REAL NOT NULL,
    implied_volatility REAL NOT NULL,
    risk_free_rate REAL DEFAULT 0.02,
    dividend_yield REAL DEFAULT 0.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_position_id (position_id),
    INDEX idx_ticker (ticker),
    INDEX idx_expiry (expiry_date)
);

-- Library usage and performance metrics
CREATE TABLE IF NOT EXISTS library_performance_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_type VARCHAR(50) NOT NULL, -- 'optimization', 'stress_test', 'options_valuation'
    library_name VARCHAR(50) NOT NULL, -- 'pypfopt', 'riskfolio', 'quantlib'
    operation_parameters TEXT, -- JSON object
    computation_time_ms INTEGER NOT NULL,
    memory_usage_mb REAL,
    error_occurred BOOLEAN DEFAULT FALSE,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_operation_type (operation_type),
    INDEX idx_library_name (library_name),
    INDEX idx_created_at (created_at)
);

-- Add indexes for better performance
CREATE INDEX IF NOT EXISTS idx_analytics_cache_type_expires 
ON analytics_cache(cache_type, expires_at);

CREATE INDEX IF NOT EXISTS idx_portfolio_optimization_status 
ON portfolio_optimizations(status, created_at);
```

---

## 7. Testing Strategy

### 7.1 Unit Tests for New Calculations

**PyPortfolioOpt Integration Tests:**

```python
# backend/tests/test_portfolio_optimization.py

import pytest
import pandas as pd
import numpy as np
from unittest.mock import Mock, patch
from app.services.portfolio_optimization import PortfolioOptimization

class TestPortfolioOptimization:
    """Test suite for PyPortfolioOpt integration"""
    
    @pytest.fixture
    def sample_returns(self):
        """Create sample returns data for testing"""
        np.random.seed(42)
        dates = pd.date_range('2023-01-01', periods=252, freq='D')
        assets = ['AAPL', 'MSFT', 'GOOGL', 'AMZN']
        
        # Generate correlated returns
        returns_data = np.random.multivariate_normal(
            mean=[0.0008, 0.0006, 0.001, 0.0007],  # Daily returns
            cov=[[0.0004, 0.0001, 0.0001, 0.0001],
                 [0.0001, 0.0003, 0.0001, 0.0001],
                 [0.0001, 0.0001, 0.0005, 0.0001],
                 [0.0001, 0.0001, 0.0001, 0.0003]],
            size=252
        )
        
        return pd.DataFrame(returns_data, index=dates, columns=assets)
    
    @pytest.fixture
    def optimizer(self):
        """Create optimizer instance for testing"""
        return PortfolioOptimization(risk_free_rate=0.02)
    
    def test_max_sharpe_optimization(self, optimizer, sample_returns):
        """Test maximum Sharpe ratio optimization"""
        result = optimizer.optimize_portfolio(sample_returns, method="max_sharpe")
        
        assert result["optimization_success"] is True
        assert "weights" in result
        assert "expected_return" in result
        assert "expected_volatility" in result
        assert "sharpe_ratio" in result
        
        # Check weights sum to 1
        weights_sum = sum(result["weights"].values())
        assert abs(weights_sum - 1.0) < 1e-6
        
        # Check all weights are non-negative
        for weight in result["weights"].values():
            assert weight >= -1e-8  # Allow for numerical precision
    
    def test_min_volatility_optimization(self, optimizer, sample_returns):
        """Test minimum volatility optimization"""
        result = optimizer.optimize_portfolio(sample_returns, method="min_volatility")
        
        assert result["optimization_success"] is True
        assert result["method"] == "min_volatility"
        assert "expected_volatility" in result
        
        # Min volatility should have lower volatility than equal weight
        equal_weight_vol = optimizer._fallback_optimization(sample_returns)["expected_volatility"]
        assert result["expected_volatility"] <= equal_weight_vol * 1.01  # Allow for precision
    
    def test_risk_parity_optimization(self, optimizer, sample_returns):
        """Test risk parity optimization"""
        result = optimizer.optimize_portfolio(sample_returns, method="risk_parity")
        
        assert result["optimization_success"] is True
        assert result["method"] == "risk_parity"
        
        # Risk parity should have more equal risk contributions
        # (This is a simplified test - real implementation would calculate risk contributions)
        weights = list(result["weights"].values())
        weight_variance = np.var(weights)
        assert weight_variance < 0.1  # Weights should be relatively balanced
    
    def test_black_litterman_optimization(self, optimizer, sample_returns):
        """Test Black-Litterman model"""
        market_caps = {"AAPL": 3000e9, "MSFT": 2800e9, "GOOGL": 1800e9, "AMZN": 1600e9}
        views = {"AAPL": 0.12, "MSFT": 0.10, "GOOGL": 0.15, "AMZN": 0.08}
        
        result = optimizer.black_litterman_optimization(
            sample_returns, market_caps, views
        )
        
        assert result["optimization_success"] is True
        assert result["method"] == "black_litterman"
        assert "prior_returns" in result
        assert "posterior_returns" in result
        assert "views_used" in result
        
        # Check that views are incorporated
        for ticker, view in views.items():
            assert ticker in result["views_used"]
    
    def test_optimization_with_constraints(self, optimizer, sample_returns):
        """Test optimization with constraints"""
        constraints = {
            "max_weight": {"AAPL": 0.4, "MSFT": 0.3},
            "min_weight": {"GOOGL": 0.1, "AMZN": 0.1}
        }
        
        result = optimizer.optimize_portfolio(
            sample_returns, 
            method="max_sharpe", 
            constraints=constraints
        )
        
        assert result["optimization_success"] is True
        
        # Check constraints are respected (simplified check)
        weights = result["weights"]
        assert weights.get("AAPL", 0) <= constraints["max_weight"]["AAPL"] + 0.01
        assert weights.get("MSFT", 0) <= constraints["max_weight"]["MSFT"] + 0.01
    
    def test_efficient_frontier_generation(self, optimizer, sample_returns):
        """Test efficient frontier point generation"""
        ef_result = optimizer._get_efficient_frontier(EfficientFrontier(
            expected_returns.mean_historical_return(sample_returns),
            risk_models.sample_cov(sample_returns)
        ))
        
        assert len(ef_result) > 0
        
        # Check efficient frontier properties
        for point in ef_result:
            assert "expected_return" in point
            assert "expected_volatility" in point
            assert "sharpe_ratio" in point
            
            # Expected return should increase with volatility (efficient frontier)
            assert point["expected_return"] > -1
            assert point["expected_volatility"] > 0
    
    def test_fallback_optimization(self, optimizer, sample_returns):
        """Test fallback to equal weights when optimization fails"""
        # Test with invalid data to trigger fallback
        empty_returns = pd.DataFrame()
        
        result = optimizer._fallback_optimization(empty_returns)
        
        assert result["optimization_success"] is False
        assert result["method"] == "equal_weight_fallback"
        
        # Should have equal weights
        expected_equal_weight = 1.0 / len(sample_returns.columns)
        for weight in result["weights"].values():
            assert abs(weight - expected_equal_weight) < 1e-6
```

**riskfolio-lib Integration Tests:**

```python
# backend/tests/test_advanced_risk_analytics.py

import pytest
import pandas as pd
import numpy as np
from app.services.risk_analytics import AdvancedRiskAnalytics

class TestAdvancedRiskAnalytics:
    """Test suite for riskfolio-lib integration"""
    
    @pytest.fixture
    def sample_returns(self):
        """Create sample returns data"""
        np.random.seed(42)
        dates = pd.date_range('2023-01-01', periods=252, freq='D')
        assets = ['AAPL', 'MSFT', 'GOOGL', 'AMZN']
        
        returns_data = np.random.normal(0.0008, 0.02, (252, 4))
        return pd.DataFrame(returns_data, index=dates, columns=assets)
    
    @pytest.fixture
    def sample_weights(self):
        """Create sample portfolio weights"""
        return {"AAPL": 0.25, "MSFT": 0.25, "GOOGL": 0.25, "AMZN": 0.25}
    
    @pytest.fixture
    def risk_analytics(self, sample_returns, sample_weights):
        """Create risk analytics instance"""
        return AdvancedRiskAnalytics(sample_returns, sample_weights)
    
    def test_comprehensive_risk_metrics(self, risk_analytics):
        """Test comprehensive risk metrics calculation"""
        metrics = risk_analytics.calculate_comprehensive_risk_metrics()
        
        assert "var_metrics" in metrics
        assert "drawdown_metrics" in metrics
        assert "correlation_metrics" in metrics
        assert "risk_decomposition" in metrics
        assert "tail_risk_metrics" in metrics
        
        # Check VaR metrics
        assert "var_95" in metrics["var_metrics"]
        assert "cvar_95" in metrics["var_metrics"]
        
        # VaR should be negative
        assert metrics["var_metrics"]["var_95"] < 0
        assert metrics["var_metrics"]["cvar_95"] < 0
        
        # CVaR should be more negative than VaR (worse case)
        assert metrics["var_metrics"]["cvar_95"] <= metrics["var_metrics"]["var_95"]
    
    def test_stress_scenarios(self, risk_analytics):
        """Test stress scenario analysis"""
        scenarios = ["2008_crisis", "covid_crash", "inflation_spike"]
        
        stress_results = risk_analytics.calculate_stress_scenarios(scenarios)
        
        assert "scenarios" in stress_results
        
        for scenario in scenarios:
            assert scenario in stress_results["scenarios"]
            scenario_result = stress_results["scenarios"][scenario]
            
            assert "portfolio_var_95" in scenario_result
            assert "max_drawdown" in scenario_result
            assert "volatility" in scenario_result
            
            # Stress scenario results should be negative
            assert scenario_result["max_drawdown"] < 0
            assert scenario_result["portfolio_var_95"] < 0
    
    def test_risk_decomposition(self, risk_analytics):
        """Test risk decomposition calculation"""
        # This would test the _calculate_risk_decomposition method
        weights_array = np.array([0.25, 0.25, 0.25, 0.25])
        
        decomposition = risk_analytics._calculate_risk_decomposition(weights_array)
        
        assert "marginal_contributions" in decomposition
        assert "component_contributions" in decomposition
        assert "percentage_contributions" in decomposition
        assert "total_cvar" in decomposition
        
        # Sum of percentage contributions should be 1
        pct_contrib_sum = sum(decomposition["percentage_contributions"].values())
        assert abs(pct_contrib_sum - 1.0) < 1e-6
    
    def test_factor_risks(self, risk_analytics):
        """Test factor risk calculations"""
        factor_risks = risk_analytics._calculate_factor_risks()
        
        expected_factors = ["market", "size", "value"]
        
        for factor in expected_factors:
            assert factor in factor_risks
            # Factor risks should be between -1 and 1 (correlations)
            assert -1 <= factor_risks[factor] <= 1
    
    def test_fallback_risk_metrics(self, risk_analytics):
        """Test fallback risk metrics"""
        fallback_metrics = risk_analytics._fallback_risk_metrics()
        
        required_keys = ["var_95", "cvar_95", "max_drawdown", "diversification_ratio"]
        
        for key in required_keys:
            assert key in fallback_metrics
        
        # Fallback metrics should have reasonable default values
        assert fallback_metrics["var_95"] < 0
        assert fallback_metrics["cvar_95"] < fallback_metrics["var_95"]
        assert fallback_metrics["max_drawdown"] < 0
        assert fallback_metrics["diversification_ratio"] >= 1.0
```

**QuantLib Integration Tests:**

```python
# backend/tests/test_derivatives.py

import pytest
import numpy as np
from app.services.derivatives import DerivativesAnalytics

class TestDerivativesAnalytics:
    """Test suite for QuantLib integration"""
    
    @pytest.fixture
    def derivatives_analytics(self):
        """Create derivatives analytics instance"""
        return DerivativesAnalytics()
    
    def test_option_pricing(self, derivatives_analytics):
        """Test Black-Scholes option pricing"""
        result = derivatives_analytics.price_option(
            option_type="call",
            spot_price=100.0,
            strike_price=105.0,
            time_to_expiry=0.25,  # 3 months
            risk_free_rate=0.05,
            volatility=0.20,
            dividend_yield=0.02
        )
        
        assert "option_price" in result
        assert "greeks" in result
        assert "intrinsic_value" in result
        assert "time_value" in result
        
        # Option price should be positive
        assert result["option_price"] > 0
        
        # Greeks should be reasonable
        greeks = result["greeks"]
        assert "delta" in greeks
        assert "gamma" in greeks
        assert "vega" in greeks
        assert "theta" in greeks
        assert "rho" in greeks
        
        # Call option delta should be between 0 and 1
        assert 0 <= greeks["delta"] <= 1
        
        # Intrinsic value should be reasonable
        intrinsic_value = max(0, 100.0 - 105.0)
        assert abs(result["intrinsic_value"] - intrinsic_value) < 1e-6
    
    def test_put_option_pricing(self, derivatives_analytics):
        """Test put option pricing"""
        result = derivatives_analytics.price_option(
            option_type="put",
            spot_price=100.0,
            strike_price=95.0,
            time_to_expiry=0.25,
            risk_free_rate=0.05,
            volatility=0.20,
            dividend_yield=0.02
        )
        
        assert result["option_price"] > 0
        assert result["greeks"]["delta"] <= 0  # Put delta should be negative
        assert result["greeks"]["delta"] >= -1
    
    def test_portfolio_options_valuation(self, derivatives_analytics):
        """Test portfolio options valuation"""
        options_data = [
            {
                "option_type": "call",
                "spot_price": 100.0,
                "strike_price": 105.0,
                "time_to_expiry": 0.25,
                "risk_free_rate": 0.05,
                "volatility": 0.20,
                "quantity": 10,
                "current_price": 2.5
            },
            {
                "option_type": "put",
                "spot_price": 100.0,
                "strike_price": 95.0,
                "time_to_expiry": 0.25,
                "risk_free_rate": 0.05,
                "volatility": 0.20,
                "quantity": 5,
                "current_price": 1.8
            }
        ]
        
        portfolio_result = derivatives_analytics.portfolio_options_valuation(options_data)
        
        assert "total_portfolio_value" in portfolio_result
        assert "options" in portfolio_result
        assert "greeks_portfolio" in portfolio_result
        assert "risk_metrics" in portfolio_result
        
        # Total portfolio value should be positive
        assert portfolio_result["total_portfolio_value"] > 0
        
        # Number of options should match input
        assert len(portfolio_result["options"]) == len(options_data)
        
        # Portfolio Greeks should be aggregated
        for greek in ["delta", "gamma", "vega", "theta", "rho"]:
            assert greek in portfolio_result["greeks_portfolio"]
    
    def test_monte_carlo_var(self, derivatives_analytics):
        """Test Monte Carlo VaR calculation"""
        # Create sample returns data
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.0008, 0.02, 252))
        
        var_result = derivatives_analytics.monte_carlo_var(
            returns,
            confidence_level=0.95,
            simulation_days=21,  # 1 month
            num_simulations=1000
        )
        
        assert "var" in var_result
        assert "expected_shortfall" in var_result
        assert "confidence_level" in var_result
        assert "simulation_days" in var_result
        assert "num_simulations" in var_result
        assert "portfolio_metrics" in var_result
        
        # VaR should be negative
        assert var_result["var"] < 0
        
        # Expected shortfall should be more negative than VaR
        assert var_result["expected_shortfall"] <= var_result["var"]
        
        # Portfolio metrics should be reasonable
        metrics = var_result["portfolio_metrics"]
        assert "expected_final_value" in metrics
        assert "volatility" in metrics
        assert "probability_of_loss" in metrics
        
        assert 0 <= metrics["probability_of_loss"] <= 1
    
    def test_put_call_parity(self, derivatives_analytics):
        """Test put-call parity verification"""
        parity_result = derivatives_analytics._verify_put_call_parity(
            spot_price=100.0,
            strike_price=105.0,
            time_to_expiry=0.25,
            risk_free_rate=0.05,
            volatility=0.20
        )
        
        assert "call_price" in parity_result
        assert "put_price" in parity_result
        assert "parity_value" in parity_result
        assert "theoretical_parity" in parity_result
        assert "parity_error" in parity_result
        assert "is_valid" in parity_result
        
        # Parity error should be small (numerical precision)
        assert parity_result["parity_error"] < 0.01
    
    def test_moneyness_calculation(self, derivatives_analytics):
        """Test moneyness calculation"""
        spot_money, forward_money = derivatives_analytics._calculate_moneyness(
            spot_price=100.0,
            strike_price=105.0,
            time_to_expiry=0.25,
            risk_free_rate=0.05
        )
        
        # Spot moneyness should be spot/strike
        assert abs(spot_money - 100.0/105.0) < 1e-6
        
        # Forward moneyness should be forward/strike
        forward_price = 100.0 * np.exp(0.05 * 0.25)
        assert abs(forward_money - forward_price/105.0) < 1e-6
```

### 7.2 Integration Tests for API Endpoints

**API Integration Tests:**

```python
# backend/tests/test_enhanced_analytics_api.py

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, Mock
import json

class TestEnhancedAnalyticsAPI:
    """Test suite for enhanced analytics API endpoints"""
    
    @pytest.fixture
    def client(self):
        """Create test client"""
        from main import app
        return TestClient(app)
    
    @pytest.fixture
    def mock_price_data(self):
        """Mock price data for testing"""
        dates = pd.date_range('2023-01-01', periods=100, freq='D')
        data = {
            'AAPL': [150 + i*0.5 for i in range(100)],
            'MSFT': [300 + i*0.3 for i in range(100)],
            'GOOGL': [2500 + i*2.0 for i in range(100)]
        }
        
        df_data = []
        for i, date in enumerate(dates):
            df_data.append({
                'date': date,
                'AAPL': data['AAPL'][i],
                'MSFT': data['MSFT'][i],
                'GOOGL': data['GOOGL'][i]
            })
        
        return df_data
    
    def test_portfolio_optimization_endpoint(self, client, mock_price_data):
        """Test portfolio optimization API endpoint"""
        with patch('app.services.data_service.DataService.fetch_historical_data') as mock_fetch:
            # Mock successful data fetch
            mock_fetch.return_value = pd.DataFrame({
                'adj_close': [150, 151, 152],
                'volume': [1000000, 1100000, 900000]
            })
            
            response = client.post("/analytics/portfolio-optimization", json={
                "tickers": ["AAPL", "MSFT"],
                "method": "max_sharpe",
                "constraints": {
                    "max_weight": {"AAPL": 0.6}
                }
            })
        
        assert response.status_code == 200
        
        result = response.json()
        assert "weights" in result
        assert "expected_return" in result
        assert "expected_volatility" in result
        assert "sharpe_ratio" in result
        assert "methodology" in result
        
        # Check that weights sum to 1
        weights_sum = sum(result["weights"].values())
        assert abs(weights_sum - 1.0) < 1e-6
    
    def test_efficient_frontier_endpoint(self, client, mock_price_data):
        """Test efficient frontier API endpoint"""
        with patch('app.services.data_service.DataService.fetch_historical_data') as mock_fetch:
            mock_fetch.return_value = pd.DataFrame({
                'adj_close': [150, 151, 152],
                'volume': [1000000, 1100000, 900000]
            })
            
            response = client.get("/analytics/efficient-frontier", params={
                "tickers": "AAPL,MSFT,GOOGL",
                "method": "max_sharpe",
                "points": 25
            })
        
        assert response.status_code == 200
        
        result = response.json()
        assert "efficient_frontier" in result
        assert "optimal_portfolio" in result
        assert "methodology" in result
        
        # Check frontier points
        frontier = result["efficient_frontier"]
        assert len(frontier) > 0
        assert len(frontier) <= 25  # Limited by requested points
        
        for point in frontier:
            assert "expected_return" in point
            assert "expected_volatility" in point
            assert "sharpe_ratio" in point
    
    def test_advanced_stress_test_endpoint(self, client):
        """Test advanced stress testing API endpoint"""
        with patch('app.services.data_service.DataService.fetch_historical_data') as mock_fetch:
            mock_fetch.return_value = pd.DataFrame({
                'adj_close': [150, 151, 152],
                'volume': [1000000, 1100000, 900000]
            })
            
            response = client.post("/analytics/advanced-stress-test", json={
                "tickers": ["AAPL", "MSFT"],
                "weights": {"AAPL": 0.6, "MSFT": 0.4},
                "scenarios": ["2020_covid", "2022_inflation"],
                "use_quantlib_monte_carlo": True,
                "confidence_levels": [0.95, 0.99]
            })
        
        assert response.status_code == 200
        
        result = response.json()
        assert "scenarios" in result
        assert "historical_scenarios" in result
        assert "methodology" in result
        
        # Check scenario results
        for scenario in ["2020_covid", "2022_inflation"]:
            if scenario in result["scenarios"]:
                scenario_result = result["scenarios"][scenario]
                assert "max_drawdown" in scenario_result
                assert "portfolio_var_95" in scenario_result
    
    def test_options_analysis_endpoint(self, client):
        """Test options portfolio analysis API endpoint"""
        options_data = [
            {
                "ticker": "AAPL",
                "option_type": "call",
                "strike": 150.0,
                "expiry": "2024-03-15",
                "quantity": 10,
                "current_price": 5.50,
                "implied_volatility": 0.25
            },
            {
                "ticker": "AAPL",
                "option_type": "put",
                "strike": 140.0,
                "expiry": "2024-03-15",
                "quantity": -5,  # Short position
                "current_price": 3.20,
                "implied_volatility": 0.22
            }
        ]
        
        response = client.post("/analytics/options-analysis", json={
            "options_positions": options_data,
            "portfolio_value": 1000000.0
        })
        
        assert response.status_code == 200
        
        result = response.json()
        assert "portfolio_valuation" in result
        assert "risk_metrics" in result
        assert "stress_scenarios" in result
        assert "greeks_breakdown" in result
        
        # Check portfolio valuation
        portfolio_val = result["portfolio_valuation"]
        assert "total_portfolio_value" in portfolio_val
        assert "greeks_portfolio" in portfolio_val
        
        # Check risk metrics
        risk_metrics = result["risk_metrics"]
        assert "overall_options_risk" in risk_metrics
        assert "risk_level" in risk_metrics
    
    def test_error_handling_invalid_tickers(self, client):
        """Test error handling for invalid tickers"""
        response = client.post("/analytics/portfolio-optimization", json={
            "tickers": ["INVALID1", "INVALID2"],
            "method": "max_sharpe"
        })
        
        # Should return an error response
        assert response.status_code == 500
        # Response should contain error information
        assert "error" in response.json() or "detail" in response.json()
    
    def test_error_handling_insufficient_data(self, client):
        """Test error handling for insufficient data"""
        with patch('app.services.data_service.DataService.fetch_historical_data') as mock_fetch:
            # Mock insufficient data
            mock_fetch.return_value = None
            
            response = client.post("/analytics/portfolio-optimization", json={
                "tickers": ["AAPL"],
                "method": "max_sharpe"
            })
        
        assert response.status_code == 500
        assert "error" in response.json() or "detail" in response.json()
    
    def test_performance_caching(self, client):
        """Test response caching for performance"""
        with patch('app.services.data_service.DataService.fetch_historical_data') as mock_fetch:
            mock_fetch.return_value = pd.DataFrame({
                'adj_close': [150, 151, 152],
                'volume': [1000000, 1100000, 900000]
            })
            
            # First request
            response1 = client.get("/analytics/efficient-frontier", params={
                "tickers": "AAPL,MSFT"
            })
            
            # Second identical request (should use cache)
            response2 = client.get("/analytics/efficient-frontier", params={
                "tickers": "AAPL,MSFT"
            })
        
        assert response1.status_code == 200
        assert response2.status_code == 200
        
        # Both responses should be successful
        result1 = response1.json()
        result2 = response2.json()
        
        assert "from_cache" in result1 or "from_cache" in result2
```

### 7.3 Performance Benchmarks

**Performance Testing Suite:**

```python
# backend/tests/test_performance_benchmarks.py

import pytest
import time
import psutil
import memory_profiler
import pandas as pd
import numpy as np
from app.services.portfolio_optimization import PortfolioOptimization
from app.services.risk_analytics import AdvancedRiskAnalytics
from app.services.derivatives import DerivativesAnalytics

class TestPerformanceBenchmarks:
    """Performance tests for library integration"""
    
    @pytest.fixture
    def large_dataset(self):
        """Create large dataset for performance testing"""
        np.random.seed(42)
        dates = pd.date_range('2020-01-01', periods=1000, freq='D')
        assets = [f"ASSET_{i:03d}" for i in range(50)]  # 50 assets
        
        # Generate realistic correlated returns
        returns_data = np.random.multivariate_normal(
            mean=[0.0005] * 50,
            cov=np.random.rand(50, 50) * 0.0001 + np.eye(50) * 0.0001,
            size=1000
        )
        
        return pd.DataFrame(returns_data, index=dates, columns=assets)
    
    @pytest.fixture
    def optimizer(self):
        return PortfolioOptimization()
    
    @pytest.mark.performance
    def test_portfolio_optimization_performance(self, optimizer, large_dataset):
        """Test portfolio optimization performance"""
        start_time = time.time()
        
        result = optimizer.optimize_portfolio(large_dataset, method="max_sharpe")
        
        end_time = time.time()
        computation_time = end_time - start_time
        
        # Optimization should complete within 30 seconds for 50 assets
        assert computation_time < 30.0
        
        # Result should be valid
        assert result["optimization_success"] is True
        assert len(result["weights"]) == 50
        
        print(f"Portfolio optimization took {computation_time:.2f} seconds for {len(large_dataset.columns)} assets")
    
    @pytest.mark.performance
    def test_risk_analytics_performance(self, large_dataset):
        """Test advanced risk analytics performance"""
        weights = {asset: 1.0/50 for asset in large_dataset.columns}
        risk_analytics = AdvancedRiskAnalytics(large_dataset, weights)
        
        start_time = time.time()
        
        metrics = risk_analytics.calculate_comprehensive_risk_metrics()
        
        end_time = time.time()
        computation_time = end_time - start_time
        
        # Risk analytics should complete within 10 seconds
        assert computation_time < 10.0
        
        # Result should contain all expected metrics
        assert "var_metrics" in metrics
        assert "drawdown_metrics" in metrics
        assert "risk_decomposition" in metrics
        
        print(f"Risk analytics took {computation_time:.2f} seconds for {len(large_dataset.columns)} assets")
    
    @pytest.mark.performance
    def test_stress_scenarios_performance(self, large_dataset):
        """Test stress scenarios performance"""
        weights = {asset: 1.0/50 for asset in large_dataset.columns}
        risk_analytics = AdvancedRiskAnalytics(large_dataset, weights)
        
        scenarios = ["2008_crisis", "covid_crash", "inflation_spike", "china_slowdown"]
        
        start_time = time.time()
        
        stress_results = risk_analytics.calculate_stress_scenarios(scenarios)
        
        end_time = time.time()
        computation_time = end_time - start_time
        
        # Stress testing should complete within 15 seconds
        assert computation_time < 15.0
        
        # Results should contain all scenarios
        assert "scenarios" in stress_results
        assert len(stress_results["scenarios"]) >= len(scenarios)
        
        print(f"Stress testing took {computation_time:.2f} seconds for {len(scenarios)} scenarios")
    
    @pytest.mark.performance
    def test_options_pricing_performance(self):
        """Test options pricing performance"""
        derivatives = DerivativesAnalytics()
        
        # Create large options portfolio
        options_data = []
        for i in range(100):  # 100 options
            options_data.append({
                "option_type": "call" if i % 2 == 0 else "put",
                "spot_price": 100.0 + np.random.randn() * 10,
                "strike_price": 100.0 + np.random.randn() * 10,
                "time_to_expiry": 0.25 + np.random.rand() * 0.75,
                "risk_free_rate": 0.02 + np.random.rand() * 0.03,
                "volatility": 0.15 + np.random.rand() * 0.20,
                "quantity": 1,
                "current_price": 2.0 + np.random.rand() * 8.0
            })
        
        start_time = time.time()
        
        portfolio_result = derivatives.portfolio_options_valuation(options_data)
        
        end_time = time.time()
        computation_time = end_time - start_time
        
        # Options portfolio valuation should complete within 5 seconds for 100 options
        assert computation_time < 5.0
        
        # Result should be valid
        assert portfolio_result["total_portfolio_value"] > 0
        assert len(portfolio_result["options"]) == 100
        
        print(f"Options valuation took {computation_time:.2f} seconds for {len(options_data)} options")
    
    @pytest.mark.performance
    @memory_profiler.profile
    def test_memory_usage_large_dataset(self, large_dataset):
        """Test memory usage with large dataset"""
        weights = {asset: 1.0/50 for asset in large_dataset.columns}
        
        initial_memory = psutil.Process().memory_info().rss / 1024 / 1024  # MB
        
        # Run operations that consume memory
        optimizer = PortfolioOptimization()
        result = optimizer.optimize_portfolio(large_dataset, method="max_sharpe")
        
        risk_analytics = AdvancedRiskAnalytics(large_dataset, weights)
        metrics = risk_analytics.calculate_comprehensive_risk_metrics()
        
        final_memory = psutil.Process().memory_info().rss / 1024 / 1024  # MB
        memory_increase = final_memory - initial_memory
        
        # Memory increase should be reasonable (less than 500 MB)
        assert memory_increase < 500
        
        print(f"Memory usage increased by {memory_increase:.2f} MB for {len(large_dataset.columns)} assets")
    
    @pytest.mark.slow
    def test_api_response_time(self, client):
        """Test API response times for all endpoints"""
        endpoints = [
            "/analytics/realized-risk",
            "/analytics/forecast-risk", 
            "/analytics/factor-exposure",
            "/analytics/concentration",
            "/analytics/liquidity"
        ]
        
        for endpoint in endpoints:
            start_time = time.time()
            
            response = client.get(endpoint)
            
            end_time = time.time()
            response_time = end_time - start_time
            
            # Each endpoint should respond within 5 seconds
            assert response_time < 5.0
            assert response.status_code == 200
            
            print(f"{endpoint} responded in {response_time:.2f} seconds")
```

---

## 8. Migration Path and Timeline

### 8.1 Phase 1: Foundation (Weeks 1-2)

**Week 1 Tasks:**
1. **Environment Setup**
   - Verify library installations and versions
   - Create development database schema updates
   - Set up performance monitoring tools

2. **PyPortfolioOpt Integration**
   - Create `PortfolioOptimization` service class
   - Implement basic efficient frontier calculations
   - Add Black-Litterman model support
   - Create unit tests for optimization functions

**Week 2 Tasks:**
1. **Enhanced Analytics Engine**
   - Integrate portfolio optimization into main engine
   - Add caching layer for optimization results
   - Implement async processing for heavy computations
   - Create new API endpoints for optimization

2. **Testing and Documentation**
   - Complete integration tests
   - Performance benchmarking
   - Update API documentation

**Success Criteria:**
- Efficient frontier generation working
- Black-Litterman model implemented
- New API endpoints responding within 2 seconds
- All tests passing with >90% coverage

### 8.2 Phase 2: Advanced Analytics (Weeks 3-4)

**Week 3 Tasks:**
1. **riskfolio-lib Integration**
   - Create `AdvancedRiskAnalytics` service class
   - Implement comprehensive risk metrics
   - Add risk decomposition capabilities
   - Enhance stress testing with scenario analysis

2. **API Enhancements**
   - Add advanced risk metrics endpoints
   - Implement stress testing enhancements
   - Create factor exposure analysis improvements

**Week 4 Tasks:**
1. **Performance Optimization**
   - Implement advanced caching strategies
   - Add database optimization for analytics results
   - Create background task processing system

2. **Testing and Validation**
   - Comprehensive testing of risk analytics
   - Performance optimization validation
   - Documentation updates

**Success Criteria:**
- Comprehensive risk metrics calculated in <3 seconds
- Risk decomposition working correctly
- Stress testing with historical scenarios operational
- Performance benchmarks met

### 8.3 Phase 3: Derivatives and Risk (Weeks 5-6)

**Week 5 Tasks:**
1. **QuantLib Integration**
   - Create `DerivativesAnalytics` service class
   - Implement options pricing models
   - Add Monte Carlo simulation capabilities
   - Create credit risk models

2. **Options Portfolio Analysis**
   - Build options position management
   - Implement Greeks calculation and risk analysis
   - Add options-specific stress testing

**Week 6 Tasks:**
1. **Advanced Features**
   - Implement complete portfolio optimization suite
   - Add correlation and factor models
   - Create comprehensive reporting system

2. **Production Readiness**
   - Performance optimization and scaling
   - Security and error handling improvements
   - Final testing and documentation

**Success Criteria:**
- Options pricing working for all standard instruments
- Monte Carlo VaR calculations operational
- Complete integration with existing risk engine
- All performance benchmarks exceeded

### 8.4 Risk Mitigation Strategies

**Technical Risks:**
1. **Library Compatibility Issues**
   - Maintain virtual environment isolation
   - Use specific library versions
   - Implement fallback mechanisms

2. **Performance Degradation**
   - Implement aggressive caching
   - Use background task processing
   - Monitor and optimize database queries

3. **Memory Usage**
   - Implement memory monitoring
   - Use data streaming for large datasets
   - Optimize data structures

**Operational Risks:**
1. **Testing Coverage**
   - Comprehensive test suite development
   - Automated testing pipeline
   - Performance regression testing

2. **Documentation**
   - Complete API documentation
   - Implementation guides
   - Performance tuning guides

### 8.5 Success Metrics

**Performance Metrics:**
- API response times <2 seconds for all endpoints
- Portfolio optimization completes in <30 seconds for 50 assets
- Memory usage <500MB for large datasets
- 99.9% uptime for analytics services

**Functionality Metrics:**
- 100% test coverage for new modules
- All libraries integrated and functional
- Comprehensive risk analytics operational
- Options pricing working for all standard instruments

**Business Metrics:**
- Enhanced risk management capabilities
- Improved portfolio optimization
- Advanced stress testing and scenario analysis
- Comprehensive derivatives analytics

---

## Conclusion

This comprehensive integration plan transforms the Daisy Risk Engine from a basic risk analytics platform into an institutional-grade quantitative finance system. The phased approach ensures:

1. **Minimal Disruption**: Gradual integration without breaking existing functionality
2. **Performance Optimization**: Advanced caching and async processing
3. **Comprehensive Testing**: Thorough validation of all new capabilities
4. **Production Readiness**: Monitoring, documentation, and deployment support

The integration of PyPortfolioOpt, riskfolio-lib, and QuantLib provides:

- **Advanced Portfolio Optimization**: Modern portfolio theory with Black-Litterman models
- **Institutional Risk Analytics**: Comprehensive risk decomposition and scenario analysis
- **Derivatives Capabilities**: Options pricing, Greeks calculation, and advanced risk simulation

This implementation positions Daisy Risk Engine as a comprehensive, production-ready quantitative risk management platform capable of handling institutional-scale portfolios with advanced risk analytics and derivatives analysis.

**Next Steps:**
1. Begin Phase 1 implementation
2. Set up development environment with new libraries
3. Create initial integration tests
4. Start performance benchmarking baseline

This guide provides the roadmap for successfully integrating advanced risk management libraries into Daisy Risk Engine, significantly enhancing its analytical capabilities while maintaining system performance and reliability.