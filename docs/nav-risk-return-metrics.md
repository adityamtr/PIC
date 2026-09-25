# Risk and Return Metrics from Daily NAV / Price History

The formulas below are the core calculation methods. They are still valid whether the input series is stock price $P_t$ or fund NAV $NAV_t$. We keep both definitions because:

- stock-level metrics are used for security selection and ranking
- fund-level metrics are used for portfolio-level risk/return targets and user sliders
- both are then combined inside the convex optimization problem

## Notation

For any asset series $V_t$:

- For a stock, $V_t = P_t$ (closing price)
- For a fund, $V_t = NAV_t$ (daily fund NAV)
- Daily return:

$$
r_t = \frac{V_t}{V_{t-1}} - 1
$$

The same formulas apply at both levels; only the input series changes.

---

# 1. Stock-Level Calculations

Use the stock closing price series $P_t$ to compute:

## 1.1 Annualized Return

$$
\text{Annualized Return} = \left(\frac{P_T}{P_0}\right)^{\frac{252}{T}} - 1
$$

Equivalent form using daily returns:

$$
\text{Annualized Return} = \left(\prod_{t=1}^{T}(1+r_t)\right)^{\frac{252}{T}} - 1
$$

## 1.2 1M, 3M, 6M Return

For a lookback window of $k$ months:

$$
R_k = \frac{P_t}{P_{t-k}} - 1
$$

Approximate trading-day windows:

- 1M ≈ 21 trading days
- 3M ≈ 63 trading days
- 6M ≈ 126 trading days

Examples:

$$
R_{1M} = \frac{P_t}{P_{t-21}} - 1
$$

$$
R_{3M} = \frac{P_t}{P_{t-63}} - 1
$$

$$
R_{6M} = \frac{P_t}{P_{t-126}} - 1
$$

## 1.3 Annualized Volatility

Average daily return:

$$
\bar{r} = \frac{1}{N}\sum_{t=1}^{N} r_t
$$

Daily variance:

$$
\sigma_{daily}^{2} = \frac{1}{N-1}\sum_{t=1}^{N}(r_t - \bar{r})^2
$$

Annualized volatility:

$$
\sigma_{annual} = \sqrt{252}\cdot \sqrt{\sigma_{daily}^{2}}
$$

## 1.4 Maximum Drawdown

At time $t$:

$$
\text{Drawdown}_t = \frac{\max_{s \le t}(P_s) - P_t}{\max_{s \le t}(P_s)}
$$

Maximum drawdown:

$$
\text{MDD} = \max_t(\text{Drawdown}_t)
$$

## 1.5 Sharpe Ratio

$$
\text{Sharpe} = \frac{\bar{r}_{annual} - r_f}{\sigma_{annual}}
$$

Where:

- $\bar{r}_{annual} = 252 \cdot \bar{r}_{daily}$
- $r_f$ = risk-free rate

## 1.6 Sortino Ratio

$$
\text{Sortino} = \frac{\bar{r}_{annual} - r_f}{\sigma_{downside}}
$$

Where downside deviation is:

$$
\sigma_{downside} = \sqrt{\frac{1}{N}\sum_{t=1}^{N}\min(r_t-r_f,0)^2}
$$

---

# 2. Fund-Level Calculations

Use the fund NAV series $NAV_t$ to compute the same metrics:

## 2.1 Annualized Return

$$
\text{Annualized Return} = \left(\frac{NAV_T}{NAV_0}\right)^{\frac{252}{T}} - 1
$$

## 2.2 1M, 3M, 6M Return

$$
R_k = \frac{NAV_t}{NAV_{t-k}} - 1
$$

Examples:

$$
R_{1M} = \frac{NAV_t}{NAV_{t-21}} - 1
$$

$$
R_{3M} = \frac{NAV_t}{NAV_{t-63}} - 1
$$

$$
R_{6M} = \frac{NAV_t}{NAV_{t-126}} - 1
$$

## 2.3 Annualized Volatility

$$
\bar{r} = \frac{1}{N}\sum_{t=1}^{N} r_t
$$

$$
\sigma_{daily}^{2} = \frac{1}{N-1}\sum_{t=1}^{N}(r_t - \bar{r})^2
$$

$$
\sigma_{annual} = \sqrt{252}\cdot \sqrt{\sigma_{daily}^{2}}
$$

## 2.4 Maximum Drawdown

At time $t$:

$$
\text{Drawdown}_t = \frac{\max_{s \le t}(NAV_s) - NAV_t}{\max_{s \le t}(NAV_s)}
$$

Maximum drawdown:

$$
\text{MDD} = \max_t(\text{Drawdown}_t)
$$

## 2.5 Sharpe Ratio

$$
\text{Sharpe} = \frac{\bar{r}_{annual} - r_f}{\sigma_{annual}}
$$

## 2.6 Sortino Ratio

$$
\text{Sortino} = \frac{\bar{r}_{annual} - r_f}{\sigma_{downside}}
$$

Where:

$$
\sigma_{downside} = \sqrt{\frac{1}{N}\sum_{t=1}^{N}\min(r_t-r_f,0)^2}
$$

