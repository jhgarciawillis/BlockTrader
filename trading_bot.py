import logging
from datetime import datetime
from collections import deque
from statistics import mean, stdev
from typing import Dict, List, Optional, Tuple
from wallet import create_wallet
from config import config_manager
from kucoin.client import Market, Trade, User

logger = logging.getLogger(__name__)

def handle_trading_errors(func):
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"An error occurred in {func.__name__}: {str(e)}")
    return wrapper

class TradingBot:
    def __init__(self, update_interval: int, liquid_ratio: float):
        self.wallet = None
        self.update_interval = update_interval
        self.liquid_ratio = liquid_ratio
        self.symbol_allocations: Dict[str, float] = {}
        self.price_history: Dict[str, deque] = {}
        self.active_trades: Dict[str, Dict] = {}
        self.total_trades: int = 0
        self.status_history: List[Dict] = []
        self.is_simulation: bool = False
        self.profit_margin: float = config_manager.get_config('profit_margin')
        self.kucoin_market_client: Optional[Market] = None
        self.kucoin_trade_client: Optional[Trade] = None
        self.kucoin_user_client: Optional[User] = None
        self.max_total_orders: int = config_manager.get_max_total_orders()
        self.currency_allocations: Dict[str, float] = config_manager.get_currency_allocations()
        self.active_orders: Dict[str, List[Dict]] = {}
        self.maker_fee: float = config_manager.get_config('fees')['maker']
        self.taker_fee: float = config_manager.get_config('fees')['taker']

    def initialize(self) -> None:
        self.is_simulation = config_manager.get_config('simulation_mode')['enabled']
        self.PRICE_HISTORY_LENGTH = config_manager.get_config('chart_config')['history_length']
        self.wallet = create_wallet(self.is_simulation, self.liquid_ratio)
        initial_balance = config_manager.get_config('simulation_mode')['initial_balance']
        self.wallet.initialize_balance(initial_balance)
        self.wallet.set_currency_allocations(self.currency_allocations)
        
        if not self.is_simulation:
            self.update_wallet_balances()
        else:
            self.kucoin_market_client = config_manager.create_simulated_market_client()
            self.kucoin_trade_client = config_manager.create_simulated_trade_client()
            self.kucoin_user_client = config_manager.create_simulated_user_client()

    def set_kucoin_clients(self, market_client: Market, trade_client: Trade, user_client: User) -> None:
        self.kucoin_market_client = market_client
        self.kucoin_trade_client = trade_client
        self.kucoin_user_client = user_client

    @handle_trading_errors
    def update_wallet_balances(self) -> None:
        try:
            self.wallet.sync_with_exchange('trading')
            logger.info(f"Updated wallet balances: {self.wallet.get_account_summary()}")
        except Exception as e:
            logger.error(f"Error updating wallet balances: {e}")

    def get_tradable_balance(self, currency: str = 'USDT') -> float:
        return self.wallet.get_tradable_balance(currency)

    def get_user_allocations(self, user_selected_symbols: List[str]) -> Dict[str, float]:
        tradable_usdt_amount = self.get_tradable_balance('USDT')
        
        if tradable_usdt_amount <= 0 or not user_selected_symbols:
            return {}

        return {symbol: tradable_usdt_amount * self.currency_allocations.get(symbol, 0) for symbol in user_selected_symbols}

    def update_price_history(self, symbols: List[str], prices: Dict[str, float]) -> None:
        for symbol in symbols:
            if symbol not in self.price_history:
                self.price_history[symbol] = deque(maxlen=self.PRICE_HISTORY_LENGTH)
            if prices[symbol] is not None:
                self.price_history[symbol].append({
                    'timestamp': datetime.now(),
                    'price': prices[symbol]
                })
                self.wallet.update_currency_price('trading', symbol, prices[symbol])

    def should_buy(self, symbol: str, current_price: float) -> Optional[float]:
        if current_price is None or len(self.price_history[symbol]) < self.PRICE_HISTORY_LENGTH:
            return None
        
        prices = [entry['price'] for entry in self.price_history[symbol]]
        price_mean = mean(prices)
        price_stdev = stdev(prices) if len(set(prices)) > 1 else 0
        
        if current_price < price_mean and (price_mean - current_price) < price_stdev:
            return price_mean
        
        return None

    def can_place_order(self, symbol: str) -> bool:
        total_orders = sum(len(orders) for orders in self.active_orders.values())
        return total_orders < self.max_total_orders

    def get_available_balance(self, symbol: str) -> float:
        return self.wallet.get_available_balance(symbol)

    @handle_trading_errors
    def place_buy_order(self, symbol: str, amount_usdt: float, limit_price: float) -> Optional[Dict]:
        if not self.can_place_order(symbol) or amount_usdt > self.get_available_balance(symbol):
            return None
        
        if self.is_simulation:
            return self._place_simulated_buy_order(symbol, amount_usdt, limit_price)
        else:
            return self._place_live_buy_order(symbol, amount_usdt, limit_price)

    def _place_simulated_buy_order(self, symbol: str, amount_usdt: float, limit_price: float) -> Optional[Dict]:
        order = config_manager.place_spot_order(symbol, 'buy', limit_price, amount_usdt / limit_price, True)
        
        if order:
            self.active_trades[order['orderId']] = {
                'symbol': symbol,
                'buy_price': float(order['price']),
                'amount': float(order['dealSize']),
                'fee': float(order['fee']),
                'buy_time': datetime.now()
            }
            self.wallet.update_wallet_state('trading', symbol, float(order['dealSize']), float(order['price']), float(order['fee']), 'buy')
            if symbol not in self.active_orders:
                self.active_orders[symbol] = []
            self.active_orders[symbol].append(order)
            return order
        return None

    def _place_live_buy_order(self, symbol: str, amount_usdt: float, limit_price: float) -> Optional[Dict]:
        try:
            order = self.kucoin_trade_client.create_limit_order(
                symbol=symbol,
                side='buy',
                price=str(limit_price),
                size=str(amount_usdt / limit_price)
            )
            self._process_order_response(order, 'buy', symbol, amount_usdt, limit_price)
            return order
        except Exception as e:
            logger.error(f"Error placing live buy order: {e}")
            return None

    @handle_trading_errors
    def place_sell_order(self, symbol: str, amount_crypto: float, target_sell_price: float) -> Optional[Dict]:
        if not self.can_place_order(symbol):
            return None
        
        if self.is_simulation:
            return self._place_simulated_sell_order(symbol, amount_crypto, target_sell_price)
        else:
            return self._place_live_sell_order(symbol, amount_crypto, target_sell_price)

    def _place_simulated_sell_order(self, symbol: str, amount_crypto: float, target_sell_price: float) -> Optional[Dict]:
        order = config_manager.place_spot_order(symbol, 'sell', target_sell_price, amount_crypto, True)
        
        if order:
            self.wallet.update_wallet_state('trading', symbol, float(order['dealSize']), float(order['price']), float(order['fee']), 'sell')
            if symbol not in self.active_orders:
                self.active_orders[symbol] = []
            self.active_orders[symbol].append(order)
            return order
        return None

    def _place_live_sell_order(self, symbol: str, amount_crypto: float, target_sell_price: float) -> Optional[Dict]:
        try:
            order = self.kucoin_trade_client.create_limit_order(
                symbol=symbol,
                side='sell',
                price=str(target_sell_price),
                size=str(amount_crypto)
            )
            self._process_order_response(order, 'sell', symbol, amount_crypto, target_sell_price)
            return order
        except Exception as e:
            logger.error(f"Error placing live sell order: {e}")
            return None

    def _process_order_response(self, order: Dict, side: str, symbol: str, amount: float, price: float) -> None:
        if side == 'buy':
            self.active_trades[order['orderId']] = {
                'symbol': symbol,
                'buy_price': float(price),
                'amount': float(amount),
                'fee': float(order.get('fee', 0)),
                'buy_time': datetime.now()
            }
        self.wallet.update_wallet_state('trading', symbol, float(amount), float(price), float(order.get('fee', 0)), side)
        if symbol not in self.active_orders:
            self.active_orders[symbol] = []
        self.active_orders[symbol].append(order)

    def get_current_status(self, prices: Dict[str, float]) -> Dict:
        current_total_usdt = self.wallet.get_total_balance('USDT')
        tradable_usdt = self.get_tradable_balance('USDT')
        liquid_usdt = self.wallet.get_liquid_balance('USDT')
        
        status = {
            'timestamp': datetime.now(),
            'prices': prices,
            'active_trades': self.active_trades.copy(),
            'profits': self.wallet.get_profits(),
            'total_profit': sum(self.wallet.get_profits().values()),
            'current_total_usdt': current_total_usdt,
            'tradable_usdt': tradable_usdt,
            'liquid_usdt': liquid_usdt,
            'wallet_summary': self.wallet.get_account_summary(),
            'total_trades': self.total_trades,
            'avg_profit_per_trade': sum(self.wallet.get_profits().values()) / self.total_trades if self.total_trades > 0 else 0,
            'active_orders': {symbol: len(orders) for symbol, orders in self.active_orders.items()},
        }
        
        self.status_history.append(status)
        
        if len(self.status_history) > 120:
            self.status_history.pop(0)
        
        return status

    def update_allocations(self, user_selected_symbols: List[str]) -> None:
        self.symbol_allocations = self.get_user_allocations(user_selected_symbols)
        self.currency_allocations = {symbol: 1/len(user_selected_symbols) for symbol in user_selected_symbols}
        self.wallet.set_currency_allocations(self.currency_allocations)

    def calculate_profit(self, buy_order: Dict, sell_order: Dict) -> float:
        buy_amount_usdt = float(buy_order['dealFunds'])
        buy_fee_usdt = float(buy_order['fee'])
        buy_amount_crypto = float(buy_order['dealSize'])

        sell_amount_usdt = float(sell_order['dealFunds'])
        sell_fee_usdt = float(sell_order['fee'])

        actual_buy_amount_crypto = buy_amount_crypto - (buy_fee_usdt / buy_amount_usdt * buy_amount_crypto)
        actual_sell_amount_usdt = sell_amount_usdt - sell_fee_usdt

        profit = actual_sell_amount_usdt - buy_amount_usdt
        return profit

    def update_profit(self, symbol: str, profit: float) -> None:
        self.wallet.update_profits(symbol, profit)
        self.total_trades += 1

    def calculate_target_sell_price(self, buy_price: float) -> float:
        return buy_price * (1 + self.profit_margin + self.maker_fee + self.taker_fee)

def create_trading_bot(update_interval: int, liquid_ratio: float) -> TradingBot:
    bot = TradingBot(update_interval, liquid_ratio)
    bot.initialize()
    return bot

# Make sure TradingBot and create_trading_bot are explicitly exported
__all__ = ['TradingBot', 'create_trading_bot']
