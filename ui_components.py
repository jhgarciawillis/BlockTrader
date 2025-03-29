import streamlit as st
import pandas as pd
from typing import Dict, List, Tuple, Any, Optional
import logging
from config import config_manager, DEFAULT_CONFIG

logger = logging.getLogger(__name__)

class UIComponent:
    def display(self, *args, **kwargs):
        raise NotImplementedError("Subclasses must implement display method")

class UIManager:
    def __init__(self, bot):
        self.bot = bot
        self.components = {
            'sidebar_controls': SidebarControls(),
            'status_table': StatusTable(bot) if bot else None,
            'trade_messages': TradeMessages(),
            'error_message': ErrorMessage(),
            'trading_controls': TradingControls(),
            'symbol_selector': SymbolSelector(),
            'chart_display': ChartDisplay(),
            'simulation_indicator': SimulationIndicator(),
        }

    def display_component(self, component_name: str, *args, **kwargs):
        if component_name in self.components:
            logger.info(f"Displaying component: {component_name}")
            
            # Special handling for symbol selector to ensure it has symbols
            if component_name == 'symbol_selector':
                available_symbols = kwargs.get('available_symbols', [])
                if not available_symbols:
                    logger.warning("No symbols available, using defaults")
                    available_symbols = DEFAULT_CONFIG['trading_symbols']
                    kwargs['available_symbols'] = available_symbols
            
            return self.components[component_name].display(*args, **kwargs)
        else:
            logger.error(f"Component '{component_name}' not found")
            st.error(f"UI component '{component_name}' not found")

class SidebarControls(UIComponent):
    def display(self, is_simulation: bool) -> Tuple[Optional[float], float, float, int]:
        logger.info("Displaying sidebar controls.")
        st.sidebar.header("Configuration")
        if is_simulation:
            logger.info("Simulation mode selected.")
            st.sidebar.write("Running in simulation mode. No real trades will be executed.")
            simulated_usdt_balance = st.sidebar.number_input(
                "Simulated USDT Balance",
                min_value=0.0,
                value=config_manager.get_config('simulation_mode')['initial_balance'],
                step=0.1,
                key='simulated_usdt_balance'
            )
        else:
            simulated_usdt_balance = None
            
        liquid_ratio = st.sidebar.number_input(
            "Enter the percentage of your assets to keep liquid in USDT (0-100%)",
            min_value=0.0,
            max_value=100.0,
            value=config_manager.get_config('liquid_ratio', 0.5) * 100,
            step=0.0001,
            format="%.4f",
            key='liquid_ratio'
        ) / 100

        profit_margin_percentage = st.sidebar.number_input(
            "Profit Margin Percentage",
            min_value=0.0001,
            value=config_manager.get_config('profit_margin', 0.0001) * 100,
            step=0.0001,
            format="%.4f",
            key='profit_margin_percentage'
        ) / 100

        max_total_orders = st.sidebar.slider(
            "Maximum Total Orders",
            min_value=1,
            max_value=50,
            value=config_manager.get_config('max_total_orders', 10),
            step=1,
            key='max_total_orders'
        )

        return simulated_usdt_balance, liquid_ratio, profit_margin_percentage, max_total_orders
    
