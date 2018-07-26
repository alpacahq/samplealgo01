# Step-by-step Tutorial
The purpose of this tutorial is to explain the general flow of
building your first algorithm by going through an example,
so that you get a sense of what is needed.  It is completely free
to run this algorithm as-is if you like, or modify for your own needs.
This is just for you to learn how you usually write an algo from scratch.

## Algorithm Idea
The idea behind the sample algorithm is this:

- We trade stocks within the S&P 500
- We build a portfolio with securities that we believe are oversold, trying to capture mean reversion - We use exponential moving average (EMA) to measure the magnitude of oversold
- We rebuild our portfolio once a day in the morning
- We maintain reasonable size of positions (~5 stocks) at a time
- Due to the liquidity and generally low volatility of S&P 500 consituents, we do not expect positions to have highly volatile returns
- Therefore, the risk should be low and there should be some correlation with S&P 500

In short, this strategy hopes to capitlaize on some of the random-walk fluctuations in stock prices by placing orders to buy when price strays too far below the EMA, hoping it will come back soon. It shuffles the portfolio by ranking the most oversold stocks and keeping the top-ranked stocks at any point. When the positions revert to the mean or don't move much at all, we also kick them out to get fresh oversold stocks in.

Now, we are going to go through the steps to write this algorithm.

## Starting point

First thing first, you need to have a main entry point, which we call `main()`.

```py
def main():
    # empty!
    pass

if __name__ == '__main__':
    main()
```

## Setting up our Universe

There are more than 7,000 tradable symbols for US equities today, but
we do not care about small companies and ETFs here to avoid too much risk. We stick
to S&P 500 stocks, which can be obtained from different sources and referenced dynamically,
but here, we just hard-code it in the source code.

```py
# SP500
Universe = ['MMM', 'ABT', 'ABBV', 'ACN', 'ATVI', 'AYI', 'ADBE', ..., 'ZTS']
```

We will store the security list in a file called `universe.py`.

## Infinite loop

Now, let's start coding the logic! Most of the algorithms watch
market movements and do some actions based on specific
conditions. For this to occur, our algorithm needs to run infinitely. 
Since we want to check the daily movement of our universe, we will
check the time (Eastern US, for consistency with market time) and do something in the morning.

```py
def main():
    done = None
    logging.info('start running')
    while True:
        now = pd.Timestamp.now(tz=NY)
        if 0 <= now.dayofweek <= 4 and done != now.strftime('%Y-%m-%d'):
            if now.time() >= pd.Timestamp('09:30', tz=NY).time():
                # ** do our stuff here! **

                do_stuff()

                # flag it as done so it doesn't work again for the day
                # TODO: this isn't tolerant to the process restart
                done = now.strftime('%Y-%m-%d')
                logger.info(f'done for {done}')

        time.sleep(1)
```

As you can see in the code, this algo checks the day of the week (Mon-Fri) and
time if it is after the market open (9:30am ET). If so, do something
interesting.  You can use Alpaca's `get_clock()` API to know more precise
time at the serverside. Also, Alpaca provides a way to check days that the market is open
from `get_calendar()` as well, but we will keep it simple here.
The `done` flag is set to the date string so we make sure
we do stuff only once a day. Depending on your idea, you may want to
kick off your logic every minute, every hour, every Monday, or whatever you want.

## Main logic
This is the fun part since this is the core of our algorithm. Remember,
our algorithm calculates EMA to find most oversold stocks in the universe.

### Get the price data
First, we want to get price data to calculate the EMA, and we use Polygon 
API to do this. Alll Alpaca customers are authorized to use Polygon's stock
data with the same API key Alpaca issues. All the complex matters are abstracted
inside the SDK, so you can simply call on the `polygon` property under the REST
object. For example,

```py
api.polygon.historic_agg('day', 'AAPL').df
```

this will give you the historical daily price data for AAPL.

Let's call this function `prices()` which takes a parameter,
symbols, to indicate which price data to get.

