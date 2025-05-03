# utils.py
import logging
from typing import Any, Callable
import time
import uuid
from simulated_trade_client import SIDE_BUY, SIDE_SELL

logger = logging.getLogger(__name__)

def handle_errors(func: Callable) -> Callable:
    def wrapper(*args, **kwargs) -> Any:
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"An error occurred in {func.__name__}: {str(e)}")
            raise
    return wrapper

def handle_trading_errors(func: Callable) -> Callable:
    def wrapper(*args, **kwargs) -> Any:
        max_retries = 3
        retry_delay = 2  # seconds
        
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error in {func.__name__}: {str(e)}")
                
                # Check if we should retry based on error type
                if "Too Many Requests" in str(e):
                    # Rate limit hit, wait longer
                    retry_wait = retry_delay * (attempt + 1) * 2
                    logger.info(f"Rate limit hit, retrying in {retry_wait} seconds...")
                    time.sleep(retry_wait)
                    continue
                    
                elif "Connection" in str(e) and attempt < max_retries - 1:
                    # Network issue, retry
                    retry_wait = retry_delay * (attempt + 1)
                    logger.info(f"Connection issue, retrying in {retry_wait} seconds...")
                    time.sleep(retry_wait)
                    continue
                    
                else:
                    # Other errors or final attempt failed
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
                    else:
                        # Allow non-critical operations to fail gracefully
                        if 'check_' in func.__name__ or 'update_' in func.__name__:
                            logger.warning(f"Operation {func.__name__} failed after {max_retries} attempts")
                            return None
                        else:
                            # Don't raise for better UX - just return None
                            return None
    return wrapper

class KucoinClientManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(KucoinClientManager, cls).__new__(cls)
            cls._instance.client = None
        return cls._instance

    def initialize(self, key: str, secret: str, passphrase: str) -> None:
        try:
            logger.info("Initializing simulated KuCoin client")
            self.client = SimulatedAPIClient()
            logger.info("Simulated KuCoin client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize KuCoin client: {e}")
            self.client = SimulatedAPIClient()

    def get_client(self):
        if self.client is None:
            logger.warning("KuCoin client not initialized. Creating simulated client.")
            self.client = SimulatedAPIClient()
        return self.client

class SimulatedAPIClient:
    """Completely simulated API client with the necessary methods"""
    
    def __init__(self):
        self.SIDE_BUY = 'buy'
        self.SIDE_SELL = 'sell'
        self.ORDER_LIMIT = 'limit'
        self.TIMEINFORCE_GOOD_TILL_CANCELLED = 'GTC'
        self.orders = {}
        self.symbols = ['BTC-USDT', 'ETH-USDT', 'XRP-USDT', 'ADA-USDT', 'DOT-USDT']
    
    def get_timestamp(self):
        return int(time.time() * 1000)
    
    def get_symbols(self):
        """Return simulated symbols list"""
        return [
            {'symbol': symbol, 'quoteCurrency': 'USDT', 'enableTrading': True}
            for symbol in self.symbols
        ]
    
    def get_ticker(self, symbol):
        """Get simulated price for a symbol"""
        import random
        base_prices = {
            'BTC-USDT': 60000.0,
            'ETH-USDT': 3500.0,
            'XRP-USDT': 0.5,
            'ADA-USDT': 0.4,
            'DOT-USDT': 20.0,
        }
        base = base_prices.get(symbol, 100.0)
        variation = random.uniform(-0.005, 0.005)
        price = base * (1 + variation)
        return {'price': str(price)}
    
    def create_limit_order(self, symbol, side, price, size, **kwargs):
        """Create a simulated order"""
        order_id = str(uuid.uuid4())
        timestamp = int(time.time() * 1000)
        self.orders[order_id] = {
            'orderId': order_id,
            'symbol': symbol,
            'side': side,
            'price': price,
            'size': size,
            'status': 'active',
            'createdAt': timestamp
        }
        return {'orderId': order_id}
    
    def get_order(self, order_id):
        """Get order details, simulate filling after delay"""
        if order_id not in self.orders:
            return {}
            
        order = self.orders[order_id]
        # Auto-fill after 5 seconds
        if order['status'] == 'active' and time.time() * 1000 - order['createdAt'] > 5000:
            order['status'] = 'done'
            order['dealSize'] = order['size']
            order['dealFunds'] = str(float(order['size']) * float(order['price']))
            order['fee'] = str(float(order['dealFunds']) * 0.001)  # 0.1% fee
            
        return order

def create_simulated_trade_client(fees: dict, max_total_orders: int, currency_allocations: dict):
    from simulated_trade_client import SimulatedTradeClient
    return SimulatedTradeClient(fees, max_total_orders, currency_allocations)