class StatusTable(UIComponent):
    def __init__(self, bot):
        self.bot = bot

    def display(self, current_status: Dict[str, Any] = None) -> None:
        if not current_status:
            logger.warning("No current status available.")
            st.warning("No current status available.")
            return
        logger.info("Displaying status table.")
        
        # Show pending orders if any
        if current_status.get('pending_orders', {}):
            st.subheader("Pending Orders")
            pending_orders_df = self._create_pending_orders_dataframe(current_status)
            st.dataframe(pending_orders_df, use_container_width=True)
        
        # Overall status
        status_df = self._create_status_dataframe(current_status)
        st.dataframe(status_df, use_container_width=True)

    def _create_pending_orders_dataframe(self, current_status: Dict[str, Any]) -> pd.DataFrame:
        logger.info("Creating pending orders dataframe.")
        pending_orders = current_status.get('pending_orders', {})
        
        if not pending_orders:
            return pd.DataFrame()
        
        data = {
            'Symbol': [],
            'Type': [],
            'Price': [],
            'Amount': [],
            'Order Time': [],
            'Status': []
        }
        
        for order_id, order in pending_orders.items():
            data['Symbol'].append(order['symbol'])
            data['Type'].append('Buy' if order['side'] == 'buy' else 'Sell')
            data['Price'].append(f"{order['price']:.4f} USDT")
            data['Amount'].append(f"{order['amount']:.8f}")
            data['Order Time'].append(order['order_time'].strftime('%Y-%m-%d %H:%M:%S'))
            data['Status'].append('Pending')
        
        return pd.DataFrame(data)

    def _create_symbol_status_data(self, current_status: Dict[str, Any]) -> Dict[str, List[Any]]:
        logger.info("Creating symbol status data.")
        symbols = list(current_status['prices'].keys())
        return {
            'Symbol': symbols,
            'Current Price': [self._format_price(current_status['prices'].get(symbol)) for symbol in symbols],
            'Buy Price': [self._format_buy_price(current_status['active_trades'], symbol) for symbol in symbols],
            'Target Sell Price': [self._format_target_sell_price(current_status['active_trades'], symbol, self.bot.profit_margin) for symbol in symbols],
            'Current P/L': [self._format_current_pl(current_status['prices'], current_status['active_trades'], symbol) for symbol in symbols],
            'Realized Profit': [self._format_realized_profit(current_status['profits'], symbol) for symbol in symbols],
            'Active Orders': [current_status['active_orders'].get(symbol, 0) for symbol in symbols],
        }

    def _create_status_dataframe(self, current_status: Dict[str, Any]) -> pd.DataFrame:
        logger.info("Creating status dataframe.")
        symbol_data = self._create_symbol_status_data(current_status)
        summary_data = self._create_summary_data(current_status)
        return pd.concat([pd.DataFrame(symbol_data), pd.DataFrame(summary_data)], ignore_index=True)

    def _create_summary_data(self, current_status: Dict[str, Any]) -> Dict[str, List[Any]]:
        logger.info("Creating summary data.")
        total_current_value = current_status['current_total_usdt']
        total_buy_value = sum(
            trade['buy_price'] * trade['amount']
            for trade in current_status['active_trades'].values()
        )
        total_active_orders = sum(current_status['active_orders'].values())
        return {
            'Symbol': ['Total'],
            'Current Price': [f"{total_current_value:.4f} USDT"],
            'Buy Price': [f"{total_buy_value:.4f} USDT"],
            'Target Sell Price': [''],
            'Current P/L': [f"{(total_current_value - total_buy_value) / total_buy_value * 100:.2f}%" if total_buy_value > 0 else 'N/A'],
            'Realized Profit': [f"{current_status['total_profit']:.4f} USDT"],
            'Active Orders': [total_active_orders],
        }

    @staticmethod
    def _format_price(price: Optional[float]) -> str:
        return f"{price:.4f} USDT" if price is not None else "N/A"

    @staticmethod
    def _format_buy_price(active_trades: Dict[str, Dict[str, Any]], symbol: str) -> str:
        buy_order = next((trade for trade in active_trades.values() if trade['symbol'] == symbol), None)
        return f"{buy_order['buy_price']:.4f} USDT" if buy_order else 'N/A'

    @staticmethod
    def _format_target_sell_price(active_trades: Dict[str, Dict[str, Any]], symbol: str, profit_margin: float) -> str:
        buy_order = next((trade for trade in active_trades.values() if trade['symbol'] == symbol), None)
        if buy_order:
            target_sell_price = buy_order.get('target_sell_price', buy_order['buy_price'] * (1 + profit_margin))
            return f"{target_sell_price:.4f} USDT"
        return 'N/A'

    @staticmethod
    def _format_current_pl(prices: Dict[str, float], active_trades: Dict[str, Dict[str, Any]], symbol: str) -> str:
        current_price = prices.get(symbol)
        buy_order = next((trade for trade in active_trades.values() if trade['symbol'] == symbol), None)
        if current_price is not None and buy_order and buy_order['buy_price'] != 0:
            pl_percentage = (current_price - buy_order['buy_price']) / buy_order['buy_price'] * 100
            return f"{pl_percentage:.2f}%"
        return 'N/A'

    @staticmethod
    def _format_realized_profit(profits: Dict[str, float], symbol: str) -> str:
        return f"{profits.get(symbol, 0):.4f} USDT"

class TradeMessages(UIComponent):
    def display(self) -> None:
        logger.info("Displaying trade messages.")
        st.text("\n".join(st.session_state.trade_messages[-10:]))  # Display last 10 messages

class ErrorMessage(UIComponent):
    def display(self, error_message: str, container) -> None:
        if error_message:
            logger.error(f"Displaying error message: {error_message}")
            container.error(error_message)

class TradingControls(UIComponent):
    def display(self) -> Tuple[bool, bool]:
        logger.info("Displaying trading controls.")
        col1, col2 = st.sidebar.columns(2)
        start_button = col1.button("Start Trading")
        stop_button = col2.button("Stop Trading")
        return start_button, stop_button

class SymbolSelector(UIComponent):
    def display(self, available_symbols: List[str], default_symbols: List[str]) -> List[str]:
        logger.info("Displaying symbol selector.")
        # Ensure we have symbols to display
        if not available_symbols:
            logger.warning("No available symbols provided, using default symbols")
            available_symbols = DEFAULT_CONFIG['trading_symbols']
        
        if not default_symbols:
            logger.warning("No default symbols provided, using first symbol")
            default_symbols = [available_symbols[0]] if available_symbols else []
        
        selected_symbols = st.sidebar.multiselect(
            "Select Symbols to Trade", 
            options=available_symbols, 
            default=default_symbols, 
            key='selected_symbols'
        )
        
        # Fallback if nothing selected
        if not selected_symbols and available_symbols:
            logger.warning("No symbols selected, using first available symbol")
            selected_symbols = [available_symbols[0]]
            st.sidebar.warning(f"No symbols selected. Using {selected_symbols[0]} by default.")
        
        return selected_symbols

class ChartDisplay(UIComponent):
    def display(self, charts: Dict[str, Any]) -> None:
        logger.info("Displaying charts.")
        if not charts:
            st.info("No chart data available yet. Start trading to see charts.")
            return
            
        for symbol, chart in charts.get('individual_price_charts', {}).items():
            st.plotly_chart(chart, use_container_width=True)
        
        if 'total_profit' in charts:
            st.plotly_chart(charts['total_profit'], use_container_width=True)

class SimulationIndicator(UIComponent):
    def display(self, is_simulation: bool) -> None:
        logger.info(f"Displaying simulation indicator: {is_simulation}")
        if is_simulation:
            st.sidebar.warning("Running in Simulation Mode")
        else:
            st.sidebar.success("Running in Live Trading Mode")