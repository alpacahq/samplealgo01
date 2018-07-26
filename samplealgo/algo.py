import alpaca_trade_api as tradeapi
import pandas as pd
import time
import logging
import concurrent.futures

from .universe import Universe

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

NY = 'America/New_York'
api = tradeapi.REST()


def _dry_run_submit(*args, **kwargs):
    logging.info(f'submit({args}, {kwargs})')
# api.submit_order =_dry_run_submit


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


def prices(symbols):
    '''Get the map of prices in DataFrame with the symbol name key.'''
    now = pd.Timestamp.now(tz=NY)
    end_dt = now
    if now.time() >= pd.Timestamp('09:30', tz=NY).time():
        end_dt = now - \
            pd.Timedelta(now.strftime('%H:%M:%S')) - pd.Timedelta('1 minute')
    return _get_polygon_prices(symbols, end_dt)


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


def trade(orders, wait=30):
    '''This is where we actually submit the orders and wait for them to fill.
    This is an important step since the orders aren't filled atomically,
    which means if your buys come first with littme cash left in the account,
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


def main():
    '''The entry point. Goes into an infinite loop and
    start trading every morning at the market open.'''
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
