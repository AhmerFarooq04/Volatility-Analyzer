"""Interactive candlestick chart rendering."""

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import mplfinance as mpf
from earnings_calculator.market_data import price_history



def show_interactive_chart(ticker: str):
    """Show completed daily price history using the shared paced Yahoo client."""
    try:
        from tkinter import messagebox

        hist = price_history(ticker)
        if hist.empty:
            messagebox.showerror("Error", f"No historical data for {ticker}.")
            return
        mpf.plot(
            hist,
            type="candle",
            style="charles",
            volume=True,
            title=f"{ticker} Chart",
        )
        plt.show()
    except Exception as e:
        from tkinter import messagebox

        messagebox.showerror(
            "Chart Error", f"Error generating chart for {ticker}: {e}"
        )
