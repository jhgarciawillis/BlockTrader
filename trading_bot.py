import logging
from datetime import datetime
from collections import deque
from statistics import mean, stdev
from typing import Dict, List, Optional, Tuple, Union
from wallet import create_wallet
from config import config_manager
from utils import handle_trading_errors
from kucoin.client import Client
from simulated_trade_client import SimulatedTradeClient

logger = logging.getLogger(__name__)

class TradingBot:
    def __init__(self, update_interval: int, liquid_ratio: float):
        self.wallet = None
        self.update_interval = update_interval
        self.liquid_ratio = liquid_ratio
        self.symbol_allocations: Dict[str, float] = {}
        self.price_history: Dict[str, deque] = {}
        self.active_trades: Dict[str, Dict] = {}
        self.pending_orders: Dict[str, Dict] = {}  # Track orders not yet filled
        self.total_trades: int = 0
        self.status_history: List[Dict] = []
        self.is_simulation: bool = False
        self.trade_client: Optional[Union[Client, SimulatedTradeClient]] = None
        self.max_total_orders: int = config_manager.get_max_total_orders()
        self.currency_allocations: Dict[str, float] = config_manager.get_currency_allocations()
        self.active_orders: Dict[str, List[Dict]] = {}

        # Fees and profit margin
        self.taker_fee: float = config_manager.get_taker_fee()
        self.maker_fee: float = config_manager.get_maker_fee()
        self.profit_margin: float = config_manager.get_profit_margin()

    def initialize(self) -> None:
        self.is_simulation = config_manager.get_config('simulation_mode')['enabled']
        self.PRICE_HISTORY_LENGTH = config_manager.get_config('chart_config')['history_length']
        self.wallet = create_wallet(self.is_simulation, self.liquid_ratio)
        initial_balance = config_manager.get_config('simulation_mode')['initial_balance']
        self.wallet.initialize_balance(initial_balance)
        self.wallet.set_currency_allocations(self.currency_allocations)
        
        if not self.is_simulation:
            self.trade_client = config_manager.kucoin_client_manager.get_client()
            self.update_wallet_balances()
        else:
            self.trade_client = config_manager.create_simulated_trade_client(
                config_manager.get_config('fees'),
                self.max_total_orders,
                self.currency_allocations
            )
        
        logger.info("Bot initialized successfully.")
        
    @handle_trading_errors
    def update_wallet_balances(self) -> None:
        try:
            self.wallet.sync_with_exchange('trading')
            logger.info(f"Updated wallet balances: {self.wallet.get_account_summary()}")
        except Exception as e:
            logger.error(f"Error updating wallet balances: {e}")

    def get_balance(self, currency: str, balance_type: str) -> float:
        return self.wallet.get_balance('trading', currency, balance_type)

    def get_user_allocations(self, user_selected_symbols: List[str]) -> Dict[str, float]:
        tradable_usdt_amount = self.get_balance('USDT', 'trading')
        
        if tradable_usdt_amount <= 0 or not user_selected_symbols:
            return {}

        return {symbol: tradable_usdt_amount * self.currency_allocations.get(symbol, 0) 
                for symbol in user_selected_symbols}

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
            return current_price
        
        return None

    def can_place_order(self, symbol: str) -> bool:
        total_orders = sum(len(orders) for orders in self.active_orders.values())
        total_pending = len(self.pending_orders)
        return (total_orders + total_pending) < self.max_total_orders

    def calculate_target_sell_price(self, buy_price: float) -> float:
        # Calculate sell price to ensure profit margin after fees
        actual_cost = buy_price * (1 + self.taker_fee)
        target_revenue = actual_cost * (1 + self.profit_margin)
        target_sell_price = target_revenue / (1 - self.taker_fee)
        return target_sell_price

    @handle_trading_errors
    def place_buy_order(self, symbol: str, amount_usdt: float, limit_price: float) -> Optional[Dict]:
        if not self.can_place_order(symbol) or amount_usdt > self.get_balance('USDT', 'trading'):
            return None
        
        try:
            # Calculate amount of crypto to buy at the limit price
            crypto_amount = amount_usdt / limit_price
            
            order = self.trade_client.create_limit_order(
                symbol=symbol,
                side=Client.SIDE_BUY,
                price=str(limit_price),
                size=str(crypto_amount),
            )
            
            if order and 'orderId' in order:
                # Add to pending orders for tracking
                self.pending_orders[order['orderId']] = {
                    'symbol': symbol,
                    'side': Client.SIDE_BUY,
                    'price': limit_price,
                    'amount': crypto_amount,
                    'amount_usdt': amount_usdt,
                    'order_time': datetime.now(),
                    'target_sell_price': self.calculate_target_sell_price(limit_price)
                }
                
                logger.info(f"Placed buy order for {symbol}: {crypto_amount} at {limit_price} USDT")
                
                if symbol not in self.active_orders:
                    self.active_orders[symbol] = []
                self.active_orders[symbol].append(order)
                
            return order
            
        except Exception as e:
            logger.error(f"Error placing buy order: {e}")
            return None

    @handle_trading_errors
    def place_sell_order(self, symbol: str, amount_crypto: float, target_sell_price: float, buy_order_id: str) -> Optional[Dict]:
        if not self.can_place_order(symbol):
            return None
        
        try:
            order = self.trade_client.create_limit_order(
                symbol=symbol,
                side=Client.SIDE_SELL,
                price=str(target_sell_price),
                size=str(amount_crypto),
            )
            
            if order and 'orderId' in order:
                # Add to pending orders for tracking
                self.pending_orders[order['orderId']] = {
                    'symbol': symbol,
                    'side': Client.SIDE_SELL,
                    'price': target_sell_price,
                    'amount': amount_crypto,
                    'order_time': datetime.now(),
                    'buy_order_id': buy_order_id
                }
                
                logger.info(f"Placed sell order for {symbol}: {amount_crypto} at {target_sell_price} USDT")
                
                if symbol not in self.active_orders:
                    self.active_orders[symbol] = []
                self.active_orders[symbol].append(order)
                
            return order
            
        except Exception as e:
            logger.error(f"Error placing sell order: {e}")
            return None

    @handle_trading_errors
    def check_pending_orders(self) -> None:
        """Check status of pending orders and update accordingly"""
        for order_id, order_data in list(self.pending_orders.items()):
            try:
                order_info = self.trade_client.get_order(order_id)
                
                # If order is filled
                if order_info.get('status') == 'done':
                    symbol = order_data['symbol']
                    side = order_data['side']
                    
                    if side == Client.SIDE_BUY:
                        # Move to active trades
                        self.active_trades[order_id] = {
                            'symbol': symbol,
                            'buy_price': float(order_data['price']),
                            'amount': float(order_data['amount']),
                            'buy_time': order_data['order_time'],
                            'target_sell_price': order_data['target_sell_price']
                        }
                        
                        # Update wallet
                        self.wallet.update_account_balance(
                            'trading', 
                            symbol, 
                            float(order_data['amount']), 
                            float(order_data['price']), 
                            float(order_info.get('fee', 0)), 
                            side
                        )
                        
                        logger.info(f"Buy order {order_id} for {symbol} filled at {order_data['price']}")
                        
                    elif side == Client.SIDE_SELL:
                        # Get the corresponding buy order
                        buy_order_id = order_data['buy_order_id']
                        buy_data = self.active_trades.get(buy_order_id)
                        
                        if buy_data:
                            # Calculate profit
                            profit = self.calculate_profit(buy_data, order_info)
                            self.update_profit(symbol, profit)
                            
                            # Update wallet
                            self.wallet.update_account_balance(
                                'trading', 
                                symbol, 
                                float(order_data['amount']), 
                                float(order_data['price']), 
                                float(order_info.get('fee', 0)), 
                                side
                            )
                            
                            logger.info(f"Sell order {order_id} for {symbol} filled at {order_data['price']} (Profit: {profit} USDT)")
                            
                            # Remove the buy order from active trades
                            del self.active_trades[buy_order_id]
                    
                    # Remove from pending orders
                    del self.pending_orders[order_id]
                    
                # Handle cancelled orders
                elif order_info.get('status') == 'cancelled':
                    logger.info(f"Order {order_id} for {order_data['symbol']} was cancelled")
                    del self.pending_orders[order_id]
                
            except Exception as e:
                logger.error(f"Error checking order {order_id}: {e}")

    def calculate_profit(self, buy_data: Dict, sell_order: Dict) -> float:
       buy_price = buy_data['buy_price']
       buy_amount = buy_data['amount']
       sell_price = float(sell_order.get('price', 0))
       sell_amount = float(sell_order.get('dealSize', 0))
       sell_fee = float(sell_order.get('fee', 0))
       
       # Calculate actual profit
       buy_cost = buy_price * buy_amount * (1 + self.taker_fee)
       sell_revenue = sell_price * sell_amount * (1 - self.taker_fee)
       
       profit = sell_revenue - buy_cost
       return profit

    def update_profit(self, symbol: str, profit: float) -> None:
       self.wallet.update_profits(symbol, profit)
       self.total_trades += 1

    def update_allocations(self, user_selected_symbols: List[str]) -> None:
       self.symbol_allocations = self.get_user_allocations(user_selected_symbols)
       self.currency_allocations = {symbol: 1/len(user_selected_symbols) 
                                  for symbol in user_selected_symbols}
       self.wallet.set_currency_allocations(self.currency_allocations)

    def get_current_status(self, prices: Dict[str, float]) -> Dict:
       # First check pending orders to update status
       self.check_pending_orders()
       
       current_total_usdt = self.wallet.get_balance('trading', 'USDT', 'liquid') + self.wallet.get_balance('trading', 'USDT', 'trading')
       tradable_usdt = self.get_balance('USDT', 'trading')
       liquid_usdt = self.wallet.get_balance('trading', 'USDT', 'liquid')
       
       status = {
           'timestamp': datetime.now(),
           'prices': prices,
           'active_trades': self.active_trades.copy(),
           'pending_orders': self.pending_orders.copy(),
           'profits': self.wallet.get_profits(),
           'total_profit': sum(self.wallet.get_profits().values()),
           'current_total_usdt': current_total_usdt,
           'tradable_usdt': tradable_usdt,
           'liquid_usdt': liquid_usdt,
           'wallet_summary': self.wallet.get_account_summary(),
           'total_trades': self.total_trades,
           'avg_profit_per_trade': sum(self.wallet.get_profits().values()) / self.total_trades 
                                 if self.total_trades > 0 else 0,
           'active_orders': {symbol: len(orders) for symbol, orders in self.active_orders.items()},
       }
       
       self.status_history.append(status)
       if len(self.status_history) > 120:
           self.status_history.pop(0)
       
       return status