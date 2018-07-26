import pandas as pd
from . import algo


class Account(object):
    '''Simulation Account which bookkeeps positions and balance'''

    def __init__(self, cash):
        self.cash = cash
        self.positions = {}
        self.trades = []
        self.equities = {}
        self._benchmark = None

    @property
    def balance_hist(self):
        timestamps = sorted([t for t in self.equities.keys()])
        data = [self.equities[t] for t in timestamps]
        series = pd.Series(data, index=timestamps)
        performance = (series - series[0]) / series[0]
        data = dict(
            algo=series,
            algo_perf=performance,
        )
        if self._benchmark is not None:
            bench = self._benchmark.close.loc[series.index]
            bench_perf = (bench - bench[0]) / bench[0]
            data.update(dict(
                bench=bench,
                bench_perf=bench_perf,
            ))
        return pd.DataFrame(data, index=series.index)

    @property
    def performance(self):
        df = self.balance_hist
        columns = [c for c in df.columns if c.endswith('perf')]
        return df[columns]

    def set_benchmark(self, df):
        self._benchmark = df

    def update(self, prices, timestamp):
        equity = self.cash
        for symbol, pos in self.positions.items():
            shares = pos['shares']
            price = prices[symbol].close.values[-1]
            equity += shares * price
        self.equities[timestamp] = equity

    def fill_order(self, order, price, timestamp):
        symbol = order['symbol']
        if order['side'] == 'buy':
            shares = order['qty']
            if shares * price > self.cash:
                print(f'{timestamp}: no cash available for {symbol}')
                return

            self.positions[symbol] = {
                'entry_timestamp': timestamp,
                'entry_price': price,
                'shares': shares,
            }
            self.cash -= price * shares
        else:
            position = self.positions.pop(symbol)
            shares = position['shares']
            self.trades.append({
                'symbol': symbol,
                'entry_timestamp': position['entry_timestamp'],
                'entry_price': position['entry_price'],
                'exit_timestamp': timestamp,
                'exit_price': price,
                'profit': price - position['entry_price'],
                'profit_perc': (
                    price - position['entry_price']
                ) / position['entry_price'] * 100,
                'shares': shares,
            })
            self.cash += price * shares


class SimulationPosition(object):
    '''A class which mocks Position Entity'''

    def __init__(self, symbol, qty):
        self.symbol = symbol
        self.qty = int(qty)


class SimulationAPI(object):
    '''A class which mocks REST API'''

    def __init__(self, account):
        self._account = account

    def get_account(self):
        return self._account

    def list_positions(self):
        return [
            SimulationPosition(symbol, pos['shares'])
            for symbol, pos in
            self._account.positions.items()
        ]


def simulate(days=10, equity=500, position_size=100,
             max_positions=5, bench='SPY'):
    '''
    equity: the initial dollar
    position_size: the dollar amount to spend for each position
    max_positions: the max number of positinos in the portfolio
    bench: a symbol for benchmarking
    '''
    account = Account(cash=equity)

    price_map = algo.prices(algo.Universe)

    bench_df = price_map.get(bench)
    if bench_df is None:
        bench_df = algo.prices([bench])[bench]
    account.set_benchmark(bench_df)

    orders = []
    tindex = price_map['AAPL'].index
    account.update({}, tindex[-days - 1])
    api = SimulationAPI(account)
    for t in tindex[-days:]:
        print(t)
        snapshot = {
            symbol: df[df.index < t]
            for symbol, df in price_map.items()
            # sanity check to exclude stale prices
            if t - df[df.index < t].index[-1] < pd.Timedelta('2 days')}

        # before market opens
        orders = algo.get_orders(api, snapshot,
                                 position_size=position_size,
                                 max_positions=max_positions)

        # right after the market opens
        for order in orders:
            # buy at the open
            price = price_map[order['symbol']].open[t]
            account.fill_order(order, price, t)

        account.update(snapshot, t)

    return account
