"""Charts reuse the same paced/cached history path."""
from unittest.mock import patch
from earnings_calculator.chart import show_interactive_chart


def test_chart_uses_shared_history(ohlcv_dataframe):
    with patch("earnings_calculator.chart.price_history", return_value=ohlcv_dataframe) as history, \
         patch("earnings_calculator.chart.mpf.plot") as plot, \
         patch("earnings_calculator.chart.plt.show") as show, \
         patch("tkinter.messagebox.showerror") as error:
        show_interactive_chart("AAPL")
    history.assert_called_once_with("AAPL")
    plot.assert_called_once()
    show.assert_called_once()
    error.assert_not_called()
