import time
import threading
import streamlit as st
from typing import List, Tuple, Dict, Any
from trading_bot import TradingBot
import logging
from config import config_manager
from simulated_trade_client import SIDE_BUY, SIDE_SELL
from utils import handle_trading_errors

logger = logging.getLogger(__name__)

class TradingLoop:
    def __init__(self, bot: TradingBot, chosen_symbols: List[str], profit_margin: float, taker_fee: float, maker_fee: float):
        self.bot = bot
        self.chosen_symbols = chosen_symbols
        self.profit_margin = profit_margin if profit_margin is not None else config_manager.get_config('profit_margin')
        self.taker_fee = taker_fee
        self.maker_fee = maker_fee
        self.order_check_interval = 10  # seconds to check order status

    @handle_trading_errors
    def run(self, stop_event: threading.Event) -> None:
        last_order_check_time = 0
        
        while not stop_event.is_set():
            try:
                current_time = time.time()
                
                # Check pending orders frequently
                if current_time - last_order_check_time >= self.order_check_interval:
                    self.bot.check_pending_orders()
                    last_order_check_time = current_time
                
                # Regular trading iteration
                self.trading_iteration()
                
                time.sleep(config_manager.get_config('bot_config')['update_interval'])
            except Exception as e:
                logger.error(f"An error occurred in the trading loop: {str(e)}")
                time.sleep(config_manager.get_config('error_config')['retry_delay'])

    @handle_trading_errors
    def trading_iteration(self) -> None:
        try:
            current_prices = config_manager.fetch_real_time_prices(self.chosen_symbols)
            
            # First check if there are any pending orders that need attention
            self.bot.check_pending_orders()
            
            # Process each symbol
            for symbol in self.chosen_symbols:
                if current_prices.get(symbol) is not None:
                    self.process_symbol(symbol, current_prices[symbol])

            self.update_bot_status(current_prices)
        except Exception as e:
            logger.error(f"Error in trading iteration: {e}")

    @handle_trading_errors
    def process_symbol(self, symbol: str, current_price: float) -> None:
        try:
            # Update price history
            self.bot.update_price_history([symbol], {symbol: current_price})

            # Process orders if possible
            if self.bot.can_place_order(symbol):
                self.check_buy_condition(symbol, current_price)
            
            self.check_sell_condition(symbol, current_price)

        except Exception as e:
            logger.error(f"Error processing symbol {symbol}: {e}")

    @handle_trading_errors
    def check_buy_condition(self, symbol: str, current_price: float) -> None:
        try:
            should_buy = self.bot.should_buy(symbol, current_price)
            if should_buy is not None:
                available_balance = self.bot.get_balance('USDT', 'trading')
                if available_balance > 0:
                    # Calculate order size in USDT
                    max_order_amount = min(available_balance, self.bot.symbol_allocations.get(symbol, 0))
                    
                    if max_order_amount > 0:
                        order = self.bot.place_buy_order(symbol, max_order_amount, should_buy)
                        if order and 'orderId' in order:
                            if 'trade_messages' in st.session_state:
                                st.session_state.trade_messages.append(
                                    f"Buy order placed for {symbol} at {should_buy} USDT"
                                )
        except Exception as e:
            logger.error(f"Error checking buy condition for {symbol}: {e}")

    @handle_trading_errors
    def check_sell_condition(self, symbol: str, current_price: float) -> None:
        try:
            # Check active trades for sell opportunities
            for order_id, trade in list(self.bot.active_trades.items()):
                if trade['symbol'] == symbol:
                    target_sell_price = trade['target_sell_price']
                    
                    # Only sell if we can get our target price or better
                    if current_price >= target_sell_price:
                        sell_amount = trade['amount']
                        
                        # Place sell order at current price (which is >= target price)
                        sell_order = self.bot.place_sell_order(
                            symbol, 
                            sell_amount, 
                            current_price,
                            order_id
                        )
                        
                        if sell_order and 'orderId' in sell_order:
                            if 'trade_messages' in st.session_state:
                                st.session_state.trade_messages.append(
                                    f"Sell order placed for {symbol} at {current_price} USDT (Target: {target_sell_price} USDT)"
                                )
        
        except Exception as e:
            logger.error(f"Error checking sell condition for {symbol}: {e}")

    @handle_trading_errors
    def update_bot_status(self, current_prices: Dict[str, float]) -> None:
        try:
            current_status = self.bot.get_current_status(current_prices)
            
            if 'trade_messages' in st.session_state:
                for symbol, profit in current_status['profits'].items():
                    if profit > 0:
                        st.session_state.trade_messages.append(
                            f"Profit for {symbol}: {profit:.8f} USDT"
                        )
                
                st.session_state.trade_messages = st.session_state.trade_messages[-10:]

            self.bot.update_allocations(self.chosen_symbols)
            
        except Exception as e:
            logger.error(f"Error updating bot status: {e}")

def initialize_trading_loop(bot: TradingBot, chosen_symbols: List[str]) -> Tuple[threading.Event, threading.Thread]:
    stop_event = threading.Event()
    profit_margin = bot.profit_margin
    taker_fee = bot.taker_fee
    maker_fee = bot.maker_fee
    trading_loop = TradingLoop(bot, chosen_symbols, profit_margin, taker_fee, maker_fee)
    trading_thread = threading.Thread(target=trading_loop.run, args=(stop_event,), daemon=True)
    trading_thread.start()
    return stop_event, trading_thread

def stop_trading_loop(stop_event: threading.Event, trading_thread: threading.Thread) -> None:
    stop_event.set()
    try:
        trading_thread.join(timeout=10)
    except TimeoutError:
        logger.warning("Trading thread did not stop within the timeout period")
    else:
        logger.info("Trading loop stopped successfully")