---

# 3. How these metrics are used in convex optimization

We keep both sets of metrics because they play different roles.

## 3.1 Stock-level metrics in the optimizer

For each stock $i$, we compute:

- expected return $\mu_i$
- volatility $\sigma_i$
- downside risk / drawdown proxy
- Sharpe or Sortino score
- transaction-cost or liquidity penalty $c_i$

Then the optimizer chooses allocations $x_i$ to maximize return while penalizing risk:

$$
\max_{x} \sum_i \mu_i x_i - \lambda \sum_i \sigma_i^2 x_i - \eta \sum_i c_i x_i
$$

where:

- $x_i$ = allocation to stock $i$
- $\mu_i$ = expected return of stock $i$
- $\sigma_i$ = stock-level volatility
- $c_i$ = liquidity or transaction cost
- $\lambda, \eta$ = tuning parameters

This decides which securities should be bought or sold.

## 3.2 Fund-level metrics in the optimizer

Fund NAV metrics are used to set the portfolio-level targets:

- target return $\mu_{target}$
- max volatility $\sigma_{max}$
- max drawdown
- Sharpe / Sortino thresholds

In contrast, the forecasting model is predicting stock-level returns $\mu_i$, not fund-level returns. Those stock return forecasts are used in the objective vector, while the fund NAV metrics remain the portfolio-level target and constraint layer.

So the optimization uses:

- stock return forecasts $\mu_i$ in the return vector
- fund NAV-derived target return $\mu_{target}$ from the slider and historical fund metrics
- fund NAV-derived risk cap $\sigma_{max}$ from volatility or drawdown limits

This is still one optimization problem, not two separate solves.

These become constraints such as:

$$
\sum_i w_i \mu_i \geq \mu_{target}
$$

$$
w^T \Sigma w \leq \sigma_{max}^2
$$

where $w_i = x_i / AUM$ and $\Sigma$ is the stock covariance matrix.

This decides whether the overall portfolio is acceptable for the user’s chosen risk and return profile.

## 3.3 Combined optimization formulation

The full optimization is:

$$
\max_{x} \sum_i \mu_i x_i - \lambda x^T \Sigma x - \eta \sum_i c_i x_i
$$

subject to:

$$
\sum_i x_i = \text{investable cash}
$$

$$
0 \leq x_i \leq \text{issuer cap}_i
$$

$$
\sum_i w_i \mu_i \geq \mu_{target}
$$

$$
w^T \Sigma w \leq \sigma_{max}^2
$$

$$
\text{max name fraction} \leq \text{configured cap}
$$

Interpretation:

- $\mu_i$ and $\Sigma$ come from stock-level calculations
- $\mu_{target}$ and $\sigma_{max}$ come from fund-level NAV calculations
- the optimizer combines both to produce a portfolio that is both attractive at the stock level and controlled at the fund level

---

# 4. How user sliders map to optimization parameters

## 4.1 Return slider

This is driven by the fund NAV return metrics:

- annualized return
- 3M return
- 6M return

and by the predicted stock return signal:

- $\mu_i$: forecasted stock return used in the asset-level return vector

The return slider influences the portfolio target, while the forecasted stock returns determine which names are attractive within that target. The optimization therefore uses:

$$
\mu_{portfolio} = \sum_i w_i \mu_i
$$

and compares it against a fund-level target such as:

$$
\sum_i w_i \mu_i \geq \mu_{target}
$$

where $\mu_{target}$ is derived from the fund NAV return metrics and the user return slider. This means the slider is applied at the portfolio level while the forecast remains at the stock level.

## 4.2 Risk slider

This is driven by the fund NAV risk metrics:

- annualized volatility
- maximum drawdown
- Sharpe ratio
- Sortino ratio

It becomes:

$$
\sigma_{max}, \quad \text{or an equivalent downside-risk cap}
$$

## 4.3 Security ranking / stock selection

This is driven by stock-level metrics:

- expected return
- volatility
- Sharpe / Sortino
- drawdown
- liquidity score

These determine which names receive the highest weights within the overall risk budget.

---

# 5. Final design intent

The correct architecture is:

- stock metrics answer: “which securities are attractive?”
- stock return forecasts answer: “what return should each stock contribute?”
- fund NAV metrics answer: “how much total risk and return is acceptable for the whole fund?”

So we keep both calculation layers because they serve different purposes, but they are used together in the same convex optimization problem. The final portfolio is not optimized twice; it is optimized once with stock-level forecast inputs and fund-level portfolio constraints assembled into one objective and constraint set.

---

# 6. Summary

| Level | Series    | Metrics                                                                   | Primary Usage                                      |
| ----- | --------- | ------------------------------------------------------------------------- | -------------------------------------------------- |
| Stock | $P_t$   | annualized return, 1M/3M/6M return, volatility, drawdown, Sharpe, Sortino | ranking and stock selection                        |
| Fund  | $NAV_t$ | annualized return, 1M/3M/6M return, volatility, drawdown, Sharpe, Sortino | user risk/return sliders and portfolio constraints |

The formulas are identical; only the input series changes. The optimization then combines both levels into one decision model.
