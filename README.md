# A Buy-on-dip algo for Alpaca API

This is a simple algo that trades every day refreshing portfolio based on the EMA ranking.
Among the universe (e.g. SP500 stocks), it ranks by daily (price - EMA) percentage as of
trading time and keep positions in sync with lowest ranked stocks.

The rationale behind this: low (price - EMA) vs price ratio indicates there is a big dip
in a short time. Since the universe is SP500 which means there is some fundamental strengths,
the belief is that the price should be recovered to some extent.

## How to run

Set up your API key in environment variables first.

```
$ export APCA_API_KEY_ID=xxx
$ export APCA_API_SECRET_KEY=yyy
```

The only dependency is alpaca-trade-api module.  You can set up the environment by
pipenv.  If python 3 and the dependency is ready,

```
$ python main.py
```

That's it.

Also, this repository is set up for Heroku.  If you have a Heroku account, create a new
app and run this as an application. It is only one worker app so make sure you set up
worker type app.


## Cutomization

universe.Universe is hard-coded.  Easy customization is to change this to more dynamic
set of stocks with some filters such as per-share price to be less than $50 or so.
Some of the numbers are also hard-coded and it is meant to run in an account with about
$500 deposit, with asuumption that one position to be up to $100, resulting in 5 positions
at most.  If your account size and position size preference are different, you can
change these valuess.

EMA-5 is also very arbitrary choice.  You could try something like 10, too.

## Future work

There is btest.py that runs a simple simulation.  This module needs more easy visualization
and more integrated setup, possibly using jupyter and matplotlib.