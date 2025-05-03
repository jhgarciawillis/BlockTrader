# simulated_trade_client.py
import time
import uuid
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

# Define constants to avoid dependency on the KuCoin client
ORDER_LIMIT = 'limit'
SIDE_BUY = 'buy'
SIDE_SELL = 'sell'
TIMEINFORCE_GOOD_TILL_CANCELLED = 'GTC'

class SimulatedTradeClient:
    def __init__(self, fees: Dict[str, float], max_total_orders: int, currency_allocations: Dict[str, float]):
        self.orders = {}
        self.MAKER_FEE = fees.get('maker', 0.001)  # Default 0.1%
        self.TAKER_FEE = fees.get('taker', 0.001)  # Default 0.1%
        self.max_total_orders = max_total_orders
        self.currency_allocations = currency_allocations
        self.pending_orders = {}  # Orders not immediately filled

    def create_limit_order(self, symbol: str, side: str, price: str, size: str, **kwargs) -> Dict[str, Any]:
        if len(self.orders) >= self.max_total_orders:
            logger.warning(f"Maximum total orders ({self.max_total_orders}) reached")
            return {}

        order_id = str(uuid.uuid4())
        timestamp = int(time.time() * 1000)
        price = float(price)
        size = float(size)
        
        # Create the initial order with status 'active'
        order = {
            'orderId': order_id,
            'symbol': symbol,
            'opType': 'DEAL',
            'type': ORDER_LIMIT,
            'side': side,
            'price': str(price),
            'size': str(size),
            'funds': str(price * size),
            'dealFunds': '0',  # No funds dealt yet
            'dealSize': '0',   # No size dealt yet
            'fee': '0',
            'feeCurrency': symbol.split('-')[1],
            'createdAt': timestamp,
            'updatedAt': timestamp,
            'status': 'active',  # Start as active, not immediately done
            'timeInForce': kwargs.get('timeInForce', TIMEINFORCE_GOOD_TILL_CANCELLED),
            'postOnly': kwargs.get('postOnly', False),
            'hidden': kwargs.get('hidden', False),
            'iceberg': kwargs.get('iceberg', False),
            'visibleSize': kwargs.get('visibleSize', '0'),
            'cancelAfter': kwargs.get('cancelAfter', 0),
            'channel': 'API',
            'clientOid': kwargs.get('clientOid', f'simulated_{side}_{symbol}_{timestamp}'),
            'remark': kwargs.get('remark', None),
            'tags': kwargs.get('tags', None),
            'isActive': True,
            'cancelExist': False,
            'tradeType': 'TRADE'
        }
        
        self.orders[order_id] = order
        logger.info(f"Created simulated {side} order: {size:.8f} {symbol} at {price:.4f} USDT")
        
        # For simulation, let's fill the order after a short delay
        self._simulate_fill_after_delay(order_id)
        
        return {'orderId': order_id}
    
    def _simulate_fill_after_delay(self, order_id):
        """Simulate order filling after a delay by marking it as ready to fill"""
        self.pending_orders[order_id] = {
            'ready_time': time.time() + 5  # 5 seconds delay
        }
    
    def get_order(self, order_id: str):
        # Check if there's a pending order ready to fill
        if order_id in self.pending_orders and time.time() > self.pending_orders[order_id]['ready_time']:
            self._fill_order(order_id)
            del self.pending_orders[order_id]
            
        return self.orders.get(order_id, {})

    def _fill_order(self, order_id: str) -> None:
        """Simulate filling an order"""
        if order_id not in self.orders:
            return
            
        order = self.orders[order_id]
        if order['status'] != 'active':
            return
        
        side = order['side']
        price = float(order['price'])
        size = float(order['size'])
        
        if side == SIDE_BUY:
            # Calculate fee in USDT
            amount_usdt = size * price
            fee_usdt = amount_usdt * self.TAKER_FEE
            
            # Update order with filled details
            order['dealFunds'] = str(amount_usdt)
            order['dealSize'] = str(size)
            order['fee'] = str(fee_usdt)
            order['status'] = 'done'
            order['isActive'] = False
            order['updatedAt'] = int(time.time() * 1000)
            
            logger.info(f"Filled simulated buy order: {size:.8f} {order['symbol']} "
                       f"at {price:.4f} USDT (Fee: {fee_usdt:.8f} USDT)")
            
        else:  # sell
            amount_crypto = size
            amount_usdt = amount_crypto * price
            fee_usdt = amount_usdt * self.TAKER_FEE
            
            # Update order with filled details
            order['dealFunds'] = str(amount_usdt)
            order['dealSize'] = str(amount_crypto)
            order['fee'] = str(fee_usdt)
            order['status'] = 'done'
            order['isActive'] = False
            order['updatedAt'] = int(time.time() * 1000)
            
            logger.info(f"Filled simulated sell order: {amount_crypto:.8f} {order['symbol']} "
                       f"at {price:.4f} USDT (Fee: {fee_usdt:.8f} USDT)")
            
        self.orders[order_id] = order

    def cancel_order(self, order_id: str):
        if order_id in self.orders:
            self.orders[order_id]['status'] = 'cancelled'
            self.orders[order_id]['isActive'] = False
            self.orders[order_id]['updatedAt'] = int(time.time() * 1000)
            logger.info(f"Cancelled order: {order_id}")
            if order_id in self.pending_orders:
                del self.pending_orders[order_id]
            return {'cancelledOrderIds': [order_id]}
        return {'cancelledOrderIds': []}

    def get_fills(self, trade_type: str = 'TRADE', order_id: str = None):
        fills = []
        for order in self.orders.values():
            if order['status'] == 'done':
                if order_id is None or order['orderId'] == order_id:
                    fills.append({
                        'symbol': order['symbol'],
                        'tradeId': str(uuid.uuid4()),
                        'orderId': order['orderId'],
                        'counterOrderId': str(uuid.uuid4()),
                        'side': order['side'],
                        'liquidity': 'taker',
                        'forceTaker': True,
                        'price': order['price'],
                        'size': order['dealSize'],
                        'funds': order['dealFunds'],
                        'fee': order['fee'],
                        'feeRate': str(self.TAKER_FEE),
                        'feeCurrency': order['feeCurrency'],
                        'stop': '',
                        'type': 'limit',
                        'createdAt': order['createdAt'],
                        'tradeType': 'TRADE'
                    })
        return fills

    def get_orders(self, symbol: str = None, status: str = None):
        orders = []
        for order in self.orders.values():
            if (symbol is None or order['symbol'] == symbol) and \
               (status is None or 
                (status == 'active' and order['isActive']) or 
                (status == 'done' and not order['isActive'])):
                orders.append(order)
        return orders

def create_simulated_trade_client(fees: dict, max_total_orders: int, currency_allocations: dict) -> SimulatedTradeClient:
    return SimulatedTradeClient(fees, max_total_orders, currency_allocations)