```py
def prices(symbols):
    '''Get the map of prices in DataFrame with the symbol name key.'''
    now = pd.Timestamp.now(tz=NY)
    end_dt = now
    if now.time() >= pd.Timestamp('09:30', tz=NY).time():
        end_dt = now - \
            pd.Timedelta(now.strftime('%H:%M:%S')) - pd.Timedelta('1 minute')
    return _get_polygon_prices(symbols, end_dt)
```

There are some checks to adjust what to specify for `end_dt` parameter
since we want to make sure this function always returns the prices
up to yesterday, even if you call it during market hours.
If you call this like `prices(['AAPL'])`, you will get a dict object
with a key 'AAPL' to AAPL's price data in a DataFrame object.

And this `_get_polygon_prices()` will look like:

```py
def _get_polygon_prices(symbols, end_dt, max_workers=5):
    '''Get the map of DataFrame price data from polygon, in parallel.'''

    start_dt = end_dt - pd.Timedelta('1200 days')
    _from = start_dt.strftime('%Y-%-m-%-d')
    to = end_dt.strftime('%Y-%-m-%-d')

    def historic_agg(symbol):
        return api.polygon.historic_agg(
            'day', symbol, _from=_from, to=to).df.sort_index()

    with concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers) as executor:
        results = {}
        future_to_symbol = {
            executor.submit(
                historic_agg,
                symbol): symbol for symbol in symbols}
        for future in concurrent.futures.as_completed(future_to_symbol):
            symbol = future_to_symbol[future]
            try:
                results[symbol] = future.result()
            except Exception as exc:
                logger.warning(
                    '{} generated an exception: {}'.format(
                        symbol, exc))
        return results
```

The use of `concurrent.futures` is to accelerate cross-symbol data fetch
by parallelizing the API calls, but it's fine to just call polygon API
sequentially too.

### Rank stocks by (price - EMA) difference
It is hard to define which stocks are "the most oversold" among a number of
stocks, but let's assume the difference ratio between the price and EMA
indicates some sort of drop here, as short-term EMA can converge close to
the price but if it diverges a lot, that means the price changed
siginificantly in a short period of time. In addition to that, we need to
normalize the value so we can compare the significance in a fair manner.

```py
def calc_scores(price_map, dayindex=-1):
    '''Calculate scores based on the indicator and 
    return the sorted result.
    '''
    diffs = {}
    param = 10
    for symbol, df in price_map.items():
        if len(df.close.values) <= param:
            continue
        ema = df.close.ewm(span=param).mean()[dayindex]
        last = df.close.values[dayindex]
        diff = (last - ema) / last
        diffs[symbol] = diff

    return sorted(diffs.items(), key=lambda x: x[1])
```

We use pandas's `ewm()` method to calculate the EMA on a DataFrame here,
but if you want to use a different technical indicator to find oversold stocks,
you could use the `ta-lib` package, which supports a wider variety of inicators.
Please note that `diff` is the difference between the last price and 10-day EMA
as a percentage of last price. This value can be negative or positive,
with a negative diff indicating the price dropped over the last day.


### Build orders
Now that we have the ranked list of stocks in hand, it's time to decide
what to buy and what to sell. We want to keep the top 5 oversold stocks
in our portfolio, and it's easy to build 5 buy orders if you start from
zero, but we need to do a bit of work here to check the current holdings
and take some diff from the targeted portfolio and current.

