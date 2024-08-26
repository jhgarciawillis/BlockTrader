import logging
from typing import Dict, List, Any, Optional
import streamlit as st
from kucoin.client import Market, Trade, User
import time

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Default configurations
DEFAULT_CONFIG = {
    'trading_symbols': ['BTC-USDT', 'ETH-USDT', 'XRP-USDT', 'ADA-USDT', 'DOT-USDT'],
    'profit_margin': 0.01,  # 1%
    'num_orders': 1,
    'usdt_liquid_percentage': 0.5,  # 50%
    'simulation_mode': {
        'enabled': True,
        'initial_balance': 1000.0,
    },
    'chart_config': {
        'update_interval': 1,  # in seconds
        'history_length': 120,  # in minutes
        'height': 600,
        'width': 800,
    },
    'bot_config': {
        'update_interval': 1,  # in seconds
        'price_check_interval': 5,  # in seconds
    },
    'error_config': {
        'max_retries': 3,
        'retry_delay': 5,  # in seconds
    }
}

class KucoinClientManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(KucoinClientManager, cls).__new__(cls)
            cls._instance.market_client = None
            cls._instance.trade_client = None
            cls._instance.user_client = None
        return cls._instance

    def initialize(self, api_key: str, api_secret: str, api_passphrase: str, api_url: str) -> None:
        self.market_client = Market(key=api_key, secret=api_secret, passphrase=api_passphrase, url=api_url)
        self.trade_client = Trade(key=api_key, secret=api_secret, passphrase=api_passphrase, url=api_url)
        self.user_client = User(key=api_key, secret=api_secret, passphrase=api_passphrase, url=api_url)

    def get_client(self, client_type: type) -> Any:
        if client_type == Market:
            return self.market_client
        elif client_type == Trade:
            return self.trade_client
        elif client_type == User:
            return self.user_client
        else:
            raise ValueError(f"Unknown client type: {client_type}")

kucoin_client_manager = KucoinClientManager()

class ConfigManager:
    def __init__(self):
        self.config = self.load_config()

    def load_config(self) -> Dict[str, Any]:
        config = DEFAULT_CONFIG.copy()
        config.update({
            'api_key': st.secrets["api_credentials"]["api_key"],
            'api_secret': st.secrets["api_credentials"]["api_secret"],
            'api_passphrase': st.secrets["api_credentials"]["api_passphrase"],
            'api_url': 'https://api.kucoin.com',
            'live_trading_access_key': st.secrets["api_credentials"]["live_trading_access_key"],
        })
        config['trading_symbols'] = self.validate_trading_symbols(config['trading_symbols'])
        return config

    def validate_trading_symbols(self, symbols: List[str]) -> List[str]:
        available_symbols = self.get_available_trading_symbols()
        valid_symbols = [symbol for symbol in symbols if symbol in available_symbols]
        if len(valid_symbols) != len(symbols):
            logger.warning(f"Some trading symbols are not available: {set(symbols) - set(valid_symbols)}")
            logger.info(f"Using available trading symbols: {valid_symbols}")
        return valid_symbols

    def get_available_trading_symbols(self) -> List[str]:
        try:
            market_client = kucoin_client_manager.get_client(Market)
            symbols = market_client.get_symbol_list()
            return [symbol['symbol'] for symbol in symbols if symbol['quoteCurrency'] == 'USDT']
        except Exception as e:
            logger.error(f"Unexpected error fetching symbol list: {e}")
            return self.config['trading_symbols']

    def verify_live_trading_access(self, input_key: str) -> bool:
        return input_key == self.config['live_trading_access_key']

    def fetch_real_time_prices(self, symbols: List[str]) -> Dict[str, float]:
        prices = {}
        try:
            market_client = kucoin_client_manager.get_client(Market)
            for symbol in symbols:
                ticker = market_client.get_ticker(symbol)
                prices[symbol] = float(ticker['price'])
            logger.info(f"Fetched real-time prices: {prices}")
        except Exception as e:
            logger.error(f"Unexpected error fetching real-time prices: {e}")
        return prices

    def place_spot_order(self, symbol: str, side: str, price: float, size: float, is_simulation: bool = False) -> Dict[str, Any]:
        try:
            if is_simulation:
                order = {
                    'orderId': f'sim_{side}_{symbol}_{time.time()}',
                    'symbol': symbol,
                    'side': side,
                    'price': price,
                    'size': size,
                    'fee': size * price * 0.001  # Simulated 0.1% fee
                }
            else:
                trade_client = kucoin_client_manager.get_client(Trade)
                order = trade_client.create_limit_order(
                    symbol=symbol,
                    side=side,
                    price=str(price),
                    size=str(size)
                )
            logger.info(f"{'Simulated' if is_simulation else 'Placed'} {side} order for {symbol}: {order}")
            return order
        except Exception as e:
            logger.error(f"Unexpected error {'simulating' if is_simulation else 'placing'} {side} order for {symbol}: {e}")
            return {}

    def initialize_kucoin_client(self) -> None:
        kucoin_client_manager.initialize(
            self.config['api_key'],
            self.config['api_secret'],
            self.config['api_passphrase'],
            self.config['api_url']
        )

config_manager = ConfigManager()

if __name__ == "__main__":
    print("Loaded configuration:", config_manager.config)
    config_manager.initialize_kucoin_client()
    symbols = config_manager.get_available_trading_symbols()
    print("Available trading symbols:", symbols)
    prices = config_manager.fetch_real_time_prices(config_manager.config['trading_symbols'])
    print("Fetched real-time prices:", prices)
