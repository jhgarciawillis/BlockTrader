# config.py
import logging
from typing import Dict, Any
import streamlit as st
from utils import KucoinClientManager, SimulatedAPIClient
from simulated_trade_client import SimulatedTradeClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    'trading_symbols': ['BTC-USDT', 'ETH-USDT', 'XRP-USDT', 'ADA-USDT', 'DOT-USDT'],
    'profit_margin': 0.05,  # 5%
    'liquid_ratio': 0.5,  # 50%
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
    },
    'fees': {
        'maker': 0.001,  # 0.1%
        'taker': 0.001,  # 0.1%
    },
    'max_total_orders': 10,
    'currency_allocations': {},
}

class ConfigManager:
    def __init__(self):
        self.config = None
        logger.info("Loading configuration")
        self.config = self.load_config()

    def load_config(self) -> Dict[str, Any]:
        logger.info("Loading default configuration")
        config = DEFAULT_CONFIG.copy()
        try:
            config.update({
                'api_key': st.secrets["api_credentials"]["api_key"],
                'api_secret': st.secrets["api_credentials"]["api_secret"],
                'api_passphrase': st.secrets["api_credentials"]["api_passphrase"],
                'api_url': 'https://api.kucoin.com',
                'live_trading_access_key': st.secrets["api_credentials"]["perso_key"],
            })
        except KeyError as e:
            logger.error(f"Missing API credential in Streamlit secrets: {e}")
            logger.warning("Using default API credentials for simulation")
        return config

    def save_config(self):
        # Implement saving configuration to a file
        pass

    def update_config(self, key: str, value: Any) -> None:
        self.config[key] = value

    def validate_config(self) -> None:
        # Implement configuration validation
        pass

    def validate_trading_symbols(self, symbols: list) -> list:
        # For simulation, just return the symbols as they are
        return symbols

    def get_available_trading_symbols(self) -> list:
        """Return a list of available trading symbols"""
        try:
            # Use our simulated client
            client = kucoin_client_manager.get_client()
            symbols_data = client.get_symbols()
            return [symbol['symbol'] for symbol in symbols_data]
        except Exception as e:
            logger.error(f"Error fetching symbols: {e}")
            return DEFAULT_CONFIG['trading_symbols']

    def fetch_real_time_prices(self, symbols: list) -> dict:
        prices = {}
        try:
            client = kucoin_client_manager.get_client()
            for symbol in symbols:
                ticker = client.get_ticker(symbol)
                prices[symbol] = float(ticker['price'])
            logger.debug(f"Fetched prices: {prices}")
        except Exception as e:
            logger.error(f"Error fetching prices: {e}")
            # Fallback to static prices
            for symbol in symbols:
                prices[symbol] = 100.0
                
        return prices

    def place_spot_order(self, symbol: str, side: str, price: float, size: float, is_simulation: bool = False) -> Dict[str, Any]:
        try:
            simulated_client = self.create_simulated_trade_client(
                self.config['fees'],
                self.config['max_total_orders'],
                self.config['currency_allocations']
            )
            order = simulated_client.create_limit_order(
                symbol=symbol,
                side=side,
                price=str(price),
                size=str(size)
            )
            return order
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return {}

    def initialize_kucoin_client(self) -> None:
        try:
            # Initialize our simulated client
            kucoin_client_manager.initialize(
                key="simulation",
                secret="simulation",
                passphrase="simulation"
            )
            logger.info("Simulated KuCoin client initialized successfully.")
        except Exception as e:
            logger.error(f"Error initializing KuCoin client: {e}")

    def verify_live_trading_access(self, input_key: str) -> bool:
        return input_key == self.config.get('live_trading_access_key', '')

    def get_config(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def get_max_total_orders(self) -> int:
        return self.config['max_total_orders']

    def get_currency_allocations(self) -> Dict[str, float]:
        return self.config['currency_allocations']

    def create_simulated_trade_client(self, fees: Dict[str, float], max_total_orders: int, currency_allocations: Dict[str, float]) -> SimulatedTradeClient:
        from simulated_trade_client import create_simulated_trade_client
        return create_simulated_trade_client(fees, max_total_orders, currency_allocations)

    def get_taker_fee(self) -> float:
        return self.config['fees']['taker']

    def get_maker_fee(self) -> float:
        return self.config['fees']['maker']

    def get_profit_margin(self) -> float:
        return self.config['profit_margin']

config_manager = ConfigManager()
kucoin_client_manager = KucoinClientManager()

if __name__ == "__main__":
    logger.info("Running config.py as main script")
    config_manager.initialize_kucoin_client()
    symbols = config_manager.get_available_trading_symbols()
    logger.info(f"Available trading symbols: {symbols}")
    prices = config_manager.fetch_real_time_prices(config_manager.config['trading_symbols'])
    logger.info(f"Current prices: {prices}")