```py
def get_orders(api, price_map, position_size=100, max_positions=5):
    '''Calculate the scores with the universe to build the optimal
    portfolio as of today, and extract orders to transition from
    current portfolio to the calculated state.
    '''
    # rank the stocks based on the indicators.
    ranked = calc_scores(price_map)
    to_buy = set()
    to_sell = set()
    account = api.get_account()
    # take the top one twentieth out of ranking,
    # excluding stocks too expensive to buy a share
    for symbol, _ in ranked[:len(ranked) // 20]:
        price = float(price_map[symbol].close.values[-1])
        if price > float(account.cash):
            continue
        to_buy.add(symbol)

    # now get the current positions and see what to buy,
    # what to sell to transition to today's desired portfolio.
    positions = api.list_positions()
    logger.info(positions)
    holdings = {p.symbol: p for p in positions}
    holding_symbol = set(holdings.keys())
    to_sell = holding_symbol - to_buy
    to_buy = to_buy - holding_symbol
    orders = []

    # if a stock is in the portfolio, and not in the desired
    # portfolio, sell it
    for symbol in to_sell:
        shares = holdings[symbol].qty
        orders.append({
            'symbol': symbol,
            'qty': shares,
            'side': 'sell',
        })
        logger.info(f'order(sell): {symbol} for {shares}')

    # likewise, if the portfoio is missing stocks from the
    # desired portfolio, buy them. We sent a limit for the total
    # position size so that we don't end up holding too many positions.
    max_to_buy = max_positions - (len(positions) - len(to_sell))
    for symbol in to_buy:
        if max_to_buy <= 0:
            break
        shares = position_size // float(price_map[symbol].close.values[-1])
        if shares == 0.0:
            continue
        orders.append({
            'symbol': symbol,
            'qty': shares,
            'side': 'buy',
        })
        logger.info(f'order(buy): {symbol} for {shares}')
        max_to_buy -= 1
    return orders
```

You can find the `calc_scores()` call to get the ranked list, and
`get_account()` and `list_positions()` to know the current available
cash and holding positions to build a list of orders. We further filter
out some stocks that exceed the size of our cash, and limit the number of
positions even if the ranked list has more stocks that are oversold.

Note the function has default parameters `position_size` and
`max_positions` that controls how much dollar you want to spend
at most for each position and how many positions at most you want to
keep in your portfolio, which you could change to see how it works later.

Finally we get the orders to transition from current portfolio to the
desired portfolio from this function.

### Place the orders!
OK, finally let's execute them. In this algorithm, we separate
the logic of calculating necessary orders and actual order submissions
so we can easily test the code, but it is possible to mix that logic too.

The main concern you have here is that the buy orders may get rejected
if you cash is not enough, so you need to wait for the sell orders to go
first and wait until they are filled. This algorithm does not care much
about the precise entry price for simplicity, and places orders in market
so you don't have to worry too much if the order doesn't fill.

```py
def trade(orders, wait=30):
    '''This is where we actually submit the orders and wait for them to fill.
    This is an important step since the orders aren't filled atomically,
    which means if your buys come first with little cash left in the account,
    the buy orders will be bounced.  In order to make the transition smooth,
    we sell first and wait for all the sell orders to fill and then submit
    buy orders.
    '''

    # process the sell orders first
    sells = [o for o in orders if o['side'] == 'sell']
    for order in sells:
        try:
            logger.info(f'submit(sell): {order}')
            api.submit_order(
                symbol=order['symbol'],
                qty=order['qty'],
                side='sell',
                type='market',
                time_in_force='day',
            )
        except Exception as e:
            logger.error(e)
    count = wait
    while count > 0:
        pending = api.list_orders()
        if len(pending) == 0:
            logger.info(f'all sell orders done')
            break
        logger.info(f'{len(pending)} sell orders pending...')
        time.sleep(1)
        count -= 1

    # process the buy orders next
    buys = [o for o in orders if o['side'] == 'buy']
    for order in buys:
        try:
            logger.info(f'submit(buy): {order}')
            api.submit_order(
                symbol=order['symbol'],
                qty=order['qty'],
                side='buy',
                type='market',
                time_in_force='day',
            )
        except Exception as e:
            logger.error(e)
    count = wait
    while count > 0:
        pending = api.list_orders()
        if len(pending) == 0:
            logger.info(f'all buy orders done')
            break
        logger.info(f'{len(pending)} buy orders pending...')
        time.sleep(1)
        count -= 1
```

