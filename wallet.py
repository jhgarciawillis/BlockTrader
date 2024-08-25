from datetime import datetime
from typing import Dict, List, Tuple, Callable, Optional
import logging
import asyncio

logger = logging.getLogger(__name__)

class Currency:
    def __init__(self, symbol: str, balance: float = 0):
        self.symbol: str = symbol
        self.balance: float = balance
        self.price_history: List[Tuple[datetime, float]] = []
        self.buy_history: List[Tuple[datetime, float, float]] = []
        self.sell_history: List[Tuple[datetime, float, float]] = []
        self.current_price: Optional[float] = None

    async def update_price(self, price: float, timestamp: Optional[datetime] = None) -> None:
        if timestamp is None:
            timestamp = datetime.now()
        self.price_history.append((timestamp, price))
        self.current_price = price

    async def record_trade(self, amount: float, price: float, trade_type: str, timestamp: Optional[datetime] = None) -> None:
        if timestamp is None:
            timestamp = datetime.now()
        
        if trade_type == 'buy':
            self.buy_history.append((timestamp, amount, price))
            self.balance += amount
        elif trade_type == 'sell':
            self.sell_history.append((timestamp, amount, price))
            self.balance -= amount
        
        logger.info(f"Recorded {trade_type}: {self.symbol} - Amount: {amount}, Price: {price}")

class Account:
    def __init__(self, account_type: str, currencies: Optional[Dict[str, Currency]] = None):
        self.account_type: str = account_type
        self.currencies: Dict[str, Currency] = currencies or {}

    async def add_currency(self, symbol: str, balance: float = 0) -> None:
        if symbol not in self.currencies:
            self.currencies[symbol] = Currency(symbol, balance)
            logger.info(f"Added currency {symbol} to account {self.account_type}")

    def get_currency_balance(self, symbol: str) -> float:
        return self.currencies.get(symbol, Currency(symbol)).balance

    async def update_currency_balance(self, symbol: str, new_balance: float) -> None:
        if symbol not in self.currencies:
            await self.add_currency(symbol, new_balance)
        else:
            self.currencies[symbol].balance = new_balance
        logger.info(f"Updated balance for {symbol} in account {self.account_type}: {new_balance}")

    async def update_currency_price(self, symbol: str, price: float) -> None:
        if symbol in self.currencies:
            await self.currencies[symbol].update_price(price)
            logger.info(f"Updated price for {symbol} in account {self.account_type}: {price}")

class Wallet:
    def __init__(self, accounts: Optional[Dict[str, Account]] = None):
        self.accounts: Dict[str, Account] = accounts or {}

    async def add_account(self, account_type: str) -> None:
        if account_type not in self.accounts:
            self.accounts[account_type] = Account(account_type)
            logger.info(f"Added account {account_type} to wallet")

    def get_account(self, account_type: str) -> Optional[Account]:
        return self.accounts.get(account_type)

    async def get_total_balance_in_usdt(self, price_fetcher: Callable[[str], Optional[float]]) -> float:
        total_usdt = 0
        for account in self.accounts.values():
            for currency in account.currencies.values():
                if currency.symbol == 'USDT':
                    total_usdt += currency.balance
                else:
                    price = await price_fetcher(currency.symbol + '-USDT')
                    if price is not None:
                        total_usdt += currency.balance * price
        return total_usdt

    async def update_account_balance(self, account_type: str, symbol: str, new_balance: float) -> None:
        if account_type not in self.accounts:
            await self.add_account(account_type)
        await self.accounts[account_type].update_currency_balance(symbol, new_balance)

    async def update_currency_price(self, account_type: str, symbol: str, price: float) -> None:
        if account_type in self.accounts:
            await self.accounts[account_type].update_currency_price(symbol, price)

    def get_account_summary(self) -> Dict[str, Dict[str, Dict[str, float]]]:
        summary = {}
        for account_type, account in self.accounts.items():
            summary[account_type] = {
                symbol: {
                    'balance': currency.balance,
                    'current_price': currency.current_price
                } for symbol, currency in account.currencies.items()
            }
        return summary

    def get_currency_history(self, account_type: str, symbol: str) -> Optional[Dict[str, List[Tuple[datetime, float]]]]:
        account = self.get_account(account_type)
        if account and symbol in account.currencies:
            currency = account.currencies[symbol]
            return {
                'price_history': currency.price_history,
                'buy_history': currency.buy_history,
                'sell_history': currency.sell_history
            }
        return None

    async def record_trade(self, account_type: str, symbol: str, amount: float, price: float, trade_type: str) -> None:
        account = self.get_account(account_type)
        if account and symbol in account.currencies:
            currency = account.currencies[symbol]
            await currency.record_trade(amount, price, trade_type)
            
            # Update USDT balance
            usdt_amount = amount * price
            if trade_type == 'buy':
                await self.update_account_balance(account_type, 'USDT', self.get_currency_balance(account_type, 'USDT') - usdt_amount)
            elif trade_type == 'sell':
                await self.update_account_balance(account_type, 'USDT', self.get_currency_balance(account_type, 'USDT') + usdt_amount)
        else:
            logger.warning(f"Failed to record trade: Account {account_type} or currency {symbol} not found")

    def get_currency_balance(self, account_type: str, symbol: str) -> float:
        account = self.get_account(account_type)
        if account:
            return account.get_currency_balance(symbol)
        return 0

    def get_all_currency_balances(self, account_type: str) -> Dict[str, float]:
        account = self.get_account(account_type)
        if account:
            return {symbol: currency.balance for symbol, currency in account.currencies.items()}
        return {}

    async def transfer_between_accounts(self, from_account: str, to_account: str, symbol: str, amount: float) -> bool:
        from_acc = self.get_account(from_account)
        to_acc = self.get_account(to_account)

        if from_acc and to_acc:
            if from_acc.get_currency_balance(symbol) >= amount:
                await from_acc.update_currency_balance(symbol, from_acc.get_currency_balance(symbol) - amount)
                await to_acc.update_currency_balance(symbol, to_acc.get_currency_balance(symbol) + amount)
                logger.info(f"Transferred {amount} {symbol} from {from_account} to {to_account}")
                return True
            else:
                logger.warning(f"Insufficient balance for transfer: {symbol} in {from_account}")
        else:
            logger.warning(f"Transfer failed: Account {from_account} or {to_account} not found")
        return False

    async def update_wallet_state(self, account_type: str, symbol: str, amount: float, price: float, trade_type: str) -> None:
        """
        Updates the wallet state after a trade (real or simulated).
        """
        await self.record_trade(account_type, symbol, amount, price, trade_type)
        await self.update_currency_price(account_type, symbol, price)
