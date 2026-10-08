"""Chart requests use yfinance's own compatible session."""
from unittest.mock import MagicMock, patch
from earnings_calculator.chart import show_interactive_chart


def test_chart_works_with_requests_session_manager(ohlcv_dataframe):
    session_manager = MagicMock(spec=["get_session", "rotate_session"])
    with patch("earnings_calculator.chart.yf.Ticker") as ticker, \
         patch("earnings_calculator.chart.mpf.plot") as plot, \
         patch("earnings_calculator.chart.plt.show") as show, \
         patch("tkinter.messagebox.showerror") as error:
        ticker.return_value.history.return_value = ohlcv_dataframe
        show_interactive_chart("AAPL", session_manager)
    ticker.assert_called_once_with("AAPL")
    plot.assert_called_once()
    show.assert_called_once()
    error.assert_not_called()