It's as simple as you read, but the order submission (`submit_order()`)
is enclosed by a try-except block in case we get some error, which might
be fine to ignore at this point, as it's better to try to go through
than stopping the rest of portfolio transition.

## Assemble them

OK, finally we have all pieces ready, we just need to execute the main
logic once a day.  Just put the `get_orders()` and `trade()` in the middle
of the main loop.

```py
def main():
    done = None
    logging.info('start running')
    while True:
        now = pd.Timestamp.now(tz=NY)
        if 0 <= now.dayofweek <= 4 and done != now.strftime('%Y-%m-%d'):
            if now.time() >= pd.Timestamp('09:30', tz=NY).time():
                price_map = prices(Universe)
                orders = get_orders(api, price_map)
                trade(orders)
                # flag it as done so it doesn't work again for the day
                # TODO: this isn't tolerant to the process restart
                done = now.strftime('%Y-%m-%d')
                logger.info(f'done for {done}')

        time.sleep(1)
```


With the default parameters you saw in the example, it trades with
- S&P 500 stocks
- $500 cash
- 5 positions at max
- Less than 100 dollars for each position

And you can adjust it based on your needs, but this should be a good
basis.  Also, note that this algo will not require day-trading margin call
($25k) since the positions are held at least for 1 day.

It is very hard to try this type of shuffling algorithm without a commission-free
trading platform with this size of cash, since a few dollars of commission will kill the cash balance pretty quickly. 


## Backtesting
OK all looks good, it's ready to run and see some results in live trading, but
you may want to check the performance beforehand, even though this is
something already tested by someone. Fair enough.

There are a number of backtesting platforms out there to validate your
idea, but it doesn't require too much if you want one for your own needs,
with some reasonable assumptions.

The code itself is beyond the scope of this tutorial, but we have built
one simple simulation code for this algorithm.  Please take a look at
`btest.py` code.  What you want to run is the `simulate()` function that returns
an `account` object holding the trading result. What you want to see
is the `account.performance` property which is a DataFrame object with
the algorithm performance and benchmark result.

The function looks like this.

```py
def simulate(days=10, equity=500, position_size=100,
             max_positions=5, bench='SPY'):
    account = Account(cash=equity)

    price_map = algo.prices(algo.Universe)

    bench_df = price_map.get(bench)
    if bench_df is None:
        bench_df = algo.prices([bench])[bench]
    account.set_benchmark(bench_df)

    orders = []
    tindex = price_map['AAPL'].index
    account.update({}, tindex[-days-1])
    api = SimulationAPI(account)
    for t in tindex[-days:]:
        print(t)
        snapshot = {symbol: df[df.index < t]
            for symbol, df in price_map.items()
            if t - df[df.index < t].index[-1] < pd.Timedelta('2 days')}

        # before market opens
        orders = algo.get_orders(api, snapshot,
                                 position_size=position_size,
                                 max_positions=max_positions)

        # right after the market opens
        for order in orders:
            # buy at the open
            price = price_map[order['symbol']].open[t]
            account.fill_order(order, price, t, position_dollar)

        account.update(snapshot, t)

    return account
```

Pretty simple, and of course there are many things to worry if you really
care, such as an S&P 500 universe change, but this can be enough to
validate our idea. Also, you may notice the function has default
parameters that you can change around to simulate different scenarios.


## Set up the enviornment
Yes we forgot to talk about the environment first. This repository is
set up using `pipenv` which is becoming the de-facto standard in python today,
as it's something sitting on top of `pip`, `virtualenv` and `pyenv`
that's easier to use. If you haven't installed `pipenv`, we'd
recommend to try it this time. Once you have `pipenv`, it's as simple as

```
$ pipenv install
$ pipenv shell
```

then you will be in the environment with all dependencies.

You can take a look at the
[Pipfile](./Pipfile) file in this directory but all we need
is to install the `alpaca-trade-api` package which comes with `pandas`.
If you prefer running backtesting in a Jupyter notebook environment,
install `jupyter` and `matplotlib` by

```
$ pipenv install --dev
```

After going into a pipenv shell, you can start jupyter by

```
$ python playground.py
```

which should pop up your browser to start with.

Jupyter is particularly easy for visualizing the result.
In one test, we got this result (blue=algo, orange=SPY)
between 10 days prior to 6/25/2018

![](https://cdn.pbrd.co/images/HrJEchQ.png)

Not too bad. Of course, you should check your result.


## Deployment
This algo has to run live to trade. The question is, where? You
may not want to keep your computer up and running all the time,
and you don't even want to worry about monitoring your computer
being alive or not.

You can borrow a machine from AWS or one of the cloud providiers, which costs a few dollars a month.
The smallest instance should be fine for this algo since it doesn't do much,
but you have to set up the environment, install dependencies etc.
Alternatively, you can break the infinite loop so it runs the main logic and exits,
so that you can run this in AWS Lambda or some sort of cron-job service,
since this algo does not need to watch the positions all the time. But if
you want to add such logic to this, it will be a bit hard with cron style.

### Heroku free
Heroku, a cloud platform designed with app hosting in mind,
offers a free tier that can run this simple program for you.
What is important to understand is that you need to
set it up as a "worker" process since this is a long-running process.

First, set up your heroku account if you haven't. Then, create an
App in the account.

![Create App](https://cdn.pbrd.co/images/HrJxZNGQ.png)

The next screen asks for the app name which has to be unique so name it as you want.

---
![Name App](https://cdn.pbrd.co/images/HrJzskv.png)

Follow Heroku's instructions to set up the command line tool so you can push your code
to Heroku.  You can either set up a github account that links to this Heroku App,
or you can install the `heroku` command line tool and add `heroku` remote to
your local github account.

Make sure you configure your free dyno for the worker.

---
The last thing to do is to configure the environment variables to give
your Alpaca APY key info.  Go to the `Setting` tab and add the
environment variables.

![Configure Env](https://cdn.pbrd.co/images/HrJAdmb.png)

---
If you run it correctly, you can see the console log from here.

![View Logs](https://cdn.pbrd.co/images/HrJzdqo.png)

If everything works fine, you will see some log output in the
log output, similar to this.

```
2018-06-26T13:30:58.502315+00:00 app[worker.1]: INFO:samplealgo.algo:1 buy orders pending...
2018-06-26T13:30:59.574241+00:00 app[worker.1]: DEBUG:urllib3.connectionpool:https:/iapi.alpaca.markets:443 "GET /v1/orders HTTP/1.1" 200 557
2018-06-26T13:30:59.574927+00:00 app[worker.1]: INFO:samplealgo.algo:1 buy orders pending...
2018-06-26T13:31:00.662481+00:00 app[worker.1]: DEBUG:urllib3.connectionpool:https://api.alpaca.markets:443 "GET /v1/orders HTTP/1.1" 200 557
2018-06-26T13:31:00.663137+00:00 app[worker.1]: INFO:samplealgo.algo:1 buy orders pending...
2018-06-26T13:31:01.740745+00:00 app[worker.1]: DEBUG:urllib3.connectionpool:https://api.alpaca.markets:443 "GET /v1/orders HTTP/1.1" 200 557
2018-06-26T13:31:01.741839+00:00 app[worker.1]: INFO:samplealgo.algo:1 buy orders pending...
2018-06-26T13:31:02.837375+00:00 app[worker.1]: DEBUG:urllib3.connectionpool:https://api.alpaca.markets:443 "GET /v1/orders HTTP/1.1" 200 557
2018-06-26T13:31:02.838408+00:00 app[worker.1]: INFO:samplealgo.algo:1 buy orders pending...
2018-06-26T13:31:03.840173+00:00 app[worker.1]: INFO:samplealgo.algo:done for 2018-06-26
```
